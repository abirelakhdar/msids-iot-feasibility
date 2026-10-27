"""Synthetic requests for the feasibility check of the architecture paper (Section 4.2).

One home, three accounts and three devices, with simple daily habits written by
hand, and four kinds of misuse injected on some days. Nothing here comes from the
dataset of the experimental study, which is reported separately.
The requests only serve to show the request path working with trained models and
to measure what it costs; they say nothing about detection on real households.

    resident (admin_01)          unlocks and locks the door morning and evening,
                                 sets the heating, turns the lamp on and off
    household member (user_01)   uses the lamp some evenings
    visitor (guest_01)           uses the lamp some afternoons; may not use the lock

Misuse (label 1): the door unlocked at night with the resident's account; an
extreme setpoint; the lamp switched on and off many times in two minutes; the
visitor trying the lock (refused by access control, never seen by the IDMS).
"""
import random
from datetime import datetime, timedelta, timezone

from features.extract import HomeHistory

ROLES = {"admin_01": "admin", "user_01": "user", "guest_01": "guest"}
PERMITTED = {"admin": {"lamp", "thermostat", "lock"}, "user": {"lamp", "thermostat"}, "guest": {"lamp"}}
DEVICES = {"lamp_01": "lamp", "thermostat_01": "thermostat", "lock_01": "lock"}
FACTORY = {
    "lamp_01": {"power": "off"},
    "thermostat_01": {"power": "on", "target_temperature": 21, "current_temperature": 22.5},
    "lock_01": {"locked": True},
}
MISUSE = ("night_unlock", "extreme_setpoint", "oscillation", "visitor_probe")


def _at(day: datetime, hour: float, rng: random.Random, spread_min: float) -> datetime:
    return day + timedelta(minutes=hour * 60 + rng.gauss(0, spread_min))


def _req(when, user, device, action, payload=None, origin="mobile", kind="normal"):
    return {"time": when, "user_id": user, "device_id": device, "action": action,
            "payload": payload, "origin": origin, "kind": kind, "label": int(kind != "normal")}


def normal_day(day: datetime, rng: random.Random) -> list[dict]:
    out = []
    # resident: door, heating, lamp
    leave = _at(day, 7.5, rng, 15)
    out += [_req(leave, "admin_01", "lock_01", "unlock"), _req(leave + timedelta(minutes=2), "admin_01", "lock_01", "lock")]
    back = _at(day, 18.0, rng, 45)
    out += [_req(back, "admin_01", "lock_01", "unlock"), _req(back + timedelta(minutes=3), "admin_01", "lock_01", "lock")]
    out.append(_req(_at(day, 6.75, rng, 15), "admin_01", "thermostat_01", "set_temperature",
                    {"temperature": rng.choice([20, 21, 22])}))
    out.append(_req(_at(day, 22.0, rng, 20), "admin_01", "thermostat_01", "set_temperature",
                    {"temperature": rng.choice([18, 19])}))
    out.append(_req(_at(day, 19.5, rng, 30), "admin_01", "lamp_01", "turn_on"))
    out.append(_req(_at(day, 23.25, rng, 30), "admin_01", "lamp_01", "turn_off"))
    # household member: lamp some evenings, from the web interface
    if rng.random() < 0.5:
        on = _at(day, 20.5, rng, 30)
        out += [_req(on, "user_01", "lamp_01", "turn_on", origin="web"),
                _req(on + timedelta(minutes=rng.uniform(40, 120)), "user_01", "lamp_01", "turn_off", origin="web")]
    # visitor: lamp some afternoons
    if rng.random() < 0.25:
        on = _at(day, 15.0, rng, 60)
        out += [_req(on, "guest_01", "lamp_01", "turn_on"),
                _req(on + timedelta(minutes=rng.uniform(30, 90)), "guest_01", "lamp_01", "turn_off")]
    return out


def misuse(day: datetime, kind: str, rng: random.Random) -> list[dict]:
    if kind == "night_unlock":
        return [_req(day + timedelta(hours=rng.uniform(0.5, 4.5)), "admin_01", "lock_01", "unlock",
                     origin=rng.choice(["mobile", "web"]), kind=kind)]
    if kind == "extreme_setpoint":
        return [_req(day + timedelta(hours=rng.uniform(9, 17)), rng.choice(["admin_01", "user_01"]), "thermostat_01",
                     "set_temperature", {"temperature": rng.choice([10, 11, 12, 30, 31, 32])}, kind=kind)]
    if kind == "oscillation":
        start = day + timedelta(hours=rng.uniform(10, 17))
        return [_req(start + timedelta(seconds=15 * i), "user_01", "lamp_01", "turn_on" if i % 2 == 0 else "turn_off",
                     origin="web", kind=kind) for i in range(6)]
    if kind == "visitor_probe":
        return [_req(day + timedelta(hours=rng.uniform(13, 18)), "guest_01", "lock_01", "unlock", kind=kind)]
    raise ValueError(kind)


def generate(seed: int, days: int, start: datetime, misuse_rate: float, every_kind: bool = False) -> list[dict]:
    """Requests of `days` days in time order. With every_kind, each kind of misuse
    appears three times, on days chosen at random."""
    rng = random.Random(seed)
    requests = []
    forced = []
    if every_kind:
        forced = [(day, kind) for kind in MISUSE for day in rng.sample(range(days), 3)]
    for d in range(days):
        day = start + timedelta(days=d)
        requests += normal_day(day, rng)
        kinds = [kind for fd, kind in forced if fd == d]
        if not every_kind and rng.random() < misuse_rate:
            kinds.append(rng.choice(MISUSE))
        for kind in kinds:
            requests += misuse(day, kind, rng)
    requests.sort(key=lambda r: r["time"])
    return requests


def trace_of(req: dict, state: dict, status: str) -> dict:
    """The execution trace the gateway would build for this request (as JSON)."""
    return {
        "trace_id": "offline",
        "timestamp": req["time"].isoformat().replace("+00:00", "Z"),
        "source": "gateway",
        "context": {"user_id": req["user_id"], "user_role": ROLES[req["user_id"]], "origin": req["origin"]},
        "target": {"service": "DCMS", "device_id": req["device_id"], "device_type": DEVICES[req["device_id"]]},
        "action": req["action"], "payload": req["payload"], "device_state": dict(state), "status": status,
    }


def training_rows(requests: list[dict]) -> tuple[list[dict], list[int]]:
    """Feature rows of the requests the IDMS would see (those the UMMS permits),
    computed by the same code as the live IDMS, in time order, with nothing blocked."""
    from features.extract import state_after

    history, states, rows, labels = HomeHistory(), {k: dict(v) for k, v in FACTORY.items()}, [], []
    for req in requests:
        if DEVICES[req["device_id"]] not in PERMITTED[ROLES[req["user_id"]]]:
            continue
        trace = trace_of(req, states[req["device_id"]], "pending")
        row = {"timestamp": trace["timestamp"], **history.features(trace)}
        rows.append(row)
        labels.append(req["label"])
        trace["status"] = "success"
        history.update(trace)
        states[req["device_id"]] = state_after(trace)
    return rows, labels


TRAIN_START = datetime(2026, 1, 5, tzinfo=timezone.utc)
TEST_START = datetime(2026, 6, 1, tzinfo=timezone.utc)

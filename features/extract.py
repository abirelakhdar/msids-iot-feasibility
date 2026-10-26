"""Features of one execution trace, computed from the trace and from what the
same home did before it.

The history only ever looks backwards: `features()` reads the past and
`update()` adds the trace afterwards. The same class can therefore run on a
stored dataset and inside a detection service on live requests.
"""
import json
import math
from collections import Counter, defaultdict, deque
from datetime import datetime
from typing import Any

HOUR = 3600.0
CATEGORICAL = ["origin", "role", "device", "action"]
NUMERIC = [
    # the request and the state of its device
    "hour_sin", "hour_cos", "weekday", "weekend", "denied",
    "requested_temperature", "room_temperature", "target_temperature", "power_on", "locked",
    "requested_minus_room", "requested_minus_target", "size_of_change", "changes_nothing",
    # how recently the home, the account and the device were used
    "gap_home", "gap_account", "gap_device", "gap_same_request",
    # how much was asked recently
    "n_home_10s", "n_home_60s", "n_home_10min", "n_home_1h",
    "n_device_60s", "n_device_10min", "n_account_10min", "n_same_request_1h",
    "n_state_changes_device_10min", "n_actions_device_10min", "n_denied_account_10min",
    # what is known of the rest of the home from earlier traces
    "known_locked", "known_lamp_on", "known_heating_on",
    "since_lock_command", "since_unlock_command",
    # how usual this request is for this account
    "account_requests_so_far", "usual_hour", "usual_origin", "usual_request", "origin_never_seen",
]
COLUMNS = CATEGORICAL + NUMERIC
CHANGES = {"turn_on": ("power", "on"), "turn_off": ("power", "off"), "lock": ("locked", True), "unlock": ("locked", False)}
# A profile is trusted to call something "never seen" only after this many requests.
PROFILE_MINIMUM = 20


def moment(trace: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(trace["timestamp"].replace("Z", "+00:00"))


def state_after(trace: dict[str, Any]) -> dict[str, Any]:
    """Device state once a successful request has been applied."""
    state = dict(trace["device_state"] or {})
    action, payload = trace["action"], trace["payload"] or {}
    if action in CHANGES:
        key, value = CHANGES[action]
        state[key] = value
    elif action == "set_temperature":
        state["target_temperature"] = payload.get("temperature")
    return state


class HomeHistory:
    def __init__(self) -> None:
        self.recent: deque[tuple[float, str, str, str]] = deque()  # time, device, account, request
        self.changes: dict[str, deque[float]] = defaultdict(deque)
        self.denied: dict[str, deque[float]] = defaultdict(deque)
        self.last: dict[tuple[str, str], float] = {}
        self.known: dict[str, dict[str, Any]] = {}
        self.hours: dict[str, Counter] = defaultdict(Counter)
        self.origins: dict[str, Counter] = defaultdict(Counter)
        self.requests: dict[str, Counter] = defaultdict(Counter)
        self.total: Counter = Counter()

    @staticmethod
    def _request(trace: dict[str, Any]) -> str:
        return f'{trace["target"]["device_id"]}|{trace["action"]}|{json.dumps(trace["payload"], sort_keys=True)}'

    def _since(self, kind: str, key: str, now: float) -> float | None:
        then = self.last.get((kind, key))
        return None if then is None else now - then

    def features(self, trace: dict[str, Any]) -> dict[str, Any]:
        when = moment(trace)
        now = when.timestamp()
        context, target = trace["context"], trace["target"]
        account, device, action = context["user_id"], target["device_id"], trace["action"]
        request = self._request(trace)
        state, payload = trace["device_state"] or {}, trace["payload"] or {}
        hour = when.hour + when.minute / 60

        requested = payload.get("temperature")
        room, target_temperature = state.get("current_temperature"), state.get("target_temperature")
        changes_nothing = None
        if action in CHANGES:
            key, value = CHANGES[action]
            changes_nothing = float(state.get(key) == value)
        elif action == "set_temperature":
            changes_nothing = float(requested == target_temperature)

        counts = Counter()
        actions_on_device = set()
        for then, other_device, other_account, other_request in reversed(self.recent):
            age = now - then
            if age > HOUR:
                break
            counts["home_1h"] += 1
            counts["same_1h"] += other_request == request
            if age <= 600:
                counts["home_10min"] += 1
                counts["account_10min"] += other_account == account
                if other_device == device:
                    counts["device_10min"] += 1
                    actions_on_device.add(other_request.split("|")[1])
            if age <= 60:
                counts["home_60s"] += 1
                counts["device_60s"] += other_device == device
            if age <= 10:
                counts["home_10s"] += 1

        seen = self.total[account]
        near = sum(self.hours[account][(when.hour + shift) % 24] for shift in (-1, 0, 1))
        origin = context["origin"]
        known = lambda name, key, yes: (
            None if name not in self.known or key not in self.known[name] else float(self.known[name][key] == yes)
        )
        return {
            "origin": origin,
            "role": context["user_role"],
            "device": target["device_type"],
            "action": action,
            "hour_sin": math.sin(2 * math.pi * hour / 24),
            "hour_cos": math.cos(2 * math.pi * hour / 24),
            "weekday": when.weekday(),
            "weekend": float(when.weekday() >= 5),
            "denied": float(trace["status"] == "denied"),
            "requested_temperature": requested,
            "room_temperature": room,
            "target_temperature": target_temperature,
            "power_on": None if "power" not in state else float(state["power"] == "on"),
            "locked": None if "locked" not in state else float(state["locked"]),
            "requested_minus_room": None if requested is None else requested - room,
            "requested_minus_target": None if requested is None else requested - target_temperature,
            "size_of_change": None if requested is None else abs(requested - target_temperature),
            "changes_nothing": changes_nothing,
            "gap_home": self._since("home", "", now),
            "gap_account": self._since("account", account, now),
            "gap_device": self._since("device", device, now),
            "gap_same_request": self._since("request", request, now),
            "n_home_10s": counts["home_10s"],
            "n_home_60s": counts["home_60s"],
            "n_home_10min": counts["home_10min"],
            "n_home_1h": counts["home_1h"],
            "n_device_60s": counts["device_60s"],
            "n_device_10min": counts["device_10min"],
            "n_account_10min": counts["account_10min"],
            "n_same_request_1h": counts["same_1h"],
            "n_state_changes_device_10min": sum(now - then <= 600 for then in self.changes[device]),
            "n_actions_device_10min": len(actions_on_device),
            "n_denied_account_10min": sum(now - then <= 600 for then in self.denied[account]),
            "known_locked": known("lock_01", "locked", True),
            "known_lamp_on": known("lamp_01", "power", "on"),
            "known_heating_on": known("thermostat_01", "power", "on"),
            "since_lock_command": self._since("command", "lock", now),
            "since_unlock_command": self._since("command", "unlock", now),
            "account_requests_so_far": seen,
            "usual_hour": (near + 1) / (seen + 8),
            "usual_origin": (self.origins[account][origin] + 1) / (seen + 3),
            "usual_request": (self.requests[account][f"{device}|{action}"] + 1) / (seen + 10),
            "origin_never_seen": float(seen >= PROFILE_MINIMUM and self.origins[account][origin] == 0),
        }

    def update(self, trace: dict[str, Any]) -> None:
        when = moment(trace)
        now = when.timestamp()
        account, device, action = trace["context"]["user_id"], trace["target"]["device_id"], trace["action"]
        request = self._request(trace)

        self.recent.append((now, device, account, request))
        while self.recent and now - self.recent[0][0] > HOUR:
            self.recent.popleft()
        for kind, key in (("home", ""), ("account", account), ("device", device), ("request", request)):
            self.last[(kind, key)] = now
        self.hours[account][when.hour] += 1
        self.origins[account][trace["context"]["origin"]] += 1
        self.requests[account][f"{device}|{action}"] += 1
        self.total[account] += 1

        for times in (self.changes[device], self.denied[account]):
            while times and now - times[0] > 600:
                times.popleft()
        if trace["status"] == "denied":
            self.denied[account].append(now)
        if trace["status"] in ("denied", "blocked", "failed"):
            # The device did not act; all the trace tells is its state.
            self.known[device] = dict(trace["device_state"] or {})
            return
        after = state_after(trace)
        if after != (trace["device_state"] or {}):
            self.changes[device].append(now)
        self.known[device] = after
        if action in ("lock", "unlock"):
            self.last[("command", action)] = now

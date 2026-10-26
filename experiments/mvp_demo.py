"""Feasibility check of the MSIDS-IoT request path (Section 4.2 of the paper).

    docker compose up -d --build
    python -m experiments.mvp_demo
    docker compose down

A handful of hand-written requests go through the real gateway, UMMS, IDMS and
DCMS. It shows that each outcome of the request path happens on the running
services: executed, refused by access control, blocked by the IDMS before the
device acts, and an altered trace rejected. It measures nothing: no dataset,
no learned model, no detection rate, no latency; these are outside the scope of this check.

The IDMS holds a placeholder policy (experiments/mvp/rules.json): the door is
not unlocked between midnight and five. It stands in for the detector.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from shared.trace_schema import ExecutionTrace, TraceContext, TraceTarget

URLS = {"gateway": "http://127.0.0.1:8300", "idms": "http://127.0.0.1:8301", "dcms": "http://127.0.0.1:8302"}
OUT = Path("results/mvp")

# Accounts of the UMMS: admin_01 is the resident, user_01 another member of the
# household, guest_01 a visitor who may use the lamp only.
SCENARIOS = [
    {"name": "Resident unlocks the door on coming home", "time": "2026-10-14T18:05:00+00:00",
     "user_id": "admin_01", "device_id": "lock_01", "action": "unlock", "origin": "mobile", "expected": "success"},
    {"name": "Resident locks the door", "time": "2026-10-14T18:06:00+00:00",
     "user_id": "admin_01", "device_id": "lock_01", "action": "lock", "origin": "mobile", "expected": "success"},
    {"name": "Household member turns on the lamp", "time": "2026-10-14T19:30:00+00:00",
     "user_id": "user_01", "device_id": "lamp_01", "action": "turn_on", "origin": "web", "expected": "success"},
    {"name": "Visitor tries to unlock the door", "time": "2026-10-14T20:15:00+00:00",
     "user_id": "guest_01", "device_id": "lock_01", "action": "unlock", "origin": "mobile", "expected": "denied"},
    {"name": "Resident's account unlocks the door at night", "time": "2026-10-15T03:10:00+00:00",
     "user_id": "admin_01", "device_id": "lock_01", "action": "unlock", "origin": "mobile", "expected": "blocked"},
]


def state_of(dcms, device_id: str) -> dict:
    return dcms.get(f"/devices/{device_id}").json()["state"]


def send(gateway, dcms, scenario: dict) -> dict:
    before = state_of(dcms, scenario["device_id"])
    response = gateway.post(
        "/request",
        json={key: scenario[key] for key in ("user_id", "device_id", "action", "origin")},
        headers={"X-Sim-Time": scenario["time"]},
    )
    body = response.json()
    return {
        "scenario": scenario["name"],
        "time": scenario["time"],
        "user_id": scenario["user_id"],
        "request": f"{scenario['action']} {scenario['device_id']}",
        "http_status": response.status_code,
        "status": body["status"],
        "idms_decision": body["decision"],
        "reason": body["reason"],
        "state_before": before,
        "state_after": state_of(dcms, scenario["device_id"]),
        "trace_id": body["trace_id"],
        "expected": scenario["expected"],
    }


def altered_trace(idms) -> dict:
    """A trace the gateway would have built for the household member's lamp
    request, altered after hashing into an unlock of the door, then given to
    the IDMS. It is not sent to the device whatever the answer."""
    trace = ExecutionTrace(
        trace_id="tr_altered_demo",
        timestamp=datetime(2026, 10, 15, 3, 20, tzinfo=timezone.utc),
        context=TraceContext(user_id="user_01", user_role="user", origin="web"),
        target=TraceTarget(service="DCMS", device_id="lamp_01", device_type="lamp"),
        action="turn_on",
        device_state={"power": "off"},
        status="pending",
    )
    trace.trace_hash = trace.compute_hash()
    trace.target = TraceTarget(service="DCMS", device_id="lock_01", device_type="lock")
    trace.action = "unlock"
    verdict = idms.post("/analyze", json=trace.model_dump(mode="json")).json()
    return {
        "scenario": "Trace altered between the gateway and the IDMS",
        "time": trace.timestamp.isoformat(),
        "user_id": "user_01",
        "request": "turn_on lamp_01, altered into unlock lock_01",
        "http_status": None,
        "status": "rejected by the IDMS",
        "idms_decision": verdict["decision"],
        "reason": verdict["reason"],
        "state_before": None,
        "state_after": None,
        "trace_id": trace.trace_id,
        "expected": "REJECT",
    }


def run(gateway, idms, dcms) -> list[dict]:
    outcomes = [send(gateway, dcms, scenario) for scenario in SCENARIOS]
    outcomes.append(altered_trace(idms))
    return outcomes


def as_expected(outcome: dict) -> bool:
    return outcome["expected"] in (outcome["status"], outcome["idms_decision"])


def wait_until_up(clients: dict, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    for name, client in clients.items():
        while True:
            try:
                if client.get("/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                sys.exit(f"{name} is not answering; start the services first (see the docstring)")
            time.sleep(1)


def main() -> None:
    clients = {name: httpx.Client(base_url=url, timeout=10) for name, url in URLS.items()}
    wait_until_up(clients)
    detector = clients["idms"].get("/detector").json()["detector"]
    if detector != "rules":
        sys.exit(f"the IDMS holds '{detector}', not the placeholder policy")
    # A fresh start: devices in their factory state, an IDMS with no history, no traces.
    clients["dcms"].post("/reset").raise_for_status()
    clients["idms"].post("/reset").raise_for_status()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "traces.jsonl").write_text("", encoding="utf-8")

    outcomes = run(clients["gateway"], clients["idms"], clients["dcms"])

    (OUT / "outcomes.json").write_text(json.dumps(outcomes, indent=1), encoding="utf-8")
    for number, outcome in enumerate(outcomes, 1):
        mark = "ok" if as_expected(outcome) else "UNEXPECTED"
        print(f"{number}. {outcome['scenario']}: {outcome['status']} "
              f"(IDMS {outcome['idms_decision']}; {outcome['reason']}) "
              f"{outcome['state_before']} -> {outcome['state_after']} [{mark}]")
    if not all(map(as_expected, outcomes)):
        sys.exit("at least one outcome differs from what was expected")


if __name__ == "__main__":
    main()

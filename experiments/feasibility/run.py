"""Run the feasibility check with trained models and measure what it costs.

    python -m experiments.feasibility.run

Needs the stack of docker-compose.feasibility.yml running and the models of
train.py. For each detector the IDMS can hold (none, the placeholder rule, the
decision tree, the SVM), the 199 synthetic test requests (scenario.py, seed 2) go
through the gateway, four times, the order of the detectors rotating between passes. The detector is exchanged through the IDMS
endpoint while the services keep running; devices and the IDMS history are reset
before each pass. Recorded per request: HTTP status, outcome, IDMS decision and the
time the client waited; before each pass, the same traces are also sent to the IDMS
alone, to time it apart from the rest of the path. During each pass, CPU and memory of every container are
sampled with `docker stats`. Then the IDMS is stopped and started again, to see
what the gateway does without it.

Writes results/feasibility/summary.json and results/feasibility/requests.csv.
"""
import csv
import json
import os
import platform
import statistics
import subprocess
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from experiments.feasibility.scenario import TEST_START, generate

URLS = {"gateway": "http://127.0.0.1:8400", "idms": "http://127.0.0.1:8401", "dcms": "http://127.0.0.1:8402"}
COMPOSE = ["docker", "compose", "-f", "docker-compose.feasibility.yml"]
DETECTORS = ["none", "rules", "tree", "svm"]
REPETITIONS = 4  # the order of the detectors rotates, so each runs once in each position
OUT = Path("results/feasibility")


def wait_healthy(client: httpx.Client, seconds: float = 90) -> float:
    start = time.perf_counter()
    while time.perf_counter() - start < seconds:
        try:
            if client.get("/health").status_code == 200:
                return time.perf_counter() - start
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise SystemExit("service did not come back")


class Sampler(threading.Thread):
    """CPU and memory of each container, from `docker stats`, until stopped."""

    def __init__(self):
        super().__init__(daemon=True)
        self.samples = defaultdict(list)
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"],
                                 capture_output=True, text=True).stdout
            for line in out.splitlines():
                row = json.loads(line)
                name = row["Name"]
                if not name.startswith("msids-feasibility-"):
                    continue
                service = name.removeprefix("msids-feasibility-").rsplit("-", 1)[0]
                cpu = float(row["CPUPerc"].rstrip("%"))
                used = row["MemUsage"].split("/")[0].strip()
                value, unit = float(used[:-3]), used[-3:]
                mib = value * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[unit]
                self.samples[service].append((cpu, mib))


def one_pass(gw, idms, dcms, requests, detector):
    dcms.post("/reset").raise_for_status()
    idms.post("/reset").raise_for_status()
    sampler = Sampler()
    sampler.start()
    rows = []
    for number, req in enumerate(requests, 1):
        body = {k: req[k] for k in ("user_id", "device_id", "action", "payload", "origin")}
        start = time.perf_counter()
        response = gw.post("/request", json=body, headers={"X-Sim-Time": req["time"].isoformat()})
        elapsed = (time.perf_counter() - start) * 1000
        reply = response.json()
        rows.append({"detector": detector, "number": number, "time": req["time"].isoformat(),
                     "user_id": req["user_id"], "device_id": req["device_id"], "action": req["action"],
                     "kind": req["kind"], "http_status": response.status_code,
                     "outcome": reply.get("status", "error"), "decision": reply.get("decision"),
                     "milliseconds": round(elapsed, 3)})
    sampler.stop.set()
    sampler.join()
    return rows, sampler.samples


def idms_alone(idms, requests) -> list[float]:
    """Milliseconds of each call to the IDMS alone, with the traces the gateway would
    send (requests the UMMS permits, device states as they evolve, hash computed)."""
    from experiments.feasibility.scenario import DEVICES, FACTORY, PERMITTED, ROLES, trace_of
    from features.extract import state_after
    from shared.trace_schema import ExecutionTrace

    idms.post("/reset").raise_for_status()
    states = {k: dict(v) for k, v in FACTORY.items()}
    times = []
    for number, req in enumerate(requests):
        if DEVICES[req["device_id"]] not in PERMITTED[ROLES[req["user_id"]]]:
            continue
        record = trace_of(req, states[req["device_id"]], "pending")
        trace = ExecutionTrace(**{**record, "trace_id": f"tr_alone_{number}"})
        trace.trace_hash = trace.compute_hash()
        start = time.perf_counter()
        verdict = idms.post("/analyze", json=trace.model_dump(mode="json")).json()
        times.append((time.perf_counter() - start) * 1000)
        if verdict["decision"] == "ALLOW":
            states[req["device_id"]] = state_after(record)
    return times


def percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def failure_test(gw, idms, dcms) -> dict:
    """Stop the IDMS; requests must be refused and devices left alone. Start it again."""
    dcms.post("/reset").raise_for_status()
    before = dcms.get("/devices").json()
    subprocess.run([*COMPOSE, "stop", "idms"], check=True, capture_output=True)
    probes = [{"user_id": "admin_01", "device_id": "lamp_01", "action": "turn_on", "origin": "mobile"},
              {"user_id": "admin_01", "device_id": "lock_01", "action": "unlock", "origin": "mobile"},
              {"user_id": "user_01", "device_id": "thermostat_01", "action": "set_temperature",
               "payload": {"temperature": 22}, "origin": "web"}]
    down = []
    for body in probes:
        start = time.perf_counter()
        response = gw.post("/request", json=body, headers={"X-Sim-Time": "2026-06-20T19:00:00+00:00"})
        down.append({"request": f'{body["action"]} {body["device_id"]}', "http_status": response.status_code,
                     "milliseconds": round((time.perf_counter() - start) * 1000, 1)})
    after_down = dcms.get("/devices").json()
    started = time.perf_counter()
    subprocess.run([*COMPOSE, "start", "idms"], check=True, capture_output=True)
    wait_healthy(idms)
    back_after = time.perf_counter() - started
    idms.post("/detector", json={"kind": "svm"}).raise_for_status()
    response = gw.post("/request", json=probes[0], headers={"X-Sim-Time": "2026-06-20T19:05:00+00:00"})
    return {"while_down": down, "devices_unchanged": before == after_down,
            "seconds_until_idms_healthy": round(back_after, 1),
            "first_request_after_restart": {"http_status": response.status_code,
                                            "outcome": response.json().get("status")}}


def main() -> None:
    clients = {name: httpx.Client(base_url=url, timeout=30) for name, url in URLS.items()}
    gw, idms, dcms = clients["gateway"], clients["idms"], clients["dcms"]
    for client in clients.values():
        wait_healthy(client)
    requests = generate(seed=2, days=18, start=TEST_START, misuse_rate=0, every_kind=True)
    # one request through the whole path before measuring
    for detector in DETECTORS:
        idms.post("/detector", json={"kind": detector}).raise_for_status()
        dcms.post("/reset"); idms.post("/reset")
        gw.post("/request", json={"user_id": "admin_01", "device_id": "lamp_01", "action": "read_status"},
                headers={"X-Sim-Time": "2026-05-31T12:00:00+00:00"})

    all_rows, stats, swaps, alone = [], defaultdict(lambda: defaultdict(list)), [], defaultdict(list)
    for repetition in range(1, REPETITIONS + 1):
        shift = (repetition - 1) % len(DETECTORS)
        for detector in DETECTORS[shift:] + DETECTORS[:shift]:
            swap = idms.post("/detector", json={"kind": detector}).json()
            swaps.append({"to": detector, "seconds": swap["seconds"]})
            alone[detector] += idms_alone(idms, requests)
            rows, samples = one_pass(gw, idms, dcms, requests, detector)
            for row in rows:
                row["repetition"] = repetition
            all_rows += rows
            for service, values in samples.items():
                stats[detector][service] += values

    summary = {"machine": {"system": platform.platform(), "logical_cpus": os.cpu_count(),
                           "python": platform.python_version()},
               "workload": {"requests": len(requests), "kinds": dict(Counter(r["kind"] for r in requests)),
                            "repetitions": REPETITIONS},
               "detectors": {}, "swaps": {"count": len(swaps),
                                          "max_seconds": round(max(s["seconds"] for s in swaps), 3)}}
    for detector in DETECTORS:
        rows = [r for r in all_rows if r["detector"] == detector]
        first = [r for r in rows if r["repetition"] == 1]
        times = [r["milliseconds"] for r in rows]
        same = all(
            [(r["outcome"]) for r in rows if r["repetition"] == k] == [r["outcome"] for r in first]
            for k in range(2, REPETITIONS + 1))
        by_kind = defaultdict(Counter)
        for r in first:
            by_kind[r["kind"]][r["outcome"]] += 1
        summary["detectors"][detector] = {
            "outcomes": dict(Counter(r["outcome"] for r in first)),
            "outcomes_by_kind": {k: dict(v) for k, v in by_kind.items()},
            "same_outcomes_in_every_repetition": same,
            "errors": sum(r["http_status"] >= 500 for r in rows),
            "latency_ms": {"median": round(statistics.median(times), 2), "p95": round(percentile(times, 0.95), 2),
                           "max": round(max(times), 2)},
            "idms_alone_ms": {"calls": len(alone[detector]), "median": round(statistics.median(alone[detector]), 2),
                              "p95": round(percentile(alone[detector], 0.95), 2)},
            "containers": {service: {"cpu_percent_mean": round(statistics.mean(v[0] for v in values), 2),
                                     "cpu_percent_max": round(max(v[0] for v in values), 2),
                                     "memory_mib_max": round(max(v[1] for v in values), 1)}
                           for service, values in sorted(stats[detector].items())},
        }
    base = summary["detectors"]["none"]["latency_ms"]["median"]
    for detector in DETECTORS:
        summary["detectors"][detector]["median_added_vs_none_ms"] = round(
            summary["detectors"][detector]["latency_ms"]["median"] - base, 2)
    summary["idms_failure"] = failure_test(gw, idms, dcms)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    with (OUT / "requests.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

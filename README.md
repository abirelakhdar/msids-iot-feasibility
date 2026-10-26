# MSIDS-IoT: feasibility check of the request path

This repository contains the code and the recorded outcomes of the feasibility
check reported in Section 4.2 of the paper *Microservices Architecture with
Machine Learning for Intrusion Detection in Internet of Things Security*
(A. El Akhdar, C. Baidada, A. Kartit, M. Hanine).

It implements the request path of the MSIDS-IoT architecture as four Python
(FastAPI) services, each in its own Docker container:

| Service | Folder | Role |
|---|---|---|
| MS Gateway | `gateway/` | Single entry point; reads the device state, asks the UMMS, builds and hashes the execution trace, calls the IDMS, forwards allowed commands, logs every trace |
| UMMS | `umms/` | Users and roles: administrator (resident), user (household member), guest (visitor) |
| IDMS | `idms/` | Checks the trace hash, computes features from the trace and the recent history of the home, applies a replaceable detector, answers ALLOW or REJECT |
| DCMS | `dcms/` | Simulated lamp, thermostat and door lock with their states |

The execution trace is defined in `shared/trace_schema.py`.

## What the check shows, and what it does not

Six requests are run against the running containers (`experiments/mvp_demo.py`):

| # | Request (account) | Outcome |
|---|---|---|
| 1 | Unlock the door at 18:05 (resident) | Executed |
| 2 | Lock the door at 18:06 (resident) | Executed |
| 3 | Turn on the lamp at 19:30 (household member) | Executed |
| 4 | Unlock the door at 20:15 (visitor) | Refused by the UMMS; the IDMS is not called |
| 5 | Unlock the door at 03:10 (resident's account) | Blocked by the IDMS before the lock moves |
| 6 | Trace altered after the gateway, sent to the IDMS | Rejected (hash mismatch) |

The IDMS holds a **placeholder policy** (`experiments/mvp/rules.json`): a single
rule that refuses to unlock the door between midnight and five, loaded through the
same interface as a trained model. The check therefore shows that the services
interact as designed; it does **not** measure detection performance, latency or
scale. Devices are simulated, the caller's identity is taken from the request (no
authentication), services talk plain HTTP, and traces are hashed but not signed.

The recorded outcomes and traces are in `results/mvp/` (`outcomes.json`,
`traces.jsonl`).

## Reproduce

Requirements: Docker with Docker Compose, and Python 3.11 or later with the
packages of `requirements.txt` (for the demo script and the tests).

    pip install -r requirements.txt
    docker compose up -d --build
    python -m experiments.mvp_demo
    docker compose down

Each request carries a set clock time (simulation mode), so the run gives the same
outcomes every time; the script exits with an error if any outcome differs from
the expected one. The same scenarios also run in one process, without Docker:

    pytest

## Licence

MIT (see `LICENSE`).

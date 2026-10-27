# MSIDS-IoT: feasibility check of the request path

This repository contains the code and the recorded outcomes of the feasibility
check reported in Section 4.2 of the paper *Trace-Driven Dual-Layer Intrusion Detection for Smart Homes Built on
Microservices and Machine Learning*
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

## Second run: trained models, latency, resources, failure of the IDMS

The second part of Section 4.2 (Table 8) puts two simple trained models in the
IDMS, next to the rule, and measures what the IDMS costs.

- `experiments/feasibility/scenario.py` generates the requests of a synthetic
  home: three accounts (resident, household member, visitor), a lamp, a
  thermostat and a door lock, daily habits written by hand, and four kinds of
  misuse (door unlocked at night, extreme heating setpoint, lamp switched six
  times in 75 seconds, visitor trying the lock).
- `experiments/feasibility/train.py` trains a decision tree and an SVM on 60
  days of such requests and saves them in `experiments/feasibility/models/`
  (the saved models are included, written with scikit-learn 1.9.1).
- `experiments/feasibility/run.py` sends 199 test requests from 18 later days
  through the gateway, four times for each detector (none, rule, tree, SVM),
  exchanging the detector in the running IDMS between runs. It also times the
  IDMS alone, samples CPU and memory with `docker stats`, then stops the IDMS
  to see what the gateway does without it.

Results (`results/feasibility/summary.json`, per-request rows in
`requests.csv`), on a laptop with 8 logical processors, Windows 11 and Docker
Desktop:

| Detector | Blocked: misuse (of 24) / legitimate (of 172) | IDMS alone, median (p95), ms | Whole request, median (p95), ms | IDMS CPU, mean |
|---|---|---|---|---|
| None | 0 / 0 | 3.9 (6.0) | 17.5 (28.2) | 9.0% |
| Rule (control baseline) | 3 / 0 | 4.1 (7.3) | 18.0 (29.7) | 9.9% |
| Decision tree | 21 / 9 | 4.5 (8.4) | 17.6 (28.8) | 11.9% |
| SVM | 21 / 0 | 7.0 (12.3) | 22.1 (37.7) | 17.6% |

The IDMS used about 100 MiB of memory with every detector. With the IDMS
stopped and the gateway waiting at most one second (`IDMS_TIMEOUT`), requests
were refused with HTTP 503 after about one second and no device changed state;
after a restart the next request was executed normally.

The home and its misuse are small and synthetic: these figures show trained
models running on the request path and what they cost, not detection
performance on real households.

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

The second run needs scikit-learn as well:

    pip install -r requirements.txt -r requirements-ml.txt
    python -m experiments.feasibility.train      # optional: the models are included
    docker compose -f docker-compose.feasibility.yml up -d --build
    python -m experiments.feasibility.run
    docker compose -f docker-compose.feasibility.yml down

Latency and CPU depend on the machine; the outcomes of each request do not.

## Licence

MIT (see `LICENSE`).

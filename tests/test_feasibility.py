"""The feasibility check with trained models (architecture paper, Section 4.2)."""
from collections import Counter
from pathlib import Path

import pytest

from experiments.feasibility.scenario import DEVICES, PERMITTED, ROLES, TEST_START, TRAIN_START, generate, training_rows

MODELS = Path(__file__).parent.parent / "experiments" / "feasibility" / "models"


def test_the_test_workload_is_fixed_and_holds_every_kind_of_misuse():
    first = generate(seed=2, days=18, start=TEST_START, misuse_rate=0, every_kind=True)
    again = generate(seed=2, days=18, start=TEST_START, misuse_rate=0, every_kind=True)
    assert first == again
    assert len(first) == 199
    kinds = Counter(r["kind"] for r in first)
    assert kinds["night_unlock"] == kinds["extreme_setpoint"] == kinds["visitor_probe"] == 3
    assert kinds["oscillation"] == 18  # three bursts of six requests
    assert [r["time"] for r in first] == sorted(r["time"] for r in first)


def test_training_and_test_requests_do_not_overlap_in_time():
    train = generate(seed=1, days=60, start=TRAIN_START, misuse_rate=0.4)
    test = generate(seed=2, days=18, start=TEST_START, misuse_rate=0, every_kind=True)
    assert max(r["time"] for r in train) < min(r["time"] for r in test)


def test_training_rows_hold_only_what_the_idms_would_see():
    requests = generate(seed=1, days=60, start=TRAIN_START, misuse_rate=0.4)
    rows, labels = training_rows(requests)
    permitted = [r for r in requests if DEVICES[r["device_id"]] in PERMITTED[ROLES[r["user_id"]]]]
    assert len(rows) == len(labels) == len(permitted)
    assert all(row["role"] != "guest" or row["device"] == "lamp" for row in rows)


@pytest.mark.parametrize("kind", ["tree", "svm"])
def test_the_idms_loads_the_trained_models(kind):
    if not (MODELS / f"{kind}.pkl").exists():
        pytest.skip("models not trained: python -m experiments.feasibility.train")
    from idms.detectors import load

    detector = load(kind, MODELS)
    rows, _ = training_rows(generate(seed=2, days=2, start=TEST_START, misuse_rate=0))
    flagged, reason = detector.decide(rows[0])
    assert isinstance(flagged, bool) and reason.startswith(kind)


def test_the_gateway_waits_the_default_time_unless_told_otherwise(monkeypatch):
    import importlib

    import gateway.main as gateway

    monkeypatch.delenv("IDMS_TIMEOUT", raising=False)
    assert importlib.reload(gateway).IDMS_TIMEOUT is None
    monkeypatch.setenv("IDMS_TIMEOUT", "1")
    assert importlib.reload(gateway).IDMS_TIMEOUT == 1.0
    monkeypatch.delenv("IDMS_TIMEOUT")
    importlib.reload(gateway)

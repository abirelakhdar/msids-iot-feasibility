"""The scenarios of the minimal prototype, run in one process."""
import copy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import dcms.main as dcms
import gateway.main as gateway
import idms.main as idms
import umms.main as umms
from experiments.mvp_demo import as_expected, run
from features.extract import HomeHistory
from idms.detectors import RuleDetector

POLICY = Path(__file__).parent.parent / "experiments" / "mvp" / "rules.json"


@pytest.fixture
def outcomes(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "TRACE_LOG", tmp_path / "traces.jsonl")
    monkeypatch.setattr(gateway, "SIMULATION_MODE", True)
    monkeypatch.setattr(dcms, "DEVICES", copy.deepcopy(dcms.FACTORY))
    monkeypatch.setattr(idms.state, "detector", RuleDetector(POLICY))
    monkeypatch.setattr(idms.state, "enforce", True)
    monkeypatch.setattr(idms.state, "history", HomeHistory())
    with TestClient(gateway.app) as client, TestClient(idms.app) as detector, TestClient(dcms.app) as devices:
        gateway.app.state.client = httpx.AsyncClient(
            mounts={
                "all://localhost:8001": httpx.ASGITransport(app=idms.app),
                "all://localhost:8002": httpx.ASGITransport(app=dcms.app),
                "all://localhost:8003": httpx.ASGITransport(app=umms.app),
            }
        )
        yield run(client, detector, devices)


def test_every_scenario_ends_as_expected(outcomes):
    assert [o["status"] for o in outcomes] == ["success", "success", "success", "denied", "blocked",
                                                 "rejected by the IDMS"]
    assert all(map(as_expected, outcomes))


def test_the_visitor_is_refused_before_the_idms(outcomes):
    visitor = outcomes[3]
    assert visitor["idms_decision"] is None
    assert visitor["state_after"] == visitor["state_before"] == {"locked": True}


def test_the_night_unlock_is_blocked_before_the_device_acts(outcomes):
    night = outcomes[4]
    assert night["idms_decision"] == "REJECT" and "night_unlock" in night["reason"]
    assert night["state_after"] == night["state_before"] == {"locked": True}


def test_the_same_account_unlocks_by_day(outcomes):
    assert outcomes[0]["state_before"] == {"locked": True}
    assert outcomes[0]["state_after"] == {"locked": False}


def test_an_altered_trace_is_rejected(outcomes):
    assert outcomes[5]["reason"] == "trace hash mismatch"


def test_the_placeholder_policy_has_one_rule():
    policy = RuleDetector(POLICY)
    quiet = {"n_home_60s": 50, "n_state_changes_device_10min": 50, "n_same_request_1h": 50,
             "n_denied_account_10min": 50, "requested_temperature": 40, "action": "turn_on",
             "timestamp": "2026-10-15T03:00:00+00:00"}
    assert policy.decide(quiet)[0] is False
    assert policy.decide({**quiet, "action": "unlock"})[0] is True

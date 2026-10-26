import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from features.extract import HomeHistory
from idms.detectors import Detector, load
from shared.trace_schema import ExecutionTrace


MODELS = Path(os.getenv("IDMS_MODELS", "models"))
SIMULATION_MODE = os.getenv("SIMULATION_MODE") == "1"


class Verdict(BaseModel):
    trace_id: str
    decision: str
    reason: str
    detector: str = "none"
    flagged: bool = False


class DetectorChoice(BaseModel):
    kind: str


class State:
    """One IDMS serves one home: it keeps that home's history of requests."""

    def __init__(self) -> None:
        self.detector: Detector = load(os.getenv("IDMS_DETECTOR", "none"), MODELS)
        # Enforcing: a flagged request is rejected. Otherwise the IDMS only
        # observes: it says what it would have done and lets the request pass.
        self.enforce = os.getenv("IDMS_ENFORCE", "1") == "1"
        self.history = HomeHistory()
        self.lock = threading.Lock()


state = State()
app = FastAPI(title="IDMS")


@app.get("/health")
def health():
    return {"status": "ok", "detector": state.detector.name}


@app.post("/analyze")
def analyze(trace: ExecutionTrace) -> Verdict:
    if trace.trace_hash != trace.compute_hash():
        return Verdict(trace_id=trace.trace_id, decision="REJECT", reason="trace hash mismatch")

    with state.lock:
        detector = state.detector
        if not detector.needs_features:
            flagged, reason = detector.decide({})
        else:
            record = trace.model_dump(mode="json")
            # The same feature code as for the stored dataset, on a request
            # whose outcome is not known yet.
            row = {"timestamp": record["timestamp"], **state.history.features(record)}
            flagged, reason = detector.decide(row)
            # A rejected request does not reach the device; the history must
            # remember it as such.
            rejected = flagged and state.enforce
            state.history.update({**record, "status": "blocked" if rejected else "success"})
        rejected = flagged and state.enforce
    return Verdict(
        trace_id=trace.trace_id,
        decision="REJECT" if rejected else "ALLOW",
        reason=reason,
        detector=detector.name,
        flagged=flagged,
    )


@app.get("/detector")
def current_detector():
    return {"detector": state.detector.name}


@app.post("/detector")
def replace_detector(choice: DetectorChoice):
    """Exchange the detector while the service keeps running. The new one is
    loaded first; requests are answered by the old one until it is in place."""
    started = time.perf_counter()
    try:
        fresh = load(choice.kind, MODELS)
    except (ValueError, FileNotFoundError, ImportError) as error:
        # ImportError: the tree detector needs scikit-learn, which a slim
        # deployment may not have. The detector in place keeps answering.
        raise HTTPException(status_code=400, detail=str(error))
    with state.lock:
        previous, state.detector = state.detector.name, fresh
    return {"previous": previous, "detector": fresh.name, "seconds": time.perf_counter() - started}


@app.post("/reset")
def reset():
    if not SIMULATION_MODE:
        raise HTTPException(status_code=403, detail="reset is only available in simulation mode")
    with state.lock:
        state.history = HomeHistory()
    return {"status": "history cleared"}

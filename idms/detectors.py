"""Detectors the IDMS can run. They share one small interface:

    decide(row) -> (flagged, reason)

where `row` is the feature row of one request (features/extract.py). The IDMS
does not care which detector it holds; one can be exchanged for another while
the service runs.
"""
import json
import pickle
from pathlib import Path
from typing import Protocol

from baselines.rules import Rules


class Detector(Protocol):
    name: str
    needs_features: bool

    def decide(self, row: dict) -> tuple[bool, str]: ...


class AllowAll:
    """No detection. The state of the IDMS when datasets are generated."""

    name = "none"
    needs_features = False

    def decide(self, row: dict) -> tuple[bool, str]:
        return False, "no detector loaded"


class RuleDetector:
    name = "rules"
    needs_features = True

    def __init__(self, path: Path):
        self.rules = Rules(**json.loads(path.read_text(encoding="utf-8")))

    def decide(self, row: dict) -> tuple[bool, str]:
        reasons = self.rules.reasons(row)
        return bool(reasons), "rules: " + (", ".join(reasons) if reasons else "nothing fired")


LEARNED = ("tree", "forest", "logistic")


class ModelDetector:
    """A learned detector as saved by experiments/export_detectors.py: the
    encoder of its training homes, the fitted model and its alarm threshold."""

    needs_features = True

    def __init__(self, name: str, path: Path):
        with path.open("rb") as file:
            saved = pickle.load(file)
        self.name = name
        # The tree was first saved under the key "tree"; that file is kept as it is.
        self.model = saved["model"] if "model" in saved else saved["tree"]
        self.encoder, self.threshold = saved["encoder"], saved["threshold"]

    def decide(self, row: dict) -> tuple[bool, str]:
        score = float(self.model.predict_proba(self.encoder.transform([row]))[0, 1])
        return score >= self.threshold, f"{self.name}: score {score:.2f}, threshold {self.threshold:.2f}"


def load(kind: str, folder: Path) -> Detector:
    if kind == "none":
        return AllowAll()
    if kind == "rules":
        return RuleDetector(folder / "rules.json")
    if kind in LEARNED:
        return ModelDetector(kind, folder / f"{kind}.pkl")
    raise ValueError(f"unknown detector '{kind}'")

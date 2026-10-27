"""Train the two simple classifiers of the feasibility check.

    python -m experiments.feasibility.train

A decision tree and an SVM are fitted on 60 synthetic days (scenario.py, seed 1)
and saved in the format the IDMS loads (encoder, model, alarm threshold), next to
the placeholder rule. The threshold is 0.5: nothing is tuned, since the point is
to show trained models running in the IDMS, not to optimize them.
"""
import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from detectors.tree import Encoder
from experiments.feasibility.scenario import TRAIN_START, generate, training_rows

OUT = Path("experiments/feasibility/models")
RULE = Path("experiments/mvp/rules.json")


def main() -> None:
    requests = generate(seed=1, days=60, start=TRAIN_START, misuse_rate=0.4)
    rows, labels = training_rows(requests)
    encoder = Encoder().fit(rows)
    table, target = encoder.transform(rows), np.array(labels)

    tree = DecisionTreeClassifier(max_depth=6, min_samples_leaf=3, class_weight="balanced", random_state=0)
    tree.fit(table, target)
    svm = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                        CalibratedClassifierCV(SVC(kernel="rbf", class_weight="balanced", random_state=0), ensemble=False))
    svm.fit(table, target)

    OUT.mkdir(parents=True, exist_ok=True)
    for name, model in (("tree", tree), ("svm", svm)):
        with (OUT / f"{name}.pkl").open("wb") as file:
            pickle.dump({"encoder": encoder, "model": model, "threshold": 0.5}, file)
    (OUT / "rules.json").write_text(RULE.read_text(encoding="utf-8"), encoding="utf-8")
    note = {"training": {"seed": 1, "days": 60, "requests": len(requests), "seen_by_idms": len(rows),
                         "misuse": int(target.sum())},
            "tree": {"max_depth": 6, "min_samples_leaf": 3, "leaves": int(tree.get_n_leaves())},
            "svm": {"kernel": "rbf", "missing values": "median", "scaling": "standard", "probabilities": "calibrated (sigmoid, 5-fold)"},
            "threshold": 0.5, "features": len(encoder.names)}
    (OUT / "README.json").write_text(json.dumps(note, indent=1), encoding="utf-8")
    print(json.dumps(note, indent=1))


if __name__ == "__main__":
    main()

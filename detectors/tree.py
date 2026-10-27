"""The encoder saved with each trained detector (experiments/feasibility/models).

It turns the feature rows of the IDMS into a table of numbers; what it needs to
know (the categories, which columns vary) is learned from the training rows.
"""
import math

import numpy as np

from features.extract import CATEGORICAL, NUMERIC


class Encoder:
    def __init__(self, drop: set[str] = frozenset(), extra_categorical: tuple[str, ...] = ()):
        self.drop = set(drop)
        self.extra_categorical = tuple(extra_categorical)

    def fit(self, rows: list[dict]) -> "Encoder":
        self.categories = {
            name: sorted({row[name] for row in rows})
            for name in [*CATEGORICAL, *self.extra_categorical]
            if name not in self.drop
        }
        self.numeric = [
            name for name in NUMERIC if name not in self.drop and len({row[name] for row in rows}) > 1
        ]
        self.names = [f"{name}={value}" for name, values in self.categories.items() for value in values] + self.numeric
        return self

    def transform(self, rows: list[dict]) -> np.ndarray:
        table = np.empty((len(rows), len(self.names)))
        for position, row in enumerate(rows):
            values = [float(row[name] == value) for name, known in self.categories.items() for value in known]
            # A value that does not exist (no earlier request, no temperature
            # for a lamp) stays missing.
            values += [math.nan if row[name] is None else row[name] for name in self.numeric]
            table[position] = values
        return table

"""Rule baseline: what a careful administrator would write by hand.

Six rules, each aimed at one kind of misuse; a request is flagged when any
rule fires. Two versions are scored:

  expert  thresholds fixed in advance from common sense, with no data
  tuned   thresholds chosen on the training homes so that each rule flags at
          most BUDGET of their normal requests

Any learned detector has to beat both to justify itself.
"""
from dataclasses import dataclass, field

BUDGET = 0.005


@dataclass
class Rules:
    burst: float = 10          # requests in the home during the last minute
    switching: float = 4       # state changes of the device in the last ten minutes
    repetition: float = 3      # identical requests in the last hour
    refusals: float = 2        # refused requests of the account in the last ten minutes
    coldest: float = 16.0      # setpoints outside [coldest, hottest]
    hottest: float = 26.0
    night_unlock: bool = True  # the door unlocked between midnight and five
    fired: dict[str, int] = field(default_factory=dict, repr=False)

    def reasons(self, row: dict) -> list[str]:
        found = []
        if row["n_home_60s"] >= self.burst:
            found.append("burst")
        if row["n_state_changes_device_10min"] >= self.switching:
            found.append("switching")
        if row["n_same_request_1h"] >= self.repetition:
            found.append("repetition")
        if row["n_denied_account_10min"] >= self.refusals:
            found.append("refusals")
        requested = row["requested_temperature"]
        if requested is not None and not self.coldest <= requested <= self.hottest:
            found.append("setpoint")
        if self.night_unlock and row["action"] == "unlock" and int(row["timestamp"][11:13]) < 5:
            found.append("night_unlock")
        return found

    def flag(self, rows: list[dict]) -> list[bool]:
        flags = []
        for row in rows:
            reasons = self.reasons(row)
            for reason in reasons:
                self.fired[reason] = self.fired.get(reason, 0) + 1
            flags.append(bool(reasons))
        return flags


def quantile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))]


def tune(rows: list[dict], labels: list[dict], budget: float = BUDGET) -> Rules:
    """Thresholds from normal requests of the training homes only: each rule
    is made as sensitive as it can be while staying within the budget."""
    normal = [row for row, label in zip(rows, labels) if label["ground_truth"] == 0]
    rules = Rules()
    for name, column in (
        ("burst", "n_home_60s"),
        ("switching", "n_state_changes_device_10min"),
        ("repetition", "n_same_request_1h"),
        ("refusals", "n_denied_account_10min"),
    ):
        values = [row[column] for row in normal]
        threshold = 1
        while sum(value >= threshold for value in values) / len(values) > budget:
            threshold += 1
        setattr(rules, name, threshold)
    setpoints = [row["requested_temperature"] for row in normal if row["requested_temperature"] is not None]
    if setpoints:
        rules.coldest, rules.hottest = quantile(setpoints, budget / 2), quantile(setpoints, 1 - budget / 2)
    unlocks = sum(row["action"] == "unlock" and int(row["timestamp"][11:13]) < 5 for row in normal)
    rules.night_unlock = unlocks / len(normal) <= budget
    return rules

"""Figure 7 of the architecture paper: latency of each request with each detector.

    python -m experiments.feasibility.plot

Reads results/feasibility/requests.csv (796 requests per detector: 199 x 4 runs)
and summary.json, and writes results/feasibility/latency.png (300 dpi) and
latency.svg: for each detector, a box of the whole-request latency (quartiles,
whiskers from the 5th to the 95th percentile, points outside) and a diamond at
the median latency of the IDMS alone. Colours are those of the paper's other
figures (papers/msids_architecture/figures.py).
"""
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

OUT = Path("results/feasibility")
INK, FILL, EDGE, ACCENT, MUTED = "#1f2933", "#e4edf5", "#3e4c59", "#b03a2e", "#9aa5b1"
LABELS = {"none": "None", "rules": "Rule", "tree": "Decision tree", "svm": "SVM"}


def main() -> None:
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    order = list(LABELS)
    whole = {d: [] for d in order}
    with open(OUT / "requests.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            whole[row["detector"]].append(float(row["milliseconds"]))
    alone = [summary["detectors"][d]["idms_alone_ms"]["median"] for d in order]

    plt.rcParams.update({"font.family": "Arial", "font.size": 9})
    fig, ax = plt.subplots(figsize=(6.3, 2.8))
    ys = list(range(len(order)))
    ax.boxplot([whole[d] for d in order], positions=ys, orientation="horizontal", whis=(5, 95), widths=0.5,
               patch_artist=True, boxprops=dict(facecolor=FILL, edgecolor=EDGE, lw=0.9),
               medianprops=dict(color=INK, lw=1.6), whiskerprops=dict(color=EDGE, lw=0.9),
               capprops=dict(color=EDGE, lw=0.9),
               flierprops=dict(marker="o", ms=2, mfc=MUTED, mec="none"))
    ax.scatter(alone, ys, marker="D", s=40, color=ACCENT, zorder=3)
    ax.set_yticks(ys, [LABELS[d] for d in order])
    ax.invert_yaxis()
    ax.set_xlim(0, 70)
    ax.set_xlabel("Latency per request (ms)")
    ax.grid(axis="x", color="#e5e5e5", lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend([Patch(facecolor=FILL, edgecolor=EDGE),
               Line2D([], [], marker="D", ls="none", color=ACCENT)],
              ["Latency of the whole request through the gateway (box: quartiles; whiskers: 5th to 95th percentile)",
               "Latency of the IDMS alone (median)"],
              loc="upper left", bbox_to_anchor=(-0.02, -0.2), frameon=False, fontsize=8.5)
    fig.tight_layout()
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"latency.{ext}", dpi=300, bbox_inches="tight")
    print({LABELS[d]: (len(whole[d]), a) for d, a in zip(order, alone)})


if __name__ == "__main__":
    main()

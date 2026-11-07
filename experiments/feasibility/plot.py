"""Figure 7 of the architecture paper: median latency of a request with each detector.

    python -m experiments.feasibility.plot

Reads results/feasibility/summary.json (medians over 796 requests per detector:
199 x 4 runs) and writes results/feasibility/latency.png (300 dpi) and latency.svg:
for each detector, the whole request (user to device) and the IDMS alone, with the
0.1 s limit from which a user notices a delay (Nielsen, Usability Engineering,
1993). Colours are those of the paper's other figures
(papers/msids_architecture/figures.py).
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path("results/feasibility")
INK, FILL, EDGE, ACCENT, MUTED = "#1f2933", "#d6e4f0", "#3e4c59", "#b03a2e", "#9aa5b1"
LABELS = {"none": "None", "rules": "Rule", "tree": "Decision tree", "svm": "SVM"}


def main() -> None:
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    order = list(LABELS)
    whole = [summary["detectors"][d]["latency_ms"]["median"] for d in order]
    alone = [summary["detectors"][d]["idms_alone_ms"]["median"] for d in order]

    plt.rcParams.update({"font.family": "Arial", "font.size": 9})
    fig, ax = plt.subplots(figsize=(6.3, 2.8))
    ys, h = range(len(order)), 0.36
    ax.barh([y - h / 2 for y in ys], whole, height=h, color=FILL, edgecolor=EDGE, lw=0.8,
            label="Whole request (user to device)")
    ax.barh([y + h / 2 for y in ys], alone, height=h, color=ACCENT, label="IDMS alone (its decision)")
    for y, w, a in zip(ys, whole, alone):
        # 17.45 is written 17.5, as in Table 8
        ax.text(w + 1.2, y - h / 2, f"{w + 1e-9:.1f} ms", va="center", fontsize=8.5, color=INK)
        ax.text(a + 1.2, y + h / 2, f"{a + 1e-9:.1f} ms", va="center", fontsize=8.5, color=ACCENT)
    ax.axvline(100, color=MUTED, ls="--", lw=1)
    ax.text(98.5, -0.55, "0.1 s: a user starts\nto notice a delay", ha="right", va="top", fontsize=8, color=EDGE)
    ax.set_yticks(list(ys), [LABELS[d] for d in order])
    ax.invert_yaxis()
    ax.set_xlim(0, 105)
    ax.set_xlabel("Median latency (ms)")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.22), ncol=2, frameon=False, fontsize=8.5)
    fig.tight_layout()
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"latency.{ext}", dpi=300, bbox_inches="tight")
    print({LABELS[d]: (w, a) for d, w, a in zip(order, whole, alone)})


if __name__ == "__main__":
    main()

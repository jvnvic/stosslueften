"""Draws the flow diagram at the top of each model notebook: data -> training -> prediction.

Run from the ml/ folder after adding or changing a version:  python flow_diagrams.py
It writes images/<version>_flow.png for every version in VERSIONS. Steps that a version
changes against the previous one are drawn with a thick border and a "new in ..." tag.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

INK, INK_2, MUTED, LINE = "#0b0b0b", "#52514e", "#898781", "#c3c2b7"
STAGE_COLOUR = {"data": "#898781", "train": "#2a78d6", "predict": "#eb6834"}

BOX_W, BOX_H, COLUMN = 1.74, 1.08, 1.98      # box size and distance between box centres
Y_TRAIN, Y_MIDDLE, Y_PREDICT = 3.75, 2.38, 1.0  # centres of the three rows


def x_of(column):
    return 0.95 + column * COLUMN


# One entry per version: the three data steps, the training lane, the prediction lane,
# a note, and the steps that are new compared with the previous version.
VERSIONS = {
    "v0_base": {
        "data": [
            ("dataset_550.csv", "550 simulations:\n10 inputs, results"),
            ("Keep status = ok", "541 simulations\n(9 failed: rerun later)"),
            ("Shared split", "80 % train, 20 % test,\nstratified by layout\nand by t90 reached"),
        ],
        "train": [
            ("Training cases", "432, of which the\n372 with a t90 value"),
            ("Inputs and target", "X: 10 setup values\ny: t90 [s]"),
            ("Preprocessing: fit", "numeric: standardise\ncategorical: one-hot"),
            ("Models: fit", "mean value, Linear,\nRidge, DecisionTree"),
        ],
        "predict": [
            ("Test cases", "109, of which the\n93 with a t90 value"),
            ("Inputs", "X: 10 setup values"),
            ("Preprocessing", "the scaling and\ncategories learned\nin training"),
            ("Models: predict", "t90 [s]"),
            ("Scores", "MAE, RMSE, R²\nagainst simulated t90\n→ results/v0_base.csv"),
        ],
        "note": ("v0: base version", "The seminar template (unit 3)\napplied to our dataset:\nt90 is predicted directly."),
        "new": set(),
    },
    "v1_tau": {
        "data": None,  # same as v0
        "train": [
            ("Training cases", "all 432, also those\nwithout a t90 value"),
            ("Inputs and target", "X: 10 setup values\ny: log(τ)"),
            ("Preprocessing: fit", "numeric: standardise\ncategorical: one-hot"),
            ("Models: fit", "mean value, Linear,\nRidge, DecisionTree"),
        ],
        "predict": [
            ("Test cases", "all 109"),
            ("Inputs", "X: 10 setup values"),
            ("Preprocessing", "the scaling and\ncategories learned\nin training"),
            ("Models: predict", "log(τ)"),
            ("Back to t90", "τ = exp(prediction)\nt90 = ln(10) · τ"),
            ("Scores", "t90 on the 93 (as v0),\nτ on all 109,\nt90 > 600 s found?"),
        ],
        "note": ("v1: predict τ", "τ exists for every case, so\nno case is dropped, and\nexp(·) keeps it positive."),
        "new": {"train 0", "train 1", "predict 0", "predict 3", "predict 4", "predict 5"},
    },
    "v2_log_wind": {
        "data": None,
        "train": [
            ("Training cases", "all 432, also those\nwithout a t90 value"),
            ("Inputs and target", "X: 10 setup values\ny: log(τ)"),
            ("Preprocessing: fit", "wind → log(wind)\nnumeric: standardise\ncategorical: one-hot"),
            ("Models: fit", "mean value, Linear,\nRidge, DecisionTree"),
        ],
        "predict": [
            ("Test cases", "all 109"),
            ("Inputs", "X: 10 setup values"),
            ("Preprocessing", "log(wind), then the\nscaling and categories\nlearned in training"),
            ("Models: predict", "log(τ)"),
            ("Back to t90", "τ = exp(prediction)\nt90 = ln(10) · τ"),
            ("Scores", "t90 on the 93 (as v0),\nτ on all 109,\nt90 > 600 s found?"),
        ],
        "note": ("v2: log(wind speed)", "τ ~ 1 / wind speed is a\nstraight line between\nlog(τ) and log(wind)."),
        "new": {"train 2", "predict 2"},
    },
    "v3_cv_tuning": {
        "data": None,
        "train": [
            ("Development data", "the 432 training cases"),
            ("Inputs, targets", "X: 10 setup values\ny: log(τ), and for the\nclassifier: t90 > 600 s?"),
            ("Cross-validation", "5 folds: each model is\nfitted 5 times, scored\non the held-out fold"),
            ("Grid search", "tree depth, leaf size,\nbest one refitted\non all 432 cases"),
        ],
        "predict": [
            ("Test cases", "all 109, used once,\nafter the selection"),
            ("Inputs", "X: 10 setup values"),
            ("Preprocessing", "log(wind), scaling and\ncategories of the\nrefitted pipeline"),
            ("Best model", "predicts log(τ)"),
            ("Back to t90", "τ = exp(prediction)\nt90 = ln(10) · τ"),
            ("Scores", "log(τ) as in unit 4,\nt90 on the 93 (as v0),\nclassification report"),
        ],
        "note": ("v3: evaluation and tuning", "Seminar unit 4 with our data:\nmodels and settings chosen\nby cross-validation only."),
        "new": {"train 1", "train 2", "train 3", "predict 0", "predict 5"},
        "handover": [(4, "best_estimator_:\nthe whole pipeline,\nrefitted")],
    },
}

DEFAULT_HANDOVER = [(3, "fitted scaling\nand categories"), (4, "fitted models")]


def box(ax, x, y, title, detail, stage, new_in=None):
    colour = STAGE_COLOUR[stage]
    ax.add_patch(FancyBboxPatch(
        (x - BOX_W / 2, y - BOX_H / 2), BOX_W, BOX_H,
        boxstyle="round,pad=0,rounding_size=0.08",
        facecolor="white", edgecolor=colour, linewidth=2.4 if new_in else 1.1, zorder=2,
    ))
    top = y + BOX_H / 2
    ax.text(x, top - 0.13, title, ha="center", va="top", fontsize=9, fontweight="bold", color=INK, zorder=3)
    ax.text(x, top - 0.40, detail, ha="center", va="top", fontsize=8, color=INK_2, linespacing=1.3, zorder=3)
    if new_in:
        ax.text(x + BOX_W / 2 - 0.06, top, f" new in {new_in} ", ha="right", va="center", fontsize=7,
                color="white", zorder=4,
                bbox=dict(boxstyle="round,pad=0.25,rounding_size=0.15", facecolor=colour, edgecolor="none"))


def arrow(ax, start, end, label=None):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=11,
                                 color=MUTED, linewidth=1.1, zorder=1, shrinkA=0, shrinkB=0))
    if label:
        ax.text(start[0] + 0.08, (start[1] + end[1]) / 2, label, ha="left", va="center",
                fontsize=7.5, color=INK_2, linespacing=1.25)


def draw(version, spec, data_steps, out):
    short = version.split("_")[0]
    new_in = lambda key: short if key in spec["new"] else None

    fig, ax = plt.subplots(figsize=(13.9, 4.5))
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 13.9)
    ax.set_ylim(0.3, 4.75)
    ax.axis("off")

    # Data column, top to bottom
    rows = [Y_TRAIN, Y_MIDDLE, Y_PREDICT]
    for i, (title, detail) in enumerate(data_steps):
        box(ax, x_of(0), rows[i], title, detail, "data")
        if i:
            arrow(ax, (x_of(0), rows[i - 1] - BOX_H / 2), (x_of(0), rows[i] + BOX_H / 2))
    ax.text(x_of(0) - BOX_W / 2, Y_TRAIN + BOX_H / 2 + 0.17, "DATA", fontsize=8.5, fontweight="bold", color=MUTED)

    # The split forks into the two lanes
    fork_x = (x_of(0) + x_of(1)) / 2
    ax.plot([x_of(0) + BOX_W / 2, fork_x, fork_x], [Y_PREDICT, Y_PREDICT, Y_TRAIN],
            color=MUTED, linewidth=1.1, zorder=1)
    arrow(ax, (fork_x, Y_TRAIN), (x_of(1) - BOX_W / 2, Y_TRAIN))
    arrow(ax, (fork_x, Y_PREDICT), (x_of(1) - BOX_W / 2, Y_PREDICT))

    for lane, y, label in [("train", Y_TRAIN, "TRAINING  (training cases)"),
                           ("predict", Y_PREDICT, "PREDICTION AND TEST  (test cases)")]:
        ax.text(x_of(1) - BOX_W / 2, y + BOX_H / 2 + 0.17, label, fontsize=8.5, fontweight="bold",
                color=STAGE_COLOUR[lane])
        steps = spec[lane]
        for i, (title, detail) in enumerate(steps):
            box(ax, x_of(i + 1), y, title, detail, lane, new_in(f"{lane} {i}"))
            if i:
                arrow(ax, (x_of(i) + BOX_W / 2, y), (x_of(i + 1) - BOX_W / 2, y))

    # What training hands over to the prediction
    for column, label in spec.get("handover", DEFAULT_HANDOVER):
        arrow(ax, (x_of(column), Y_TRAIN - BOX_H / 2), (x_of(column), Y_PREDICT + BOX_H / 2), label)

    # Note on what this version is about, next to the training lane
    title, text = spec["note"]
    left = x_of(5) - BOX_W / 2
    ax.add_patch(FancyBboxPatch((left, Y_TRAIN - BOX_H / 2), 2 * COLUMN - (COLUMN - BOX_W), BOX_H,
                                boxstyle="round,pad=0,rounding_size=0.08", facecolor="#f4f4f1",
                                edgecolor="none", zorder=2))
    ax.text(left + 0.15, Y_TRAIN + BOX_H / 2 - 0.13, title, va="top", fontsize=9, fontweight="bold", color=INK, zorder=3)
    ax.text(left + 0.15, Y_TRAIN + BOX_H / 2 - 0.40, text, va="top", fontsize=8, color=INK_2, linespacing=1.3, zorder=3)

    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    data_steps = None
    for version, spec in VERSIONS.items():
        data_steps = spec["data"] or data_steps
        draw(version, spec, data_steps, Path("images") / f"{version}_flow.png")

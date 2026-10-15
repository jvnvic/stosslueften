"""Compare method A (steady flow + tracer) with method B (time-varying flow) on solved cases.

Usage, from the repository root with the venv active (OpenFOAM is not needed):
    python -m analysis.compare_methods configs/comparison/cmp_*.yaml --out docs/images/method_comparison.png

Every case needs both results: `python -m cfd.queue --transient <configs>` computes them.
Prints one table row per case and draws the two air-replacement curves of each case.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files only, no window
import matplotlib.pyplot as plt
import numpy as np

from analysis.visualize import GRID, INK, MUTED, SERIES_1, SERIES_2, SURFACE
from cfd.config import CaseConfig, ConfigError, load_config

CASES = Path("cases")
DEFAULT_WINDOW_M = 0.05  # cell size at the windows of the standard (medium) mesh


def describe(cfg: CaseConfig) -> str:
    """Short case label, e.g. 'same wall, turn 90 / tilt 6, 3 m/s' (plus the cell size if not standard)."""
    windows = " / ".join(f"{w.mode} {w.angle_deg:g}" for w in (cfg.window1, cfg.window2))
    scale = cfg.mesh.window_m / DEFAULT_WINDOW_M
    mesh = "" if math.isclose(scale, 1) else f", cells ×{scale:.2g}"
    return f"{cfg.layout.replace('_', ' ')}, {windows}, {cfg.wind_speed_ms:g} m/s{mesh}"


def load_case(cfg: CaseConfig) -> dict:
    """Both curves and the metrics of one case. B's curve is used only as far as it was simulated."""
    case_dir = CASES / cfg.case_id
    summary = json.loads((case_dir / "summary.json").read_text())
    if "transient" not in summary:
        raise SystemExit(f"{cfg.case_id} has no method B result: run `python -m cfd.queue --transient` for it")
    a = np.loadtxt(case_dir / "fresh_fraction.csv", delimiter=",", skiprows=1)
    b = np.loadtxt(case_dir / "fresh_fraction_transient.csv", delimiter=",", skiprows=1)
    b = b[b[:, 0] <= summary["transient"]["tracer_simulated_s"]]
    n = min(len(a), len(b))
    return {"label": describe(cfg), "A": summary, "B": summary["transient"], "curve_a": a, "curve_b": b,
            "largest_gap": float(np.max(np.abs(a[:n, 1] - b[:n, 1]))) * 100}


def table(cases: list[dict]) -> str:
    def t90(value):
        return "–" if value is None or math.isnan(value) else f"{value:.0f}"

    lines = ["| Case | τ A [s] | τ B [s] | A vs B | t90 A [s] | t90 B [s] | largest gap [% points] |",
             "|---|---|---|---|---|---|---|"]
    for c in cases:
        tau_a, tau_b = c["A"]["tau_s"], c["B"]["tau_s"]
        lines.append(f"| {c['label']} | {tau_a:.0f} | {tau_b:.0f} | {(tau_a / tau_b - 1) * 100:+.0f} % | "
                     f"{t90(c['A']['t90_s'])} | {t90(c['B']['t90_s'])} | {c['largest_gap']:.1f} |")
    return "\n".join(lines)


def plot(cases: list[dict], out: Path, columns: int = 4) -> None:
    rows = math.ceil(len(cases) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(3.2 * columns, 2.5 * rows), dpi=130,
                             sharex=True, sharey=True, facecolor=SURFACE, squeeze=False)
    for ax, c in zip(axes.flat, cases):
        ax.set_facecolor(SURFACE)
        ax.plot(c["curve_a"][:, 0], 100 * c["curve_a"][:, 1], color=SERIES_1, linewidth=1.8)
        ax.plot(c["curve_b"][:, 0], 100 * c["curve_b"][:, 1], color=SERIES_2, linewidth=1.8)
        tau_a, tau_b = c["A"]["tau_s"], c["B"]["tau_s"]
        ax.set_title(f"{c['label']}\nτ: A {tau_a:.0f} s, B {tau_b:.0f} s ({(tau_a / tau_b - 1) * 100:+.0f} %)",
                     loc="left", fontsize=7.5, color=INK)
        ax.grid(color=GRID, linewidth=0.6)
        ax.tick_params(colors=MUTED, labelsize=7)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
    for ax in axes.flat[len(cases):]:
        ax.set_visible(False)
    ax0 = axes.flat[0]
    ax0.set_xlim(0, 600)
    ax0.set_ylim(0, 100)
    for ax in axes[-1]:
        ax.set_xlabel("time [s]", color=INK, fontsize=8)
    for ax in axes[:, 0]:
        ax.set_ylabel("air replaced [%]", color=INK, fontsize=8)
    handles = [plt.Line2D([], [], color=SERIES_1, linewidth=2), plt.Line2D([], [], color=SERIES_2, linewidth=2)]
    fig.legend(handles, ["A: steady flow + tracer", "B: time-varying flow (URANS)"], loc="upper right",
               ncol=2, frameon=False, fontsize=9, labelcolor=INK)
    fig.suptitle("Air replacement, method A vs B", x=0.01, ha="left", color=INK, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Compare method A and B on solved cases.")
    parser.add_argument("configs", nargs="+", type=Path, help="case YAML files, in plot order")
    parser.add_argument("--out", type=Path, help="output PNG file for the curves (optional)")
    args = parser.parse_args(argv)
    try:
        cases = [load_case(load_config(config)) for config in args.configs]
    except ConfigError as error:
        raise SystemExit(f"Invalid configuration: {error}")
    print(table(cases))
    if args.out:
        plot(cases, args.out)
        print(f"saved {args.out}")


if __name__ == "__main__":
    main()

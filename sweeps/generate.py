"""Draw the cases of a sweep run from its spec file (DATASET_PLAN.md §2, PLAN.md §2).

Usage, from the repository root (any OS; OpenFOAM is not needed):
    python -m sweeps.generate configs/sweep/train-v1/spec.yaml

Writes, next to the spec file:
    <run_id>_001.yaml …   one complete case each, in the format of configs/default.yaml
    manifest.json         seed, counts, redraws, coverage per input, code commit
    coverage.png          the sampled inputs plotted against each other

Running it again with the same spec writes the same files.

Sampling: exactly equal shares per layout; within each layout a Latin hypercube spreads every
input evenly over its range. A draw whose windows overlap or whose sashes collide gets new window
positions (uniform), and keeps its other values. The cases are interleaved by layout, so every
block of three cases holds one of each, and any first N cases (e.g. a pilot) stay balanced.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import numpy as np
import yaml
from scipy.stats import qmc

from cfd.config import ConfigError, config_from_dict, load_config
from geometry.windows import LAYOUT_WALLS, place_windows, walls

LAYOUTS = ("same_wall", "opposite_walls", "adjacent_walls")
# One Latin hypercube dimension per sampled input, in this order.
DIMS = ("window1_x_m", "window2_x_m", "window1_mode", "window2_mode", "window1_angle_deg",
        "window2_angle_deg", "window1_hinge", "window2_hinge", "wind_speed_ms")
MAX_REDRAWS = 1000
SPEC_KEYS = {"run_id", "split", "n_cases", "seed", "base_config", "turn_share", "turn_angle_deg",
             "tilt_angle_deg", "hinge", "wind_speed_ms"}


def load_spec(path: Path) -> dict:
    spec = yaml.safe_load(path.read_text())
    missing, unknown = SPEC_KEYS - spec.keys(), spec.keys() - SPEC_KEYS
    if missing or unknown:
        raise SystemExit(f"{path}: missing keys {sorted(missing)}, unknown keys {sorted(unknown)}")
    if spec["split"] not in ("train", "test") or spec["hinge"] not in ("sampled", "left", "right"):
        raise SystemExit(f"{path}: split must be train or test, hinge sampled, left or right")
    return spec


def position_range(base, wall_name: str) -> tuple[float, float]:
    """Window centre positions that keep the frame clear of both room corners (PLAN.md §2)."""
    wall = walls(base.room)[wall_name]
    margin = base.clearance_m + base.window_size.width_m / 2
    return margin, wall.length_m - margin


def inputs_from_unit(u: np.ndarray, spec: dict, ranges: list[tuple[float, float]]) -> dict:
    """Turn one point of the unit hypercube into input values (rounded for readable files)."""
    lo_angle, hi_angle = spec["turn_angle_deg"]
    lo_wind, hi_wind = spec["wind_speed_ms"]
    values = {}
    for i, name in enumerate(("window1", "window2")):
        lo, hi = ranges[i]
        mode = "turn" if u[2 + i] < spec["turn_share"] else "tilt"
        values[name] = {
            "x_m": round(lo + u[i] * (hi - lo), 3),
            "mode": mode,
            "angle_deg": round(lo_angle + u[4 + i] * (hi_angle - lo_angle), 1) if mode == "turn"
            else spec["tilt_angle_deg"],
            # a tilted window has no hinge side; its config says "left" (the CSV writes "none")
            "hinge": ("left" if u[6 + i] < 0.5 else "right") if spec["hinge"] == "sampled" and mode == "turn"
            else ("left" if mode == "tilt" else spec["hinge"]),
        }
    values["wind_speed_ms"] = round(lo_wind + u[8] * (hi_wind - lo_wind), 2)
    return values


def _config_dict(base_dict: dict, layout: str, values: dict) -> dict:
    return {**base_dict, "case_id": "draft", "layout": layout, "window1": values["window1"],
            "window2": values["window2"], "wind_speed_ms": values["wind_speed_ms"]}


def draw_layout(spec: dict, base_dict: dict, layout: str, n: int, seed: int) -> tuple[list[dict], int]:
    """n valid input sets for one layout, and the number of position redraws that were needed."""
    base = config_from_dict(base_dict)
    ranges = [position_range(base, wall) for wall in LAYOUT_WALLS[layout]]
    points = qmc.LatinHypercube(d=len(DIMS), rng=np.random.default_rng(seed)).random(n)
    redraw_rng = np.random.default_rng(seed + 1_000_000)
    cases, redraws = [], 0
    for u in points:
        u = u.copy()
        for _ in range(MAX_REDRAWS):
            values = inputs_from_unit(u, spec, ranges)
            try:
                place_windows(config_from_dict(_config_dict(base_dict, layout, values)))
                break
            except ConfigError:  # windows overlap or sashes collide: new positions, other values kept
                u[:2] = redraw_rng.random(2)
                redraws += 1
        else:
            raise SystemExit(f"no valid window positions found for a {layout} case after {MAX_REDRAWS} redraws")
        cases.append({"layout": layout, **values})
    return cases, redraws


def case_text(base_text: str, case_id: str, case: dict, header: str) -> str:
    """The base config with this case's values put in; comments and layout stay as in the base."""
    def window(w):
        return f"{{x_m: {w['x_m']}, mode: {w['mode']}, angle_deg: {w['angle_deg']}, hinge: {w['hinge']}}}"

    text = re.sub(r"^case_id: \S+", f"case_id: {case_id}", base_text, count=1, flags=re.M)
    text = re.sub(r"^layout: \S+", f"layout: {case['layout']}", text, count=1, flags=re.M)
    text = re.sub(r"^window1: \{[^}]*\}", f"window1: {window(case['window1'])}", text, count=1, flags=re.M)
    text = re.sub(r"^window2: \{[^}]*\}", f"window2: {window(case['window2'])}", text, count=1, flags=re.M)
    text = re.sub(r"^wind_speed_ms: \S+", f"wind_speed_ms: {case['wind_speed_ms']}", text, count=1, flags=re.M)
    return header + text


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def coverage(cases: list[dict]) -> dict:
    """Min, max and mean of every numeric input, and counts of the categorical ones."""
    def numbers(key, window=None, turn_only=False):
        rows = [c[window] if window else c for c in cases]
        return [r[key] for r in rows if not turn_only or r["mode"] == "turn"]

    stats = {}
    for name, values in (("window1_x_m", numbers("x_m", "window1")), ("window2_x_m", numbers("x_m", "window2")),
                         ("window1_angle_deg (turned)", numbers("angle_deg", "window1", True)),
                         ("window2_angle_deg (turned)", numbers("angle_deg", "window2", True)),
                         ("wind_speed_ms", numbers("wind_speed_ms"))):
        stats[name] = {"min": min(values), "max": max(values), "mean": round(float(np.mean(values)), 3)}
    pairs = [f"{c['window1']['mode']}/{c['window2']['mode']}" for c in cases]
    stats["mode_pairs"] = {p: pairs.count(p) for p in sorted(set(pairs))}
    hinges = [c[w]["hinge"] for c in cases for w in ("window1", "window2") if c[w]["mode"] == "turn"]
    stats["hinges_of_turned_windows"] = {h: hinges.count(h) for h in sorted(set(hinges))}
    return stats


def plot_coverage(cases: list[dict], title: str, out: Path) -> None:
    """Every pair of numeric inputs as a scatter plot, one colour per layout."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from analysis.visualize import GRID, INK, MUTED, SURFACE

    # categorical palette slots 1-3 in fixed order; same wall in orange like method B elsewhere
    colors = {"opposite_walls": "#2a78d6", "same_wall": "#eb6834", "adjacent_walls": "#1baf7a"}
    columns = {
        "window 1 position [m]": lambda c: c["window1"]["x_m"],
        "window 2 position [m]": lambda c: c["window2"]["x_m"],
        "window 1 angle [°]": lambda c: c["window1"]["angle_deg"],
        "window 2 angle [°]": lambda c: c["window2"]["angle_deg"],
        "wind speed [m/s]": lambda c: c["wind_speed_ms"],
    }
    names = list(columns)
    k = len(names)
    fig, axes = plt.subplots(k, k, figsize=(2.0 * k, 2.0 * k), dpi=110, facecolor=SURFACE)
    for row, ny in enumerate(names):
        for col, nx in enumerate(names):
            ax = axes[row, col]
            ax.set_facecolor(SURFACE)
            ax.tick_params(colors=MUTED, labelsize=6.5, length=2)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            for side in ("left", "bottom"):
                ax.spines[side].set_color(GRID)
            if col > row:
                ax.set_visible(False)
                continue
            for layout in ("opposite_walls", "same_wall", "adjacent_walls"):
                sub = [c for c in cases if c["layout"] == layout]
                xs = [columns[nx](c) for c in sub]
                if row == col:
                    ax.hist(xs, bins=10, histtype="step", color=colors[layout], linewidth=1.4)
                else:
                    ax.scatter(xs, [columns[ny](c) for c in sub], s=9, color=colors[layout], linewidths=0)
            if row == k - 1:
                ax.set_xlabel(nx, fontsize=7, color=INK)
            if col == 0 and row > 0:
                ax.set_ylabel(ny, fontsize=7, color=INK)
    handles = [plt.Line2D([], [], marker="o", linestyle="", color=c, markersize=5) for c in colors.values()]
    fig.legend(handles, [name.replace("_", " ") for name in colors], loc="upper right", frameon=False,
               fontsize=8, labelcolor=INK, bbox_to_anchor=(0.98, 0.97))
    fig.suptitle(title, x=0.02, ha="left", color=INK, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def generate(spec_path: Path, plot: bool = True) -> list[Path]:
    """Write the case files, manifest.json and coverage.png of one run; returns the case files."""
    spec = load_spec(spec_path)
    folder = spec_path.parent
    base_path = Path(spec["base_config"])
    base_text = base_path.read_text()
    base_dict = yaml.safe_load(base_text)

    shares = [spec["n_cases"] // len(LAYOUTS) + (i < spec["n_cases"] % len(LAYOUTS)) for i in range(len(LAYOUTS))]
    per_layout, redraws = {}, {}
    for i, (layout, n) in enumerate(zip(LAYOUTS, shares)):
        per_layout[layout], redraws[layout] = draw_layout(spec, base_dict, layout, n, spec["seed"] + i)

    # interleave the layouts: every block of three cases has one of each
    cases = [per_layout[layout][k] for k in range(max(shares)) for layout in LAYOUTS if k < len(per_layout[layout])]
    for old in folder.glob(f"{spec['run_id']}_*.yaml"):  # a smaller n_cases must not leave old files behind
        old.unlink()
    header = (f"# Generated by `python -m sweeps.generate {spec_path.as_posix()}` "
              f"(seed {spec['seed']}). Do not edit; change the spec and generate again.\n")
    paths = []
    for k, case in enumerate(cases, start=1):
        case_id = f"{spec['run_id']}_{k:03d}"
        path = folder / f"{case_id}.yaml"
        path.write_text(case_text(base_text, case_id, case, header))
        loaded = load_config(path)  # every written file must load and validate
        place_windows(loaded)
        paths.append(path)

    methods = {"B": sum(c["layout"] == "same_wall" for c in cases)}  # PLAN.md §5, decision M1
    methods["A"] = len(cases) - methods["B"]
    manifest = {
        "run_id": spec["run_id"], "split": spec["split"], "n_cases": len(cases), "spec": spec,
        "cases_per_layout": dict(zip(LAYOUTS, shares)), "cases_per_method": methods,
        "position_redraws": redraws, "coverage": coverage(cases),
        "git_commit": _git_commit(), "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    # the creation time and commit change every run; everything else is reproducible from the spec
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if plot:
        plot_coverage(cases, f"Sampled inputs of {spec['run_id']} ({len(cases)} cases)", folder / "coverage.png")
    return paths


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Draw the cases of a sweep run from its spec file.")
    parser.add_argument("spec", type=Path, help="spec file, e.g. configs/sweep/train-v1/spec.yaml")
    parser.add_argument("--no-plot", action="store_true", help="skip coverage.png")
    args = parser.parse_args(argv)
    paths = generate(args.spec, plot=not args.no_plot)
    manifest = json.loads((args.spec.parent / "manifest.json").read_text())
    print(f"wrote {len(paths)} cases to {args.spec.parent}/")
    print(f"  per layout: {manifest['cases_per_layout']}   per method: {manifest['cases_per_method']}")
    print(f"  position redraws: {manifest['position_redraws']}")
    print(f"  mode pairs: {manifest['coverage']['mode_pairs']}")


if __name__ == "__main__":
    main()

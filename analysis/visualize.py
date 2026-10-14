"""Pictures of a solved case.

Usage, from the repository root with the venv active (OpenFOAM is not needed):
    python -m analysis.visualize --config configs/default.yaml --kind flow   --out flow.png
    python -m analysis.visualize --config configs/default.yaml --kind tracer --out tracer.png
    python -m analysis.visualize --config configs/default.yaml --kind curve  --out curve.png

- flow:   air speed and streamlines at window height, seen from above
- tracer: where the original indoor air still is after 30, 60 and 120 s, seen from above
- curve:  share of air replaced over time, compared with a perfectly mixed room

The results are read from cases/<case_id>/ with PyVista's OpenFOAM reader.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files only, no window
import matplotlib.pyplot as plt
import numpy as np
import pyvista as pv
from matplotlib.colors import LinearSegmentedColormap

from cfd.config import CaseConfig, ConfigError, load_config

CASES = Path("cases")
# Sequential one-hue ramps (light = little, dark = much). Blue for air speed,
# orange for the share of original indoor air.
SPEED_COLORS = LinearSegmentedColormap.from_list(
    "speed", ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
)
OLD_AIR_COLORS = LinearSegmentedColormap.from_list(
    "old_air", ["#fdf1ea", "#f9cdb7", "#f4a382", "#eb6834", "#c24f1e", "#8f3812", "#5c230a"]
)
INK, MUTED, WALLS = "#2b2b2b", "#6b6b6b", "#b9b4ab"
SURFACE, GRID, SERIES_1 = "#fcfcfb", "#e1e0d9", "#2a78d6"
TRACER_TIMES = (30, 60, 120)


def read_time(case_dir: Path, time: float | None = None) -> pv.UnstructuredGrid:
    """Internal mesh with its fields at `time` (latest written time if None)."""
    foam_file = case_dir / "case.foam"
    foam_file.touch()  # the reader needs a (possibly empty) .foam file in the case folder
    reader = pv.OpenFOAMReader(str(foam_file))
    reader.set_active_time_value(reader.time_values[-1] if time is None else time)
    return reader.read()["internalMesh"]


def plan_slice(cfg: CaseConfig, mesh: pv.UnstructuredGrid, height: float) -> pv.PolyData:
    """Horizontal cut through the air at `height`, around the building, moved to z = 0."""
    W, D = cfg.room.width_m, cfg.room.depth_m
    cut = mesh.slice(normal="z", origin=(0, 0, height))
    cut = cut.clip_box((-3.0, W + 3.0, -3.0, D + 6.0, height - 1, height + 1), invert=False)
    cut = cut.extract_surface(algorithm="dataset_surface").cell_data_to_point_data()
    cut.points[:, 2] = 0.0
    if "U" in cut.point_data:
        velocity = np.array(cut.point_data["U"])
        velocity[:, 2] = 0.0  # keep the in-plane part for 2D streamlines
        cut.point_data["U"] = velocity
        cut.point_data["speed"] = np.linalg.norm(velocity, axis=1)
    return cut


def _window_height(cfg: CaseConfig) -> float:
    return cfg.window_size.sill_height_m + cfg.window_size.height_m / 2


def _add_footprint(plotter: pv.Plotter, cfg: CaseConfig) -> None:
    """Gray building footprint below the cut: walls and sashes are holes in the air slice."""
    room, t = cfg.room, cfg.room.wall_thickness_m
    footprint = pv.Plane(center=(room.width_m / 2, room.depth_m / 2, -0.05),
                         i_size=room.width_m + 2 * t, j_size=room.depth_m + 2 * t)
    plotter.add_mesh(footprint, color=WALLS, lighting=False)


def _top_view(plotter: pv.Plotter, zoom: float) -> None:
    plotter.view_xy()
    plotter.enable_parallel_projection()
    plotter.camera.zoom(zoom)


def _seeds(cfg: CaseConfig) -> pv.PolyData:
    """Streamline start points: a row upstream of the building and a row across the room."""
    W, D = cfg.room.width_m, cfg.room.depth_m
    upstream_x = np.arange(-2.5, W + 2.5 + 1e-9, 0.5)
    room_x = np.arange(0.25, W - 0.25 + 1e-9, 0.5)
    points = [(x, -2.5, 0) for x in upstream_x] + [(x, D / 2, 0) for x in room_x]
    return pv.PolyData(np.array(points, dtype=float))


def _scalar_bar(title: str, fmt: str, n_labels: int = 4) -> dict:
    return dict(title=title, color=INK, vertical=False, position_x=0.2, position_y=0.03, width=0.6, height=0.06,
                title_font_size=18, label_font_size=16, fmt=fmt, n_labels=n_labels)


def render_flow(cfg: CaseConfig, case_dir: Path, out: Path) -> None:
    height = _window_height(cfg)
    cut = plan_slice(cfg, read_time(case_dir), height)
    lines = cut.streamlines_from_source(
        _seeds(cfg), vectors="U", integration_direction="both", surface_streamlines=True,
        initial_step_length=0.2, max_steps=4000, max_length=30,
    )
    plotter = pv.Plotter(off_screen=True, window_size=(1000, 1250))
    plotter.set_background("white")
    _add_footprint(plotter, cfg)
    plotter.add_mesh(cut, scalars="speed", cmap=SPEED_COLORS, clim=(0, np.ceil(np.percentile(cut["speed"], 99.5))),
                     lighting=False, scalar_bar_args=_scalar_bar("Air speed [m/s]", "%.1f"))
    if lines.n_points:
        plotter.add_mesh(lines.translate((0, 0, 0.01)), color=INK, line_width=1.8, opacity=0.8, lighting=False)

    flows = json.loads((case_dir / "summary.json").read_text())["window_net_inflow_m3h"]
    plotter.add_text(
        f"Air speed at window height (z = {height:.2f} m), seen from above\n"
        f"Wind {cfg.wind_speed_ms:g} m/s from the south (bottom)\n"
        f"Net flow in through window 1: {flows['window1']:,.0f} m³/h",
        position="upper_left", font_size=12, color=INK,
    )
    _top_view(plotter, 1.1)
    plotter.screenshot(str(out))
    plotter.close()


def render_tracer(cfg: CaseConfig, case_dir: Path, out: Path) -> None:
    height = _window_height(cfg)
    summary = json.loads((case_dir / "summary.json").read_text())
    plotter = pv.Plotter(off_screen=True, shape=(1, len(TRACER_TIMES)), border=False,
                         window_size=(700 * len(TRACER_TIMES), 900))
    plotter.set_background("white")
    for i, t in enumerate(TRACER_TIMES):
        plotter.subplot(0, i)
        cut = plan_slice(cfg, read_time(case_dir / "tracer", t), height)
        _add_footprint(plotter, cfg)
        plotter.add_mesh(cut, scalars="C", cmap=OLD_AIR_COLORS, clim=(0, 1), lighting=False,
                         show_scalar_bar=(i == len(TRACER_TIMES) // 2),
                         scalar_bar_args=_scalar_bar("Share of original indoor air", "%.1f", n_labels=2))
        replaced = summary.get(f"fresh_frac_{t:03d}s")
        label = f"{t} s after opening" + (f": {replaced:.0%} of the air replaced" if replaced is not None else "")
        plotter.add_text(label, position="upper_edge", font_size=12, color=INK)
        _top_view(plotter, 1.5)
    plotter.screenshot(str(out))
    plotter.close()


def plot_curve(cfg: CaseConfig, case_dir: Path, out: Path) -> None:
    """Share of air replaced over time, with a perfectly mixed room for comparison."""
    summary = json.loads((case_dir / "summary.json").read_text())
    curve = np.loadtxt(case_dir / "fresh_fraction.csv", delimiter=",", skiprows=1)
    t, fresh = curve[:, 0], curve[:, 1]
    room = cfg.room
    volume = room.width_m * room.depth_m * room.height_m
    flow = np.mean(np.abs(list(summary["window_net_inflow_m3h"].values()))) / 3600  # m^3/s
    t90 = summary["t90_s"]

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.plot(t, 100 * fresh, color=SERIES_1, linewidth=2, label="Simulation (CFD)")
    if flow > 1e-6:
        mixed = 1 - np.exp(-t * flow / volume)  # every bit of incoming air mixes instantly
        ax.plot(t, 100 * mixed, color=MUTED, linewidth=1.5, linestyle="--", label="Perfectly mixed room")
    if np.isfinite(t90):
        ax.axvline(t90, color=MUTED, linewidth=0.8, linestyle=":")
        ax.annotate(f"90 % replaced after {t90:.0f} s", xy=(t90, 90), xytext=(t90 + 12, 70), color=INK, fontsize=9,
                    arrowprops=dict(arrowstyle="-", color=MUTED, linewidth=0.8))
    ax.set_xlim(0, min(300, t[-1]))
    ax.set_ylim(0, 100)
    ax.set_xlabel("Time after opening the windows [s]", color=INK)
    ax.set_ylabel("Air replaced [%]", color=INK)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=MUTED)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.legend(frameon=False, loc="lower right", labelcolor=INK)
    windows = " / ".join(
        f"{w.mode} {w.angle_deg:g}°" for w in (cfg.window1, cfg.window2)
    )
    ax.set_title(f"Air replacement: {cfg.layout.replace('_', ' ')}, {windows}, wind {cfg.wind_speed_ms:g} m/s",
                 loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


KINDS = {"flow": render_flow, "tracer": render_tracer, "curve": plot_curve}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Pictures of a solved case.")
    parser.add_argument("--config", required=True, type=Path, help="case YAML file of a solved case")
    parser.add_argument("--kind", choices=KINDS, default="flow", help="which picture (default: flow)")
    parser.add_argument("--out", required=True, type=Path, help="output PNG file")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as error:
        raise SystemExit(f"Invalid configuration: {error}")
    case_dir = CASES / cfg.case_id
    if not (case_dir / "summary.json").exists():
        raise SystemExit(f"No solved case in {case_dir}: run `python -m cfd.run_case --config {args.config}` first")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    KINDS[args.kind](cfg, case_dir, args.out)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()

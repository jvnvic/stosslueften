"""Picture of a solved case: air speed and streamlines at window height, seen from above.

Usage, from the repository root with the venv active (OpenFOAM is not needed):
    python -m analysis.visualize --config configs/default.yaml --out docs/images/default_flow.png

It reads the latest result in cases/<case_id>/ with PyVista's OpenFOAM reader.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pyvista as pv
from matplotlib.colors import LinearSegmentedColormap

from cfd.config import CaseConfig, ConfigError, load_config

CASES = Path("cases")
# Sequential one-hue ramp (light = slow, dark = fast), steps 100-700 of the reference blue.
SPEED_COLORS = LinearSegmentedColormap.from_list(
    "speed", ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
)
INK, MUTED, WALLS = "#2b2b2b", "#6b6b6b", "#b9b4ab"


def read_latest(case_dir: Path) -> pv.UnstructuredGrid:
    """Internal mesh of the latest written time, with the velocity field U."""
    foam_file = case_dir / "case.foam"
    foam_file.touch()  # the reader needs a (possibly empty) .foam file in the case folder
    reader = pv.OpenFOAMReader(str(foam_file))
    reader.set_active_time_value(reader.time_values[-1])
    return reader.read()["internalMesh"]


def speed_slice(cfg: CaseConfig, mesh: pv.UnstructuredGrid, height: float) -> pv.PolyData:
    """Horizontal cut through the air at `height`, around the building, moved to z = 0."""
    W, D = cfg.room.width_m, cfg.room.depth_m
    cut = mesh.slice(normal="z", origin=(0, 0, height))
    cut = cut.clip_box((-3.0, W + 3.0, -3.0, D + 6.0, height - 1, height + 1), invert=False)
    cut = cut.extract_surface(algorithm="dataset_surface").cell_data_to_point_data()
    velocity = np.array(cut.point_data["U"])
    velocity[:, 2] = 0.0  # keep the in-plane part for 2D streamlines
    cut.points[:, 2] = 0.0
    cut.point_data["U"] = velocity
    cut.point_data["speed"] = np.linalg.norm(velocity, axis=1)
    return cut


def _seeds(cfg: CaseConfig) -> pv.PolyData:
    """Streamline start points: a row upstream of the building and a row across the room."""
    W, D = cfg.room.width_m, cfg.room.depth_m
    upstream_x = np.arange(-2.5, W + 2.5 + 1e-9, 0.5)
    room_x = np.arange(0.25, W - 0.25 + 1e-9, 0.5)
    points = [(x, -2.5, 0) for x in upstream_x] + [(x, D / 2, 0) for x in room_x]
    return pv.PolyData(np.array(points, dtype=float))


def render(cfg: CaseConfig, case_dir: Path, out: Path) -> None:
    size, room, t = cfg.window_size, cfg.room, cfg.room.wall_thickness_m
    height = size.sill_height_m + size.height_m / 2  # middle of the windows
    cut = speed_slice(cfg, read_latest(case_dir), height)
    lines = cut.streamlines_from_source(
        _seeds(cfg), vectors="U", integration_direction="both", surface_streamlines=True,
        initial_step_length=0.2, max_steps=4000, max_length=30,
    )

    plotter = pv.Plotter(off_screen=True, window_size=(1000, 1250))
    plotter.set_background("white")
    # Gray building footprint below the cut: walls and sashes are holes in the air slice.
    footprint = pv.Plane(center=(room.width_m / 2, room.depth_m / 2, -0.05),
                         i_size=room.width_m + 2 * t, j_size=room.depth_m + 2 * t)
    plotter.add_mesh(footprint, color=WALLS, lighting=False)
    plotter.add_mesh(
        cut, scalars="speed", cmap=SPEED_COLORS, clim=(0, np.ceil(np.percentile(cut["speed"], 99.5))), lighting=False,
        scalar_bar_args=dict(title="Air speed [m/s]", color=INK, vertical=False, position_x=0.2, position_y=0.03,
                             width=0.6, height=0.06, title_font_size=18, label_font_size=16, fmt="%.1f",
                             n_labels=4),
    )
    if lines.n_points:
        plotter.add_mesh(lines.translate((0, 0, 0.01)), color=INK, line_width=1.8, opacity=0.8, lighting=False)

    summary_file = case_dir / "summary.json"
    flow_text = ""
    if summary_file.exists():
        flows = json.loads(summary_file.read_text())["window_net_inflow_m3h"]
        flow_text = f"\nNet flow in through window 1: {flows['window1']:,.0f} m³/h"
    plotter.add_text(
        f"Air speed at window height (z = {height:.2f} m), seen from above\n"
        f"Wind {cfg.wind_speed_ms:g} m/s from the south (bottom){flow_text}",
        position="upper_left", font_size=12, color=INK,
    )
    plotter.view_xy()
    plotter.enable_parallel_projection()
    plotter.camera.zoom(1.1)
    out.parent.mkdir(parents=True, exist_ok=True)
    plotter.screenshot(str(out))
    plotter.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Render air speed and streamlines of a solved case.")
    parser.add_argument("--config", required=True, type=Path, help="case YAML file of a solved case")
    parser.add_argument("--out", required=True, type=Path, help="output PNG file")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as error:
        raise SystemExit(f"Invalid configuration: {error}")
    case_dir = CASES / cfg.case_id
    if not (case_dir / "constant" / "polyMesh").exists():
        raise SystemExit(f"No solved case in {case_dir}: run `python -m cfd.run_case --config {args.config}` first")
    render(cfg, case_dir, args.out)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()

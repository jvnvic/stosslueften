"""Pictures of a solved case.

Usage, from the repository root with the venv active (OpenFOAM is not needed):
    python -m analysis.visualize --config configs/default.yaml --kind flow   --out flow.png
    python -m analysis.visualize --config configs/default.yaml --kind tracer --out tracer.png
    python -m analysis.visualize --config configs/default.yaml --kind curve  --out curve.png
    python -m analysis.visualize --config configs/default.yaml --kind mesh   --out mesh.png

- flow:   air speed and streamlines at window height, seen from above
- tracer: where the original indoor air still is after 30, 60 and 120 s, seen from above
- curve:  share of air replaced over time, compared with a perfectly mixed room
- mesh:   the computational grid: cuts through the domain and window 1, and the surface grid

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
# Light ramp for the mesh pictures, so that cell edges stay visible: blue = small cells, pale = large cells.
CELL_SIZE_COLORS = LinearSegmentedColormap.from_list(
    "cell_size", ["#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb", "#f3f7fd"]
)
INK, MUTED, WALLS = "#2b2b2b", "#6b6b6b", "#b9b4ab"
SURFACE, GRID, SERIES_1, SERIES_2 = "#fcfcfb", "#e1e0d9", "#2a78d6", "#eb6834"
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

    summary = json.loads((case_dir / "summary.json").read_text())
    airflow = summary.get("airflow_m3h", summary["window_net_inflow_m3h"]["window1"])  # older cases: net flow
    plotter.add_text(
        f"Air speed at window height (z = {height:.2f} m), seen from above\n"
        f"Wind {cfg.wind_speed_ms:g} m/s from the south (bottom)\n"
        f"Airflow into the room: {airflow:,.0f} m³/h",
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


def read_grid(case_dir: Path, patches: tuple[str, ...]) -> tuple[pv.UnstructuredGrid, dict[str, pv.PolyData]]:
    """The mesh cells, with their size in a 'size' array, and the named boundary patches."""
    foam_file = case_dir / "case.foam"
    foam_file.touch()
    reader = pv.OpenFOAMReader(str(foam_file))
    reader.set_active_time_value(reader.time_values[0])
    for name in patches:
        reader.enable_patch_array(f"patch/{name}")
    data = reader.read()
    cells = data["internalMesh"].compute_cell_sizes(length=False, area=False, volume=True)
    # VTK counts prism volumes negative (different corner order than OpenFOAM), so use the magnitude
    cells.cell_data["size"] = np.cbrt(np.abs(cells.cell_data["Volume"]))
    return cells, {name: data["boundary"][name] for name in patches}


def _grid_style(show_bar: bool) -> dict:
    return dict(scalars="size", cmap=CELL_SIZE_COLORS, log_scale=True, clim=(0.02, 1.6), show_edges=True,
                edge_color=INK, line_width=0.5, edge_opacity=0.55, lighting=False, show_scalar_bar=show_bar,
                scalar_bar_args=_scalar_bar("Cell size [m]", "%.2f", n_labels=4))


def _crop(cut: pv.PolyData, x0: float, x1: float, y0: float, y1: float) -> pv.PolyData:
    """Keep the whole cells whose centre lies in the box (clip_box would split them into triangles)."""
    centres = cut.cell_centers().points
    inside = (centres[:, 0] > x0) & (centres[:, 0] < x1) & (centres[:, 1] > y0) & (centres[:, 1] < y1)
    return cut.extract_cells(inside)


def _flat(cut: pv.PolyData, u_axis: np.ndarray, v_axis: np.ndarray, origin: np.ndarray) -> pv.PolyData:
    """Express a planar cut in its own 2D coordinates (u, v), drawn in the plane z = 0."""
    flat = cut.copy()
    rel = flat.points - origin
    flat.points = np.column_stack([rel @ u_axis, rel @ v_axis, np.zeros(len(rel))])
    return flat


def render_mesh(cfg: CaseConfig, case_dir: Path, out: Path) -> None:
    """The computational grid: the whole domain and the building cut at window height,
    a vertical cut through window 1, and the surface grid with the roof removed."""
    from geometry.render import COLORS, SURFACE, _add_lights, _cut, _wall_tops  # same look as the 3D room picture
    from geometry.windows import place_windows

    W, D, Hr = cfg.room.width_m, cfg.room.depth_m, cfg.room.height_m
    cells, patches = read_grid(case_dir, ("building", "room_walls", "sashes", "ground"))
    # Small offsets keep the cuts off the grid planes of the hex mesh, which would give double edges.
    height = _window_height(cfg) + 0.004
    plan = cells.slice(normal="z", origin=(0, 0, height))
    plan.points[:, 2] = 0.0
    xmin, xmax, ymin, ymax = cells.bounds[:4]

    plotter = pv.Plotter(off_screen=True, shape=(2, 2), border=False, window_size=(1800, 1700))
    plotter.set_background("white")

    plotter.subplot(0, 0)
    _add_footprint(plotter, cfg)
    plotter.add_mesh(plan, **_grid_style(False))
    plotter.add_text(f"Whole domain ({xmax - xmin:.0f} × {ymax - ymin:.0f} m), cut at window height\n"
                     f"{cells.n_cells:,} cells. Wind from the south (bottom)",
                     position="upper_left", font_size=11, color=INK)
    _top_view(plotter, 1.0)

    plotter.subplot(0, 1)
    near = _crop(plan, -2.0, W + 2.0, -2.0, D + 2.0)
    _add_footprint(plotter, cfg)
    plotter.add_mesh(near, **_grid_style(True))
    plotter.add_text("Around the building, same cut\n(gray: walls and open sashes)",
                     position="upper_left", font_size=11, color=INK)
    _top_view(plotter, 1.15)

    plotter.subplot(1, 0)
    window = place_windows(cfg)[0]
    centre = window.start + window.wall.along * (cfg.window_size.width_m / 2 + 0.004)
    section = cells.slice(normal=window.wall.along, origin=centre)
    # u: distance into the room from the inner wall face, v: height
    flat = _flat(section, window.wall.inward, np.array([0.0, 0.0, 1.0]), centre * np.array([1, 1, 0]))
    flat = _crop(flat, -2.2, 2.8, -0.1, 3.4)
    # gray behind the building part of the cut, showing through where there are no cells:
    # from the outer wall face to where the room cells end, and from the floor to the top of the roof
    t = cfg.room.wall_thickness_m
    room_end = flat.points[flat.points[:, 1] < Hr, 0].max()
    plotter.add_mesh(pv.Plane(center=((room_end - t) / 2, (Hr + t) / 2, -0.05), i_size=room_end + t, j_size=Hr + t),
                     color=WALLS, lighting=False)
    plotter.add_mesh(flat, **_grid_style(False))
    plotter.add_text("Vertical cut through the middle of window 1\n(outside left, room right; gray: solid parts)",
                     position="upper_left", font_size=11, color=INK)
    _top_view(plotter, 1.15)

    plotter.subplot(1, 1)
    edges = dict(show_edges=True, edge_color="#55504a", line_width=0.6)
    room = _cut(patches["room_walls"].extract_surface(algorithm="dataset_surface"), Hr - 1e-3)
    plotter.add_mesh(room, color=COLORS["inner_walls"], **edges, **SURFACE)
    plotter.add_mesh(_cut(patches["building"].extract_surface(algorithm="dataset_surface"), Hr - 1e-3),
                     color=COLORS["outer_walls"], **edges, **SURFACE)
    plotter.add_mesh(_wall_tops(cfg), color=COLORS["wall_cut"], **SURFACE)
    plotter.add_mesh(patches["sashes"], color=COLORS["sashes"], **edges, **SURFACE)
    ground = _crop(patches["ground"], -3.5, W + 3.5, -5.0, D + 3.0)
    plotter.add_mesh(ground, color=COLORS["ground"], **edges, **SURFACE)
    plotter.add_text("Surface grid of the building, roof removed", position="upper_left", font_size=11, color=INK)
    plotter.camera.focal_point = (W / 2, D / 2 - 0.6, 1.0)
    plotter.camera.position = (W / 2 + 6.0, D / 2 - 9.5, 11.5)
    plotter.camera.up = (0, 0, 1)
    plotter.camera.view_angle = 30
    _add_lights(plotter, cfg)

    plotter.screenshot(str(out))
    plotter.close()


def plot_curve(cfg: CaseConfig, case_dir: Path, out: Path) -> None:
    """Share of air replaced over time, with a perfectly mixed room for comparison."""
    summary = json.loads((case_dir / "summary.json").read_text())
    curve = np.loadtxt(case_dir / "fresh_fraction.csv", delimiter=",", skiprows=1)
    t, fresh = curve[:, 0], curve[:, 1]
    room = cfg.room
    volume = room.width_m * room.depth_m * room.height_m
    if "airflow_m3h" in summary:  # inflow through both windows
        flow = summary["airflow_m3h"] / 3600  # m^3/s
    else:  # older cases: net flow measured on a plane
        flow = np.mean(np.abs(list(summary["window_net_inflow_m3h"].values()))) / 3600
    t90 = summary["t90_s"]

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    transient_file = case_dir / "fresh_fraction_transient.csv"
    if transient_file.exists():
        # Benchmark case: show both methods (PLAN.md §5, options A and B).
        ax.plot(t, 100 * fresh, color=SERIES_1, linewidth=2, label="Steady flow + tracer (A)")
        tb = np.loadtxt(transient_file, delimiter=",", skiprows=1)
        ax.plot(tb[:, 0], 100 * tb[:, 1], color=SERIES_2, linewidth=2, label="Time-varying flow, URANS (B)")
    else:
        ax.plot(t, 100 * fresh, color=SERIES_1, linewidth=2, label="Simulation (CFD)")
    if flow > 1e-6:
        mixed = 1 - np.exp(-t * flow / volume)  # every bit of incoming air mixes instantly
        ax.plot(t, 100 * mixed, color=MUTED, linewidth=1.5, linestyle="--", label="Perfectly mixed, same airflow")
    # Show at least 5 min, more if 90 % is reached later (in whole minutes).
    x_max = min(300 if not np.isfinite(t90) or t90 < 250 else 60 * np.ceil(t90 * 1.2 / 60), t[-1])
    ax.set_xlim(0, x_max)
    if np.isfinite(t90):
        ax.axvline(t90, color=MUTED, linewidth=0.8, linestyle=":")
        on_right = t90 < 0.6 * x_max  # put the label where there is room
        label = f"90 % replaced after {t90:.0f} s"
        if transient_file.exists() and np.isfinite(summary.get("transient", {}).get("t90_s", np.nan)):
            t90_b = summary["transient"]["t90_s"]
            ax.axvline(t90_b, color=SERIES_2, linewidth=0.8, linestyle=":")
            label = f"90 % replaced after\n{t90:.0f} s (A) / {t90_b:.0f} s (B)"
        ax.annotate(label, xy=(t90, 90), xytext=(t90 + (12 if on_right else -12), 70 if on_right else 45),
                    ha="left" if on_right else "right", color=INK, fontsize=9,
                    arrowprops=dict(arrowstyle="-", color=MUTED, linewidth=0.8))
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


KINDS = {"flow": render_flow, "tracer": render_tracer, "curve": plot_curve, "mesh": render_mesh}


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

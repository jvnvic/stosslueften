"""Render the room setup of one or more cases as a picture (no window opens).

The picture shows the same Gmsh geometry the simulation uses, as a cut-away
view: the roof is removed so you can look into the room from above.

Usage, from the repository root with the venv active:
    python -m geometry.render configs/default.yaml --out docs/images/default.png
    python -m geometry.render configs/examples/*.yaml --out docs/images/layouts.png   # side by side
"""

from __future__ import annotations

import argparse
from pathlib import Path

import gmsh
import numpy as np
import pyvista as pv

from cfd.config import CaseConfig, ConfigError, load_config
from geometry.generate import build_model
from geometry.windows import place_windows

COLORS = {
    "background": "#ffffff",
    "ground": "#e3e9dc",
    "floor": "#d2a679",
    "inner_walls": "#f7f4ee",
    "outer_walls": "#ece7de",
    "wall_cut": "#a59d90",
    "sashes": "#4a90d9",
    "wind": "#2f5d8a",
}
SURFACE = dict(ambient=0.18, diffuse=0.85)  # how every surface reacts to light


def surface_meshes(cfg: CaseConfig) -> dict[str, pv.PolyData]:
    """Triangulated surfaces of the 'building', 'room_walls' and 'sashes' patches."""
    placed = place_windows(cfg)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        _, patches = build_model(cfg, placed)
        gmsh.option.setNumber("Mesh.MeshSizeMax", 0.25)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)  # round hinge posts
        gmsh.model.mesh.generate(2)
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        points = np.zeros((node_tags.max() + 1, 3))
        points[node_tags] = coords.reshape(-1, 3)

        meshes = {}
        for name in ("building", "room_walls", "sashes"):
            triangles = []
            for surface in patches[name]:
                types, _, nodes = gmsh.model.mesh.getElements(2, surface)
                triangles += [n.reshape(-1, 3) for t, n in zip(types, nodes) if t == 2]  # type 2 = triangle
            triangles = np.vstack(triangles).astype(np.int64)  # Gmsh gives unsigned ints
            faces = np.hstack([np.full((len(triangles), 1), 3), triangles]).ravel()
            meshes[name] = pv.PolyData(points, faces).clean()
    finally:
        gmsh.finalize()
    return meshes


def _wall_tops(cfg: CaseConfig) -> pv.PolyData:
    """Flat caps on the cut walls, so they look solid instead of hollow."""
    W, D, Hr, t = cfg.room.width_m, cfg.room.depth_m, cfg.room.height_m, cfg.room.wall_thickness_m
    strips = [(-t, W + t, -t, 0), (-t, W + t, D, D + t), (-t, 0, 0, D), (W, W + t, 0, D)]
    caps = [pv.Rectangle([[x0, y0, Hr], [x1, y0, Hr], [x1, y1, Hr]]) for x0, x1, y0, y1 in strips]
    return pv.merge(caps)


def _cut(mesh: pv.PolyData, height: float) -> pv.PolyData:
    """Keep only the part below `height`."""
    return mesh.clip(normal="z", origin=(0, 0, height))


def add_case(plotter: pv.Plotter, cfg: CaseConfig, title: str) -> None:
    meshes = surface_meshes(cfg)
    W, D, Hr = cfg.room.width_m, cfg.room.depth_m, cfg.room.height_m
    cut = Hr - 1e-3  # just below the ceiling, which is removed for the view

    room = _cut(meshes["room_walls"], cut)
    is_floor = room.cell_centers().points[:, 2] < 1e-3
    plotter.add_mesh(room.extract_cells(is_floor), color=COLORS["floor"], **SURFACE)
    plotter.add_mesh(room.extract_cells(~is_floor), color=COLORS["inner_walls"], **SURFACE)
    plotter.add_mesh(_cut(meshes["building"], cut), color=COLORS["outer_walls"], **SURFACE)
    plotter.add_mesh(_wall_tops(cfg), color=COLORS["wall_cut"], **SURFACE)
    plotter.add_mesh(meshes["sashes"], color=COLORS["sashes"], specular=0.5, specular_power=30, **SURFACE)

    ground = pv.Plane(center=(W / 2, D / 2 - 1.0, -0.01), i_size=W + 7, j_size=D + 8)
    plotter.add_mesh(ground, color=COLORS["ground"], **SURFACE)
    # Wind arrow on the south side, pointing north.
    arrow = pv.Arrow(start=(W / 2, -cfg.room.wall_thickness_m - 3.2, 1.4), direction=(0, 1, 0), scale=2.2,
                     shaft_radius=0.04, tip_radius=0.1)
    plotter.add_mesh(arrow, color=COLORS["wind"], **SURFACE)
    plotter.add_text(title, position="upper_edge", font_size=11, color="#333333")

    plotter.camera.focal_point = (W / 2, D / 2 - 0.6, 0.4)
    plotter.camera.position = (W / 2 + 6.0, D / 2 - 9.5, 11.5)  # from the south-east, above
    plotter.camera.up = (0, 0, 1)
    plotter.camera.view_angle = 30


def _add_lights(plotter: pv.Plotter, cfg: CaseConfig) -> None:
    """A sun from the south-west, a weaker fill light from the east and a soft camera light."""
    plotter.remove_all_lights()
    x, y = cfg.room.width_m / 2, cfg.room.depth_m / 2
    plotter.add_light(pv.Light(position=(x - 12, y - 16, 20), focal_point=(x, y, 0), intensity=0.75))
    plotter.add_light(pv.Light(position=(x + 16, y - 4, 6), focal_point=(x, y, 0), intensity=0.35))
    plotter.add_light(pv.Light(light_type="headlight", intensity=0.3))


def describe(cfg: CaseConfig) -> str:
    def window(w):
        return f"{w.mode} {w.angle_deg:g}°"

    return f"{cfg.layout.replace('_', ' ')}: {window(cfg.window1)} / {window(cfg.window2)}"


def render(configs: list[CaseConfig], out: Path, panel_size=(900, 700)) -> None:
    plotter = pv.Plotter(off_screen=True, shape=(1, len(configs)), border=False,
                         window_size=(panel_size[0] * len(configs), panel_size[1]))
    plotter.set_background(COLORS["background"])
    for i, cfg in enumerate(configs):
        plotter.subplot(0, i)
        add_case(plotter, cfg, describe(cfg))
        plotter.enable_ssao(radius=0.3)  # soft shadows in corners
    _add_lights(plotter, configs[0])  # added to every panel
    plotter.enable_anti_aliasing("ssaa")
    out.parent.mkdir(parents=True, exist_ok=True)
    plotter.screenshot(str(out))
    plotter.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Render the room setup of one or more cases.")
    parser.add_argument("configs", nargs="+", type=Path, help="case YAML file(s); several are shown side by side")
    parser.add_argument("--out", required=True, type=Path, help="output PNG file")
    args = parser.parse_args(argv)
    try:
        configs = [load_config(path) for path in args.configs]
        render(configs, args.out)
    except ConfigError as error:
        raise SystemExit(f"Invalid configuration: {error}")
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()

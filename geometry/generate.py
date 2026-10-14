"""Build the 3D model (room, walls, windows, outdoor air) and mesh it with Gmsh.

Usage, from the repository root with the venv active:
    python -m geometry.generate --config configs/default.yaml
    python -m geometry.generate --config configs/default.yaml --no-mesh --gui   # just look at it

Output: cases/<case_id>/mesh.msh in Gmsh format 2.2, which OpenFOAM's gmshToFoam
reads. All air (outdoors, window openings, room) is one volume called "fluid";
its boundary surfaces are grouped into the patches listed in PATCHES.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import NamedTuple

import gmsh
import numpy as np

from cfd.config import CaseConfig, ConfigError, load_config
from geometry.windows import PlacedWindow, place_windows

PATCHES = ("inlet", "outlet", "sides", "top", "ground", "building", "room_walls", "sashes")
EPS = 1e-4  # geometric tolerance in metres (OpenCASCADE bounding boxes are slightly padded)


class Bounds(NamedTuple):
    """Outer limits of the computational domain. It starts at the ground, z = 0."""

    x0: float
    x1: float
    y0: float
    y1: float
    z1: float


def domain_bounds(cfg: CaseConfig) -> Bounds:
    room, d = cfg.room, cfg.domain
    t, H = room.wall_thickness_m, cfg.building_height_m
    return Bounds(
        x0=-t - d.lateral_H * H,
        x1=room.width_m + t + d.lateral_H * H,
        y0=-t - d.upstream_H * H,  # the wind comes from the south (-y side)
        y1=room.depth_m + t + d.downstream_H * H,
        z1=H + d.top_H * H,
    )


def _add_box(corners: np.ndarray) -> int:
    lo, hi = corners.min(axis=0), corners.max(axis=0)
    return gmsh.model.occ.addBox(*lo, *(hi - lo))


def build_model(cfg: CaseConfig, placed: tuple[PlacedWindow, ...]) -> tuple[int, dict[str, list[int]]]:
    """Create the air volume in the current Gmsh model.

    Returns the volume tag and a dict mapping each patch name to its surface tags.
    """
    occ = gmsh.model.occ
    room, t = cfg.room, cfg.room.wall_thickness_m
    b = domain_bounds(cfg)

    domain = occ.addBox(b.x0, b.y0, 0, b.x1 - b.x0, b.y1 - b.y0, b.z1)
    building = occ.addBox(-t, -t, 0, room.width_m + 2 * t, room.depth_m + 2 * t, cfg.building_height_m)
    room_air = occ.addBox(0, 0, 0, room.width_m, room.depth_m, room.height_m)
    openings = [_add_box(pw.opening_corners()) for pw in placed]
    sashes = []
    for pw in placed:
        plate = _add_box(pw.closed_sash_corners())
        occ.rotate([(3, plate)], *pw.hinge_point, *pw.hinge_axis, pw.rotation_rad)
        start, axis, radius = pw.hinge_post()
        sashes += [plate, occ.addCylinder(*start, *axis, radius)]

    # Air = (domain minus building) + room + window openings, minus sashes and hinge posts.
    outdoor, _ = occ.cut([(3, domain)], [(3, building)])
    air, _ = occ.fuse(outdoor, [(3, room_air)] + [(3, o) for o in openings])
    air, _ = occ.cut(air, [(3, s) for s in sashes])
    occ.synchronize()
    if len(air) != 1:
        raise RuntimeError(f"geometry problem: expected one connected air volume, got {len(air)}")

    patches = {name: [] for name in PATCHES}
    for _, tag in gmsh.model.getBoundary(air, oriented=False):
        patches[_classify(tag, cfg, placed, b)].append(tag)
    if empty := [name for name, tags in patches.items() if not tags]:
        raise RuntimeError(f"geometry problem: no surfaces found for patch(es) {empty}")
    return air[0][1], patches


def _classify(tag: int, cfg: CaseConfig, placed, b: Bounds) -> str:
    """Decide which patch a boundary surface belongs to, from its position."""
    x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(2, tag)

    def flat_at(lo, hi, value):
        return abs(lo - value) < EPS and abs(hi - value) < EPS

    W, D, Hr = cfg.room.width_m, cfg.room.depth_m, cfg.room.height_m
    inside_room = x0 > -EPS and x1 < W + EPS and y0 > -EPS and y1 < D + EPS and z1 < Hr + EPS

    if flat_at(z0, z1, b.z1):
        return "top"
    if flat_at(x0, x1, b.x0) or flat_at(x0, x1, b.x1):
        return "sides"
    if flat_at(y0, y1, b.y0):
        return "inlet"
    if flat_at(y0, y1, b.y1):
        return "outlet"
    if flat_at(z0, z1, 0.0):
        return "room_walls" if inside_room else "ground"
    on_room_plane = any(
        (flat_at(x0, x1, 0), flat_at(x0, x1, W), flat_at(y0, y1, 0), flat_at(y0, y1, D), flat_at(z0, z1, Hr))
    )
    if on_room_plane and inside_room:
        return "room_walls"
    centre = gmsh.model.occ.getCenterOfMass(2, tag)
    if any(pw.contains_sash_point(centre) for pw in placed):
        return "sashes"
    return "building"  # outer walls, roof and the window reveals


def _inside_opening(tag: int, placed) -> bool:
    """True if a surface lies within one of the window openings (the reveals)."""
    lo, hi = np.split(np.array(gmsh.model.getBoundingBox(2, tag)), 2)
    for pw in placed:
        corners = pw.opening_corners()
        if np.all(lo >= corners.min(axis=0) - EPS) and np.all(hi <= corners.max(axis=0) + EPS):
            return True
    return False


def _set_mesh_sizes(cfg: CaseConfig, placed, patches: dict[str, list[int]]) -> None:
    """Fine cells at the windows, medium in the room and near the building, coarse far away."""
    field = gmsh.model.mesh.field
    m, room = cfg.mesh, cfg.room
    t, H = room.wall_thickness_m, cfg.building_height_m

    near_windows = patches["sashes"] + [s for s in patches["building"] if _inside_opening(s, placed)]
    distance = field.add("Distance")
    field.setNumbers(distance, "SurfacesList", near_windows)
    windows = field.add("Threshold")
    field.setNumber(windows, "InField", distance)
    field.setNumber(windows, "SizeMin", m.window_m)
    field.setNumber(windows, "SizeMax", m.room_m)
    field.setNumber(windows, "DistMin", 0.02)
    field.setNumber(windows, "DistMax", 0.5)
    field.setNumber(windows, "StopAtDistMax", 1)  # no effect further away

    def box(size, x0, x1, y0, y1, z0, z1, transition):
        tag = field.add("Box")
        for key, value in dict(VIn=size, VOut=m.far_m, XMin=x0, XMax=x1, YMin=y0, YMax=y1, ZMin=z0, ZMax=z1,
                               Thickness=transition).items():
            field.setNumber(tag, key, value)
        return tag

    in_room = box(m.room_m, 0, room.width_m, 0, room.depth_m, 0, room.height_m, 0)
    # Wake region: 1 H around the building, 3 H downstream (wind from the south).
    near_building = box(m.building_m, -t - H, room.width_m + t + H, -t - H, room.depth_m + t + 3 * H, 0, 2 * H, 2 * H)

    smallest = field.add("Min")
    field.setNumbers(smallest, "FieldsList", [windows, in_room, near_building])
    field.setAsBackgroundMesh(smallest)

    # Take sizes only from the fields above.
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Algorithm3D", 10)  # HXT: fast and multi-threaded
    gmsh.option.setNumber("General.NumThreads", os.cpu_count() or 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)


def _mesh_stats() -> dict:
    _, tags, _ = gmsh.model.mesh.getElements(3)
    elements = np.concatenate(tags)
    quality = gmsh.model.mesh.getElementQualities(elements, "minSICN")  # 1 = perfect, <= 0 = broken
    nodes, _, _ = gmsh.model.mesh.getNodes()
    return {
        "n_nodes": len(nodes),
        "n_tets": len(elements),
        "min_quality": round(float(quality.min()), 3),
        "n_poor_tets": int((quality < 0.1).sum()),
    }


def generate(cfg: CaseConfig, out_dir: Path | None = None, mesh: bool = True, gui: bool = False) -> dict:
    """Build (and optionally mesh) one case. Writes <out_dir>/mesh.msh when meshing.

    Raises ConfigError if the windows cannot be placed as configured.
    """
    placed = place_windows(cfg)
    started = time.perf_counter()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.option.setNumber("General.Verbosity", 2)  # only warnings and errors
        gmsh.model.add(cfg.case_id)
        volume, patches = build_model(cfg, placed)
        gmsh.model.addPhysicalGroup(3, [volume], name="fluid")
        for name, tags in patches.items():
            gmsh.model.addPhysicalGroup(2, tags, name=name)
        summary = {"case_id": cfg.case_id, "surfaces_per_patch": {k: len(v) for k, v in patches.items()}}

        if mesh:
            _set_mesh_sizes(cfg, placed, patches)
            gmsh.model.mesh.generate(3)
            summary.update(_mesh_stats())
            if out_dir is not None:
                out_dir.mkdir(parents=True, exist_ok=True)
                gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)  # the format gmshToFoam reads
                gmsh.write(str(out_dir / "mesh.msh"))
                summary["mesh_file"] = str(out_dir / "mesh.msh")
        summary["seconds"] = round(time.perf_counter() - started, 1)
        if gui:
            gmsh.fltk.run()
    finally:
        gmsh.finalize()
    return summary


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Build and mesh the geometry of one case.")
    parser.add_argument("--config", required=True, type=Path, help="case YAML file, e.g. configs/default.yaml")
    parser.add_argument("--out", type=Path, help="output folder (default: cases/<case_id>)")
    parser.add_argument("--no-mesh", action="store_true", help="only build the geometry (quick check)")
    parser.add_argument("--gui", action="store_true", help="open the Gmsh window to look at the result")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        summary = generate(cfg, args.out or Path("cases") / cfg.case_id, mesh=not args.no_mesh, gui=args.gui)
    except ConfigError as error:
        raise SystemExit(f"Invalid configuration: {error}")
    for key, value in summary.items():
        print(f"{key:>20}: {value}")


if __name__ == "__main__":
    main()

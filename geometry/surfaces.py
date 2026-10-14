"""Surface of the solid parts (walls, roof, sashes, hinge posts) as an STL file for snappyHexMesh.

snappyHexMesh cuts this surface out of a block mesh of the whole domain and keeps
the air side. The solid reaches BELOW_GROUND_M under the ground so that it cuts
cleanly through the ground plane; its bottom face lies outside the domain and is
left out of the file.

The STL has one region per patch: building (outer walls, roof, window reveals),
room_walls (inside of the room) and sashes (sash plates and hinge posts).
"""

from __future__ import annotations

from pathlib import Path

import gmsh

from cfd.config import CaseConfig
from geometry.generate import EPS, _add_box, add_sashes
from geometry.windows import place_windows

BELOW_GROUND_M = 0.1
REGIONS = ("building", "room_walls", "sashes")


def _region(tag: int, cfg: CaseConfig, placed) -> str | None:
    """Which STL region a surface of the solid belongs to (None: below the ground, left out)."""
    x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(2, tag)

    def flat_at(lo, hi, value):
        return abs(lo - value) < EPS and abs(hi - value) < EPS

    if flat_at(z0, z1, -BELOW_GROUND_M):
        return None
    W, D, Hr = cfg.room.width_m, cfg.room.depth_m, cfg.room.height_m
    inside_room = x0 > -EPS and x1 < W + EPS and y0 > -EPS and y1 < D + EPS and z1 < Hr + EPS
    on_room_plane = any(
        (flat_at(x0, x1, 0), flat_at(x0, x1, W), flat_at(y0, y1, 0), flat_at(y0, y1, D), flat_at(z0, z1, Hr))
    )
    if on_room_plane and inside_room:
        return "room_walls"
    centre = gmsh.model.occ.getCenterOfMass(2, tag)
    if any(pw.contains_sash_point(centre) for pw in placed):
        return "sashes"
    return "building"


def write_obstacle_stl(cfg: CaseConfig, path: Path) -> dict[str, int]:
    """Write the solid parts as an STL file with one region per patch; returns triangles per region."""
    placed = place_windows(cfg)
    room, t, below = cfg.room, cfg.room.wall_thickness_m, BELOW_GROUND_M
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        building = occ.addBox(-t, -t, -below, room.width_m + 2 * t, room.depth_m + 2 * t,
                              cfg.building_height_m + below)
        cavity = occ.addBox(0, 0, -below, room.width_m, room.depth_m, room.height_m + below)
        openings = [_add_box(pw.opening_corners()) for pw in placed]
        shell, _ = occ.cut([(3, building)], [(3, cavity)] + [(3, o) for o in openings])
        solid, _ = occ.fuse(shell, [(3, s) for s in add_sashes(placed)])
        occ.synchronize()

        groups = {name: [] for name in REGIONS}
        for _, tag in gmsh.model.getBoundary(solid, oriented=False):
            region = _region(tag, cfg, placed)
            if region:
                groups[region].append(tag)
        if empty := [name for name, tags in groups.items() if not tags]:
            raise RuntimeError(f"geometry problem: no surfaces found for STL region(s) {empty}")
        for name, tags in groups.items():
            gmsh.model.addPhysicalGroup(2, tags, name=name)

        # Triangles only describe the shape; flat faces need few, the round hinge posts more.
        gmsh.option.setNumber("Mesh.MeshSizeMax", 0.25)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
        gmsh.model.mesh.generate(2)
        gmsh.option.setNumber("Mesh.StlOneSolidPerSurface", 2)  # one STL solid per region, named like the group
        path.parent.mkdir(parents=True, exist_ok=True)
        gmsh.write(str(path))
        counts = {}
        for name, tags in groups.items():
            counts[name] = sum(len(gmsh.model.mesh.getElements(2, s)[1][0]) for s in tags)
        return counts
    finally:
        gmsh.finalize()

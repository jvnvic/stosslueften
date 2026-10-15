"""Write the OpenFOAM case files (0/, constant/, system/) for one case.

Each case has up to three stages, each with its own templates in cfd/templates/<stage>/:
- "flow":      steady wind flow with simpleFoam, in cases/<case_id>/
- "tracer":    air replacement with tracerFoam on the frozen flow, in cases/<case_id>/tracer/
- "transient": comparison run with time-varying flow (pimpleFoam), in cases/<case_id>/transient/

The @PLACEHOLDERS@ in the templates are filled in from the case config. The mesh
itself comes from geometry/generate.py (see run_case.py).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from cfd.config import CaseConfig
from geometry.windows import PlacedWindow, place_windows

TEMPLATES = Path(__file__).parent / "templates"
KAPPA, CMU = 0.40, 0.09  # same constants as templates/0/include/ABLConditions

# OpenFOAM patch type for each Gmsh patch. Wall functions only work on type "wall".
PATCH_TYPES = {
    "inlet": "patch",
    "outlet": "patch",
    "top": "patch",
    "sides": "symmetry",
    "ground": "wall",
    "building": "wall",
    "room_walls": "wall",
    "sashes": "wall",
}


def wind_profile(cfg: CaseConfig) -> dict[str, float]:
    """Friction velocity u* of the log-law wind profile, and k and omega at roof height."""
    z0, H = cfg.flow.roughness_length_m, cfg.building_height_m
    u_star = KAPPA * cfg.wind_speed_ms / math.log((H + z0) / z0)
    return {
        "u_star": u_star,
        "k": u_star**2 / math.sqrt(CMU),
        "omega": u_star / (math.sqrt(CMU) * KAPPA * H),
    }


def _vector(values) -> str:
    return "(" + " ".join(f"{v:.6g}" for v in values) + ")"


# Margin around the opening for the measuring plate; outside the opening it lies inside the solid wall.
ZONE_MARGIN_M = 0.05


def _opening_axes(pw: PlacedWindow) -> tuple[int, int]:
    """Indices of the coordinate axes along the wall and through the wall (walls are axis-aligned)."""
    return int(np.argmax(np.abs(pw.wall.along))), int(np.argmax(np.abs(pw.wall.inward)))


def window_zone(pw: PlacedWindow) -> str:
    """topoSet action: a face zone across the window opening, in the middle of the wall.

    It holds every mesh face whose owner-neighbour line crosses a plate in that plane, so the
    sum of the face fluxes phi over the zone is the exact flow through the opening (PLAN.md §5,
    finding 6). The sash and hinge post never reach this plane.
    """
    size = pw.size
    along, normal = _opening_axes(pw)
    centre = pw.start + pw.wall.along * size.width_m / 2 - pw.wall.inward * pw.wall_thickness_m / 2
    origin, span = centre.copy(), np.zeros(3)
    origin[along] = centre[along] - size.width_m / 2 - ZONE_MARGIN_M
    origin[2] = pw.start[2] - ZONE_MARGIN_M
    span[along] = size.width_m + 2 * ZONE_MARGIN_M
    span[2] = size.height_m + 2 * ZONE_MARGIN_M
    return f"""    {{
        name        {pw.name}FlowZone;
        type        faceZoneSet;
        action      new;
        source      searchableSurfaceToFaceZone;
        surfaceType searchablePlate;
        origin      {_vector(origin)};
        span        {_vector(span)};
    }}"""


def window_zone_sign(pw: PlacedWindow) -> float:
    """+1 or -1: turns the zone's flux sum into a flow into the room.

    The zone faces point along the plate normal, the positive axis through the wall.
    """
    _, normal = _opening_axes(pw)
    return float(np.sign(pw.wall.inward[normal]))


def window_monitor(pw: PlacedWindow) -> str:
    """Function objects for the flow through one window opening, summed over its face zone [m^3/s].

    Net = sum of phi (sign: see window_zone_sign). Abs = sum of |phi|, i.e. inflow plus outflow.
    Inflow = (Abs + net into the room) / 2, which also counts air that enters and leaves through
    the same window.
    """
    common = f"""    type            surfaceFieldValue;
    libs            (fieldFunctionObjects);
    regionType      faceZone;
    name            {pw.name}FlowZone;
    fields          (phi);
    writeFields     false;
    writeControl    timeStep;
    writeInterval   10;"""
    return f"""{pw.name}Net
{{
{common}
    operation       sum;
}}

{pw.name}Abs
{{
{common}
    operation       sumMag;
}}
"""


def average_start(cfg: CaseConfig) -> int:
    """Iteration from which the steady flow is averaged: the second half of the iterations."""
    return cfg.flow.max_iterations // 2


def mesh_levels(cfg: CaseConfig) -> dict[str, float]:
    """snappyHexMesh: background cell size and refinement levels (each level halves the cell size).

    The background size is window_m times a power of two close to far_m, so the
    window, room and building sizes of the config are met as closely as possible.
    """
    m = cfg.mesh
    base = m.window_m * 2 ** round(math.log2(m.far_m / m.window_m))

    def level(size: float) -> int:
        return max(0, round(math.log2(base / size)))

    window = level(m.window_m)
    return {"base": base, "building": level(m.building_m), "room": level(m.room_m), "window": window,
            "sash": window + 1}  # sash plates (6 cm) need cells clearly smaller than their thickness


def snappy_placeholders(cfg: CaseConfig) -> dict[str, str]:
    from geometry.generate import domain_bounds  # imported here: geometry imports cfd.config

    b, levels = domain_bounds(cfg), mesh_levels(cfg)
    room, t, H = cfg.room, cfg.room.wall_thickness_m, cfg.building_height_m
    geometry, regions = [], []
    for pw in place_windows(cfg):
        # Refinement box: the opening through the wall plus 15 cm all around.
        corners = pw.opening_corners()
        lo, hi = corners.min(axis=0) - 0.15, corners.max(axis=0) + 0.15
        geometry.append(f"    {pw.name}Opening\n    {{\n        type box;\n        min  {_vector(lo)};\n"
                        f"        max  {_vector(hi)};\n    }}")
        regions.append(f"        {pw.name}Opening {{ mode inside; levels ((1e15 {levels['window']})); }}")
    cells = [max(1, round(extent / levels["base"])) for extent in (b.x1 - b.x0, b.y1 - b.y0, b.z1)]
    # A point in the air: the room centre, nudged so it never lies exactly on a cell face.
    location = (room.width_m / 2 + 0.0123, room.depth_m / 2 + 0.0171, room.height_m / 2 + 0.0137)
    return {
        "BASE_SIZE": f"{levels['base']:g}",
        "X0": f"{b.x0:g}", "X1": f"{b.x1:g}", "Y0": f"{b.y0:g}", "Y1": f"{b.y1:g}", "Z1": f"{b.z1:g}",
        "NX": str(cells[0]), "NY": str(cells[1]), "NZ": str(cells[2]),
        "L_BUILDING": str(levels["building"]), "L_ROOM": str(levels["room"]),
        "L_WINDOW": str(levels["window"]), "L_SASH": str(levels["sash"]),
        "NEAR_MIN": f"{-t - H:g} {-t - H:g} 0",
        "NEAR_MAX": f"{room.width_m + t + H:g} {room.depth_m + t + 3 * H:g} {2 * H:g}",
        "OPENING_GEOMETRY": "\n".join(geometry),
        "OPENING_REGIONS": "\n".join(regions),
        "LOCATION_IN_MESH": " ".join(f"{v:g}" for v in location),
    }


def placeholders(cfg: CaseConfig) -> dict[str, str]:
    profile = wind_profile(cfg)
    room = cfg.room
    return {
        "WIND_SPEED": f"{cfg.wind_speed_ms:g}",
        "ZREF": f"{cfg.building_height_m:g}",
        "Z0": f"{cfg.flow.roughness_length_m:g}",
        "USTAR_SQ": f"{profile['u_star'] ** 2:.6g}",
        "K_INIT": f"{profile['k']:.6g}",
        "OMEGA_INIT": f"{profile['omega']:.6g}",
        "MAX_ITERATIONS": str(cfg.flow.max_iterations),
        "N_PROCS": str(cfg.flow.n_procs),
        "TRACER_DURATION": f"{cfg.flow.tracer_duration_s:g}",
        "TRACER_TIME_STEP": f"{cfg.flow.tracer_time_step_s:g}",
        "SPINUP": f"{cfg.flow.transient_spinup_s:g}",
        "TRANSIENT_END": f"{cfg.flow.transient_spinup_s + cfg.flow.tracer_duration_s:g}",
        "MAX_COURANT": f"{cfg.flow.transient_max_courant:g}",
        "ROOM_MAX": f"{room.width_m:g} {room.depth_m:g} {room.height_m:g}",
        "ROOM_FLOOR_MAX": f"{room.width_m:g} {room.depth_m:g} 0.01",
        "WINDOW_MONITORS": "\n".join(window_monitor(pw) for pw in place_windows(cfg)),
        "WINDOW_ZONES": "\n".join(window_zone(pw) for pw in place_windows(cfg)),
        "AVERAGE_START": str(average_start(cfg)),
        **snappy_placeholders(cfg),
    }


def write_case_files(cfg: CaseConfig, case_dir: Path, stage: str) -> None:
    """Copy every template of `stage` (flow, snappy, tracer, transient) into case_dir with the placeholders filled in."""
    values = placeholders(cfg)
    stage_dir = TEMPLATES / stage
    for template in sorted(stage_dir.rglob("*")):
        if not template.is_file():
            continue
        text = template.read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace(f"@{key}@", value)
        if leftover := sorted(set(re.findall(r"@[A-Z_]+@", text))):
            raise RuntimeError(f"{template}: placeholder(s) without a value: {leftover}")
        target = case_dir / template.relative_to(stage_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def set_patch_types(case_dir: Path) -> None:
    """gmshToFoam gives every patch the type 'patch'; set walls and symmetry planes."""
    boundary = case_dir / "constant" / "polyMesh" / "boundary"
    text = boundary.read_text(encoding="utf-8")
    for name, patch_type in PATCH_TYPES.items():
        for key in ("type", "physicalType"):
            pattern = rf"(\n\s*{name}\s*\{{[^}}]*?\b{key}\s+)\w+;"
            text, count = re.subn(pattern, rf"\g<1>{patch_type};", text)
            if key == "type" and count != 1:
                raise RuntimeError(f"patch {name!r} not found exactly once in {boundary}")
    boundary.write_text(text, encoding="utf-8")

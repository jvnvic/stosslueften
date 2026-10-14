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

from cfd.config import CaseConfig
from geometry.windows import UP, PlacedWindow, place_windows

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


def window_monitor(pw: PlacedWindow) -> str:
    """Function object for the net air flow through one window opening (positive = into the room).

    It integrates the velocity over a plane in the middle of the wall opening,
    where the sash and hinge post never reach.
    """
    size = pw.size
    centre = pw.start + pw.wall.along * size.width_m / 2 - pw.wall.inward * pw.wall_thickness_m / 2 + UP * size.height_m / 2
    corners = pw.opening_corners()
    return f"""{pw.name}Flow
{{
    type            surfaceFieldValue;
    libs            (fieldFunctionObjects);
    regionType      sampledSurface;
    name            {pw.name};
    sampledSurfaceDict
    {{
        type        cuttingPlane;
        point       {_vector(centre)};
        normal      {_vector(pw.wall.inward)};
        bounds      {_vector(corners.min(axis=0))} {_vector(corners.max(axis=0))};
        interpolate true;
    }}
    operation       areaNormalIntegrate;
    fields          (U);
    writeFields     false;
    writeControl    timeStep;
    writeInterval   10;
}}
"""


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
        "WINDOW_MONITORS": "\n".join(window_monitor(pw) for pw in place_windows(cfg)),
    }


def write_case_files(cfg: CaseConfig, case_dir: Path, stage: str) -> None:
    """Copy every template of `stage` ("flow" or "tracer") into case_dir with the placeholders filled in."""
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

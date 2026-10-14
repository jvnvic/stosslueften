"""Case configuration: read one YAML file and check it before anything is built.

Each simulation case is described by one complete YAML file (see
configs/default.yaml). Unknown or missing keys are errors, so a typo never
silently falls back to a default value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from pathlib import Path

import yaml

LAYOUTS = ("same_wall", "opposite_walls", "adjacent_walls")
MODES = ("turn", "tilt")
# Allowed opening angles in degrees. Below the minimum the sash is almost closed
# and the remaining gap would need extremely small mesh cells.
ANGLE_LIMITS_DEG = {"turn": (5.0, 90.0), "tilt": (2.0, 15.0)}


class ConfigError(ValueError):
    """An invalid configuration. The message says which key is wrong and why."""


@dataclass(frozen=True)
class Room:
    width_m: float  # inner size in x (south and north walls)
    depth_m: float  # inner size in y (west and east walls)
    height_m: float
    wall_thickness_m: float  # walls and roof


@dataclass(frozen=True)
class WindowSize:
    width_m: float
    height_m: float
    sill_height_m: float
    sash_thickness_m: float
    hinge_radius_m: float  # solid hinge post along the sash's rotation axis


@dataclass(frozen=True)
class Window:
    x_m: float  # window centre, measured along the wall (PLAN.md §1)
    mode: str  # "turn" or "tilt"
    angle_deg: float


@dataclass(frozen=True)
class Domain:
    """Outdoor air region around the building, in multiples of the building height H."""

    upstream_H: float
    downstream_H: float
    lateral_H: float
    top_H: float


@dataclass(frozen=True)
class MeshSizes:
    """Target cell sizes in metres, from finest to coarsest."""

    window_m: float
    room_m: float
    building_m: float
    far_m: float


@dataclass(frozen=True)
class CaseConfig:
    case_id: str
    layout: str
    window1: Window
    window2: Window
    wind_speed_ms: float
    room: Room
    window_size: WindowSize
    clearance_m: float
    domain: Domain
    mesh: MeshSizes

    @property
    def building_height_m(self) -> float:
        return self.room.height_m + self.room.wall_thickness_m


_NESTED = {cls.__name__: cls for cls in (Room, WindowSize, Window, Domain, MeshSizes)}


def load_config(path: str | Path) -> CaseConfig:
    """Read a case YAML file. Raises ConfigError if anything is missing or invalid."""
    with Path(path).open(encoding="utf-8") as f:
        return config_from_dict(yaml.safe_load(f))


def config_from_dict(data: dict) -> CaseConfig:
    cfg = _build(CaseConfig, data, "")
    _check_values(cfg)
    return cfg


def _build(cls, data, where: str):
    """Create dataclass `cls` from a dict, with clear errors for wrong keys or types."""
    label = where or "config"
    if not isinstance(data, dict):
        raise ConfigError(f"{label}: expected a mapping of keys, got {data!r}")
    names = [f.name for f in fields(cls)]
    if unknown := sorted(set(data) - set(names)):
        raise ConfigError(f"{label}: unknown key(s) {unknown}")
    if missing := sorted(set(names) - set(data)):
        raise ConfigError(f"{label}: missing key(s) {missing}")

    values = {}
    for f in fields(cls):
        key = f"{where}.{f.name}" if where else f.name
        value = data[f.name]
        if f.type in _NESTED:
            value = _build(_NESTED[f.type], value, key)
        elif f.type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{key}: expected a number, got {value!r}")
            value = float(value)
        elif f.type == "str" and not isinstance(value, str):
            raise ConfigError(f"{key}: expected text, got {value!r}")
        values[f.name] = value
    return cls(**values)


def _check_values(cfg: CaseConfig) -> None:
    def require(ok: bool, message: str) -> None:
        if not ok:
            raise ConfigError(message)

    require(
        re.fullmatch(r"[A-Za-z0-9_-]+", cfg.case_id) is not None,
        f"case_id {cfg.case_id!r}: use only letters, digits, '_' and '-' (it becomes a folder name)",
    )
    require(cfg.layout in LAYOUTS, f"layout {cfg.layout!r}: must be one of {', '.join(LAYOUTS)}")
    for name in ("window1", "window2"):
        window = getattr(cfg, name)
        require(window.mode in MODES, f"{name}.mode {window.mode!r}: must be 'turn' or 'tilt'")
        lo, hi = ANGLE_LIMITS_DEG[window.mode]
        require(
            lo <= window.angle_deg <= hi,
            f"{name}.angle_deg = {window.angle_deg}: must be between {lo} and {hi} in {window.mode} mode",
        )
    require(cfg.wind_speed_ms > 0, "wind_speed_ms must be > 0")
    require(cfg.clearance_m > 0, "clearance_m must be > 0")
    for section in ("room", "window_size", "domain", "mesh"):
        group = getattr(cfg, section)
        for f in fields(group):
            require(getattr(group, f.name) > 0, f"{section}.{f.name} must be > 0")

    size, room, mesh = cfg.window_size, cfg.room, cfg.mesh
    require(
        size.sill_height_m + size.height_m < room.height_m,
        "window_size: sill_height_m + height_m must be below the ceiling (room.height_m)",
    )
    require(
        size.sash_thickness_m / 2 < size.hinge_radius_m < cfg.clearance_m,
        "window_size.hinge_radius_m must be larger than half the sash thickness and smaller than clearance_m",
    )
    require(
        mesh.window_m <= mesh.room_m <= mesh.building_m <= mesh.far_m,
        "mesh sizes must grow: window_m <= room_m <= building_m <= far_m",
    )

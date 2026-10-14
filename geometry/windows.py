"""Window placement: wall coordinate frames, sash positions and validity checks.

This module only does vector maths (numpy, no Gmsh), so it is fast and easy to
test. geometry/generate.py turns the results into the 3D model.

Conventions (PLAN.md §1):
- Origin at the inner south-west floor corner; x points east, y north, z up.
- A window's x_m is its centre, measured along the wall from the west end
  (south/north walls) or the south end (west/east walls).
- Each sash is a plate that opens into the room about a solid hinge post: a
  vertical post on the hinge side in turn mode (`hinge: left|right`, seen from
  inside the room facing the window), a horizontal post along the sill in tilt
  mode. The post covers the plate's hinge edge, which avoids paper-thin gaps
  between sash and wall that could not be meshed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cfd.config import CaseConfig, ConfigError, WindowSize, Window, Room

UP = np.array([0.0, 0.0, 1.0])
# Open sashes of the two windows must stay at least this far apart (plan view),
# so the air gap between them can still be meshed.
MIN_SASH_GAP_M = 0.1
# The sash overlaps the opening on all sides (like a real sash on its frame), and the
# hinge post reaches a bit further. Then no sash or post surface lies exactly in a
# plane of the opening; such touching surfaces give razor-thin, unusable mesh cells.
SASH_OVERLAP_M = 0.025
POST_EXTENSION_M = SASH_OVERLAP_M + 0.02

# Which walls each layout uses (PLAN.md §1). The wind always comes from the south.
LAYOUT_WALLS = {
    "same_wall": ("south", "south"),
    "opposite_walls": ("south", "north"),
    "adjacent_walls": ("south", "east"),
}


@dataclass(frozen=True, eq=False)
class Wall:
    name: str
    origin: np.ndarray  # start corner on the inner wall face, at floor level
    along: np.ndarray  # unit vector along the wall, the direction in which x_m grows
    inward: np.ndarray  # unit normal pointing into the room
    length_m: float


def walls(room: Room) -> dict[str, Wall]:
    W, D = room.width_m, room.depth_m

    def wall(name, origin, along, inward, length):
        return Wall(name, np.array(origin, float), np.array(along, float), np.array(inward, float), length)

    return {
        "south": wall("south", (0, 0, 0), (1, 0, 0), (0, 1, 0), W),
        "north": wall("north", (0, D, 0), (1, 0, 0), (0, -1, 0), W),
        "west": wall("west", (0, 0, 0), (0, 1, 0), (1, 0, 0), D),
        "east": wall("east", (W, 0, 0), (0, 1, 0), (-1, 0, 0), D),
    }


def rotate(points, origin, axis, angle_rad: float) -> np.ndarray:
    """Rotate points (N×3) about the line through `origin` along `axis` (right-hand rule).

    Same convention as gmsh.model.occ.rotate, so numpy and Gmsh agree.
    """
    k = np.asarray(axis, float) / np.linalg.norm(axis)
    p = np.atleast_2d(points) - origin
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    return p * c + np.cross(k, p) * s + np.outer(p @ k, k) * (1 - c) + origin


@dataclass(frozen=True, eq=False)
class PlacedWindow:
    """One window in global coordinates, with its sash in the open position."""

    name: str  # "window1" or "window2"
    wall: Wall
    window: Window
    size: WindowSize
    wall_thickness_m: float

    @property
    def start(self) -> np.ndarray:
        """Opening corner on the inner wall face, at the wall's start side (smaller x_m), at sill height."""
        offset = self.window.x_m - self.size.width_m / 2
        return self.wall.origin + self.wall.along * offset + UP * self.size.sill_height_m

    @property
    def hinge_at_end(self) -> bool:
        """True if the turn hinge is on the opening's end side (larger x_m) rather than its start side."""
        right = np.cross(UP, self.wall.inward)  # "right" for someone inside the room facing the window
        towards_hinge = right if self.window.hinge == "right" else -right
        return bool(towards_hinge @ self.wall.along > 0)

    @property
    def hinge_point(self) -> np.ndarray:
        """A point on the rotation axis: the hinge-side bottom corner of the opening."""
        if self.window.mode == "turn" and self.hinge_at_end:
            return self.start + self.wall.along * self.size.width_m
        return self.start  # tilt: the axis runs along the whole sill, so the start corner works

    @property
    def hinge_axis(self) -> np.ndarray:
        return UP if self.window.mode == "turn" else self.wall.along

    @property
    def rotation_rad(self) -> float:
        """Signed rotation about hinge_axis that opens the sash into the room."""
        # The sash edge opposite the hinge points along the wall (turn) or up (tilt);
        # pick the rotation direction that moves this edge towards the room.
        if self.window.mode == "turn":
            free_edge = -self.wall.along if self.hinge_at_end else self.wall.along
        else:
            free_edge = UP
        sign = np.sign(np.cross(self.hinge_axis, free_edge) @ self.wall.inward)
        return float(sign * np.radians(self.window.angle_deg))

    def _wall_box(self, u_range, n_range, z_range) -> np.ndarray:
        """8 corners of a box given in wall coordinates (along, inward, up) relative to `start`."""
        w = self.wall
        return np.array(
            [self.start + u * w.along + n * w.inward + z * UP for u in u_range for n in n_range for z in z_range]
        )

    def opening_corners(self) -> np.ndarray:
        """The hole through the wall, from the outer to the inner wall face."""
        return self._wall_box((0, self.size.width_m), (-self.wall_thickness_m, 0), (0, self.size.height_m))

    def closed_sash_corners(self) -> np.ndarray:
        """Sash plate in the closed position, centred on the inner wall face, overlapping the opening."""
        half, a = self.size.sash_thickness_m / 2, SASH_OVERLAP_M
        return self._wall_box((-a, self.size.width_m + a), (-half, half), (-a, self.size.height_m + a))

    def sash_corners(self) -> np.ndarray:
        return rotate(self.closed_sash_corners(), self.hinge_point, self.hinge_axis, self.rotation_rad)

    def hinge_post(self) -> tuple[np.ndarray, np.ndarray, float]:
        """Hinge post cylinder as (start point, axis vector with full length, radius).

        It runs along the hinge edge of the opening and sticks out by POST_EXTENSION_M at both ends.
        """
        length = self.size.height_m if self.window.mode == "turn" else self.size.width_m
        start = self.hinge_point - self.hinge_axis * POST_EXTENSION_M
        return start, self.hinge_axis * (length + 2 * POST_EXTENSION_M), self.size.hinge_radius_m

    def footprint_xy(self) -> np.ndarray:
        """Plan-view outline (x, y) of the open sash plus hinge post, as a convex polygon."""
        start, axis, r = self.hinge_post()
        side_dirs = [d for d in (self.wall.along, self.wall.inward, UP) if abs(d @ axis) < 1e-9]
        post = [p + a * r * side_dirs[0] + b * r * side_dirs[1] for p in (start, start + axis) for a in (-1, 1) for b in (-1, 1)]
        return convex_hull(np.vstack([self.sash_corners(), post])[:, :2])

    def contains_sash_point(self, point, tol: float = 1e-4) -> bool:
        """True if `point` lies inside or on the open sash plate or its hinge post."""
        point = np.asarray(point, float)
        # Rotate the point back to the closed position and test the closed plate box.
        p = rotate(point, self.hinge_point, self.hinge_axis, -self.rotation_rad)[0] - self.start
        u, n, z = p @ self.wall.along, p @ self.wall.inward, p @ UP
        half, a = self.size.sash_thickness_m / 2, SASH_OVERLAP_M
        in_plate = (
            -a - tol <= u <= self.size.width_m + a + tol
            and -half - tol <= n <= half + tol
            and -a - tol <= z <= self.size.height_m + a + tol
        )
        start, axis, r = self.hinge_post()
        length = np.linalg.norm(axis)
        d = point - start
        along_post = d @ axis / length
        radial = np.linalg.norm(d - along_post * axis / length)
        in_post = -tol <= along_post <= length + tol and radial <= r + tol
        return bool(in_plate or in_post)


def place_windows(cfg: CaseConfig) -> tuple[PlacedWindow, PlacedWindow]:
    """Put both windows on their walls and check that the arrangement can be built.

    Raises ConfigError if a window does not fit on its wall, the two windows
    overlap, or the open sashes would collide.
    """
    all_walls = walls(cfg.room)
    size, clearance = cfg.window_size, cfg.clearance_m
    placed = []
    for name, wall_name in zip(("window1", "window2"), LAYOUT_WALLS[cfg.layout]):
        window, wall = getattr(cfg, name), all_walls[wall_name]
        lo = clearance + size.width_m / 2
        hi = wall.length_m - clearance - size.width_m / 2
        if not lo <= window.x_m <= hi:
            raise ConfigError(
                f"{name}.x_m = {window.x_m} m does not fit on the {wall_name} wall: allowed range is {lo:.2f}-{hi:.2f} m"
            )
        placed.append(PlacedWindow(name, wall, window, size, cfg.room.wall_thickness_m))

    w1, w2 = placed
    min_distance = size.width_m + clearance
    if w1.wall.name == w2.wall.name and abs(w1.window.x_m - w2.window.x_m) < min_distance:
        raise ConfigError(
            f"window1 and window2 overlap on the {w1.wall.name} wall: their x_m must differ by at least {min_distance:.2f} m"
        )
    if not polygons_apart(w1.footprint_xy(), w2.footprint_xy(), MIN_SASH_GAP_M):
        raise ConfigError(
            "the open sashes of window1 and window2 collide or are closer than "
            f"{MIN_SASH_GAP_M} m: move the windows apart or reduce the opening angles"
        )
    return w1, w2


def convex_hull(points: np.ndarray) -> np.ndarray:
    """Convex hull of 2D points, counter-clockwise (Andrew's monotone chain)."""
    pts = list(dict.fromkeys(map(tuple, np.round(points, 9))))
    pts.sort()

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def polygons_apart(a: np.ndarray, b: np.ndarray, gap: float) -> bool:
    """True if convex polygons a and b are at least `gap` apart (separating axis test)."""
    for poly in (a, b):
        for edge in np.roll(poly, -1, axis=0) - poly:
            axis = np.array([-edge[1], edge[0]]) / np.linalg.norm(edge)
            pa, pb = a @ axis, b @ axis
            if pa.max() + gap <= pb.min() or pb.max() + gap <= pa.min():
                return True
    return False

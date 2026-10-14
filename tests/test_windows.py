import numpy as np
import pytest

from cfd.config import ConfigError, Window
from geometry.windows import PlacedWindow, place_windows, walls


def _placed(cfg, wall_name, window):
    return PlacedWindow("window1", walls(cfg.room)[wall_name], window, cfg.window_size, cfg.room.wall_thickness_m)


@pytest.mark.parametrize("wall_name", ["south", "north", "west", "east"])
@pytest.mark.parametrize("mode, angle", [("turn", 90), ("turn", 20), ("tilt", 6)])
@pytest.mark.parametrize("hinge", ["left", "right"])
def test_sash_opens_into_the_room(make_config, wall_name, mode, angle, hinge):
    cfg = make_config()
    size = cfg.window_size
    pw = _placed(cfg, wall_name, Window(2.0, mode, angle, hinge))

    inward = (pw.sash_corners() - pw.wall.origin) @ pw.wall.inward
    free_edge = size.width_m if mode == "turn" else size.height_m
    a = np.radians(angle)
    # The free edge of the sash swings into the room by free_edge * sin(angle).
    assert inward.max() == pytest.approx(free_edge * np.sin(a) + size.sash_thickness_m / 2 * np.cos(a))


# Window centred at x_m = 2.0 on a 1.0 m wide opening, so its edges are at 1.5 and 2.5 along the wall.
# Seen from inside facing the wall, "right" is west on the south wall, east on the north wall,
# south on the east wall and north on the west wall.
@pytest.mark.parametrize(
    "wall_name, hinge, edge",
    [("south", "right", 1.5), ("south", "left", 2.5), ("north", "right", 2.5), ("north", "left", 1.5),
     ("east", "right", 1.5), ("east", "left", 2.5), ("west", "right", 2.5), ("west", "left", 1.5)],
)
def test_turn_sash_stands_at_its_hinge_edge(make_config, wall_name, hinge, edge):
    cfg = make_config()
    pw = _placed(cfg, wall_name, Window(2.0, "turn", 90, hinge))
    along = (pw.sash_corners() - pw.wall.origin) @ pw.wall.along
    # Opened 90°, the sash stands perpendicular to the wall at the hinge edge.
    half = cfg.window_size.sash_thickness_m / 2
    assert along.min() == pytest.approx(edge - half)
    assert along.max() == pytest.approx(edge + half)


def test_hinge_side_does_not_change_a_tilted_sash(make_config):
    cfg = make_config()
    left = _placed(cfg, "south", Window(2.0, "tilt", 6, "left")).sash_corners()
    right = _placed(cfg, "south", Window(2.0, "tilt", 6, "right")).sash_corners()
    np.testing.assert_allclose(left, right)


def test_window_must_fit_on_its_wall(make_config):
    with pytest.raises(ConfigError, match="window2.x_m = 3.5 m does not fit on the east wall"):
        place_windows(make_config("adjacent_walls", w1=(2.5, "turn", 90), w2=(3.5, "turn", 90)))


def test_windows_on_the_same_wall_must_not_overlap(make_config):
    with pytest.raises(ConfigError, match="overlap on the south wall"):
        place_windows(make_config("same_wall", w1=(1.5, "turn", 90), w2=(2.6, "turn", 90)))


@pytest.mark.parametrize("angle", [15, 45, 90])
def test_closest_allowed_windows_on_same_wall_are_valid(make_config, angle):
    place_windows(make_config("same_wall", w1=(1.5, "turn", angle), w2=(2.7, "turn", 90)))


def test_sashes_near_a_shared_corner_collide(make_config):
    # Both sashes swing towards the south-east corner and meet there.
    with pytest.raises(ConfigError, match="collide"):
        place_windows(make_config("adjacent_walls", w1=(4.3, "turn", 45, "right"), w2=(0.7, "turn", 45, "right")))


def test_hinge_side_can_avoid_a_collision(make_config):
    # Same positions as above, but the south sash now swings away from the corner.
    place_windows(make_config("adjacent_walls", w1=(4.3, "turn", 45, "left"), w2=(0.7, "turn", 45, "right")))


def test_sashes_far_from_the_shared_corner_are_valid(make_config):
    place_windows(make_config("adjacent_walls", w1=(1.0, "turn", 45), w2=(3.3, "turn", 45)))

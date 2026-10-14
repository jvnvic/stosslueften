import numpy as np
import pytest

from cfd.config import ConfigError, Window
from geometry.windows import PlacedWindow, place_windows, walls


@pytest.mark.parametrize("wall_name", ["south", "north", "west", "east"])
@pytest.mark.parametrize("mode, angle", [("turn", 90), ("turn", 20), ("tilt", 6)])
def test_sash_opens_into_the_room(make_config, wall_name, mode, angle):
    cfg = make_config()
    size = cfg.window_size
    wall = walls(cfg.room)[wall_name]
    pw = PlacedWindow("window1", wall, Window(2.0, mode, angle), size, cfg.room.wall_thickness_m)

    inward = (pw.sash_corners() - wall.origin) @ wall.inward
    free_edge = size.width_m if mode == "turn" else size.height_m
    a = np.radians(angle)
    # The free edge of the sash swings into the room by free_edge * sin(angle).
    assert inward.max() == pytest.approx(free_edge * np.sin(a) + size.sash_thickness_m / 2 * np.cos(a))


def test_turn_sash_hinges_on_the_start_side(make_config):
    cfg = make_config(w1=(2.5, "turn", 90))
    w1, _ = place_windows(cfg)
    x = w1.sash_corners()[:, 0]
    # Opened 90°, the sash stands next to the west edge of the opening (x = 2.0).
    assert x.min() == pytest.approx(2.0 - cfg.window_size.sash_thickness_m / 2)
    assert x.max() == pytest.approx(2.0 + cfg.window_size.sash_thickness_m / 2)


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
        place_windows(make_config("adjacent_walls", w1=(4.3, "turn", 45), w2=(0.7, "turn", 45)))


def test_sashes_far_from_the_shared_corner_are_valid(make_config):
    place_windows(make_config("adjacent_walls", w1=(1.0, "turn", 45), w2=(3.3, "turn", 45)))

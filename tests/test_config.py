import pytest

from cfd.config import ConfigError, config_from_dict, load_config
from tests.conftest import DEFAULT_CONFIG


def test_default_config_loads():
    cfg = load_config(DEFAULT_CONFIG)
    assert cfg.layout == "opposite_walls"
    assert cfg.building_height_m == pytest.approx(2.8)


def test_unknown_key_is_an_error(default_dict):
    default_dict["window1"]["angle"] = 45
    with pytest.raises(ConfigError, match=r"window1: unknown key\(s\) \['angle'\]"):
        config_from_dict(default_dict)


def test_missing_key_is_an_error(default_dict):
    del default_dict["wind_speed_ms"]
    with pytest.raises(ConfigError, match="missing key"):
        config_from_dict(default_dict)


def test_text_instead_of_number_is_an_error(default_dict):
    default_dict["window1"]["x_m"] = "2.5 m"
    with pytest.raises(ConfigError, match="window1.x_m: expected a number"):
        config_from_dict(default_dict)


@pytest.mark.parametrize(
    "mode, angle, ok", [("turn", 90, True), ("turn", 4, False), ("turn", 95, False), ("tilt", 6, True), ("tilt", 30, False)]
)
def test_angle_limits_depend_on_mode(default_dict, mode, angle, ok):
    default_dict["window2"] = {"x_m": 2.5, "mode": mode, "angle_deg": angle}
    if ok:
        config_from_dict(default_dict)
    else:
        with pytest.raises(ConfigError, match="window2.angle_deg"):
            config_from_dict(default_dict)


def test_unknown_layout_is_an_error(default_dict):
    default_dict["layout"] = "corner"
    with pytest.raises(ConfigError, match="layout 'corner'"):
        config_from_dict(default_dict)

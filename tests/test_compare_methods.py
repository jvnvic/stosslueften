import dataclasses

from analysis.compare_methods import describe, table


def test_label_names_layout_windows_wind_and_non_standard_mesh(make_config):
    cfg = make_config(layout="same_wall", w1=(1.4, "turn", 90), w2=(3.6, "tilt", 6))
    assert describe(cfg) == "same wall, turn 90 / tilt 6, 3 m/s"
    coarse = dataclasses.replace(cfg, mesh=dataclasses.replace(cfg.mesh, window_m=0.07))
    assert describe(coarse).endswith(", cells ×1.4")


def test_table_shows_difference_and_missing_t90():
    case = {"label": "x", "A": {"tau_s": 120.0, "t90_s": float("nan")}, "B": {"tau_s": 100.0, "t90_s": 250.0},
            "largest_gap": 3.25}
    row = table([case]).splitlines()[-1]
    assert row == "| x | 120 | 100 | +20 % | – | 250 | 3.2 |"

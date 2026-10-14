"""OpenFOAM case files are written correctly (no OpenFOAM installation needed)."""

import math

import pytest

from cfd.case_setup import PATCH_TYPES, set_patch_types, wind_profile, write_case_files


def test_wind_profile_matches_the_log_law(make_config):
    cfg = make_config()
    u_star = wind_profile(cfg)["u_star"]
    z0, H = cfg.flow.roughness_length_m, cfg.building_height_m
    # The log-law profile u(z) = u*/kappa * ln((z + z0)/z0) gives the wind speed at roof height.
    assert u_star / 0.40 * math.log((H + z0) / z0) == pytest.approx(cfg.wind_speed_ms)


@pytest.mark.parametrize("stage", ["flow", "tracer", "transient"])
def test_all_placeholders_are_filled(make_config, tmp_path, stage):
    cfg = make_config("same_wall", w1=(1.4, "turn", 45), w2=(3.6, "tilt", 6))
    write_case_files(cfg, tmp_path, stage)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert "@" not in path.read_text(), f"placeholder left in {path}"
    if stage == "flow":
        assert "internalField   uniform (0 3 0);" in (tmp_path / "0" / "U").read_text()
        monitors = (tmp_path / "system" / "monitors").read_text()
        assert "window1Flow" in monitors and "window2Flow" in monitors
    elif stage == "tracer":
        control = (tmp_path / "system" / "controlDict").read_text()
        assert "endTime         600;" in control and "deltaT          0.2;" in control
    else:
        control = (tmp_path / "system" / "controlDict").read_text()
        assert "endTime         660;" in control and "maxCo           10;" in control  # 60 s spin-up + 600 s
        assert "timeStart       60;" in (tmp_path / "system" / "monitors").read_text()


def test_patch_types_are_set(tmp_path):
    entries = "".join(
        f"\n    {name}\n    {{\n        type            patch;\n        physicalType    patch;\n"
        f"        nFaces          10;\n        startFace       0;\n    }}"
        for name in PATCH_TYPES
    )
    boundary = tmp_path / "constant" / "polyMesh" / "boundary"
    boundary.parent.mkdir(parents=True)
    boundary.write_text(f"8\n({entries}\n)\n")

    set_patch_types(tmp_path)
    text = boundary.read_text()
    assert "ground\n    {\n        type            wall;\n        physicalType    wall;" in text
    assert "sides\n    {\n        type            symmetry;" in text
    assert "inlet\n    {\n        type            patch;" in text

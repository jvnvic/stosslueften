"""OpenFOAM case files are written correctly (no OpenFOAM installation needed)."""

import math

import pytest

from cfd.case_setup import (PATCH_TYPES, mesh_levels, set_patch_types, wind_profile, window_zone,
                             window_zone_sign, write_case_files)
from geometry.windows import place_windows


def test_wind_profile_matches_the_log_law(make_config):
    cfg = make_config()
    u_star = wind_profile(cfg)["u_star"]
    z0, H = cfg.flow.roughness_length_m, cfg.building_height_m
    # The log-law profile u(z) = u*/kappa * ln((z + z0)/z0) gives the wind speed at roof height.
    assert u_star / 0.40 * math.log((H + z0) / z0) == pytest.approx(cfg.wind_speed_ms)


@pytest.mark.parametrize("stage", ["flow", "snappy", "tracer", "transient"])
def test_all_placeholders_are_filled(make_config, tmp_path, stage):
    cfg = make_config("same_wall", w1=(1.4, "turn", 45), w2=(3.6, "tilt", 6))
    write_case_files(cfg, tmp_path, stage)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert "@" not in path.read_text(), f"placeholder left in {path}"
    if stage == "flow":
        assert "internalField   uniform (0 3 0);" in (tmp_path / "0" / "U").read_text()
        monitors = (tmp_path / "system" / "monitors").read_text()
        assert all(f"window{i}{op}" in monitors for i in (1, 2) for op in ("Net", "Abs"))
        assert "type            fieldAverage;" in monitors and "timeStart       1000;" in monitors
        topo = (tmp_path / "system" / "topoSetDict").read_text()
        assert topo.count("source      searchableSurfaceToFaceZone;") == 2 and "window1FlowZone" in topo
    elif stage == "snappy":
        block = (tmp_path / "system" / "blockMeshDict").read_text()
        assert "hex (0 1 2 3 4 5 6 7) (21 38 10)" in block  # 1.6 m background cells
        assert "window2Opening" in (tmp_path / "system" / "snappyHexMeshDict").read_text()
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


def test_mesh_levels_match_the_configured_sizes(make_config):
    levels = mesh_levels(make_config())
    # Background 1.6 m; 0.4 m near the building, 0.2 m in the room, 0.05 m in the openings, 0.025 m at sashes.
    assert levels == {"base": pytest.approx(1.6), "building": 2, "room": 3, "window": 5, "sash": 6}


def test_window_zone_plates_lie_in_the_wall_and_signs_point_into_the_room(make_config):
    cfg = make_config("adjacent_walls", w1=(2.5, "turn", 60), w2=(2.0, "tilt", 6))
    south, east = place_windows(cfg)
    assert window_zone_sign(south) == 1.0  # zone normal +y = into the room through the south wall
    assert window_zone_sign(east) == -1.0  # zone normal +x points out of the room through the east wall
    # the east plate is a y-z plate in the middle of the east wall (x = 5 + 0.3/2)
    assert "origin      (5.15 1.45 0.85);" in window_zone(east)
    assert "span        (0 1.1 1.35);" in window_zone(east)

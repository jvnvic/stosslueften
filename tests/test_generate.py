"""Gmsh builds the model for every layout and mode combination (geometry only, fast)."""

import gmsh
import numpy as np
import pytest

from cfd.config import LAYOUTS
from geometry.generate import PATCHES, generate
from geometry.windows import place_windows

POSITIONS = {"same_wall": (1.2, 3.8), "opposite_walls": (2.5, 1.5), "adjacent_walls": (1.5, 2.0)}
ANGLES = {"turn": (15, 90), "tilt": (6, 6)}


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("modes", [("turn", "turn"), ("turn", "tilt"), ("tilt", "turn"), ("tilt", "tilt")])
@pytest.mark.parametrize("angle_index", [0, 1])
def test_model_has_one_air_volume_and_all_patches(make_config, layout, modes, angle_index):
    x1, x2 = POSITIONS[layout]
    m1, m2 = modes
    cfg = make_config(layout, w1=(x1, m1, ANGLES[m1][angle_index]), w2=(x2, m2, ANGLES[m2][angle_index]))
    summary = generate(cfg, mesh=False)  # raises if the air volume or any patch is missing
    assert set(summary["surfaces_per_patch"]) == set(PATCHES)


@pytest.mark.parametrize("mode, angle", [("turn", 35), ("tilt", 6)])
def test_gmsh_rotation_matches_numpy(make_config, mode, angle):
    cfg = make_config("adjacent_walls", w1=(1.5, mode, angle), w2=(2.0, mode, angle))
    gmsh.initialize()
    try:
        for pw in place_windows(cfg):
            corners = pw.closed_sash_corners()
            lo, hi = corners.min(axis=0), corners.max(axis=0)
            plate = gmsh.model.occ.addBox(*lo, *(hi - lo))
            gmsh.model.occ.rotate([(3, plate)], *pw.start, *pw.hinge_axis, pw.rotation_rad)
            gmsh.model.occ.synchronize()
            box = np.array(gmsh.model.getBoundingBox(3, plate))
            expected = pw.sash_corners()
            np.testing.assert_allclose(box[:3], expected.min(axis=0), atol=1e-4)
            np.testing.assert_allclose(box[3:], expected.max(axis=0), atol=1e-4)
    finally:
        gmsh.finalize()

"""The STL surface for snappyHexMesh has all three regions (no OpenFOAM needed)."""

import pytest

from geometry.surfaces import REGIONS, write_obstacle_stl


@pytest.mark.parametrize("layout, w1, w2", [
    ("opposite_walls", (2.5, "turn", 90), (2.5, "turn", 90)),
    ("same_wall", (1.4, "turn", 45), (3.6, "tilt", 6)),
    ("adjacent_walls", (1.5, "turn", 60, "right"), (2.5, "turn", 30)),
])
def test_stl_has_all_regions(make_config, tmp_path, layout, w1, w2):
    path = tmp_path / "obstacle.stl"
    counts = write_obstacle_stl(make_config(layout, w1=w1, w2=w2), path)
    assert set(counts) == set(REGIONS) and all(n > 0 for n in counts.values())
    solids = [line.split()[1] for line in path.read_text().splitlines() if line.startswith("solid")]
    assert sorted(solids) == sorted(REGIONS)

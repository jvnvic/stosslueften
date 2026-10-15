import pyvista as pv

from analysis.visualize import _crop


def test_crop_keeps_whole_cells_inside_the_box():
    grid = pv.Plane(center=(0, 0, 0), i_size=4, j_size=4, i_resolution=4, j_resolution=4)  # 16 unit squares
    kept = _crop(grid, -2.0, 0.0, -2.0, 2.0)  # left half by cell centre
    assert kept.n_cells == 8
    assert all(kept.get_cell(i).n_points == 4 for i in range(kept.n_cells))  # still squares, not triangles

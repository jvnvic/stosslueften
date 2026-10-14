"""The render step gets real surfaces from the Gmsh model (no picture is drawn here)."""

from geometry.render import surface_meshes


def test_surface_meshes_are_not_empty(make_config):
    meshes = surface_meshes(make_config("same_wall", w1=(1.4, "turn", 45), w2=(3.6, "tilt", 6)))
    assert set(meshes) == {"building", "room_walls", "sashes"}
    assert all(mesh.n_cells > 0 for mesh in meshes.values())

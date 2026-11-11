"""Seats and table tops are found from the furniture's own GLB (named parts, else its flat faces), and points are judged
inside its real solid, not its box: a one-mesh table's leg room is empty."""
import pytest

from services.procedural_3d.compose import compose_glb
from services.procedural_3d.furniture import KINDS, furniture_glb, furniture_spec
from services.procedural_3d.glb_bounds import glb_bounds
from services.procedural_3d.glb_parts import glb_parts
from services.world3d_mesh_solid import crossings, flat_tops, inside, mesh_of
from services.world3d_scene_bounds import normalisation
from services.world3d_seats import seat_surface, table_top


def _box(centre, size, colour="#8a5a3b"):
    return {"type": "box", "position": list(centre), "scale": list(size), "color": colour}


def one_mesh_chair():
    """A chair built as ONE mesh node (like the Kenney chair): seat at 0.46 m, back along -z up to 0.9 m."""
    legs = [_box((x, 0.2, z), (0.04, 0.4, 0.04)) for x in (-0.2, 0.2) for z in (-0.2, 0.2)]
    return [_box((0, 0.43, 0), (0.46, 0.06, 0.46)), _box((0, 0.68, -0.205), (0.46, 0.44, 0.05)), *legs]


def one_mesh_table():
    legs = [_box((x, 0.355, z), (0.05, 0.71, 0.05)) for x in (-0.55, 0.55) for z in (-0.35, 0.35)]
    return [_box((0, 0.73, 0), (1.2, 0.04, 0.8)), *legs]


def one_mesh_bed():
    """Frame, mattress (top 0.5) and a headboard across the short -x end, all one node; 2 m along x, 1.4 m along z."""
    return [_box((0, 0.2, 0), (2.0, 0.2, 1.4)), _box((0.03, 0.4, 0), (1.94, 0.2, 1.36)), _box((-0.97, 0.5, 0), (0.06, 1.0, 1.4))]


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def measured(path, height=None):
    """(box, factor, mesh, parts) with the model drawn ``height`` metres tall (its real size when None)."""
    box = glb_bounds(path)
    scale = (height or box["size"][1]) / 1.7
    return box, normalisation(box) * scale, mesh_of(path), glb_parts(path)["parts"]


@pytest.mark.parametrize("kind", KINDS)
def test_every_procedural_kind_is_named_parts_at_its_real_size_standing_on_the_floor(tmp_path, kind):
    spec = furniture_spec(kind)
    path = write(tmp_path, f"{kind}.glb", furniture_glb(spec))
    box, parts = glb_bounds(path), glb_parts(path)["parts"]
    assert box["min"][1] == pytest.approx(0, abs=1e-6) and abs(box["center"][0]) < 0.05 and abs(box["center"][2]) < 0.05
    names = {part["name"] for part in parts}
    assert names & {"seat", "top", "mattress"}, names
    assert len(parts) == len(names), "every part is its own named node"


def test_the_seat_height_sets_a_chairs_height_and_sizes_are_checked():
    assert furniture_spec({"kind": "chair", "seat": 0.28}) == {"kind": "chair", "height": 0.5478, "width": 0.46, "depth": 0.46,
                                                                "color": "#8a5a3b", "seat": 0.28}
    assert furniture_spec({"kind": "table", "height": 0.7})["height"] == 0.7 and "seat" not in furniture_spec("table")
    for bad in ({"kind": "throne"}, {"kind": "chair", "seat": 2}, {"kind": "chair", "height": 0.5, "seat": 0.45}, {"kind": "bed", "color": "red"}):
        with pytest.raises(ValueError):
            furniture_spec(bad)


def test_a_multi_part_chair_sits_on_its_named_seat_facing_away_from_its_back(tmp_path):
    path = write(tmp_path, "chair.glb", furniture_glb(furniture_spec("chair")))
    seat = seat_surface(*measured(path))
    assert seat.y == pytest.approx(0.46, abs=1e-4) and seat.name == "seat" and seat.how == "part" and not seat.guessed
    assert seat.front == [0.0, 1.0]


def test_a_one_mesh_chair_is_found_from_its_faces_and_says_it_guessed(tmp_path):
    path = write(tmp_path, "chair-mesh.glb", compose_glb(one_mesh_chair(), "chair"))
    assert len(glb_parts(path)["parts"]) == 1
    box, factor, mesh, parts = measured(path)
    seat = seat_surface(box, factor, mesh, parts)
    assert seat.y == pytest.approx(0.46, abs=0.005), "the seat, not the back's top edge at 0.9 m"
    assert seat.how == "faces" and seat.guessed and seat.front == [0.0, 1.0]


def test_a_one_mesh_stool_sits_on_its_box_top_without_guessing(tmp_path):
    legs = [_box((x, 0.21, z), (0.04, 0.42, 0.04)) for x in (-0.14, 0.14) for z in (-0.14, 0.14)]
    path = write(tmp_path, "stool.glb", compose_glb([_box((0, 0.44, 0), (0.36, 0.04, 0.36)), *legs], "stool"))
    seat = seat_surface(*measured(path))
    assert seat.y == pytest.approx(0.46, abs=0.005) and not seat.guessed and seat.front is None


def test_a_bed_is_sat_on_along_its_long_side_and_the_headboard_is_not_a_backrest(tmp_path):
    named = seat_surface(*measured(write(tmp_path, "bed.glb", furniture_glb(furniture_spec("bed")))))
    assert named.name == "mattress" and named.y == pytest.approx(0.55, abs=1e-4) and named.front is None
    mesh_bed = seat_surface(*measured(write(tmp_path, "bed-mesh.glb", compose_glb(one_mesh_bed(), "bed"))))
    assert mesh_bed.y == pytest.approx(0.5, abs=0.005) and mesh_bed.front is None
    assert mesh_bed.size[0] > 1.8, "the whole mattress, not the frame under it"


def test_a_sofa_seat_is_its_cushion_not_its_back_or_arms(tmp_path):
    seat = seat_surface(*measured(write(tmp_path, "sofa.glb", furniture_glb(furniture_spec("sofa")))))
    assert seat.name == "seat" and seat.y == pytest.approx(0.44, abs=1e-4) and seat.front == [0.0, 1.0]


def test_a_table_top_comes_from_a_named_top_or_the_highest_wide_face(tmp_path):
    named = table_top(*measured(write(tmp_path, "table.glb", furniture_glb(furniture_spec("table")))))
    assert named.name == "top" and named.y == pytest.approx(0.75, abs=1e-4)
    path = write(tmp_path, "table-mesh.glb", compose_glb(one_mesh_table(), "table"))
    top = table_top(*measured(path))
    assert top.y == pytest.approx(0.75, abs=0.005) and top.size[0] == pytest.approx(1.2, abs=0.01)


def test_a_one_mesh_table_is_solid_only_where_it_has_material(tmp_path):
    mesh = mesh_of(write(tmp_path, "table-mesh.glb", compose_glb(one_mesh_table(), "table")))
    depth, part = inside(mesh, [[0.0, 0.4, 0.0], [0.0, 0.73, 0.0], [0.55, 0.3, 0.35], [0.0, 0.9, 0.0]])
    assert depth[0] == 0, "knees under the top are in the leg room, not in the table"
    assert depth[1] == pytest.approx(0.02, abs=0.002) and depth[2] > 0 and depth[3] == 0
    assert list(part[[0, 3]]) == [-1, -1]
    assert len(crossings(mesh, [0.0, 0.6, 0.0], [0.0, 0.9, 0.0])) == 2, "a forearm through the top crosses its two faces"
    assert len(crossings(mesh, [0.0, 0.4, 0.0], [0.0, 0.6, 0.0])) == 0


def test_flat_tops_group_faces_by_height_with_their_area(tmp_path):
    mesh = mesh_of(write(tmp_path, "chair-mesh.glb", compose_glb(one_mesh_chair(), "chair")))
    tops = flat_tops(mesh)
    assert tops[0]["y"] == pytest.approx(0.9, abs=1e-3) and tops[0]["area"] == pytest.approx(0.46 * 0.05, rel=0.05)
    seat = next(item for item in tops if abs(item["y"] - 0.46) < 0.005)
    assert seat["area"] == pytest.approx(0.46 * 0.46, rel=0.05), "the whole top face of the seat box (the back stands on it)"

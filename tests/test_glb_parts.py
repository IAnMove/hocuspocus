"""glb_parts: one world-space box per mesh node of a GLB, from its JSON chunk (tiny hand-built files, no buffers)."""
import pytest

from services.procedural_3d.glb_parts import glb_parts
from tests.test_glb_bounds import Q_Y90, accessor, mesh, write


def town(tmp_path, boxes, nodes=None, scene_nodes=None, name="town.glb"):
    """A GLB with one mesh and one accessor per box ``(low, high)``; ``nodes`` says how they hang in the tree (default: all roots)."""
    document = {"scene": 0, "scenes": [{"nodes": scene_nodes if scene_nodes is not None else list(range(len(boxes)))}],
                "nodes": nodes or [{"mesh": index, "name": f"part {index}"} for index in range(len(boxes))],
                "meshes": [mesh(index) for index in range(len(boxes))], "accessors": [accessor(list(low), list(high)) for low, high in boxes]}
    return write(tmp_path, document, name)


def test_each_mesh_node_has_its_own_box_in_traversal_order(tmp_path):
    result = glb_parts(town(tmp_path, [((-10, -0.2, -10), (10, 0, 10)), ((-2, 0, -2), (2, 3, 2)), ((4, 0, 4), (6, 5, 6))]))
    assert result["ok"] and result["omitted"] == 0 and result["reason"] is None
    assert [part["index"] for part in result["parts"]] == [0, 1, 2]
    assert result["parts"][1] == {"index": 1, "node": 1, "name": "part 1", "min": [-2, 0, -2], "max": [2, 3, 2]}
    assert result["parts"][2]["min"] == [4, 0, 4] and result["parts"][2]["max"] == [6, 5, 6]


def test_the_node_tree_moves_turns_and_scales_a_part_like_glb_bounds_does(tmp_path):
    nodes = [{"name": "block", "translation": [10, 0, 0], "scale": [2, 2, 2], "rotation": Q_Y90, "children": [1]}, {"mesh": 0, "name": "house", "translation": [0, 1, 0]}]
    result = glb_parts(town(tmp_path, [((-1, 0, -0.5), (1, 2, 0.5))], nodes=nodes, scene_nodes=[0]))
    part = result["parts"][0]
    # the house box moved up 1 inside its parent, then scaled by 2, turned a quarter about y (x and z swap) and moved 10 along x
    assert part["min"] == pytest.approx([9, 2, -2], abs=1e-4) and part["max"] == pytest.approx([11, 6, 2], abs=1e-4)
    assert part["name"] == "house" and part["node"] == 1 and part["index"] == 0


def test_a_mesh_node_with_several_primitives_is_one_part_and_a_node_without_positions_is_none(tmp_path):
    document = {"scene": 0, "scenes": [{"nodes": [0, 1]}], "nodes": [{"mesh": 0}, {"mesh": 1}],
                "meshes": [mesh(0, 1), {"primitives": [{"attributes": {"NORMAL": 2}}]}],
                "accessors": [accessor([0, 0, 0], [1, 1, 1]), accessor([3, 0, 0], [4, 2, 1]), accessor([0, 0, 0], [1, 1, 1])]}
    result = glb_parts(write(tmp_path, document))
    assert [(part["min"], part["max"]) for part in result["parts"]] == [([0, 0, 0], [4, 2, 1])]


def test_more_parts_than_the_cap_keeps_the_largest_with_their_indexes_and_counts_the_rest(tmp_path):
    boxes = [((0, 0, 0), (size, size, size)) for size in (1, 5, 2, 4, 3)]
    result = glb_parts(town(tmp_path, boxes), max_parts=3)
    assert [part["index"] for part in result["parts"]] == [1, 3, 4] and result["omitted"] == 2


@pytest.mark.parametrize("make, reason", [
    (lambda path: path / "missing.glb", "missing_file"),
    (lambda path: (path / "text.glb").write_bytes(b"not a glb at all") and path / "text.glb", "not_glb"),
])
def test_a_bad_file_is_refused_with_a_reason_and_never_raises(tmp_path, make, reason):
    result = glb_parts(make(tmp_path))
    assert result["ok"] is False and result["parts"] == [] and result["reason"] == reason


def test_a_model_with_no_mesh_nodes_says_so(tmp_path):
    document = {"scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"name": "empty"}], "meshes": [], "accessors": []}
    assert glb_parts(write(tmp_path, document))["reason"] == "no_meshes"

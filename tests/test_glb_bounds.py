"""glb_bounds: the rest-pose box of a GLB from its JSON chunk, with tiny hand-built files (no buffers needed)."""
import json
import math
import struct

import pytest

from services.procedural_3d.glb_bounds import glb_bounds
from tests.test_procedural_glb_inspector import JSON_CHUNK, two_clip_scene, pack_glb

Q_Y90 = [0, math.sin(math.pi / 4), 0, math.cos(math.pi / 4)]     # 90 degrees about +Y


def accessor(low, high):
    return {"componentType": 5126, "count": 3, "type": "VEC3", "min": low, "max": high}


def mesh(*accessor_indexes):
    return {"primitives": [{"attributes": {"POSITION": index}} for index in accessor_indexes]}


def write(tmp_path, document, name="model.glb"):
    path = tmp_path / name
    path.write_bytes(pack_glb({"asset": {"version": "2.0"}, **document}))
    return path


def single(tmp_path, node=None, low=(-1, 0, -0.5), high=(1, 2, 0.5)):
    return write(tmp_path, {"scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, **(node or {})}],
                            "meshes": [mesh(0)], "accessors": [accessor(list(low), list(high))]})


def test_an_untransformed_mesh_gives_its_accessor_box(tmp_path):
    box = glb_bounds(single(tmp_path))
    assert box == {"ok": True, "min": [-1, 0, -0.5], "max": [1, 2, 0.5], "size": [2, 2, 1], "center": [0, 1, 0], "bottomY": 0, "reason": None}


def test_translation_rotation_and_scale_of_a_node_apply_in_that_order(tmp_path):
    box = glb_bounds(single(tmp_path, {"translation": [10, 0, 0], "scale": [2, 2, 2], "rotation": Q_Y90}))
    # scaled to 4 x 4 x 2, then turned a quarter about y: x and z extents swap; the move comes last
    assert box["size"] == pytest.approx([2, 4, 4], abs=1e-5)
    assert box["center"] == pytest.approx([10, 2, 0], abs=1e-5)
    assert box["bottomY"] == pytest.approx(0, abs=1e-5)


def test_a_matrix_node_is_read_column_major(tmp_path):
    matrix = [3, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, -1, 0, 1]
    box = glb_bounds(single(tmp_path, {"matrix": matrix}))
    assert box["min"] == [2, -1, -0.5] and box["max"] == [8, 1, 0.5] and box["bottomY"] == -1


def test_parents_compose_and_a_shared_mesh_counts_at_every_node(tmp_path):
    document = {"scenes": [{"nodes": [0]}], "meshes": [mesh(0)], "accessors": [accessor([0, 0, 0], [1, 1, 1])],
                "nodes": [{"translation": [0, 1, 0], "scale": [2, 2, 2], "children": [1, 2]},
                          {"mesh": 0}, {"mesh": 0, "translation": [3, 0, 0]}]}
    box = glb_bounds(write(tmp_path, document))
    assert box["min"] == [0, 1, 0] and box["max"] == [8, 3, 2]


def test_without_a_scene_the_unparented_nodes_are_the_roots_and_every_primitive_counts(tmp_path):
    document = {"nodes": [{"children": [1]}, {"mesh": 0}], "meshes": [mesh(0, 1)],
                "accessors": [accessor([0, 0, 0], [1, 1, 1]), accessor([-2, 0, 0], [-1, 5, 1])]}
    box = glb_bounds(write(tmp_path, document))
    assert box["min"] == [-2, 0, 0] and box["max"] == [1, 5, 1] and box["size"] == [3, 5, 1]


def test_a_skinned_mesh_is_measured_in_its_bind_pose_under_its_node_transform(tmp_path):
    """Joints, clips and the armature's own scale are not applied: the rest-pose approximation the docs name."""
    document = {"scenes": [{"nodes": [0, 1]}], "meshes": [mesh(0)], "accessors": [accessor([-0.5, 0, -0.5], [0.5, 1.8, 0.5])],
                "nodes": [{"name": "Armature", "scale": [0.01, 0.01, 0.01], "children": [2]},
                          {"mesh": 0, "skin": 0, "translation": [0, 0.5, 0]}, {"name": "Hips"}],
                "skins": [{"joints": [2]}],
                "animations": [{"channels": [{"sampler": 0, "target": {"node": 2, "path": "translation"}}], "samplers": []}]}
    box = glb_bounds(write(tmp_path, document))
    assert box["ok"] and box["size"] == [1, 1.8, 1] and box["bottomY"] == 0.5


def test_a_file_that_is_not_a_glb_is_refused_with_a_reason(tmp_path):
    (tmp_path / "plain.glb").write_bytes(b"not a glb at all, just text")
    (tmp_path / "tiny.glb").write_bytes(b"glTF")
    (tmp_path / "empty.glb").write_bytes(b"")
    for name in ("plain.glb", "tiny.glb", "empty.glb"):
        assert glb_bounds(tmp_path / name)["reason"] == "not_glb"
    assert glb_bounds(tmp_path / "gone.glb") == {"ok": False, "min": None, "max": None, "size": None, "center": None, "bottomY": None, "reason": "missing_file"}


def test_a_folder_and_odd_inputs_never_raise(tmp_path):
    for odd in (tmp_path, str(tmp_path / "nope"), "", 12, None):
        assert glb_bounds(odd)["ok"] is False


def test_a_truncated_wrong_version_or_oversize_container_is_refused(tmp_path):
    good = single(tmp_path).read_bytes()
    cut = tmp_path / "cut.glb"
    cut.write_bytes(good[:-8])
    assert glb_bounds(cut)["reason"] == "truncated"
    old = tmp_path / "old.glb"
    old.write_bytes(good[:4] + struct.pack("<I", 1) + good[8:])
    assert glb_bounds(old)["reason"] == "unsupported_version"
    assert glb_bounds(single(tmp_path), max_json_bytes=16)["reason"] == "json_too_large"
    bin_first = tmp_path / "bin-first.glb"
    bin_first.write_bytes(good[:16] + struct.pack("<I", 0x004E4942) + good[20:])
    assert glb_bounds(bin_first)["reason"] == "not_glb"


def test_trailing_bytes_after_the_declared_length_are_ignored(tmp_path):
    path = single(tmp_path)
    path.write_bytes(path.read_bytes() + b"\x00" * 64)
    assert glb_bounds(path)["ok"]


def test_broken_json_is_refused(tmp_path):
    body = b"{not json"
    body += b" " * ((4 - len(body) % 4) % 4)
    chunk = struct.pack("<II", len(body), JSON_CHUNK) + body
    path = tmp_path / "bad.glb"
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(chunk)) + chunk)
    assert glb_bounds(path)["reason"] == "invalid_json"


def test_missing_min_max_is_refused_and_a_real_skinned_file_without_them_says_so(tmp_path):
    bare = {"scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}], "meshes": [mesh(0)],
            "accessors": [{"componentType": 5126, "count": 3, "type": "VEC3"}]}
    assert glb_bounds(write(tmp_path, bare))["reason"] == "missing_min_max"
    document, blob = two_clip_scene()          # the inspector's skinned fixture: POSITION has no min/max
    path = tmp_path / "skinned.glb"
    path.write_bytes(pack_glb(document, blob))
    assert glb_bounds(path)["reason"] == "missing_min_max"


@pytest.mark.parametrize("document,reason", [
    ({"scenes": [{"nodes": [0]}], "nodes": [{"name": "empty"}]}, "no_meshes"),
    ({"scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}], "meshes": [{"primitives": [{"attributes": {"NORMAL": 0}}]}],
      "accessors": [accessor([0, 0, 0], [1, 1, 1])]}, "no_meshes"),
    ({"scenes": [{"nodes": [3]}], "nodes": [{"mesh": 0}]}, "bad_reference"),
    ({"scenes": [{"nodes": [0]}], "nodes": [{"mesh": 4}], "meshes": [mesh(0)], "accessors": [accessor([0, 0, 0], [1, 1, 1])]}, "bad_reference"),
    ({"scenes": [{"nodes": [0]}], "nodes": [{"children": [1]}, {"children": [0]}]}, "cyclic_nodes"),
    ({"scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "scale": [1, 1]}], "meshes": [mesh(0)], "accessors": [accessor([0, 0, 0], [1, 1, 1])]}, "bad_transform"),
    ({"scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "rotation": [0, 0, 0, 0]}], "meshes": [mesh(0)], "accessors": [accessor([0, 0, 0], [1, 1, 1])]}, "bad_transform"),
    ({"scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "scale": [1e308, 1e308, 1e308]}], "meshes": [mesh(0)],
      "accessors": [accessor([0, 0, 0], [1e308, 1, 1])]}, "non_finite"),
])
def test_unmeasurable_documents_are_refused_with_their_reason(tmp_path, document, reason):
    assert glb_bounds(write(tmp_path, document)) == {"ok": False, "min": None, "max": None, "size": None, "center": None, "bottomY": None, "reason": reason}


def test_a_deep_chain_of_nodes_is_refused_not_recursed(tmp_path):
    nodes = [{"children": [index + 1]} for index in range(200)] + [{"mesh": 0}]
    document = {"scenes": [{"nodes": [0]}], "nodes": nodes, "meshes": [mesh(0)], "accessors": [accessor([0, 0, 0], [1, 1, 1])]}
    assert glb_bounds(write(tmp_path, document))["reason"] == "cyclic_nodes"
    assert json.dumps(glb_bounds(tmp_path / "missing.glb"))        # always a plain JSON-able dict

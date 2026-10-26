"""Real CPU geometry, transforms, vertex colors and transport replay."""
import asyncio
import json
import math
import struct

import pytest

from routers.model3d_compose import command_handlers
from services.procedural_3d.compose import compose_glb
from services.procedural_3d.glb_container import parse_glb_container
from services.procedural_3d.glb_inspector import inspect_glb_bytes


def unpack(data):
    container = parse_glb_container(data, max_chunks=2, max_json_bytes=100_000)
    document = json.loads(container.json_bytes)
    arrays = []
    for accessor, view in zip(document["accessors"], document["bufferViews"]):
        offset, count = view["byteOffset"], accessor["count"]
        array = struct.unpack_from(f"<{count * 3}f", container.bin_bytes, offset)
        arrays.append([array[i:i + 3] for i in range(0, len(array), 3)])
    return document, arrays


@pytest.mark.parametrize("kind", ["box", "sphere", "cylinder", "cone"])
def test_closed_outward_flat_geometry(kind):
    data = compose_glb([{"type": kind, "color": "#FF8000"}])
    report = inspect_glb_bytes(data)
    assert report.status == "valid"
    assert not report.issues and not report.skins and not report.animations
    doc, (positions, normals, colors) = unpack(data)
    assert doc["accessors"][0]["min"] == pytest.approx([-.5, -.5, -.5])
    assert doc["accessors"][0]["max"] == pytest.approx([.5, .5, .5])
    for i in range(0, len(positions), 3):
        assert normals[i] == normals[i + 1] == normals[i + 2]
        assert sum(n * n for n in normals[i]) == pytest.approx(1, abs=1e-6)
        center = [sum(p[j] for p in positions[i:i + 3]) / 3 for j in range(3)]
        assert sum(center[j] * normals[i][j] for j in range(3)) > 0
    assert colors[0] == pytest.approx([1, .21586, 0], abs=1e-5)
    assert all(color == colors[0] for color in colors)


def test_rotated_scaled_translated_box_bounds_and_determinism():
    pieces = [{"type": "box", "scale": [2, 4, 6], "position": [1, 2, 3], "rotation": [0, 0, math.pi / 2]}]
    data = compose_glb(pieces, "My box")
    doc, _ = unpack(data)
    assert doc["accessors"][0]["min"] == pytest.approx([-1, 1, 0])
    assert doc["accessors"][0]["max"] == pytest.approx([3, 3, 6])
    assert compose_glb(pieces, "My box") == data


@pytest.mark.parametrize("pieces", [[], [{"type": "torus"}], [{"type": "box", "scale": [0, 1, 1]}],
                                       [{"type": "box", "position": [float("nan"), 0, 0]}],
                                       [{"type": "box", "color": "red"}], [{"type": "box"}] * 129])
def test_invalid_or_unbounded_inputs_fail_before_publication(pieces):
    with pytest.raises(ValueError):
        compose_glb(pieces)


def test_workspace_publication_has_manifest_and_replays(tmp_path):
    root = tmp_path / "ws"
    handlers = command_handlers(lambda ws: str(root / ws), tmp_path / "journal.db")
    args = {"version": 1, "intent_id": "tree-1", "input": {"workspace": "test", "name": "Tree",
            "pieces": [{"type": "cylinder", "scale": [.2, 1, .2], "color": "#784421"},
                       {"type": "cone", "position": [0, 1, 0], "color": "#248340"}]}}
    result = asyncio.run(handlers["model3d.compose"](args))["result"]
    path = root / "test" / result["file"]
    assert inspect_glb_bytes(path.read_bytes()).status == "valid"
    manifest = json.loads(path.with_suffix(".meta.json").read_text())
    assert manifest["params"]["pieces"] == args["input"]["pieces"]
    assert result["url"].endswith("?workspace=test")
    retry = asyncio.run(command_handlers(lambda ws: str(root / ws), tmp_path / "journal.db")["model3d.compose"](args))
    assert retry["result"] == result
    assert len(list((root / "test").glob("*.glb"))) == 1
    args["input"]["name"] = "Changed"
    with pytest.raises(ValueError, match="different parameters"):
        asyncio.run(handlers["model3d.compose"](args))


def _front_z(positions, colors, color_rgb):
    """Largest z among the +Z faces of one colour."""
    return max(p[2] for p, c in zip(positions, colors) if c == pytest.approx(color_rgb, abs=1e-5) and abs(p[2]) > 0.01)


def test_a_screen_laid_on_a_cabinet_no_longer_shares_its_face_plane():
    cabinet = {"type": "box", "position": [0, 0, 0], "scale": [1, 1, 0.5], "color": "#203040"}
    screen = {"type": "box", "position": [0, 0, 0.2], "scale": [0.7, 0.6, 0.1], "color": "#80D0C0"}   # front face at z = 0.25, the cabinet's
    doc, (positions, _normals, colors) = unpack(compose_glb([cabinet, screen]))
    cabinet_rgb, screen_rgb = colors[0], next(c for c in colors if c != colors[0])
    cabinet_front = _front_z(positions, colors, cabinet_rgb)
    screen_front = _front_z(positions, colors, screen_rgb)
    assert cabinet_front == pytest.approx(0.25, abs=1e-6)       # the larger surface stays put
    assert screen_front - 0.25 == pytest.approx(0.004, abs=1e-6)  # the smaller one is lifted off the plane
    assert doc["accessors"][0]["max"][2] == pytest.approx(0.254, abs=1e-6)


def test_models_without_shared_planes_are_unchanged_and_hidden_faces_stay_put():
    from services.procedural_3d.coplanar import separate_coplanar
    cloud = [{"type": "sphere", "position": [i, 0, 0], "color": "#FFFFFF" if i else "#CCDDEE"} for i in range(3)]
    data = compose_glb(cloud)
    _doc, (positions, normals, colors) = unpack(data)
    assert separate_coplanar(positions, normals, colors) == [tuple(p) for p in positions]
    # two boxes touching back to back share a plane but face opposite ways: nothing is lifted
    touching = [{"type": "box", "color": "#FF0000"}, {"type": "box", "position": [0, 0, 1], "color": "#0000FF"}]
    _doc, (positions, normals, colors) = unpack(compose_glb(touching))
    assert max(p[2] for p in positions) == pytest.approx(1.5, abs=1e-6)


def test_the_same_pieces_always_give_the_same_file():
    pieces = [{"type": "box", "scale": [1, 1, 0.5], "color": "#203040"}, {"type": "box", "position": [0, 0, 0.2], "scale": [0.7, 0.6, 0.1], "color": "#80D0C0"}]
    assert compose_glb(pieces) == compose_glb(pieces)


# SHA-256 of compose_glb on fixtures/blob2_pieces.json with no segments, computed on origin/development
# d9fc09859 before segments existed. Omitting segments must stay byte-identical.
BLOB2_GOLD_SHA256 = "d003d1c9c2c077946ef94b5b4825ba87a9dce925ad337db97f7c008fab414aa8"


def test_blob2_pieces_without_segments_match_the_gold_hash():
    import hashlib
    from pathlib import Path
    pieces = json.loads((Path(__file__).parent / "fixtures" / "blob2_pieces.json").read_text())["pieces"]
    assert hashlib.sha256(compose_glb(pieces, "blob2")).hexdigest() == BLOB2_GOLD_SHA256


def test_segments_smooth_a_sphere_and_reject_anything_outside_6_to_48():
    coarse = compose_glb([{"type": "sphere"}])
    fine = compose_glb([{"type": "sphere", "segments": 24}])
    assert fine != coarse and len(fine) > len(coarse)
    report = inspect_glb_bytes(fine)
    assert report.status == "valid" and report.total_triangles == 24 * (24 // 2 - 1) * 2
    for bad in (5, 49, 8.0, True):
        with pytest.raises(ValueError, match="segments"):
            compose_glb([{"type": "cylinder", "segments": bad}])


def _normals_of(data):
    _doc, (_positions, normals, _colors) = unpack(data)
    return normals


def test_smooth_is_opt_in_and_keeps_flat_caps_off_the_side():
    """Without smooth the gold mesh stays byte-identical; with it, side normals vary and caps stay axial."""
    plain = compose_glb([{"type": "cylinder", "scale": [1, 2, 1], "segments": 12}])
    assert compose_glb([{"type": "cylinder", "scale": [1, 2, 1], "segments": 12, "smooth": False}]) == plain
    smooth = compose_glb([{"type": "cylinder", "scale": [1, 2, 1], "segments": 12, "smooth": True}])
    assert smooth != plain
    _doc, (positions, normals, _colors) = unpack(smooth)
    # The wall and the cap share the rim but not the normal: the cap stays axial.
    radial = [n for p, n in zip(positions, normals) if math.hypot(p[0], p[2]) > 0.35 and abs(n[1]) < 0.2]
    axial = [n for p, n in zip(positions, normals) if math.hypot(p[0], p[2]) > 0.35 and abs(n[1]) > 0.9]
    centers = [n for p, n in zip(positions, normals) if math.hypot(p[0], p[2]) < 1e-3 and abs(abs(p[1]) - 1.0) < 1e-3]
    assert len({tuple(round(c, 3) for c in n) for n in radial}) > 4
    assert axial and centers and all(abs(n[1]) > 0.95 for n in centers)
    sphere = _normals_of(compose_glb([{"type": "sphere", "smooth": True}]))
    assert any(sphere[i] != sphere[i + 1] for i in range(0, len(sphere), 3))
    whole = compose_glb([{"type": "sphere"}], smooth=True)
    assert _normals_of(whole) == _normals_of(compose_glb([{"type": "sphere", "smooth": True}]))
    for bad in ("yes", 1, 0):
        with pytest.raises(ValueError, match="smooth"):
            compose_glb([{"type": "sphere", "smooth": bad}])


def test_smooth_normals_survive_the_humanoid_bake():
    """The rig bakes an identity mesh in place and must not replace radial normals with flat ones."""
    import numpy as np

    from services.humanoid_rig.gltf_buffers import read_floats
    from services.humanoid_rig.gltf_export import _iter_primitives, _load
    from services.humanoid_rig.gltf_world import world_space_primitives

    data = compose_glb([{"type": "sphere", "smooth": True, "segments": 16}])
    gltf, blob = _load(data)
    primitive = next(item[2] for item in _iter_primitives(gltf))
    before = read_floats(gltf, blob, primitive.attributes.NORMAL, 3)
    assert not np.allclose(before[0], before[1])
    world_space_primitives(gltf, blob, list(_iter_primitives(gltf)))
    after = read_floats(gltf, blob, primitive.attributes.NORMAL, 3)
    assert np.allclose(before, after, atol=1e-6)


def test_capsule_and_frustum_are_closed_and_sized_by_scale():
    capsule = compose_glb([{"type": "capsule", "scale": [1, 2, 1], "segments": 12, "smooth": True}])
    report = inspect_glb_bytes(capsule)
    assert report.status == "valid" and not report.issues
    _doc, (positions, normals, _colors) = unpack(capsule)
    assert min(p[1] for p in positions) == pytest.approx(-1, abs=1e-4)
    assert max(p[1] for p in positions) == pytest.approx(1, abs=1e-4)
    assert max(abs(p[0]) for p in positions) == pytest.approx(0.5, abs=1e-3)
    assert any(normals[i] != normals[i + 1] for i in range(0, len(normals), 3))
    frustum = compose_glb([{"type": "frustum", "scale": [1, 2, 1], "taper": 0.5, "segments": 12}])
    _doc, (positions, normals, _colors) = unpack(frustum)
    bottom = [p for p in positions if p[1] < -0.99]
    top = [p for p in positions if p[1] > 0.99]
    assert max(math.hypot(p[0], p[2]) for p in bottom) == pytest.approx(0.5, abs=1e-3)
    assert max(math.hypot(p[0], p[2]) for p in top) == pytest.approx(0.25, abs=1e-3)
    for i in range(0, len(normals), 3):
        assert normals[i] == normals[i + 1] == normals[i + 2]
    for bad in (0.19, 1.01, 0, True):
        with pytest.raises(ValueError, match="taper"):
            compose_glb([{"type": "frustum", "taper": bad}])
    with pytest.raises(ValueError, match="Unknown piece field"):
        compose_glb([{"type": "box", "taper": 0.5}])

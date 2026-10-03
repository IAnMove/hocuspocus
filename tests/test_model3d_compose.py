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

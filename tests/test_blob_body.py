"""Round-head bodies: traits, overlap, and a real CPU humanoid rig. No server."""
import asyncio
import math

import pytest
from fastapi import HTTPException

from routers.model3d_compose import command_catalog, command_handlers
from services.blob_builder import EXTREMES, PRESETS, BlobTraitsError, blob_pieces
from services.blob_make import BlobRigError, resolve_request, rig_glb
from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.rig import rig_humanoid
from services.mcp_profiles import GAME_TOOLS, SERIES_TOOLS
from services.procedural_3d.compose import _faces, _transform, compose_glb, normalized_pieces
from services.procedural_3d.glb_inspector import inspect_glb_bytes
from services.series_guide import guide_text

CASES = [("preset", name, traits) for name, traits in PRESETS.items()]
CASES += [("extreme", str(index), traits) for index, traits in enumerate(EXTREMES)]
RIG_PRESETS = ("sailor", "kid", "lanky")
CLIP_NAMES = {"Idle", "Walk", "Talk", "Nod", "Wave", "Shrug", "Point", "Run"}


def _boxes(pieces):
    boxes = []
    for piece in normalized_pieces(pieces):
        points = [_transform(point, piece) for face in _faces(piece) for point in face]
        xs, ys, zs = zip(*points)
        boxes.append((min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)))
    return boxes


def _overlaps(left, right):
    gap = 1e-4
    return (min(left[3], right[3]) - max(left[0], right[0]) > gap
            and min(left[4], right[4]) - max(left[1], right[1]) > gap
            and min(left[5], right[5]) - max(left[2], right[2]) > gap)


def _mirrored(piece, pieces):
    x, y, z = piece["position"]
    if abs(x) <= 1e-4:
        return True
    want = (-x, y, z)
    return any(
        other["type"] == piece["type"] and all(abs(other["position"][i] - want[i]) < 1e-4 for i in range(3))
        for other in pieces
    )


def test_twelve_bodies_stay_one_connected_person():
    heights = set()
    for _kind, label, traits in CASES:
        built = blob_pieces(traits)
        pieces, anchor = built["pieces"], built["faceAnchor"]
        assert 1 <= len(pieces) <= 128, label
        assert all(math.isfinite(number) for piece in pieces for number in (*piece["position"], *piece["scale"])), label
        boxes = _boxes(pieces)
        lonely = [index for index, box in enumerate(boxes) if not any(_overlaps(box, other) for other_index, other in enumerate(boxes) if other_index != index)]
        assert lonely == [], (label, lonely)
        assert min(box[1] for box in boxes) == pytest.approx(0, abs=1e-4), label
        head = pieces[0]
        assert head["type"] == "sphere" and head["segments"] >= 24, label
        assert all(piece.get("segments", 12) >= 12 for piece in pieces if piece["type"] == "cylinder"), label
        assert all(_mirrored(piece, pieces) for piece in pieces), label
        assert anchor["center"][1] == pytest.approx(head["position"][1])
        assert anchor["radii"] == pytest.approx([value / 2 for value in head["scale"]])
        assert anchor["front"][2] == pytest.approx(anchor["center"][2] + anchor["radii"][2])
        heights.add(round(built["traits"]["height"], 3))
    assert len({round(blob_pieces(traits)["traits"]["height"], 3) for traits in PRESETS.values()}) == 6
    assert len(heights) >= 6


def test_unknown_traits_and_a_preset_override_are_explicit():
    with pytest.raises(BlobTraitsError) as caught:
        blob_pieces({"moustache": True})
    assert caught.value.code == "unknown_field"
    with pytest.raises(BlobTraitsError) as bad_height:
        blob_pieces({"height": True})
    assert bad_height.value.code == "invalid_height"
    merged, clips = resolve_request({"preset": "sailor", "traits": {"height": 1.5, "colors": {"top": "#112233"}}})
    built = blob_pieces(merged)
    assert built["traits"]["height"] == 1.5 and built["traits"]["build"] == "average"
    assert built["traits"]["colors"]["top"] == "#112233"
    assert clips == ["idle", "walk", "talk", "nod", "wave", "shrug", "point", "run"]
    egg = blob_pieces(PRESETS["lanky"])["pieces"][0]["scale"]
    assert egg[1] >= egg[0] * 1.12 and egg[2] <= egg[0] * 0.92


def test_the_operation_is_on_both_agent_profiles_and_in_the_guide():
    names = {item["name"] for item in command_catalog()}
    assert {"model3d.blob.make", "model3d.blob.presets"} <= names
    assert "model3d.blob.make" in SERIES_TOOLS and "model3d.blob.presets" in SERIES_TOOLS
    assert "model3d.blob.make" in GAME_TOOLS and "model3d.blob.presets" in GAME_TOOLS
    guide = guide_text()
    assert "model3d.blob.make" in guide and "blob_make" in guide and "subject_1" in guide


def _handlers(tmp_path):
    return command_handlers(lambda name: str(tmp_path / name), tmp_path / "journal.sqlite3")


def _call(handlers, preset, intent, clips=None):
    payload = {"workspace": "studio", "name": preset, "preset": preset}
    if clips is not None:
        payload["clips"] = clips
    return asyncio.run(handlers["model3d.blob.make"]({"version": 1, "intent_id": intent, "input": payload}))


def test_three_presets_rig_as_humanoids(tmp_path):
    handlers = _handlers(tmp_path)
    for preset in RIG_PRESETS:
        envelope = _call(handlers, preset, f"rig-{preset}")
        result = envelope["result"]
        assert envelope["status"] == "completed"
        report = inspect_glb_bytes((tmp_path / "studio" / result["rigged_file"]).read_bytes())
        assert report.status == "valid" and len(report.skins) == 1 and report.skins[0].joint_count == 25
        assert CLIP_NAMES <= {clip.name for clip in report.animations}
        assert CLIP_NAMES <= {row["name"] for row in result["clips"]}
        assert all(row["id"] and row["duration"] > 0 for row in result["clips"])
        assert (tmp_path / "studio" / result["rigged_file"]).with_suffix(".humanoid.json").is_file()
        assert result["traits"]["height"] == PRESETS[preset]["height"]
    replay = _call(handlers, "sailor", "rig-sailor")
    assert replay["result"]["rigged_file"].endswith("-rigged.glb")
    assert len(list((tmp_path / "studio").glob("*.glb"))) == 6


def _refuse(reason):
    def boom(*_args, **_kwargs):
        raise BlobRigError(reason)
    return boom


def test_a_refused_mesh_keeps_the_rig_reason(tmp_path, monkeypatch):
    box = compose_glb([{"type": "box", "scale": [0.4, 1.7, 0.3]}])
    with pytest.raises(NotHumanoid) as real:
        rig_humanoid(box, ["idle"])
    with pytest.raises(BlobRigError) as wrapped:
        rig_glb(box, ["idle"])
    assert wrapped.value.reason == real.value.reason and real.value.reason not in {"", "not_humanoid"}
    monkeypatch.setattr("routers.model3d_blob.build_body", _refuse(real.value.reason))
    handlers = _handlers(tmp_path)
    with pytest.raises(HTTPException) as caught:
        _call(handlers, "sailor", "refused")
    detail = caught.value.detail
    assert detail["code"] == "not_humanoid" and detail["reason"] == real.value.reason
    assert detail["message"] == f"not_humanoid: {real.value.reason}"


def test_bad_traits_name_their_code_and_presets_are_readable(tmp_path):
    handlers = _handlers(tmp_path)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["model3d.blob.make"]({
            "version": 1, "intent_id": "bad-traits",
            "input": {"workspace": "studio", "name": "Nope", "traits": {"glasses": True}},
        }))
    assert caught.value.detail["code"] == "unknown_field"
    catalog = asyncio.run(handlers["model3d.blob.presets"]({"version": 1}))["result"]
    assert set(catalog["presets"]) == set(PRESETS)
    assert "moustache" in catalog["accessories"]["notHere"]

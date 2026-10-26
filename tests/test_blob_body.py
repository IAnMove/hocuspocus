"""Round-head bodies: traits, overlap, and a real CPU humanoid rig. No server."""
import asyncio
import base64
import json
import math

import numpy as np
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
    classic = ("sailor", "cashier", "boss", "kid", "big", "lanky")
    assert len({round(blob_pieces(PRESETS[name])["traits"]["height"], 3) for name in classic}) == 6
    assert len(PRESETS) == 15
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


NEW_PRESETS = (
    "blob_chef", "blob_pirate", "blob_scout",
    "anime_girl", "anime_boy", "anime_senpai",
    "chibi_kid", "chibi_mage", "chibi_knight",
)
CLASSIC_PRESETS = ("sailor", "cashier", "boss", "kid", "big", "lanky")


def test_fifteen_presets_cover_three_families():
    """Nine new bodies share one trait table with the six classic presets."""
    assert len(PRESETS) == 15
    assert set(PRESETS) == set(CLASSIC_PRESETS) | set(NEW_PRESETS)
    anime = blob_pieces({"family": "anime"})
    chibi = blob_pieces({"family": "chibi"})
    assert anime["traits"]["family"] == "anime" and anime["traits"]["head"]["shape"] == "anime"
    assert chibi["traits"]["head"]["shape"] == "chibi" and chibi["traits"]["head"]["height"] >= 0.36
    girl = blob_pieces(PRESETS["anime_girl"])
    assert girl["traits"]["hair"]["style"] == "long"
    assert {"capsule", "frustum"} <= {piece["type"] for piece in girl["pieces"]}


@pytest.mark.parametrize("kind", ["cap", "sailor_cap", "top_hat", "beanie", "bucket_hat"])
def test_head_gear_stays_above_the_brows_where_a_face_is_drawn(kind):
    """The 2D face has its brows about 0.28 of the head height over the head centre. A hat that dips below 0.30 covers eyes."""
    for preset in ("kid", "cashier", "big"):
        bare = blob_pieces({**PRESETS[preset], "accessories": []})
        worn = blob_pieces({**PRESETS[preset], "accessories": [{"kind": kind}]})
        anchor = worn["faceAnchor"]
        centre, height = anchor["center"][1], 2 * anchor["radii"][1]
        old = {tuple(map(tuple, (piece["position"], piece["scale"]))) for piece in bare["pieces"]}
        extra = [piece for piece in worn["pieces"] if tuple(map(tuple, (piece["position"], piece["scale"]))) not in old]
        assert extra, kind
        low = min(piece["position"][1] - piece["scale"][1] / 2 for piece in extra)
        assert low >= centre + 0.29 * height, (preset, kind, round((low - centre) / height, 3))


def _piece_key(piece):
    return (piece["type"], tuple(round(v, 4) for v in piece["position"]), tuple(round(v, 4) for v in piece["scale"]), piece["color"])


def _world_vertices(pieces):
    found = []
    for piece in normalized_pieces(pieces):
        for face in _faces(piece):
            found.extend(_transform(point, piece) for point in face)
    return found


def _in_face(point, anchor):
    """Front of the head, from the mouth up to the brow. Long hair behind this box is allowed."""
    x, y, z = point
    cy, cz = anchor["center"][1], anchor["center"][2]
    width, height, depth = (2 * value for value in anchor["radii"])
    return (cy - 0.22 * height) < y < (cy + 0.30 * height) and z > cz + 0.15 * depth and abs(x) < 0.45 * width


@pytest.mark.parametrize("style", ["short", "bangs", "spiky", "long", "ponytail", "twin_tails", "bun"])
def test_hair_stays_off_the_face_and_long_hair_can_hang_behind(style):
    for preset in ("sailor", "anime_girl", "chibi_kid"):
        traits = {**PRESETS[preset], "hair": {"style": style, "color": "#221815"}, "accessories": []}
        worn = blob_pieces(traits)
        bare = blob_pieces({**traits, "hair": {"style": "none"}})
        old = {_piece_key(piece) for piece in bare["pieces"]}
        extra = [piece for piece in worn["pieces"] if _piece_key(piece) not in old]
        assert extra, (preset, style)
        anchor = worn["faceAnchor"]
        bad = [point for piece in extra for point in _world_vertices([piece]) if _in_face(point, anchor)]
        assert bad == [], (preset, style, len(bad))
        if style == "long":
            cy = anchor["center"][1]
            assert any(point[1] < cy - 0.3 * 2 * anchor["radii"][1] and point[2] < anchor["center"][2] for piece in extra for point in _world_vertices([piece]))


@pytest.mark.parametrize("kind", ["skirt", "jacket", "sleeves_long", "shorts", "school_collar", "cape"])
def test_new_clothes_add_pieces(kind):
    bare = blob_pieces({"family": "anime", "accessories": []})
    worn = blob_pieces({"family": "anime", "accessories": [{"kind": kind}]})
    assert len(worn["pieces"]) > len(bare["pieces"])


def _skin(data):
    pytest.importorskip("pygltflib")
    from pygltflib import GLTF2

    gltf = GLTF2.load_from_bytes(data)
    blob = gltf.binary_blob()
    primitive = gltf.meshes[0].primitives[0]

    def grab(index, width, dtype):
        accessor = gltf.accessors[index]
        view = gltf.bufferViews[accessor.bufferView]
        offset = (view.byteOffset or 0) + (accessor.byteOffset or 0)
        return np.frombuffer(blob, dtype=dtype, count=accessor.count * width, offset=offset).reshape(-1, width).copy()

    return (grab(primitive.attributes.POSITION, 3, "<f4").astype(np.float64),
            grab(primitive.attributes.JOINTS_0, 4, np.uint16),
            grab(primitive.attributes.WEIGHTS_0, 4, "<f4").astype(np.float64))


def _posed(rig, clip, positions, joints, weights, u):
    from tests.humanoid_skinning import batch_worlds, skin_vertices

    frame = int(np.argmin(np.abs(clip["times"] / clip["times"][-1] - u)))
    local = []
    for bone in rig.bones:
        track = clip["rotations"].get(bone["name"])
        local.append(track[frame] if track is not None else bone["rotation"])
    rest = batch_worlds(rig.bones, np.asarray([bone["rotation"] for bone in rig.bones], dtype=np.float64)[None])[0]
    worlds = batch_worlds(rig.bones, np.asarray(local, dtype=np.float64)[None], clip["hips_translation"][frame][None])[0]
    posed = skin_vertices(positions, joints, weights, list(rest), list(worlds))
    return posed, rest, worlds


def _bone_distance(points, dominant, worlds, bones):
    heads = worlds[:, :3, 3]
    kids = {bone["name"]: [] for bone in bones}
    for index, bone in enumerate(bones):
        if bone["parent"]:
            kids[bone["parent"]].append(index)
    tails = np.zeros_like(heads)
    for index, bone in enumerate(bones):
        tails[index] = heads[kids[bone["name"]][0]] if kids[bone["name"]] else heads[index] + worlds[index, :3, 1] * 0.05
    found = np.empty(len(points))
    for bone in np.unique(dominant):
        mask = dominant == bone
        delta = tails[bone] - heads[bone]
        scale = float(delta @ delta) + 1e-12
        weight = np.clip(((points[mask] - heads[bone]) @ delta) / scale, 0.0, 1.0)
        found[mask] = np.linalg.norm(points[mask] - (heads[bone] + weight[:, None] * delta), axis=1)
    return found


def _arm_capsules(pieces):
    return [piece for piece in pieces if piece["type"] == "capsule" and abs(piece["rotation"][2]) > 1.0]


def test_an_elbow_sphere_joins_the_upper_arm_to_the_forearm():
    """A walk bends the elbow. Two bare capsules open a gap there."""
    for name in ("blob_scout", "anime_girl", "chibi_kid"):
        pieces = blob_pieces({**PRESETS[name], "accessories": []})["pieces"]
        rights = sorted((piece for piece in _arm_capsules(pieces) if piece["position"][0] > 0), key=lambda piece: piece["scale"][1], reverse=True)
        upper, fore = rights[0], rights[1]
        half = lambda piece: piece["scale"][1] / 2
        overlap_lo = max(upper["position"][0] - half(upper), fore["position"][0] - half(fore))
        overlap_hi = min(upper["position"][0] + half(upper), fore["position"][0] + half(fore))
        spheres = [piece for piece in pieces if piece["type"] == "sphere" and abs(piece["position"][1] - upper["position"][1]) < 1e-4]
        assert any(overlap_lo - 0.01 <= piece["position"][0] <= overlap_hi + 0.01 for piece in spheres), name


def test_hat_brims_keep_enough_sides_to_read_as_round():
    for name in ("blob_chef", "chibi_mage", "chibi_knight"):
        pieces = blob_pieces(PRESETS[name])["pieces"]
        head_y = pieces[0]["position"][1]
        brims = [piece for piece in pieces if piece["type"] == "cylinder" and piece["position"][1] > head_y]
        assert brims, name
        assert min(piece["segments"] for piece in brims) >= 24, name


def test_fifteen_presets_share_one_rig_and_keep_their_shape():
    """One Mixamo skeleton. A walk or a wave must not tear a vertex off its bone, sink a foot, or put an arm through the head."""
    from services.blob_make import build_body
    from services.humanoid_rig.animate import stored_rig
    from services.humanoid_rig.clips import clip_library
    from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES

    arms = [BONE_BY_NAME[name] for name in ("LeftArm", "RightArm", "LeftForeArm", "RightForeArm", "LeftHand", "RightHand")]
    for name in (*CLASSIC_PRESETS, *NEW_PRESETS):
        body = build_body(PRESETS[name], ["walk", "wave"])
        rig = stored_rig(body["rigged"])
        assert [bone["name"] for bone in rig.bones] == list(BONE_NAMES), name
        assert {"Walk", "Wave"} <= {row["name"] for row in body["sidecar"]["clips"]}, name
        positions, joints, weights = _skin(body["rigged"])
        dominant = joints[np.arange(len(joints)), np.argmax(weights, axis=1)]
        center = np.asarray(body["faceAnchor"]["center"], dtype=np.float64)
        radii = np.asarray(body["faceAnchor"]["radii"], dtype=np.float64)
        rest_score = (((positions - center) / radii) ** 2).sum(axis=1)
        clips = {clip["id"]: clip for clip in clip_library(120.0, ["walk", "wave"], rig)}
        for clip_id in ("walk", "wave"):
            posed, rest, worlds = _posed(rig, clips[clip_id], positions, joints, weights, 0.25)
            growth = _bone_distance(posed, dominant, worlds, rig.bones) - _bone_distance(positions, dominant, rest, rig.bones)
            assert float(growth.max()) < 0.15, (name, clip_id, round(float(growth.max()), 3))
            floor = posed[positions[:, 1] < 0.08, 1]
            assert floor.min() > -0.03, (name, clip_id, round(float(floor.min()), 3))
            score = (((posed - center) / radii) ** 2).sum(axis=1)
            entered = np.isin(dominant, arms) & (rest_score > 1.15) & (score < 0.80)
            assert int(entered.sum()) == 0, (name, clip_id, int(entered.sum()))


def _nodes(spec):
    kids = {index: [] for index in range(len(spec))}
    for index, (_name, parent, _offset) in enumerate(spec):
        if parent is not None:
            kids[parent].append(index)
    nodes = []
    for index, (name, _parent, offset) in enumerate(spec):
        node = {"name": name, "translation": [float(v) for v in offset], "rotation": [0, 0, 0, 1]}
        if kids[index]:
            node["children"] = kids[index]
        nodes.append(node)
    return nodes


def _spin_gltf(spec, spin, clip_name):
    """A .gltf with one rotation from rest to a turn over one second. Synthetic, not a Meshy download."""
    times = np.array([0.0, 1.0], dtype="<f4")
    turned = np.array([0.0, 0.0, math.sin(0.55), math.cos(0.55)], dtype="<f4")
    values = np.stack([np.array([0.0, 0.0, 0.0, 1.0], dtype="<f4"), turned])
    chunks = [times.tobytes(), np.ascontiguousarray(values).tobytes()]
    views, accessors, offset = [], [], 0
    for index, data in enumerate(chunks):
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data)})
        entry = {"bufferView": index, "componentType": 5126, "count": 2, "type": "SCALAR" if index == 0 else "VEC4"}
        if index == 0:
            entry["min"] = [0.0]
            entry["max"] = [1.0]
        accessors.append(entry)
        offset += len(data)
    blob = b"".join(chunks)
    document = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": _nodes(spec),
        "animations": [{"name": clip_name, "samplers": [{"input": 0, "output": 1, "interpolation": "LINEAR"}],
                        "channels": [{"sampler": 0, "target": {"node": spin, "path": "rotation"}}]}],
        "accessors": accessors, "bufferViews": views,
        "buffers": [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64," + base64.b64encode(blob).decode()}],
    }
    return json.dumps(document).encode()


# Same pose, three name sets the retarget already understands. Spine01 is mapped by hierarchy, not by the word spine01.
_LIMB = [
    ("Hips", None, (0, 0.9, 0)), ("Spine", 0, (0, 0.08, 0)), ("Spine01", 1, (0, 0.1, 0)), ("Spine02", 2, (0, 0.1, 0)),
    ("neck", 3, (0, 0.12, 0)), ("Head", 4, (0, 0.1, 0)),
    ("LeftShoulder", 3, (0.08, 0.08, 0)), ("LeftArm", 6, (0.12, 0, 0)), ("LeftForeArm", 7, (0.22, 0, 0)), ("LeftHand", 8, (0.2, 0, 0)),
    ("RightShoulder", 3, (-0.08, 0.08, 0)), ("RightArm", 10, (-0.12, 0, 0)), ("RightForeArm", 11, (-0.22, 0, 0)), ("RightHand", 12, (-0.2, 0, 0)),
    ("LeftUpLeg", 0, (0.1, -0.05, 0)), ("LeftLeg", 14, (0, -0.4, 0)), ("LeftFoot", 15, (0, -0.4, 0)), ("LeftToeBase", 16, (0, -0.04, 0.1)),
    ("RightUpLeg", 0, (-0.1, -0.05, 0)), ("RightLeg", 18, (0, -0.4, 0)), ("RightFoot", 19, (0, -0.4, 0)), ("RightToeBase", 20, (0, -0.04, 0.1)),
]
_VRM = [
    ("hips", None, (0, 0.9, 0)), ("spine", 0, (0, 0.08, 0)), ("chest", 1, (0, 0.1, 0)), ("upperChest", 2, (0, 0.1, 0)),
    ("neck", 3, (0, 0.12, 0)), ("head", 4, (0, 0.1, 0)),
    ("leftShoulder", 3, (0.08, 0.08, 0)), ("leftUpperArm", 6, (0.12, 0, 0)), ("leftLowerArm", 7, (0.22, 0, 0)), ("leftHand", 8, (0.2, 0, 0)),
    ("rightShoulder", 3, (-0.08, 0.08, 0)), ("rightUpperArm", 10, (-0.12, 0, 0)), ("rightLowerArm", 11, (-0.22, 0, 0)), ("rightHand", 12, (-0.2, 0, 0)),
    ("leftUpperLeg", 0, (0.1, -0.05, 0)), ("leftLowerLeg", 14, (0, -0.4, 0)), ("leftFoot", 15, (0, -0.4, 0)), ("leftToes", 16, (0, -0.04, 0.1)),
    ("rightUpperLeg", 0, (-0.1, -0.05, 0)), ("rightLowerLeg", 18, (0, -0.4, 0)), ("rightFoot", 19, (0, -0.4, 0)), ("rightToes", 20, (0, -0.04, 0.1)),
]


def _same_quat(left, right):
    return abs(float(np.dot(left, right))) > 0.999


def test_synthetic_mixamo_meshy_and_vrm_clips_retarget_onto_both_families():
    """No Meshy file is on disk. The clips use the documented joint names only."""
    from services.blob_make import build_body
    from services.humanoid_rig.animate import stored_rig
    from services.humanoid_rig.errors import InvalidInput
    from services.humanoid_rig.retarget import retarget_file

    mixamo = [(f"mixamorig:{name}", parent, offset) for name, parent, offset in _LIMB]
    sources = (("meshy_take", _LIMB), ("mixamo_take", mixamo), ("vrm_take", _VRM))
    for preset in ("anime_girl", "chibi_kid"):
        rig = stored_rig(build_body(PRESETS[preset], ["idle"])["rigged"])
        for clip_name, spec in sources:
            clip = retarget_file(_spin_gltf(spec, 7, clip_name), ".gltf", rig, "Imported")[0]
            assert clip["name"] == clip_name and clip["duration"] == pytest.approx(1.0, abs=0.05)
            assert not _same_quat(clip["rotations"]["LeftArm"][0], clip["rotations"]["LeftArm"][-1])
            assert _same_quat(clip["rotations"]["RightArm"][0], clip["rotations"]["RightArm"][-1])
    extra = list(_LIMB) + [
        ("LeftHandIndex1", 9, (0.04, 0, 0)), ("LeftHandThumb1", 9, (0.02, 0.03, 0)),
        ("jaw", 5, (0, -0.02, 0.04)), ("eyes", 5, (0, 0.02, 0.05)), ("HeadTop_End", 5, (0, 0.08, 0)),
    ]
    rig = stored_rig(build_body(PRESETS["anime_girl"], ["idle"])["rigged"])
    warned = retarget_file(_spin_gltf(extra, 7, "meshy_take"), ".gltf", rig, "Imported")[0]
    assert any("not used" in note for note in warned["warnings"])
    junk = [("Bone", None, (0, 0, 0)), ("Bone.001", 0, (0, 0.2, 0)), ("Bone.002", 0, (0, -0.2, 0))]
    with pytest.raises(InvalidInput, match="no humanoid skeleton"):
        retarget_file(_spin_gltf(junk, 1, "junk"), ".gltf", rig, "Imported")


@pytest.mark.parametrize("preset", ["sailor", "anime_girl", "anime_boy", "chibi_kid"])
def test_torso_top_is_a_dome_not_a_flat_shelf(preset):
    """A cylinder or frustum capping the torso reads as a shelf wider than the neck. The highest of them stops a dome short of the top."""
    traits = {**PRESETS[preset], "accessories": [], "hair": {"style": "none"}}
    built = blob_pieces(traits)
    head_y = built["faceAnchor"]["center"][1]
    tops = {"sphere": [], "flat": []}
    for piece in built["pieces"]:
        top = piece["position"][1] + piece["scale"][1] / 2
        if piece["position"][1] < head_y - built["faceAnchor"]["radii"][1] and piece["position"][0] == 0 and piece["scale"][0] > 0.12:
            tops["sphere" if piece["type"] == "sphere" else "flat"].append((top, piece["type"]))
    flat = max(t for t, kind in tops["flat"] if kind in ("cylinder", "frustum"))
    dome = max(t for t, kind in tops["sphere"])
    assert dome > flat + 0.02, (preset, dome, flat)


def test_school_collar_hangs_below_the_chin_and_the_jacket_hem_covers_the_body():
    built = blob_pieces({"family": "anime", "accessories": [{"kind": "school_collar"}], "hair": {"style": "none"}})
    bare = blob_pieces({"family": "anime", "accessories": [], "hair": {"style": "none"}})
    old = {_piece_key(piece) for piece in bare["pieces"]}
    extra = [piece for piece in built["pieces"] if _piece_key(piece) not in old]
    anchor = built["faceAnchor"]
    chin = anchor["center"][1] - anchor["radii"][1]
    assert extra and max(point[1] for point in _world_vertices(extra)) < chin + 0.01
    jacket = blob_pieces({"family": "anime", "build": "slim", "accessories": [{"kind": "jacket"}], "hair": {"style": "none"}})
    shell = [piece for piece in jacket["pieces"] if piece["type"] == "frustum"]
    assert len(shell) == 2  # body barrel and jacket barrel
    body, coat = sorted(shell, key=lambda piece: piece["scale"][0])
    # Half the width at the coat's lower rim: the body must be narrower there, or skin shows through.
    low = coat["position"][1] - coat["scale"][1] / 2
    f = (low - (body["position"][1] - body["scale"][1] / 2)) / body["scale"][1]
    body_w = body["scale"][0] * (body["taper"] + (1 - body["taper"]) * f)
    assert coat["scale"][0] * coat["taper"] >= body_w


def test_an_anime_arm_is_one_tube_while_blob_and_chibi_keep_their_joints():
    """Anime: the elbow sphere and the forearm keep the upper arm's diameter and the shoulder sphere stays inside the sleeve,
    so the toon ink draws no ring at the elbow. Blob and chibi are unchanged: a thinner forearm and a smaller elbow."""
    for name, elbow_k, fore_k in (("anime_girl", 1.0, 1.0), ("anime_boy", 1.0, 1.0), ("blob_scout", 0.82, 0.86), ("chibi_kid", 0.82, 0.86)):
        spec = {**PRESETS[name], "accessories": []}
        pieces = blob_pieces(spec)["pieces"]
        rights = sorted((piece for piece in _arm_capsules(pieces) if piece["position"][0] > 0), key=lambda piece: piece["scale"][1], reverse=True)
        upper, fore = rights[0], rights[1]
        assert fore["scale"][0] == pytest.approx(upper["scale"][0] * fore_k, rel=1e-6), name
        y = upper["position"][1]
        spheres = [piece for piece in pieces if piece["type"] == "sphere" and abs(piece["position"][1] - y) < 1e-4 and piece["position"][0] > 0]
        elbow = min(spheres, key=lambda piece: abs(piece["position"][0] - (upper["position"][0] + upper["scale"][1] / 2)))
        assert elbow["scale"][0] == pytest.approx(upper["scale"][0] * elbow_k, rel=1e-6), name
        shoulder = min(spheres, key=lambda piece: piece["position"][0])
        if spec.get("family") == "anime":
            assert shoulder["scale"][0] == pytest.approx(upper["scale"][0], rel=1e-6), name
        else:
            assert shoulder["scale"][0] > upper["scale"][0], name


def test_a_lofted_anime_body_rigs_with_its_head_in_the_egg_and_leaves_the_default_untouched():
    """mesh loft is one smooth tube mesh. The humanoid rig still finds a T-posed person in it, its Head joint lands inside
    the egg the face cap hugs, and a body without the field is the same pieces as before."""
    import json, struct
    from services.blob_loft import loft_mesh, egg_scale
    from services.blob_make import build_body

    girl = {**PRESETS["anime_girl"], "accessories": [{"kind": "skirt", "color": "#1B2350"}, {"kind": "school_collar", "color": "#F7F4EF"}]}
    plain = blob_pieces(girl)
    assert "mesh" not in plain["traits"] and "layout" not in plain
    lofted = blob_pieces({**girl, "mesh": "loft"})
    assert lofted["traits"]["mesh"] == "loft" and lofted["faceAnchor"] == plain["faceAnchor"]
    mesh = loft_mesh(lofted["traits"], lofted["layout"])
    assert 1500 <= len(mesh.vertices) // 3 <= 6000 and len(mesh.normals) == len(mesh.vertices) == len(mesh.colors)
    assert egg_scale(0.5) == 1.0 and abs(egg_scale(-1.0) - 0.65) < 1e-9
    with pytest.raises(BlobTraitsError) as refused:
        blob_pieces({**PRESETS["blob_scout"], "mesh": "loft"})
    assert refused.value.code == "invalid_mesh"

    body = build_body({**girl, "mesh": "loft"}, ["idle"])
    glb = body["rigged"]
    length = struct.unpack("<I", glb[12:16])[0]
    nodes = json.loads(glb[20:20 + length])["nodes"]
    parent = {child: index for index, node in enumerate(nodes) for child in node.get("children", [])}
    head = next(index for index, node in enumerate(nodes) if node.get("name") == "Head")
    y = 0.0
    while head is not None:
        y += nodes[head].get("translation", [0, 0, 0])[1]
        head = parent.get(head)
    center, radii = plain["faceAnchor"]["center"], plain["faceAnchor"]["radii"]
    assert center[1] - radii[1] < y < center[1] + radii[1]

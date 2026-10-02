"""Compatibility contract: hierarchy map, clips, and pose math.

A finished parse is ``mapped``. It is not ``retarget_verified``.
"""

from __future__ import annotations

import base64
import os
import struct

import numpy as np
import pytest

from services.humanoid_rig.body_roles import REQUIRED_RETARGET_ROLES
from services.humanoid_rig.clip_inventory import (
    ClipSelectError,
    default_motion_index,
    list_clips,
    playback_time,
    select_by_name,
    select_clip,
)
from services.humanoid_rig.compatibility import (
    describe,
    preservation_plan,
    record_verification,
    retarget_locals,
    retarget_root,
    retarget_world,
    weight_issues,
)
from services.humanoid_rig.descriptor import (
    ALGORITHM_VERSION,
    analysis_reusable,
    apply_role_overrides,
    assign_clip_selection,
    assign_destination,
    assign_options,
    assign_reference_pose,
    build_descriptor,
    cache_identity,
    load_descriptor,
    save_descriptor,
    verification_applies,
)
from services.humanoid_rig.gltf_accessors import AccessorError, read_accessor, split_glb
from services.humanoid_rig.names import BONE_PARENTS, CLIP_IDS
from services.humanoid_rig.pose_math import (
    IDENTITY_QUAT,
    PoseMathError,
    axis_angle_quat,
    constant_child_translation,
    quat_mul,
    quat_rotate,
    quats_equivalent,
    rest_axes_agree,
    sample_channel,
    scale_channel_policy,
    target_world_quat,
    trs_matrix,
    world_matrices,
)
from services.humanoid_rig.retarget import _floats_at, retarget_gltf
from services.humanoid_rig.role_map import is_ancestor, node_parents

IDENTITY = [0.0, 0.0, 0.0, 1.0]


def _nodes(rows):
    nodes = []
    indexes = {}
    for name, _parent, extra in rows:
        node = {"name": name, "children": []}
        node.update(extra)
        indexes[name] = len(nodes)
        nodes.append(node)
    for name, parent, _extra in rows:
        if parent is not None:
            nodes[indexes[parent]]["children"].append(indexes[name])
    return nodes


def _body(hips_scale=None):
    extra = {} if hips_scale is None else {"scale": hips_scale}
    rows = [
        ("Armature", None, {"scale": [0.01, 0.01, 0.01]}),
        ("Hips", "Armature", extra),
        ("Spine02", "Hips", {}),
        ("Spine01", "Spine02", {}),
        ("Spine", "Spine01", {}),
        ("neck", "Spine", {}),
        ("Head", "neck", {}),
        ("head_end", "Head", {}),
        ("headfront", "Head", {}),
        ("LeftArm", "Spine", {}),
        ("LeftForeArm", "LeftArm", {}),
        ("LeftHand", "LeftForeArm", {}),
        ("RightArm", "Spine", {}),
        ("RightForeArm", "RightArm", {}),
        ("RightHand", "RightForeArm", {}),
        ("LeftUpLeg", "Hips", {}),
        ("LeftLeg", "LeftUpLeg", {}),
        ("LeftFoot", "LeftLeg", {}),
        ("RightUpLeg", "Hips", {}),
        ("RightLeg", "RightUpLeg", {}),
        ("RightFoot", "RightLeg", {}),
    ]
    return _nodes(rows)


def _mixamo_rows():
    return [
        ("Hips", None, {}),
        ("Spine", "Hips", {}),
        ("Spine1", "Spine", {}),
        ("Spine2", "Spine1", {}),
        ("Neck", "Spine2", {}),
        ("Head", "Neck", {}),
        ("LeftArm", "Spine2", {}),
        ("LeftForeArm", "LeftArm", {}),
        ("LeftHand", "LeftForeArm", {}),
        ("RightArm", "Spine2", {}),
        ("RightForeArm", "RightArm", {}),
        ("RightHand", "RightForeArm", {}),
        ("LeftUpLeg", "Hips", {}),
        ("LeftLeg", "LeftUpLeg", {}),
        ("LeftFoot", "LeftLeg", {}),
        ("RightUpLeg", "Hips", {}),
        ("RightLeg", "RightUpLeg", {}),
        ("RightFoot", "RightLeg", {}),
    ]


def _clips():
    return {
        "accessors": [
            {"count": 1, "type": "SCALAR", "min": [0.0], "max": [0.0]},
            {"count": 2, "type": "SCALAR", "min": [2.0], "max": [3.033]},
            {"count": 2, "type": "SCALAR", "min": [0.0], "max": [0.633]},
        ],
        "animations": [
            {"name": "pose", "samplers": [{"input": 0, "interpolation": "STEP"}], "channels": [{"sampler": 0}]},
            {
                "name": "Walking",
                "samplers": [{"input": 1, "interpolation": "LINEAR"}],
                "channels": [{"sampler": 0}, {"sampler": 0}],
            },
            {"name": "Walking", "samplers": [{"input": 2, "interpolation": "LINEAR"}], "channels": [{"sampler": 0}]},
        ],
    }


def _described_body():
    document = {"nodes": _body(), "skins": [{"joints": [1]}], **_clips()}
    return describe(document)


def test_spine_chain_wins_over_the_name_spine():
    described = _described_body()
    assert described["roles"]["spine"]["name"] == "Spine02"
    assert described["roles"]["chest"]["name"] == "Spine01"
    assert described["roles"]["upperChest"]["name"] == "Spine"
    assert described["roles"]["neck"]["name"] == "neck"
    assert described["roles"]["head"]["name"] == "Head"
    assert described["status"] == "mapped"
    assert described["retarget_verified"] is False
    assert described["profile_id"] == "meshy-blender-body-reference-v1"
    assert described["profile_evidence"] == "hierarchy"


def test_missing_toe_end_is_not_a_missing_body_part():
    described = _described_body()
    assert described["missing_required"] == []
    assert "LeftToe_End" not in described["roles"]
    assert described["auxiliaries"]["head_end"]["export_name"] == "HeadTop_End"
    assert described["auxiliaries"]["headfront"]["required"] is False
    assert set(REQUIRED_RETARGET_ROLES) <= set(described["roles"])


def test_mixamo_order_and_names_do_not_invent_a_version():
    document = {"nodes": _nodes(_mixamo_rows()), "skins": [{"joints": [0]}]}
    described = describe(document)
    assert described["roles"]["spine"]["name"] == "Spine"
    assert described["roles"]["chest"]["name"] == "Spine1"
    assert described["roles"]["upperChest"]["name"] == "Spine2"
    assert described["profile_id"] == "external-native"
    assert described["profile_evidence"] == "unversioned"
    assert described["preservation"]["clear_previous_skin"] is False


def test_legacy_profile_matches_a_saved_export():
    rows = [(name, parent, {}) for name, parent in BONE_PARENTS]
    rows[0] = ("Hips", None, {"scale": [1.2, 1.2, 1.2]})
    described = describe({"nodes": _nodes(rows)})
    assert described["profile_id"] == "hocuspocus-legacy-body-v0"
    assert described["profile_evidence"] == "export_structure"
    assert described["preservation"]["silent_migration"] is False
    assert described["preservation"]["legacy_clip_count"] == 14
    assert len(CLIP_IDS) == 14


def test_metadata_profile_overrides_the_chain():
    described = describe({"nodes": _body()}, metadata={"profile_id": "hocuspocus-body-v1"})
    assert described["profile_id"] == "hocuspocus-body-v1"
    assert described["profile_evidence"] == "metadata"
    assert preservation_plan("hocuspocus-body-v1")["hips_normalization_scale"] == 1


def test_static_pose_is_not_the_default_motion():
    clips = list_clips(_clips())
    assert clips[0]["duration"] == 0.0
    assert clips[0]["static_pose"] is True
    assert clips[1]["duration"] == pytest.approx(1.033)
    assert clips[1]["time_start"] == 2.0
    assert default_motion_index(clips) == 1
    assert playback_time(clips[1], 0.0) == 2.0
    assert playback_time(clips[1], 1.033) == pytest.approx(3.033)
    with pytest.raises(ClipSelectError):
        playback_time(clips[1], 1.1)
    with pytest.raises(ClipSelectError):
        select_by_name(clips, "Walking")
    chosen = select_clip(_clips(), 2, asset_hash="abc")
    assert chosen["index"] == 2
    assert chosen["asset_hash"] == "abc"
    with pytest.raises(ClipSelectError):
        select_clip(_clips(), 9)


def test_position_bounds_are_the_recorded_height():
    document = {
        "nodes": [
            {"name": "Armature", "scale": [0.01, 0.01, 0.01], "translation": [0, 0, 0]},
            {"name": "Hips", "translation": [0, 98.0, 0]},
        ],
        "meshes": [{
            "primitives": [{
                "attributes": {"POSITION": 0},
            }],
        }],
        "accessors": [{"min": [0.0, 0.0, 0.0], "max": [0.4, 1.7, 0.2], "type": "VEC3"}],
        "skins": [{"joints": [1]}],
    }
    described = describe(document)
    assert described["height_m"] == pytest.approx(1.7)
    assert described["height_method"] == "position_bounds_m"
    assert described["wrapper_scale_applied_again"] is False
    assert described["rejected"][0]["method"] == "node_translation_span"
    assert described["rejected"][0]["value"] == pytest.approx(98.0)
    assert described["height_m"] != described["rejected"][0]["value"]


def test_wrapper_scale_is_applied_once_in_fk():
    parent = trs_matrix([0, 0, 0], IDENTITY, [0.01, 0.01, 0.01])
    child = trs_matrix([0, 170, 0], IDENTITY, [1, 1, 1])
    worlds = world_matrices([parent, child], [None, 0])
    assert worlds[1][1, 3] == pytest.approx(1.7)


def test_step_holds_and_cubicspline_is_explicit():
    held = sample_channel([0.0, 1.0], [[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]], 0.9, "STEP", channel="translation")
    landed = sample_channel([0.0, 1.0], [[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]], 1.0, "STEP", channel="translation")
    np.testing.assert_allclose(held, [0.0, 0.0, 0.0])
    np.testing.assert_allclose(landed, [1.0, 2.0, 3.0])
    with pytest.raises(PoseMathError) as caught:
        sample_channel([0.0, 1.0], [IDENTITY, IDENTITY], 0.5, "CUBICSPLINE", clip="Walking", channel="Hips.rotation")
    assert caught.value.reason == "unsupported_interpolation"
    assert caught.value.clip == "Walking"
    assert caught.value.channel == "Hips.rotation"


def test_negative_quaternion_is_the_same_orientation():
    turn = axis_angle_quat([0, 1, 0], np.pi / 2)
    assert quats_equivalent(turn, -turn)
    worlds = retarget_world({"leftUpperArm": -turn}, {"leftUpperArm": turn}, {"leftUpperArm": IDENTITY})
    assert quats_equivalent(worlds["leftUpperArm"], IDENTITY)


def test_reference_pose_lands_on_the_target_reference():
    source_ref = {"hips": IDENTITY, "spine": IDENTITY, "leftUpperArm": IDENTITY, "rightUpperArm": IDENTITY}
    target_ref = {
        "hips": IDENTITY,
        "spine": axis_angle_quat([1, 0, 0], np.pi / 2),
        "leftUpperArm": IDENTITY,
        "rightUpperArm": axis_angle_quat([0, 0, 1], 0.3),
    }
    worlds = retarget_world(source_ref, source_ref, target_ref)
    for role, quat in target_ref.items():
        assert quats_equivalent(worlds[role], quat)
    moved = dict(source_ref)
    moved["leftUpperArm"] = axis_angle_quat([0, 1, 0], np.pi / 2)
    changed = retarget_world(moved, source_ref, target_ref)
    assert quats_equivalent(changed["rightUpperArm"], target_ref["rightUpperArm"])
    assert not quats_equivalent(changed["leftUpperArm"], target_ref["leftUpperArm"])
    locals_out = retarget_locals(worlds, {"spine": "hips", "leftUpperArm": "spine", "rightUpperArm": "spine", "hips": None})
    assert quats_equivalent(locals_out["spine"], target_ref["spine"])


def test_in_place_drops_horizontal_travel_and_refuses_a_hundredfold_scale():
    samples = [[0.0, 0.9, 0.0], [2.0, 1.1, -3.0]]
    short, short_meta = retarget_root(samples, 1.7, 1.0)
    same, same_meta = retarget_root(samples, 1.7, 1.7)
    np.testing.assert_allclose(short[:, 0], [0.0, 0.0])
    np.testing.assert_allclose(short[:, 2], [0.0, 0.0])
    assert short[1, 1] == pytest.approx(0.9 + 0.2 / 1.7)
    assert same[1, 1] == pytest.approx(1.1)
    assert short_meta["trajectory_yaw"] == "not_removed"
    assert short_meta["policy"] == "in_place"
    assert same_meta["height_ratio"] == pytest.approx(1.0)
    kept, kept_meta = retarget_root(samples, 1.7, 1.0, policy="preserve")
    assert kept[1, 0] == pytest.approx(2.0 / 1.7)
    assert kept_meta["policy"] == "preserve"
    with pytest.raises(PoseMathError) as caught:
        retarget_root(samples, 0.017, 1.7)
    assert caught.value.reason == "height_ratio_refused"


def test_constant_channels_record_their_policy():
    rest = constant_child_translation([[0.0, 1.0, 0.0], [0.0, 1.0 + 1e-6, 0.0]], [0.0, 1.0, 0.0])
    moving = constant_child_translation([[0.0, 1.0, 0.0], [0.2, 1.0, 0.0]], [0.0, 1.0, 0.0])
    assert rest["collapsed"] is True
    assert rest["policy"] == "constant_child_translation_to_rest"
    assert moving["reason"] == "variable_translation"
    quiet = scale_channel_policy([[1.0, 1.0, 1.0], [1.0, 1.0 + 1e-7, 1.0]])
    loud = scale_channel_policy([[1.0, 1.0, 1.0], [1.0, 1.2, 1.0]])
    assert quiet["ignored"] is True
    assert loud["reason"] == "variable_scale"


def test_stride_is_honored_and_weights_are_not_truncated():
    blob = struct.pack("<3ff3f", 1, 2, 3, 9, 4, 5, 6)
    document = {
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteStride": 16, "byteLength": len(blob)}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 2, "type": "VEC3"}],
    }
    read = read_accessor(document, 0, [blob])
    tight = _floats_at(blob, 0, 2, 3)
    np.testing.assert_allclose(read, [[1, 2, 3], [4, 5, 6]])
    assert not np.allclose(read, tight)
    wide = np.full((2, 8), 0.125)
    assert weight_issues(np.zeros((2, 8), dtype=np.int32), wide, 4) == []
    assert "negative_weight" in weight_issues([[0]], [[-0.2]], 1)
    assert "joint_index_outside_skin" in weight_issues([[4]], [[1.0]], 4)


def _weighted(document):
    joints = np.array([[0, 0, 0, 0]], dtype="<u2").tobytes()
    weights = np.array([[1, 0, 0, 0]], dtype="<f4").tobytes()
    blob = joints + weights
    accessors = list(document.get("accessors") or [])
    base = len(accessors)
    weighted = {
        **document,
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(joints)},
            {"buffer": 0, "byteOffset": len(joints), "byteLength": len(weights)},
        ],
        "accessors": accessors + [
            {"bufferView": 0, "componentType": 5123, "count": 1, "type": "VEC4"},
            {"bufferView": 1, "componentType": 5126, "count": 1, "type": "VEC4"},
        ],
        "meshes": [{"primitives": [{"attributes": {"JOINTS_0": base, "WEIGHTS_0": base + 1}}]}],
    }
    return weighted, [blob]


def _evidence(described, **overrides):
    evidence = {
        "destination_id": "target-a",
        "source_hash": "source-hash",
        "target_hash": "target-hash",
        "clip_index": 1,
        "profile_id": described["profile_id"],
        "contract_version": described["contract_version"],
        "reference": "rest",
        "options": {"root": "in_place"},
        "neutral_passed": True,
        "axis_passed": True,
    }
    evidence.update(overrides)
    return evidence


def test_verification_requires_destination_evidence():
    document, buffers = _weighted({"nodes": _body(), "skins": [{"joints": [1]}], **_clips()})
    described = describe(document, buffers, asset_hash="source-hash")
    assert described["weights_status"] == "passed"
    refused = record_verification(described, {"neutral_passed": True, "axis_passed": True})
    assert refused["retarget_verified"] is False
    accepted = record_verification(described, _evidence(described))
    assert accepted["retarget_verified"] is True
    assert accepted["status"] == "retarget_verified"
    assert accepted["verification"]["scope"] == "clip"
    assert described["retarget_verified"] is False
    revoked = record_verification(accepted, _evidence(described, neutral_passed=False))
    assert revoked["retarget_verified"] is False
    assert revoked["status"] == "mapped"


def test_reflection_and_cycles_are_not_silently_fixed():
    rows = _mixamo_rows()
    rows[6] = ("LeftArm", "Spine2", {"scale": [-1.0, 1.0, 1.0]})
    reflected = describe({"nodes": _nodes(rows), "skins": [{"joints": [0]}]})
    assert reflected["retarget_status"] == "needs_review"
    assert reflected["native_playback"] is False
    assert reflected["native_candidate"] is True
    assert any(reason.startswith("unsupported_transform") for reason in reflected["reasons"])
    loop = [
        {"name": "Hips", "children": [1]},
        {"name": "Spine", "children": [0]},
    ]
    cycled = describe({"nodes": loop, "skins": [{"joints": [0]}]})
    assert cycled["status"] == "unsupported"
    parents = node_parents(_body())
    assert is_ancestor(parents, 6, 1)


def test_legacy_reader_still_defaults_to_clip_zero_and_rejects_step():
    times = np.array([0.0, 1.0], dtype="<f4").tobytes()
    first = np.array([IDENTITY, IDENTITY], dtype="<f4").tobytes()
    second = np.array([IDENTITY, axis_angle_quat([0, 1, 0], np.pi / 2)], dtype="<f4").tobytes()
    blob = times + first + second
    uri = "data:application/octet-stream;base64," + base64.b64encode(blob).decode("ascii")
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": uri, "byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 8},
            {"buffer": 0, "byteOffset": 8, "byteLength": 32},
            {"buffer": 0, "byteOffset": 40, "byteLength": 32},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 2, "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC4"},
            {"bufferView": 2, "componentType": 5126, "count": 2, "type": "VEC4"},
        ],
        "nodes": [{"name": "LeftArm"}],
        "animations": [
            {"samplers": [{"input": 0, "output": 1, "interpolation": "LINEAR"}], "channels": [
                {"sampler": 0, "target": {"node": 0, "path": "rotation"}},
            ]},
            {"samplers": [{"input": 0, "output": 2, "interpolation": "LINEAR"}], "channels": [
                {"sampler": 0, "target": {"node": 0, "path": "rotation"}},
            ]},
        ],
    }
    default = retarget_gltf(document, 1.0, source_height=1.0)
    chosen = retarget_gltf(document, 1.0, source_height=1.0, animation_index=1)
    np.testing.assert_allclose(default["rotations"]["LeftArm"][1], IDENTITY)
    assert not np.allclose(chosen["rotations"]["LeftArm"][1], IDENTITY)
    with pytest.raises(ValueError, match="invalid animation_index"):
        retarget_gltf(document, 1.0, source_height=1.0, animation_index=4)
    document["animations"][0]["samplers"][0]["interpolation"] = "STEP"
    with pytest.raises(ValueError, match="unsupported interpolation"):
        retarget_gltf(document, 1.0, source_height=1.0)


def test_old_name_match_misses_the_reference_spine():
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "data:application/octet-stream;base64," + base64.b64encode(
            np.array([0.0, 1.0], dtype="<f4").tobytes() + np.array([IDENTITY, IDENTITY], dtype="<f4").tobytes()
        ).decode("ascii"), "byteLength": 40}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 8},
            {"buffer": 0, "byteOffset": 8, "byteLength": 32},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 2, "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC4"},
        ],
        "nodes": _body(),
        "animations": [{"samplers": [{"input": 0, "output": 1, "interpolation": "LINEAR"}], "channels": [
            {"sampler": 0, "target": {"node": 1, "path": "rotation"}},
        ]}],
    }
    parsed = retarget_gltf(document, 1.0, source_height=1.7)
    assert "unrecognized joint Spine02" in parsed["warnings"]
    assert "Spine02" not in parsed["bones"]
    described = describe(document)
    assert described["roles"]["spine"]["name"] == "Spine02"
    assert described["roles"]["upperChest"]["name"] == "Spine"


def test_opt_in_reference_glb_lists_motion_clips():
    path = os.environ.get("HOCUS_RIG_REFERENCE_GLB")
    if not path:
        pytest.skip("HOCUS_RIG_REFERENCE_GLB is not set")
    document, buffers = split_glb(open(path, "rb").read())
    described = describe(document, buffers)
    assert len(described["clips"]) == 10
    assert described["clips"][0]["duration"] == 0.0
    assert described["default_motion_index"] not in (None, 0)
    assert described["roles"]["spine"]["name"] == "Spine02"
    assert described["roles"]["chest"]["name"] == "Spine01"
    assert described["roles"]["upperChest"]["name"] == "Spine"
    assert described["status"] == "mapped"
    assert described["retarget_verified"] is False
    assert described["profile_id"] == "meshy-blender-body-reference-v1"
    assert described["preservation"]["clear_previous_skin"] is False
    assert described["height_method"] != "node_translation_span"
    if described["height_m"] is not None:
        assert described["height_m"] == pytest.approx(1.7, abs=1e-3)
        assert described["height_m"] < 10


def _rotate(quat, vector):
    return trs_matrix([0, 0, 0], quat, [1, 1, 1])[:3, :3] @ np.asarray(vector, dtype=float)


def test_crossed_or_disconnected_limbs_need_review():
    crossed = [(name, "RightArm" if name == "LeftForeArm" else parent, extra) for name, parent, extra in _mixamo_rows()]
    disconnected = [(name, None if name == "LeftArm" else parent, extra) for name, parent, extra in _mixamo_rows()]
    for rows in (crossed, disconnected):
        result = describe({"nodes": _nodes(rows), "skins": [{"joints": list(range(16))}]})
        assert result["retarget_status"] != "mapped"
        assert any(reason.startswith("semantic_parent:") for reason in result["reasons"])


def test_arbitrary_hips_scale_stays_external():
    rows = _mixamo_rows()
    rows[0] = ("Hips", None, {"scale": [1.2, 1.2, 1.2], "rotation": axis_angle_quat([0, 0, 1], np.pi / 2).tolist()})
    result = describe({"nodes": _nodes(rows), "skins": [{"joints": [0]}]})
    assert result["profile_id"] == "external-native"


def test_zero_scale_and_empty_skin_are_rejected():
    rows = _mixamo_rows()
    rows[0] = ("Hips", None, {"scale": [0, 0, 0]})
    zero = describe({"nodes": _nodes(rows), "skins": [{"joints": [0]}]})
    assert zero["retarget_status"] != "mapped"
    empty = describe({"nodes": _nodes(_mixamo_rows()), "skins": [{"joints": []}]})
    assert empty["native_playback"] is False
    assert empty["native_candidate"] is False


def test_world_delta_moves_the_anatomical_endpoint():
    source_ref = axis_angle_quat([0, 0, 1], np.pi / 2)
    target_ref = IDENTITY_QUAT
    world_motion = axis_angle_quat([0, 1, 0], np.pi / 2)
    source_animated = quat_mul(world_motion, source_ref)
    np.testing.assert_allclose(_rotate(source_ref, [0, -1, 0]), _rotate(target_ref, [1, 0, 0]), atol=1e-10)
    assert rest_axes_agree(source_ref, target_ref, [0, -1, 0], [1, 0, 0])
    target_animated = target_world_quat(source_animated, source_ref, target_ref)
    np.testing.assert_allclose(_rotate(target_animated, [1, 0, 0]), _rotate(source_animated, [0, -1, 0]), atol=1e-10)
    assert rest_axes_agree(source_ref, target_ref, [0, 1, 0], [1, 0, 0]) is False


def test_quaternion_rotation_keeps_length_and_zero():
    np.testing.assert_allclose(quat_rotate(IDENTITY_QUAT, [2, 0, 0]), [2, 0, 0])
    np.testing.assert_allclose(quat_rotate(IDENTITY_QUAT, [0, 0, 0]), [0, 0, 0])


def test_verification_rejects_bad_evidence():
    unsupported = {
        "status": "unsupported",
        "retarget_status": "unsupported",
        "retarget_verified": False,
        "reasons": ["skeleton_cycle"],
        "weights_status": "passed",
    }
    evidence = {"destination_id": "target-a", "neutral_passed": True, "axis_passed": True}
    assert record_verification(unsupported, evidence)["retarget_verified"] is False
    document, buffers = _weighted({"nodes": _body(), "skins": [{"joints": [1]}], **_clips()})
    described = describe(document, buffers, asset_hash="source-hash")
    text = record_verification(described, _evidence(described, neutral_passed="false", axis_passed="false"))
    assert text["retarget_verified"] is False
    assert text["status"] == "mapped"
    other = record_verification(described, _evidence(described, target_hash="other-target", neutral_passed=False))
    assert other["retarget_verified"] is False
    assert other["verification"]["target_hash"] == "other-target"


def test_accessor_stays_inside_its_buffer_view():
    document = {
        "bufferViews": [{"buffer": 0, "byteLength": 4}],
        "accessors": [{"bufferView": 0, "count": 2, "componentType": 5126, "type": "SCALAR"}],
    }
    with pytest.raises(AccessorError):
        read_accessor(document, 0, [struct.pack("<ff", 1, 999)])


def test_unreadable_samples_are_not_a_static_pose():
    document = {
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 4}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 2, "type": "SCALAR"}],
        "animations": [{
            "name": "pose",
            "samplers": [{"input": 0, "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0}],
        }],
    }
    clip = list_clips(document, [struct.pack("<f", 1.0)])[0]
    assert clip["unreadable"] is True
    assert clip["static_pose"] is False


def test_height_uses_every_primitive_and_one_wrapper_scale():
    nodes = _nodes(_mixamo_rows())
    document = {
        "nodes": nodes,
        "skins": [{"joints": [0]}],
        "meshes": [{"primitives": [
            {"attributes": {"POSITION": 0}},
            {"attributes": {"POSITION": 1}},
        ]}],
        "accessors": [
            {"type": "VEC3", "min": [0, 0, 0], "max": [0.3, 0.5, 0.2]},
            {"type": "VEC3", "min": [0, 0, 0], "max": [0.8, 1.7, 0.5]},
        ],
    }
    assert describe(document)["height_m"] == pytest.approx(1.7)
    wrapped = {
        "nodes": [
            {"name": "Armature", "scale": [0.01, 0.01, 0.01], "children": [1]},
            {"name": "Body", "mesh": 0},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [{"type": "VEC3", "min": [0, 0, 0], "max": [0.2, 170, 0.2]}],
    }
    measured = describe(wrapped)
    assert measured["height_m"] == pytest.approx(1.7)
    assert measured["height_method"] == "node_bounds_m"
    assert measured["wrapper_scale_applied_again"] is False


def test_bind_shape_scale_is_applied_once():
    points = np.array([[0, 0, 0], [0, 170, 0]], dtype="<f4").tobytes()
    joints = np.array([[0, 0, 0, 0], [0, 0, 0, 0]], dtype="<u2").tobytes()
    weights = np.array([[1, 0, 0, 0], [1, 0, 0, 0]], dtype="<f4").tobytes()
    inverse = np.identity(4, dtype="<f4")
    inverse[0, 0] = inverse[1, 1] = inverse[2, 2] = 0.01
    blob = points + joints + weights + inverse.reshape(-1, order="F").tobytes()
    document = {
        "nodes": [{"name": "Hips", "skin": 0, "mesh": 0}],
        "skins": [{"joints": [0], "inverseBindMatrices": 3}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "JOINTS_0": 1, "WEIGHTS_0": 2}}]}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(points)},
            {"buffer": 0, "byteOffset": len(points), "byteLength": len(joints)},
            {"buffer": 0, "byteOffset": len(points) + len(joints), "byteLength": len(weights)},
            {"buffer": 0, "byteOffset": len(points) + len(joints) + len(weights), "byteLength": 64},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 2, "type": "VEC3", "min": [0, 0, 0], "max": [0, 170, 0]},
            {"bufferView": 1, "componentType": 5123, "count": 2, "type": "VEC4"},
            {"bufferView": 2, "componentType": 5126, "count": 2, "type": "VEC4"},
            {"bufferView": 3, "componentType": 5126, "count": 1, "type": "MAT4"},
        ],
    }
    described = describe(document, [blob])
    assert described["height_m"] == pytest.approx(1.7)
    assert described["height_method"] == "skinned_bounds_m"
    assert described["height_m"] < 10


def _append_child(nodes, parent_index, name):
    index = len(nodes)
    nodes.append({"name": name, "children": []})
    nodes[parent_index].setdefault("children", []).append(index)
    return index


def _descriptor_nodes():
    nodes = _body()
    left_a = _append_child(nodes, 10, "LeftExtra")
    left_b = _append_child(nodes, 10, "LeftExtra")
    right_extra = _append_child(nodes, 10, "RightExtra")
    return nodes, left_a, left_b, right_extra


def test_rig_descriptor_round_trip(tmp_path):
    nodes, left_a, left_b, _right_extra = _descriptor_nodes()
    document = {"nodes": nodes, "skins": [{"joints": [1]}], **_clips()}
    described = describe(document, asset_hash="asset-a")
    descriptor = build_descriptor(document, asset_hash="asset-a", options={"root": "in_place"})
    assert set(described) <= set(descriptor)
    assert descriptor["skin_index"] == 0
    assert descriptor["algorithm_version"] == ALGORITHM_VERSION
    assert descriptor["parent_indexes"][left_b] == 10
    assert descriptor["height_m"] == described["height_m"]
    assert descriptor["height_method"] == described["height_method"]
    assert descriptor["clips"] == described["clips"]
    assert descriptor["native_playback"] is False
    assert descriptor["retarget_verified"] is False
    saved = apply_role_overrides(descriptor, nodes, {"leftHand": left_b})
    assert saved["role_overrides"] == {"leftHand": left_b}
    assert saved["roles"]["leftHand"]["node_index"] == left_b
    assert nodes[left_a]["name"] == nodes[left_b]["name"] == "LeftExtra"
    asset = tmp_path / "hero.glb"
    asset.write_bytes(b"synthetic")
    path = save_descriptor(saved, asset)
    assert path.name == "hero.glb.rig-descriptor.json"
    loaded = load_descriptor(asset)
    assert loaded == saved
    assert loaded["role_overrides"] == {"leftHand": left_b}
    names = sorted(item.name for item in tmp_path.iterdir())
    assert names == ["hero.glb", "hero.glb.rig-descriptor.json"]


def test_role_override_uses_the_node_index():
    nodes, left_a, left_b, _right_extra = _descriptor_nodes()
    document = {"nodes": nodes, "skins": [{"joints": [1]}]}
    descriptor = build_descriptor(document, asset_hash="asset-a")
    saved = apply_role_overrides(descriptor, nodes, {"leftHand": left_b})
    assert saved["status"] == "mapped"
    assert saved["retarget_verified"] is False
    assert saved["native_playback"] is False
    assert saved["role_nodes"]["leftHand"] == left_b
    assert saved["role_nodes"]["leftHand"] != left_a
    assert saved["roles"]["leftHand"]["name"] == nodes[left_a]["name"]
    assert len(set(saved["role_nodes"].values())) == len(saved["role_nodes"])


def test_role_override_rejects_crossed_side_and_duplicate_role():
    nodes, left_a, left_b, right_extra = _descriptor_nodes()
    document = {"nodes": nodes, "skins": [{"joints": [1]}]}
    descriptor = build_descriptor(document, asset_hash="asset-a")
    crossed = apply_role_overrides(descriptor, nodes, {"leftHand": right_extra})
    assert crossed["status"] == "needs_review"
    assert crossed["retarget_status"] == "needs_review"
    assert crossed["retarget_verified"] is False
    assert crossed["verification"] is None
    assert crossed["native_playback"] is False
    assert any(reason.startswith("crossed_side:") for reason in crossed["reasons"])
    assert any(item["code"] == "crossed_side" for item in crossed["structured_reasons"])
    duplicate = apply_role_overrides(descriptor, nodes, [("leftHand", left_a), ("leftHand", left_b)])
    assert duplicate["status"] == "needs_review"
    assert duplicate["retarget_verified"] is False
    assert any(reason.startswith("duplicate_role:leftHand") for reason in duplicate["reasons"])
    assert any(item["code"] == "duplicate_role" for item in duplicate["structured_reasons"])
    assert descriptor["retarget_verified"] is False
    assert descriptor["roles"]["leftHand"]["name"] == "LeftHand"


def test_verification_clears_when_override_or_destination_changes():
    nodes, _left_a, left_b, _right_extra = _descriptor_nodes()
    document, buffers = _weighted({"nodes": nodes, "skins": [{"joints": [1]}], **_clips()})
    descriptor = build_descriptor(document, buffers, asset_hash="source-hash", options={"root": "in_place"})
    certified = record_verification(descriptor, _evidence(descriptor))
    assert certified["retarget_verified"] is True
    assert verification_applies(certified, "target-a") is True
    assert verification_applies(certified, "target-b") is False
    overridden = apply_role_overrides(certified, nodes, {"leftHand": left_b})
    assert overridden["status"] == "mapped"
    assert overridden["retarget_verified"] is False
    assert overridden["verification"] is None
    moved = assign_destination(certified, "target-b")
    assert cache_identity(moved) == cache_identity(certified)
    assert moved["retarget_verified"] is False
    assert moved["verification"] is None
    assert verification_applies(moved, "target-a") is False
    assert verification_applies(moved, "target-b") is False
    assert assign_reference_pose(certified, "t")["retarget_verified"] is False
    assert assign_clip_selection(certified, 1)["retarget_verified"] is False
    assert assign_options(certified, {"root": "preserve"})["retarget_verified"] is False
    assert certified["retarget_verified"] is True
    assert descriptor["retarget_verified"] is False


def test_stale_asset_hash_is_not_a_cache_hit(tmp_path):
    nodes = _body()
    document = {"nodes": nodes, "skins": [{"joints": [1]}]}
    stored = build_descriptor(document, asset_hash="hash-a", options={"pose": "rest", "root": "in_place"})
    asset = tmp_path / "hero.glb"
    asset.write_bytes(b"synthetic")
    save_descriptor(stored, asset)
    loaded = load_descriptor(asset)
    assert loaded["asset_hash"] == "hash-a"
    assert loaded["profile_id"] == "meshy-blender-body-reference-v1"
    stale = dict(loaded)
    stale["asset_hash"] = "hash-b"
    assert analysis_reusable(loaded, loaded) is True
    assert analysis_reusable(loaded, stale) is False
    assert cache_identity(loaded) != cache_identity(stale)
    profile = dict(loaded)
    profile["profile_id"] = "external-native"
    assert cache_identity(loaded) == cache_identity(profile)
    assert analysis_reusable(loaded, profile) is False
    other_skin = dict(loaded)
    other_skin["skin_index"] = 1
    assert analysis_reusable(loaded, other_skin) is False
    other_options = dict(loaded)
    other_options["options"] = {"root": "in_place", "pose": "rest"}
    assert analysis_reusable(loaded, other_options) is True

"""Importing animations: other tools' conventions land as the same motion on our rig."""
import base64
import copy
import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from services.humanoid_rig.animate import stored_rig
from services.humanoid_rig.clips import clip_library, default_rig
from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES
from services.humanoid_rig.retarget import retarget_file
from services.humanoid_rig.retarget_names import bone_for, words
from services.humanoid_rig.rig import rig_humanoid
from tests.humanoid_bodies import as_glb, body
from tests.humanoid_sources import as_bytes, canonical_motion, cmu_like_bvh, mixamo_like_gltf
from tests.humanoid_skinning import batch_worlds

ROOT = Path(__file__).parents[1] / "tests" / "fixtures" / "humanoid_rig"
LIMBS = (("LeftArm", "LeftForeArm"), ("LeftForeArm", "LeftHand"), ("RightArm", "RightForeArm"), ("RightForeArm", "RightHand"),
         ("LeftUpLeg", "LeftLeg"), ("LeftLeg", "LeftFoot"), ("RightUpLeg", "RightLeg"), ("Spine", "Neck"))


def _target(kind="human_a"):
    rigged, _sidecar = rig_humanoid(as_glb(body(kind)))
    return stored_rig(rigged)


def _worst_angles(source_rig, clip_id, target, clip):
    motion = canonical_motion(source_rig, clip_id)
    count = min(len(motion["times"]), len(clip["times"]))
    local = np.stack([clip["rotations"].get(name, np.tile(target.bones[index]["rotation"], (len(clip["times"]), 1)))
                      for index, name in enumerate(BONE_NAMES)], axis=1)
    worlds = batch_worlds(target.bones, local, clip["hips_translation"])
    worst = {}
    for start, end in LIMBS:
        source = motion["positions"][:count, BONE_BY_NAME[end]] - motion["positions"][:count, BONE_BY_NAME[start]]
        ours = worlds[:count, BONE_BY_NAME[end], :3, 3] - worlds[:count, BONE_BY_NAME[start], :3, 3]
        cosine = np.sum(source * ours, axis=1) / np.linalg.norm(source, axis=1) / np.linalg.norm(ours, axis=1)
        worst[start] = float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))).max())
    return worst


@pytest.mark.parametrize("clip_id", ("walk", "clap", "jump"))
def test_a_mixamo_style_export_lands_as_the_same_motion(clip_id):
    target = _target()
    document = mixamo_like_gltf(default_rig(), clip_id)
    clips = retarget_file(as_bytes(document), ".gltf", target, "Mixamo")
    assert [clip["name"] for clip in clips] == ["mixamo.com"]
    worst = _worst_angles(default_rig(), clip_id, target, clips[0])
    assert max(worst.values()) < 4.0, worst


def test_a_cmu_style_bvh_lands_as_the_same_motion():
    target = _target("pet")
    clips = retarget_file(cmu_like_bvh(default_rig(), "dance_side").encode(), ".bvh", target, "dance")
    assert clips[0]["name"] == "dance" and clips[0]["warnings"] == []
    worst = _worst_angles(default_rig(), "dance_side", target, clips[0])
    assert max(worst.values()) < 4.0, worst


def test_every_animation_in_a_file_is_imported_and_step_keys_hold():
    document = mixamo_like_gltf(default_rig(), "wave")
    second = copy.deepcopy(document["animations"][0])
    second["name"] = "held"
    for sampler in second["samplers"]:
        sampler["interpolation"] = "STEP"
    document["animations"].append(second)
    clips = retarget_file(as_bytes(document), ".gltf", default_rig(), "pack")
    assert [clip["name"] for clip in clips] == ["mixamo.com", "held"]
    # Held keys never blend: every frame of the STEP clip is one of the linear clip's key frames.
    for bone in ("RightForeArm", "LeftUpLeg"):
        held, keyed = clips[1]["rotations"][bone], clips[0]["rotations"][bone]
        closest = np.abs(np.abs(held @ keyed.T) - 1.0).min(axis=1)
        assert float(closest.max()) < 1e-6, bone


def test_root_motion_is_removed_so_the_clip_plays_in_place():
    document = mixamo_like_gltf(default_rig(), "walk")
    hips = document["animations"][0]["channels"][-1]["sampler"]
    accessor = document["animations"][0]["samplers"][hips]["output"]
    view = document["bufferViews"][document["accessors"][accessor]["bufferView"]]
    blob = bytearray(base64.b64decode(document["buffers"][0]["uri"].split(",", 1)[1]))
    values = np.frombuffer(bytes(blob[view["byteOffset"]:view["byteOffset"] + view["byteLength"]]), dtype="<f4").reshape(-1, 3).copy()
    values[:, 1] -= np.linspace(0.0, 200.0, len(values))
    blob[view["byteOffset"]:view["byteOffset"] + view["byteLength"]] = values.astype("<f4").tobytes()
    document["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(bytes(blob)).decode()
    clip = retarget_file(as_bytes(document), ".gltf", default_rig(), "walk")[0]
    assert any("in place" in item for item in clip["warnings"])
    drift = clip["hips_translation"][-1] - clip["hips_translation"][0]
    assert abs(float(drift[0])) + abs(float(drift[2])) < 1e-6


def test_the_small_bvh_fixture_imports_and_names_what_it_skipped():
    clips = retarget_file((ROOT / "wave.bvh").read_bytes(), ".bvh", default_rig(), "wave")
    warnings = clips[0]["warnings"]
    assert "1 joints were not used (fingers, props or extra bones)" in warnings
    assert any(item.startswith("not in the file, kept at rest") for item in warnings)
    assert clips[0]["rotations"]["LeftArm"].shape[1] == 4


@pytest.mark.parametrize("name,bone", [
    ("mixamorig:LeftUpLeg", "LeftUpLeg"), ("mixamorig1:RightForeArm", "RightForeArm"), ("J_Bip_L_UpperArm", "LeftArm"),
    ("upperarm_l", "LeftArm"), ("calf_r", "RightLeg"), ("thigh.L", "LeftUpLeg"), ("shin.R", "RightLeg"),
    ("upper_arm.L", "LeftArm"), ("lShldr", "LeftArm"), ("rThigh", "RightUpLeg"), ("lCollar", "LeftShoulder"),
    ("LeftToeBase", "LeftToeBase"), ("ball_l", "LeftToeBase"), ("pelvis", "Hips"), ("Head", "Head"),
    ("LHipJoint", None), ("LeftHandIndex1", None), ("HeadTop_End", None),
    ("Bip01 L Thigh", "LeftUpLeg"), ("Bip001 Pelvis", "Hips"), ("Bip01 R Toe0", "RightToeBase"), ("Character1_LeftArm", "LeftArm"),
    ("Armature|Hips", "Hips"), ("lShldrBend", "LeftArm"), ("lForearmBend", "LeftForeArm"), ("rThighBend", "RightUpLeg"),
    ("neckLower", "Neck"), ("upperarm_twist_01_l", None), ("neck_01", "Neck"),
])
def test_joint_names_from_common_tools_map_to_the_standard_bones(name, bone):
    assert bone_for(name) == bone
    assert all(part == part.lower() for part in words(name))


def test_files_without_a_humanoid_or_with_external_buffers_are_refused():
    document = {"asset": {"version": "2.0"}, "nodes": [{"name": "Box"}], "animations": []}
    with pytest.raises(ValueError, match="no animation"):
        retarget_file(json.dumps(document).encode(), ".gltf", default_rig())
    document = mixamo_like_gltf(default_rig(), "idle")
    document["buffers"][0]["uri"] = "anim.bin"
    with pytest.raises(ValueError, match="export it as .glb"):
        retarget_file(as_bytes(document), ".gltf", default_rig())
    document = mixamo_like_gltf(default_rig(), "idle")
    for node in document["nodes"]:
        node["name"] = "bone"
    with pytest.raises(ValueError, match="no humanoid skeleton"):
        retarget_file(as_bytes(document), ".gltf", default_rig())
    with pytest.raises(ValueError, match=".bvh, .glb or .gltf"):
        retarget_file(b"x", ".fbx", default_rig())


def _bone_axes(rig, clip, bone, axis):
    local = np.stack([clip["rotations"].get(name, np.tile(rig.bones[index]["rotation"], (len(clip["times"]), 1)))
                      for index, name in enumerate(BONE_NAMES)], axis=1)
    worlds = batch_worlds(rig.bones, local, clip["hips_translation"])
    direction = worlds[:, BONE_BY_NAME[bone], :3, :3] @ np.asarray(axis, dtype=float)
    return direction / np.linalg.norm(direction, axis=1, keepdims=True)


def test_an_a_pose_source_keeps_hands_and_feet_straight_on_a_t_pose_body():
    source_glb, _sidecar = rig_humanoid(as_glb(body("human_a")), ["wave", "walk"], 120)
    source = stored_rig(source_glb)
    target = _target("human_t")
    imported = retarget_file(source_glb, ".glb", target, "from A")
    originals = {clip["id"]: clip for clip in clip_library(120, ["wave", "walk"], source)}
    for clip, clip_id in zip(imported, ("wave", "walk")):
        for bone, axis in (("LeftHand", [1, 0, 0]), ("RightHand", [-1, 0, 0]), ("LeftForeArm", [1, 0, 0]), ("LeftFoot", [0, 0, 1])):
            ours = _bone_axes(target, clip, bone, axis)
            theirs = _bone_axes(source, originals[clip_id], bone, axis)
            count = min(len(ours), len(theirs))
            worst = float(np.degrees(np.arccos(np.clip(np.sum(ours[:count] * theirs[:count], axis=1), -1.0, 1.0))).max())
            assert worst < 5.0, (clip_id, bone, worst)


def test_files_saved_with_a_byte_order_mark_still_import():
    bvh = (ROOT / "wave.bvh").read_bytes()
    plain = retarget_file(bvh, ".bvh", default_rig(), "wave")
    marked = retarget_file(b"\xef\xbb\xbf" + bvh, ".bvh", default_rig(), "wave")
    assert np.allclose(plain[0]["rotations"]["LeftArm"], marked[0]["rotations"]["LeftArm"])
    gltf = as_bytes(mixamo_like_gltf(default_rig(), "wave"))
    assert retarget_file(b"\xef\xbb\xbf" + gltf, ".gltf", default_rig(), "wave")[0]["rotations"]


def test_a_mesh_named_like_a_bone_does_not_replace_the_skin_joint():
    document = mixamo_like_gltf(default_rig(), "wave")
    bones = list(range(1, len(document["nodes"])))
    document["nodes"].append({"name": "Head", "mesh": 0})  # a shallow mesh node with a bone's name
    document["nodes"][0]["children"].append(len(document["nodes"]) - 1)
    document["skins"] = [{"joints": bones}]
    target = _target("pet")
    clips = retarget_file(as_bytes(document), ".gltf", target, "wave")
    worst = _worst_angles(default_rig(), "wave", target, clips[0])
    assert max(worst.values()) < 4.0, worst
    plain = retarget_file(as_bytes(mixamo_like_gltf(default_rig(), "wave")), ".gltf", target, "wave")
    assert np.allclose(clips[0]["rotations"]["Head"], plain[0]["rotations"]["Head"], atol=1e-6)


def test_a_jump_keeps_its_height_on_the_same_body_even_without_toe_bones():
    rig = default_rig()
    motion = canonical_motion(rig, "jump")
    document = mixamo_like_gltf(rig, "jump")
    for node in document["nodes"]:
        if "Toe" in node["name"]:
            node["name"] = "Extra"  # a source measured down to its ankles only
    clips = retarget_file(as_bytes(document), ".gltf", rig, "jump")
    source = float(np.ptp(motion["positions"][:, 0, 1]))
    ours = float(np.ptp(clips[0]["hips_translation"][:, 1]))
    assert abs(ours - source) < source * 0.02, (ours, source)

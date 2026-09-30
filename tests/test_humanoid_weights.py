"""Skin weights: unit sum, symmetry, and a posed arm that leaves the other side still."""
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES, LEFT_ARM_BONES, LEFT_LEG_BONES, RIGHT_ARM_BONES, RIGHT_LEG_BONES
from services.humanoid_rig.skeleton import axis_quaternion, build_skeleton, skin_vertices, world_matrices
from services.humanoid_rig.weights import compute_weights, dominant_distance
from services.procedural_3d.compose import compose_glb
from services.procedural_3d.glb_container import parse_glb_container

ROOT = Path(__file__).parents[1] / "tests" / "fixtures" / "humanoid_rig"
PAIRS = tuple(zip(LEFT_ARM_BONES + LEFT_LEG_BONES, RIGHT_ARM_BONES + RIGHT_LEG_BONES))


def _positions(data):
    container = parse_glb_container(data, max_chunks=2, max_json_bytes=200_000)
    document = json.loads(container.json_bytes)
    view = document["bufferViews"][0]
    accessor = document["accessors"][0]
    count = accessor["count"]
    offset = view.get("byteOffset", 0)
    values = struct.unpack_from(f"<{count * 3}f", container.bin_bytes, offset)
    return np.asarray(values, dtype=np.float64).reshape(-1, 3)


def _cloud(name):
    fixture = json.loads((ROOT / f"{name}.json").read_text())
    return _positions(compose_glb(fixture["pieces"], name))


def _weighted(name):
    cloud = _cloud(name)
    found = detect_landmarks(cloud)
    skeleton = build_skeleton(found["points"], found["height"], found["y_min"])
    joints, weights = compute_weights(cloud, None, skeleton)
    return cloud, found, skeleton, joints, weights


@pytest.mark.parametrize("name", ("robot", "pet", "a_pose"))
def test_weights_are_normalized_and_close_to_their_bone(name):
    cloud, found, skeleton, joints, weights = _weighted(name)
    assert joints.shape == (len(cloud), 4)
    assert weights.shape == (len(cloud), 4)
    assert joints.dtype == np.uint16
    assert np.allclose(weights.sum(axis=1), 1.0, atol=1e-5)
    assert np.all(weights >= -1e-8)
    assert np.all(joints < len(BONE_NAMES))
    distance = dominant_distance(cloud, joints, weights, skeleton)
    assert float(distance.max()) < found["height"] * 0.35


def test_symmetric_robot_mirrors_left_and_right_within_five_percent():
    cloud, _found, _skeleton, joints, weights = _weighted("robot")
    center = 0.0
    mirrored = cloud.copy()
    mirrored[:, 0] = 2 * center - cloud[:, 0]
    # Compose splits every corner, so match the welded position, not the index.
    rounded = np.round(cloud, 4)
    mirror_key = np.round(mirrored, 4)
    lookup = {tuple(row): index for index, row in enumerate(rounded)}
    errors = []
    dense = np.zeros((len(cloud), len(BONE_NAMES)))
    np.add.at(dense, (np.repeat(np.arange(len(cloud)), 4), joints.reshape(-1)), weights.reshape(-1))
    for index, key in enumerate(mirror_key):
        partner = lookup.get(tuple(key))
        if partner is None or partner == index:
            continue
        for left, right in PAIRS:
            errors.append(abs(dense[index, BONE_BY_NAME[left]] - dense[partner, BONE_BY_NAME[right]]))
    assert errors
    assert float(np.mean(errors)) < 0.05


def test_right_arm_pose_leaves_the_left_torso_still():
    cloud, found, skeleton, joints, weights = _weighted("robot")
    bind = world_matrices(skeleton["bones"])
    posed = world_matrices(skeleton["bones"], {"RightArm": axis_quaternion(np.array([0.0, 0.0, 1.0]), 90.0)})
    moved = skin_vertices(cloud, joints, weights, bind, posed)
    delta = np.linalg.norm(moved - cloud, axis=1)
    height = found["height"]
    hips_y = found["points"]["crotch"][1]
    shoulder_y = found["points"]["left_shoulder"][1]
    left_torso = (
        (cloud[:, 0] > 0.02)
        & (cloud[:, 0] < 0.20)
        & (cloud[:, 1] > hips_y)
        & (cloud[:, 1] < shoulder_y + 0.02)
        & (np.abs(cloud[:, 2]) < 0.12)
    )
    right_hand = cloud[:, 0] < -0.95
    assert int(left_torso.sum()) > 20
    assert int(right_hand.sum()) > 8
    assert float(delta[left_torso].max()) < 0.02
    assert float(delta[right_hand].min()) > 0.20
    rest = skin_vertices(cloud, joints, weights, bind, bind)
    assert float(np.linalg.norm(rest - cloud, axis=1).max()) < 1e-6


def test_knee_bend_moves_the_shin_and_leaves_the_thigh_and_pelvis():
    cloud, found, skeleton, joints, weights = _weighted("robot")
    bind = world_matrices(skeleton["bones"])
    posed = world_matrices(skeleton["bones"], {"LeftLeg": axis_quaternion(np.array([1.0, 0.0, 0.0]), 70.0)})
    moved = skin_vertices(cloud, joints, weights, bind, posed)
    delta = np.linalg.norm(moved - cloud, axis=1)
    hip_y = found["points"]["left_hip"][1]
    knee_y = found["points"]["left_knee"][1]
    thigh = (cloud[:, 0] > 0.10) & (cloud[:, 1] > knee_y + 0.08) & (cloud[:, 1] < hip_y + 0.01)
    pelvis = (cloud[:, 1] > hip_y + 0.04) & (np.abs(cloud[:, 0]) < 0.24)
    shin = (cloud[:, 0] > 0.10) & (cloud[:, 1] > 0.08) & (cloud[:, 1] < knee_y - 0.04)
    assert int(thigh.sum()) > 8 and int(pelvis.sum()) > 8 and int(shin.sum()) > 8
    assert float(delta[thigh].max()) < 0.02
    assert float(delta[pelvis].max()) < 0.02
    assert float(delta[shin].min()) > 0.05


def test_opposite_arm_and_leg_do_not_drag_the_other_limb():
    cloud, found, skeleton, joints, weights = _weighted("robot")
    bind = world_matrices(skeleton["bones"])
    height = found["height"]
    cases = (
        ("LeftArm", np.array([0.0, 0.0, 1.0]), 80.0, cloud[:, 0] < -0.30),
        ("RightUpLeg", np.array([1.0, 0.0, 0.0]), -40.0, cloud[:, 0] > 0.30),
    )
    for bone, axis, degrees, still in cases:
        posed = world_matrices(skeleton["bones"], {bone: axis_quaternion(axis, degrees)})
        moved = skin_vertices(cloud, joints, weights, bind, posed)
        delta = np.linalg.norm(moved - cloud, axis=1)
        assert int(still.sum()) > 20
        assert float(delta[still].max()) < 0.02, bone
        assert float(delta.max()) > height * 0.05, bone

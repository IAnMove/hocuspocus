"""Standard Mixamo skeleton placed on the compose humanoids."""
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.names import BONE_NAMES, BONE_PARENTS, NORMAL_HEIGHT
from services.humanoid_rig.skeleton import build_skeleton, world_matrices
from services.procedural_3d.compose import compose_glb
from services.procedural_3d.glb_container import parse_glb_container

ROOT = Path(__file__).parents[1] / "tests" / "fixtures" / "humanoid_rig"
VALID = ("robot", "pet", "a_pose")
LIMB = {
    "LeftArm": "left_shoulder",
    "RightArm": "right_shoulder",
    "LeftForeArm": "left_elbow",
    "RightForeArm": "right_elbow",
    "LeftHand": "left_hand",
    "RightHand": "right_hand",
    "LeftUpLeg": "left_hip",
    "RightUpLeg": "right_hip",
    "LeftLeg": "left_knee",
    "RightLeg": "right_knee",
    "LeftFoot": "left_foot",
    "RightFoot": "right_foot",
    "HeadTop_End": "crown",
}


def _load(name):
    return json.loads((ROOT / f"{name}.json").read_text())


def _positions(data):
    container = parse_glb_container(data, max_chunks=2, max_json_bytes=200_000)
    document = json.loads(container.json_bytes)
    view = document["bufferViews"][0]
    accessor = document["accessors"][0]
    count = accessor["count"]
    offset = view.get("byteOffset", 0)
    values = struct.unpack_from(f"<{count * 3}f", container.bin_bytes, offset)
    return np.asarray(values, dtype=np.float64).reshape(-1, 3)


def _rig(name):
    fixture = _load(name)
    cloud = _positions(compose_glb(fixture["pieces"], name))
    found = detect_landmarks(cloud)
    skeleton = build_skeleton(found["points"], found["height"], found["y_min"])
    return fixture, cloud, found, skeleton


@pytest.mark.parametrize("name", VALID)
def test_hierarchy_names_and_parents(name):
    _fixture, _cloud, _found, skeleton = _rig(name)
    bones = skeleton["bones"]
    assert [bone["name"] for bone in bones] == list(BONE_NAMES)
    assert [(bone["name"], bone["parent"]) for bone in bones] == list(BONE_PARENTS)
    assert all(not bone["name"].startswith("mixamorig") for bone in bones)
    assert len(bones) == 25


@pytest.mark.parametrize("name", VALID)
def test_hips_scale_normalizes_height_and_left_is_positive_x(name):
    _fixture, _cloud, found, skeleton = _rig(name)
    height = found["height"]
    assert skeleton["scale"] == pytest.approx(height / NORMAL_HEIGHT)
    hips = skeleton["bones"][0]
    assert hips["name"] == "Hips"
    assert np.allclose(hips["scale"], height / NORMAL_HEIGHT)
    assert np.allclose(hips["translation"], found["points"]["crotch"])
    worlds = {bone["name"]: skeleton["world"][bone["name"]] for bone in skeleton["bones"]}
    assert worlds["LeftHand"][0] > worlds["Hips"][0]
    assert worlds["RightHand"][0] < worlds["Hips"][0]
    assert worlds["LeftFoot"][2] > worlds["LeftUpLeg"][2]


@pytest.mark.parametrize("name", VALID)
def test_limb_joints_sit_on_the_landmarks(name):
    _fixture, _cloud, found, skeleton = _rig(name)
    height = found["height"]
    for bone, landmark in LIMB.items():
        error = np.linalg.norm(skeleton["world"][bone] - np.asarray(found["points"][landmark]))
        assert error / height < 1e-6, bone
    assert np.allclose(skeleton["world"]["Hips"], found["points"]["crotch"])


@pytest.mark.parametrize("name", VALID)
def test_rest_world_matrices_recover_joint_positions(name):
    _fixture, _cloud, _found, skeleton = _rig(name)
    matrices = world_matrices(skeleton["bones"])
    for bone, matrix in zip(skeleton["bones"], matrices):
        assert np.allclose(matrix[:3, 3], skeleton["world"][bone["name"]], atol=1e-8)
        assert np.allclose(bone["rotation"], [0, 0, 0, 1])

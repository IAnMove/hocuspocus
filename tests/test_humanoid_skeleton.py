"""Standard Mixamo skeleton: names, rest placement and canonical T-pose frames."""
import numpy as np
import pytest

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.names import BONE_NAMES, BONE_PARENTS, NORMAL_HEIGHT
from services.humanoid_rig.skeleton import build_skeleton, world_matrices
from tests.humanoid_bodies import body, transformed
from tests.humanoid_skinning import batch_worlds


def _skeleton(item):
    found = detect_landmarks(item["positions"], item["indices"])
    return found, build_skeleton(found["points"], found["height"], found["y_min"], found["facing"], found["head_region"])


def _direction(worlds, start, end):
    delta = worlds[BONE_NAMES.index(end)][:3, 3] - worlds[BONE_NAMES.index(start)][:3, 3]
    return delta / np.linalg.norm(delta)


@pytest.mark.parametrize("kind", ("human_t", "human_a", "pet"))
def test_hierarchy_names_and_hips_scale(kind):
    found, skeleton = _skeleton(body(kind))
    bones = skeleton["bones"]
    assert [(bone["name"], bone["parent"]) for bone in bones] == list(BONE_PARENTS)
    assert all(not bone["name"].startswith("mixamorig") for bone in bones)
    assert np.allclose(bones[0]["scale"], found["height"] / NORMAL_HEIGHT)
    assert skeleton["world"]["LeftHand"][0] > skeleton["world"]["Hips"][0] > skeleton["world"]["RightHand"][0]
    assert skeleton["world"]["LeftToe_End"][2] > skeleton["world"]["LeftFoot"][2]


@pytest.mark.parametrize("kind", ("human_t", "human_a", "alien"))
def test_rest_matrices_put_every_joint_on_its_place(kind):
    _found, skeleton = _skeleton(body(kind))
    for bone, matrix in zip(skeleton["bones"], world_matrices(skeleton["bones"])):
        assert np.allclose(matrix[:3, 3], skeleton["world"][bone["name"]], atol=1e-7), bone["name"]


def test_an_a_pose_rests_with_arms_down_and_identity_is_the_t_pose():
    _found, skeleton = _skeleton(body("human_a"))
    rest = world_matrices(skeleton["bones"])
    assert _direction(rest, "LeftArm", "LeftForeArm")[1] < -0.5
    canonical = np.tile(rot.IDENTITY, (1, len(BONE_NAMES), 1))
    canonical[0, 0] = skeleton["bones"][0]["rotation"]
    posed = batch_worlds(skeleton["bones"], canonical)[0]
    for start, end, axis in (("LeftArm", "LeftForeArm", [1, 0, 0]), ("LeftForeArm", "LeftHand", [1, 0, 0]),
                             ("RightArm", "RightForeArm", [-1, 0, 0]), ("RightForeArm", "RightHand", [-1, 0, 0])):
        assert float(_direction(posed, start, end) @ np.array(axis, dtype=float)) > 0.9998, start
    for side in ("Left", "Right"):
        thigh = _direction(posed, f"{side}UpLeg", f"{side}Leg")
        shin = _direction(posed, f"{side}Leg", f"{side}Foot")
        assert abs(thigh[2]) < 1e-6 and thigh[1] < -0.9
        assert float(thigh @ shin) > 0.9999


def test_a_body_facing_back_gets_a_turned_skeleton():
    _found, skeleton = _skeleton(transformed(body("human_t"), yaw_degrees=180.0))
    assert skeleton["facing"] == -1
    canonical = np.tile(rot.IDENTITY, (1, len(BONE_NAMES), 1))
    canonical[0, 0] = skeleton["bones"][0]["rotation"]
    posed = batch_worlds(skeleton["bones"], canonical)[0]
    assert _direction(posed, "LeftArm", "LeftForeArm")[0] < -0.99
    assert _direction(posed, "LeftFoot", "LeftToe_End")[2] < 0.0

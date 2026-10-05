"""Skin weights: normalized, symmetric, and a posed limb leaves the rest of the body still."""
import numpy as np
import pytest
from scipy.spatial import cKDTree

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES
from services.humanoid_rig.skeleton import build_skeleton, world_matrices
from services.humanoid_rig.weights import compute_weights, dominant_distance
from tests.humanoid_bodies import body
from tests.humanoid_skinning import skin_vertices


def _weighted(kind):
    item, skeleton, joints, weights, _found = _draped(kind)
    return item, skeleton, joints, weights


def _draped(kind):
    item = body(kind)
    found = detect_landmarks(item["positions"], item["indices"])
    skeleton = build_skeleton(found["points"], found["height"], found["y_min"], found["facing"], found["head_region"], found["base"],
                              found["robe"])
    joints, weights = compute_weights(item["positions"], item["indices"], skeleton, found["cloth"])
    return item, skeleton, joints, weights, found


def _skinned(skeleton, joints, weights, points, bone, degrees, axis):
    rest = world_matrices(skeleton["bones"])
    local = skeleton["bones"][BONE_BY_NAME[bone]]["rotation"]
    posed = world_matrices(skeleton["bones"], {bone: rot.multiply(local, rot.axis_angle(axis, degrees))})
    return skin_vertices(points, joints, weights, rest, posed)


def _posed(skeleton, joints, weights, points, bone, degrees, axis):
    return np.linalg.norm(_skinned(skeleton, joints, weights, points, bone, degrees, axis) - points, axis=1)


def _stretch(points, moved, indices, chosen):
    """Largest length ratio, posed over rest, of the mesh edges between ``chosen`` vertices."""
    edges = np.concatenate((indices[:, [0, 1]], indices[:, [1, 2]], indices[:, [2, 0]]))
    edges = edges[chosen[edges[:, 0]] & chosen[edges[:, 1]]]
    rest = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
    posed = np.linalg.norm(moved[edges[:, 0]] - moved[edges[:, 1]], axis=1)
    return float((posed[rest > 1e-6] / rest[rest > 1e-6]).max())


def _dominant(joints, weights):
    return joints[np.arange(len(joints)), np.argmax(weights, axis=1)]


@pytest.mark.parametrize("kind", ("human_t", "pet", "alien"))
def test_weights_are_normalized_and_near_their_bone(kind):
    item, skeleton, joints, weights = _weighted(kind)
    assert joints.shape == weights.shape == (len(item["positions"]), 4)
    assert joints.dtype == np.uint16
    assert np.allclose(weights.sum(axis=1), 1.0, atol=1e-6) and np.all(weights >= 0.0)
    ends = [BONE_BY_NAME[name] for name in BONE_NAMES if name.endswith("_End")]
    assert not np.any(np.isin(joints[weights > 0], ends))
    body_part = _dominant(joints, weights) != BONE_BY_NAME["Head"]
    assert float(dominant_distance(item["positions"], joints, weights, skeleton)[body_part].max()) < skeleton["height"] * 0.35
    rest = world_matrices(skeleton["bones"])
    assert np.abs(skin_vertices(item["positions"], joints, weights, rest, rest) - item["positions"]).max() < 1e-6


def test_a_symmetric_body_gets_mirrored_weights():
    item, _skeleton, joints, weights = _weighted("human_t")
    points = item["positions"]
    distance, partner = cKDTree(points).query(points * np.array([-1.0, 1.0, 1.0]))
    matched = distance < 1e-4
    assert matched.mean() > 0.95
    dense = np.zeros((len(points), len(BONE_NAMES)))
    np.add.at(dense, (np.repeat(np.arange(len(points)), 4), joints.reshape(-1).astype(int)), weights.reshape(-1))
    mirror = [BONE_BY_NAME[name.replace("Left", "@").replace("Right", "Left").replace("@", "Right")] for name in BONE_NAMES]
    moved = 0.5 * np.abs(dense[matched][:, mirror] - dense[partner[matched]]).sum(axis=1)
    assert float(moved.mean()) < 0.04


def test_raising_an_arm_leaves_the_big_head_and_the_other_side_still():
    item, skeleton, joints, weights = _weighted("pet")
    points = item["positions"]
    moved = _posed(skeleton, joints, weights, points, "RightArm", -70.0, [0.0, 0.0, 1.0])
    dominant = _dominant(joints, weights)
    head = (dominant == BONE_BY_NAME["Head"]) & (points[:, 1] > skeleton["head_region"]["y"])
    left_arm = np.isin(dominant, [BONE_BY_NAME[name] for name in ("LeftArm", "LeftForeArm", "LeftHand")])
    right_hand = dominant == BONE_BY_NAME["RightHand"]
    assert head.sum() > 200 and left_arm.sum() > 50
    assert float(moved[head].max()) < 0.002
    assert float(moved[left_arm].max()) < 0.002
    assert float(moved[right_hand].min()) > skeleton["height"] * 0.1


def test_a_knee_bend_moves_the_shin_but_not_the_thigh_or_the_other_leg():
    item, skeleton, joints, weights = _weighted("human_t")
    points = item["positions"]
    moved = _posed(skeleton, joints, weights, points, "LeftLeg", 70.0, [1.0, 0.0, 0.0])
    knee, hip = skeleton["world"]["LeftLeg"], skeleton["world"]["LeftUpLeg"]
    thigh = (points[:, 0] > 0.04) & (points[:, 1] > knee[1] + 0.1) & (points[:, 1] < hip[1] - 0.05)
    other = points[:, 0] < -0.04
    shin = (points[:, 0] > 0.04) & (points[:, 1] < knee[1] - 0.08) & (points[:, 1] > 0.12)
    assert thigh.sum() > 50 and other.sum() > 50 and shin.sum() > 50
    assert float(moved[thigh].max()) < 0.01
    assert float(moved[other & (points[:, 1] < hip[1])].max()) < 0.001
    assert float(moved[shin].min()) > 0.1


def test_a_thigh_swing_does_not_drag_the_other_leg():
    item, skeleton, joints, weights = _weighted("human_a")
    points = item["positions"]
    moved = _posed(skeleton, joints, weights, points, "RightUpLeg", -40.0, [1.0, 0.0, 0.0])
    left_leg = (points[:, 0] > 0.05) & (points[:, 1] < skeleton["world"]["LeftUpLeg"][1] - 0.05)
    assert left_leg.sum() > 50
    assert float(moved[left_leg].max()) < 0.005


@pytest.mark.parametrize("kind", ("robe", "back_cape"))
def test_a_robe_or_a_cape_over_the_legs_hangs_from_the_hips(kind):
    item, skeleton, joints, weights, found = _draped(kind)
    points, indices = item["positions"], item["indices"]
    assert np.allclose(weights.sum(axis=1), 1.0, atol=1e-6)
    world = skeleton["world"]
    bottom = skeleton["robe"]["hem"] if skeleton["robe"] else world["LeftFoot"][1]
    hanging = (points[:, 1] > bottom + 0.03) & (points[:, 1] < world["LeftUpLeg"][1] - 0.03)
    if kind == "back_cape":
        hanging &= found["cloth"]
    assert hanging.sum() > 1000
    stride = _skinned(skeleton, joints, weights, points, "LeftUpLeg", 40.0, [1.0, 0.0, 0.0])
    # The plain surface weights split the cloth between the thighs and stretch an edge 10 to 14 times.
    assert _stretch(points, stride, indices, hanging) < 3.0
    assert float(np.linalg.norm(stride - points, axis=1)[hanging].mean()) > 0.03, "the cloth follows the stride in part"
    knee = _posed(skeleton, joints, weights, points, "LeftLeg", 70.0, [1.0, 0.0, 0.0])
    assert float(knee[hanging].max()) < 0.005, "a bent knee does not fold the cloth"
    foot = (points[:, 1] < bottom - 0.02) & (points[:, 0] * skeleton["facing"] > 0.04)
    assert float(knee[foot].min()) > 0.05, "the foot under the hem still follows the knee"


def test_raising_an_arm_under_a_cape_lifts_its_side_only():
    item, skeleton, joints, weights, found = _draped("cape")
    points, indices = item["positions"], item["indices"]
    cloth = found["cloth"]
    raised = _skinned(skeleton, joints, weights, points, "LeftArm", -70.0, [0.0, 0.0, 1.0])
    moved = np.linalg.norm(raised - points, axis=1)
    near, far = cloth & (points[:, 0] > 0.25), cloth & (points[:, 0] < -0.05)
    assert near.sum() > 200 and far.sum() > 200
    assert float(moved[far].max()) < 0.002
    assert float(moved[near].mean()) > 0.05, "the cape over the upper arm rises with it"
    assert _stretch(points, raised, indices, cloth & (points[:, 0] > 0.05)) < 2.0

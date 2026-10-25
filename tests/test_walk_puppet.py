"""The walk puppet cuts one drawing into a cycle (services/walk_puppet.py).

The twelve hashes are the unsplit cutter on a stick figure. A split that moves a pixel fails here.
Joints are passed in, so the pose model is never asked.
"""
import hashlib

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from services.walk_puppet import WalkPuppetError, build, cut_groups, limb_mesh

# SHA256 of each frame, then the lowest opaque row. The two rows differ by one pixel.
FRAMES = (
    ("49bec58543513bd54b0c06a406daef5296d3687f8a5db3d42490b973e5df4ed9", 412),
    ("1855ed771b632e344f1c528e31bda27c7a690567a93ad4e0ee478925e680a509", 412),
    ("1a791605a320e648888e437a4bc0f620ea7c4caf2f2a3377b85a9ee123448437", 413),
    ("2fcdb1571c0031acbaff74dc4cf06f5c1105cfbb080ff68adba5b358ee816ed1", 413),
    ("b95b7dcc81c4d1b2a87d899b470d0efa33c47662f12f09eda3a0e9388807071d", 413),
    ("7e3dddcdac825305dc6a32b2c4e1ff2d2ca721bd951f60eb42e5a4794f647af1", 413),
    ("f33ae01d1a201b37a99685437f3169e8a8acf66fcb000a1fec6945e9ac7941c7", 413),
    ("63b73e922ce566a9f325497fcf67e9595426a5f76f812c0df0d33a3284709096", 413),
    ("7b0e2487043996f6883e99b9ea5d076c738d1ff7aeb84dccf292d0ca6df5e744", 413),
    ("9731a37ec09dcd439b14e7aedcacf639d90e5f887f452003c389a4443b76f779", 413),
    ("461693781823315d5c09ac8752497f8154d07d7ee4761f3e1e9a00367f98c2f4", 413),
    ("70f0047daecc7e0f8b2c8413801dd38c60371d4b30061d0582966f826d557959", 413),
)


def _joints() -> dict[str, np.ndarray]:
    return {
        "nose": np.array([78.0, 18.0]), "neck": np.array([80.0, 34.0]),
        "r_shoulder": np.array([68.0, 40.0]), "r_elbow": np.array([40.0, 72.0]), "r_wrist": np.array([22.0, 104.0]),
        "l_shoulder": np.array([96.0, 42.0]), "l_elbow": np.array([124.0, 74.0]), "l_wrist": np.array([142.0, 106.0]),
        "r_hip": np.array([72.0, 108.0]), "r_knee": np.array([56.0, 156.0]), "r_ankle": np.array([44.0, 200.0]),
        "l_hip": np.array([90.0, 110.0]), "l_knee": np.array([108.0, 158.0]), "l_ankle": np.array([120.0, 202.0]),
    }


def _figure() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """A 220×160 stick figure: thickness 8, head circle at (78, 16) radius 14."""
    rgba = np.zeros((220, 160, 4), np.uint8)
    joints = _joints()

    def bone(a: str, b: str, color: tuple[int, int, int, int]) -> None:
        cv2.line(rgba, tuple(np.round(joints[a]).astype(int)), tuple(np.round(joints[b]).astype(int)), color, 8)

    bone("neck", "r_shoulder", (180, 140, 90, 255))
    bone("r_shoulder", "r_elbow", (180, 140, 90, 255))
    bone("r_elbow", "r_wrist", (180, 140, 90, 255))
    bone("neck", "l_shoulder", (160, 120, 80, 255))
    bone("l_shoulder", "l_elbow", (160, 120, 80, 255))
    bone("l_elbow", "l_wrist", (160, 120, 80, 255))
    bone("neck", "r_hip", (40, 40, 140, 255))
    bone("neck", "l_hip", (40, 40, 140, 255))
    bone("r_hip", "r_knee", (30, 30, 120, 255))
    bone("r_knee", "r_ankle", (30, 30, 120, 255))
    bone("l_hip", "l_knee", (20, 20, 90, 255))
    bone("l_knee", "l_ankle", (20, 20, 90, 255))
    cv2.circle(rgba, (78, 16), 14, (200, 160, 120, 255), -1)
    return rgba, joints


def test_the_cycle_matches_the_unsplit_frames_and_the_feet_stay_within_one_pixel():
    rgba, joints = _figure()
    frames, info = build(rgba, "side", 12, None, joints)
    assert frames[0].shape == (440, 320, 4)
    assert abs(info["start"] - 0.4583333333333333) < 1e-9
    lows = []
    for frame, (digest, low) in zip(frames, FRAMES):
        assert hashlib.sha256(frame.tobytes()).hexdigest() == digest
        rows = np.nonzero(frame[..., 3] > 10)[0]
        assert int(rows.max()) == low
        lows.append(low)
    assert max(lows) - min(lows) <= 1


def test_the_cut_keeps_the_two_arms_and_the_two_legs_apart():
    rgba, joints = _figure()
    parts = cut_groups(rgba, joints, None)
    assert parts["skirt"] is None
    for name in ("arm_r", "arm_l", "leg_r", "leg_l", "head", "torso"):
        assert int((parts[name][..., 3] > 0).sum()) >= 40
    right = np.nonzero(parts["arm_r"][..., 3] > 0)[1].mean()
    left = np.nonzero(parts["arm_l"][..., 3] > 0)[1].mean()
    assert right < left


def test_a_short_bottom_is_a_skirt_and_a_long_one_is_trousers():
    rgba, joints = _figure()
    skirt = np.zeros_like(rgba)
    skirt[100:150, 60:110] = (220, 20, 60, 255)
    cut = cut_groups(rgba, joints, {"bottomwear": skirt})
    assert cut["skirt"] is not None
    assert int((cut["torso"][..., 0] > 180).sum()) > 50

    trousers = np.zeros_like(rgba)
    trousers[100:210, 50:130] = (20, 40, 160, 255)
    cut = cut_groups(rgba, joints, {"bottomwear": trousers})
    assert cut["skirt"] is None
    leg_pixels = int((cut["leg_r"][..., 2] > 100).sum()) + int((cut["leg_l"][..., 2] > 100).sum())
    assert leg_pixels > 50


def test_limb_mesh_weights_sum_to_one():
    picture = np.zeros((80, 40, 4), np.uint8)
    picture[10:70, 10:30, 3] = 255
    picture[10:70, 10:30, :3] = (20, 20, 90)
    chain = [np.array([20.0, 10.0]), np.array([20.0, 40.0]), np.array([20.0, 70.0])]
    weights = limb_mesh(picture, chain, 12.0, 4.0)["weights"]
    assert len(weights) > 0 and weights.shape[1] == 3
    assert np.allclose(weights.sum(axis=1), 1.0)


def test_a_drawing_with_no_separated_arm_is_refused_and_builds_nothing():
    rgba = np.zeros((40, 40, 4), np.uint8)
    rgba[5:35, 18:22] = (40, 40, 140, 255)
    joints = _joints()
    try:
        build(rgba, "side", 4, None, joints)
    except WalkPuppetError as error:
        assert "no arm" in str(error)
    else:
        raise AssertionError("a single stroke is not a walk")

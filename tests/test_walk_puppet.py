"""The walk puppet cuts one drawing into a cycle (services/walk_puppet.py).

Joints are passed in, so the pose model is never asked. Exact pixels depend on
the OpenCV build (CI is 4.12, a local app env may be 4.13), so the cycle is
locked by shape, start phase, determinism and the planted foot, not by a hash.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from services.walk_puppet import WalkPuppetError, build, cut_groups, limb_mesh


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


def test_the_cycle_is_deterministic_and_the_feet_stay_within_one_pixel():
    rgba, joints = _figure()
    frames, info = build(rgba, "side", 12, None, joints)
    again, _info = build(rgba, "side", 12, None, joints)
    assert len(frames) == 12 and frames[0].shape == (440, 320, 4)
    assert abs(info["start"] - 0.4583333333333333) < 1e-9
    lows = []
    for frame, repeat in zip(frames, again):
        assert np.array_equal(frame, repeat)
        rows = np.nonzero(frame[..., 3] > 10)[0]
        assert rows.size > 1000
        lows.append(int(rows.max()))
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


def test_garment_layers_take_the_local_gpu_lane(tmp_path, monkeypatch):
    """See-through for the puppet uses the same GPU lane as the face layers."""
    from PIL import Image
    from services import resource_scheduler
    from services.walk_puppet_method import garment_layers
    acquired: list[str] = []
    real = resource_scheduler.coordinator.acquire

    def spy(lane, *args, **kwargs):
        acquired.append(lane.key)
        return real(lane, *args, **kwargs)

    monkeypatch.setattr(resource_scheduler.coordinator, "acquire", spy)
    rgba = np.zeros((8, 8, 4), np.uint8)
    rgba[..., 3] = 255

    def decompose(image, label):
        assert isinstance(image, Image.Image) and label == "puppet"
        return {"images": {}}

    _layers, used = garment_layers(
        rgba, str(tmp_path), "hero", "cast", installed_fn=lambda: True, decompose=decompose)
    assert acquired == ["local_gpu:0"]
    assert used is True


def test_a_half_written_layer_folder_is_not_a_cache(tmp_path):
    from PIL import Image
    from services.walk_puppet_method import _cached_layers
    folder = tmp_path / "layers"
    folder.mkdir()
    Image.new("RGBA", (4, 4), (1, 2, 3, 255)).save(folder / "topwear.png")
    assert _cached_layers(str(folder)) is None


def test_finished_garment_layers_are_marked_complete(tmp_path):
    from PIL import Image
    from services.walk_puppet_method import _cached_layers, garment_layers
    image = Image.new("RGBA", (4, 4), (9, 8, 7, 255))

    def decompose(_image, label):
        assert label == "puppet"
        return {"images": {"topwear": image}}

    garment_layers(np.array(image), str(tmp_path), "hero", "cast", installed_fn=lambda: True, decompose=decompose)
    folder = next((tmp_path / "puppet-layers").iterdir())
    assert (folder / ".complete").is_file()
    cached = _cached_layers(str(folder))
    assert cached is not None and "topwear" in cached

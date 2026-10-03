"""A walk along a path keeps every planted foot still in the world."""
import numpy as np
import pytest

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.clips import default_rig
from services.humanoid_rig.errors import InvalidInput
from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES
from services.humanoid_rig.path_walk import _Route, _Steps, _eased_progress, _points, path_clip
from services.humanoid_rig.clips import rig_for_skeleton
from services.humanoid_rig.skeleton import build_skeleton
from tests.humanoid_bodies import body


def _rig(kind):
    if kind == "default":
        return default_rig()
    item = body(kind)
    found = detect_landmarks(item["positions"], item["indices"])
    return rig_for_skeleton(build_skeleton(found["points"], found["height"], found["y_min"], found["facing"], found["head_region"]))


def _motion(rig, clip):
    count = len(clip["times"])
    local = np.stack([clip["rotations"].get(name, np.tile(rig.rest_local[index], (count, 1)))
                      for index, name in enumerate(BONE_NAMES)], axis=1)
    return rig.forward(local, clip["hips_translation"])


def _stance_slip(rig, clip, points, duration):
    """Largest horizontal drift of an ankle between its landing and its next lift, in leg lengths.

    The windows come from the planned footprints, trimmed by the heel strike and the heel rise.
    """
    positions, _worlds = _motion(rig, clip)
    times = clip["times"]
    route = _Route(rig, _points(points))
    steps = _Steps(route, route.length * _eased_progress(times, duration), times)
    worst = 0.0
    for side in ("Left", "Right"):
        ankle = positions[:, BONE_BY_NAME[f"{side}Foot"]]
        moves = [event for event in steps.events if event["side"] == side]
        lands = [0.0] + [event["land"] for event in moves]
        lifts = [event["lift"] for event in moves] + [float(times[-1])]
        for land, lift in zip(lands, lifts):
            hold = (times >= land + 0.13) & (times <= lift - 0.16)
            if hold.sum() >= 2:
                worst = max(worst, float(np.max(np.ptp(ankle[hold][:, [0, 2]], axis=0))) / rig.leg)
    return worst


@pytest.mark.parametrize("kind", ("default", "pet"))
@pytest.mark.parametrize("points,duration", [
    ([[0, 0], [0, 3]], 4.0),
    ([[0, 0], [0, 2], [2, 2]], 5.0),
    ([[0, 0], [1.5, 1.0], [0.0, 2.5], [-1.0, 1.0]], 6.0),
])
def test_planted_feet_stay_put_in_the_world(kind, points, duration):
    rig = _rig(kind)
    scale = rig.leg / default_rig().leg
    scaled = np.asarray(points) * scale
    clip = path_clip(rig, scaled, duration)
    assert _stance_slip(rig, clip, scaled, duration) < 0.002
    assert clip["warnings"] == []


def test_the_hips_reach_the_end_and_face_the_way_they_walk():
    rig = default_rig()
    points = [[0, 0], [0, 2], [2, 2]]
    clip = path_clip(rig, points, 5.0)
    hips = clip["hips_translation"]
    assert np.allclose(hips[-1][[0, 2]], [2.0, 2.0], atol=rig.leg * 0.02)
    _positions, worlds = _motion(rig, clip)
    forward = rot.rotate(worlds[:, BONE_BY_NAME["Hips"]], np.broadcast_to([0.0, 0.0, 1.0], (len(hips), 3)))
    route = _Route(rig, _points(points))
    travel = route.length * _eased_progress(clip["times"], 5.0)
    heading = np.degrees(np.arctan2(forward[:, 0], forward[:, 2]))
    gap = (heading - route.heading(travel) + 180.0) % 360.0 - 180.0
    assert float(np.abs(gap).max()) < 6.0, "only the walk's own hip twist (5 degrees) turns the body off the path"
    assert float(forward[-1][0]) > 0.95, "after the turn the walker faces +x"


def test_the_walk_starts_and_ends_with_the_feet_side_by_side():
    rig = default_rig()
    clip = path_clip(rig, [[0, 0], [0, 3]], 4.0)
    positions, _worlds = _motion(rig, clip)
    left, right = positions[:, BONE_BY_NAME["LeftFoot"]], positions[:, BONE_BY_NAME["RightFoot"]]
    for frame in (0, -1):
        assert abs(float(left[frame][2] - right[frame][2])) < rig.leg * 0.02
    sides = [c["foot"] for c in clip["contacts"]]
    assert all(a != b for a, b in zip(sides, sides[1:])), "landings alternate"
    floor_gap = min(positions[:, BONE_BY_NAME["LeftToeBase"], 1].min(), positions[:, BONE_BY_NAME["RightToeBase"], 1].min()) - rig.floor
    assert floor_gap > -rig.leg * 0.01, "no toe goes under the floor"


def test_a_walk_faster_than_natural_is_flagged():
    rig = default_rig()
    clip = path_clip(rig, [[0, 0], [0, 12]], 3.0)
    assert any(item.startswith("path_too_fast") for item in clip["warnings"])


@pytest.mark.parametrize("points,duration,message", [
    ([[0, 0]], 2.0, "2 to"), ([[0, 0], [0, 0]], 2.0, "same place"), ([[0, 0], [0, float("nan")]], 2.0, "finite"),
    ([[0, 0], [1, 1]], 0.1, "duration"), ([[0, 0], [1, 1]], 500.0, "duration"), ("north", 2.0, "pairs"),
])
def test_bad_paths_are_refused(points, duration, message):
    with pytest.raises(InvalidInput, match=message):
        path_clip(default_rig(), points, duration)


def test_the_same_path_bakes_the_same_clip():
    rig = default_rig()
    a = path_clip(rig, [[0, 0], [1, 2]], 3.0)
    b = path_clip(rig, [[0, 0], [1, 2]], 3.0)
    assert all(np.array_equal(a["rotations"][name], b["rotations"][name]) for name in a["rotations"])
    assert np.array_equal(a["hips_translation"], b["hips_translation"])


def test_a_rigged_glb_gets_a_path_walk_that_keeps_its_landings():
    from services.humanoid_rig.animate import animate_humanoid
    from services.humanoid_rig.rig import rig_humanoid
    from tests.humanoid_bodies import as_glb

    rigged, _sidecar = rig_humanoid(as_glb(body("human_t")), ["idle"], 120)
    data, clips, warnings = animate_humanoid(rigged, [], 120, path={"points": [[0, 0], [0, 1.5], [1.0, 2.0]], "duration": 4.0})
    assert [clip["name"] for clip in clips] == ["Path Walk"] and clips[0]["index"] == 1
    assert abs(clips[0]["duration"] - 4.0) < 1e-9
    sides = [contact["foot"] for contact in clips[0]["contacts"]]
    assert len(sides) >= 4 and all(a != b for a, b in zip(sides, sides[1:]))
    assert warnings == []
    assert data[:4] == b"glTF"

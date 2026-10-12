"""A mouth hint is a place to look unless it is exact; sure landmarks overrule a far one."""
import pytest

pytest.importorskip("cv2")

from services import flat_rig_hints
from services.flat_rig import FlatRigError, rig_hints

LIPS = [[100, 200], [110, 196], [120, 194], [130, 194], [140, 196], [150, 198],
        [160, 200], [150, 205], [140, 207], [130, 208], [120, 207], [110, 205]]
SIZE = (400, 400)
SURE = {"mouth": LIPS, "scores": {"mouth": 0.95}}


def _hint(x, y, **extra):
    return {"mouth": [x / SIZE[0] * 100, y / SIZE[1] * 100], "mouthWidth": 15.0, **extra}


def test_a_hint_near_sure_lips_gives_way_to_them_quietly():
    kept, ignored = flat_rig_hints.trusted(_hint(134, 203), SURE, SIZE)
    assert kept is None and ignored["far"] is False and ignored["offset"] <= flat_rig_hints.FAR


def test_a_hint_far_from_sure_lips_is_left_out_with_its_eyes_kept():
    hint = {**_hint(175, 245), "eyes": [30.0, 25.0]}
    kept, ignored = flat_rig_hints.trusted(hint, SURE, SIZE)
    assert kept == {"eyes": [30.0, 25.0]}
    assert ignored["hint"] == hint["mouth"] and ignored["far"] and ignored["offset"] > flat_rig_hints.FAR
    assert ignored["score"] == 0.95
    assert ignored["landmarks"] == pytest.approx([32.5, 50.5], abs=0.5)


def test_exact_hints_and_unsure_landmarks_leave_the_hint_alone():
    far = _hint(175, 245, exact=True)
    assert flat_rig_hints.trusted(far, SURE, SIZE) == (far, None)
    plain = _hint(175, 245)
    assert flat_rig_hints.trusted(plain, {"mouth": LIPS, "scores": {"mouth": 0.6}}, SIZE) == (plain, None)
    assert flat_rig_hints.trusted(plain, None, SIZE) == (plain, None)


def test_exact_is_a_boolean_hint_key():
    assert rig_hints({"busto": {"mouth": [40, 20], "exact": True}}) == {"busto": {"mouth": [40.0, 20.0], "exact": True}}
    with pytest.raises(FlatRigError):
        rig_hints({"busto": {"mouth": [40, 20], "exact": "yes"}})

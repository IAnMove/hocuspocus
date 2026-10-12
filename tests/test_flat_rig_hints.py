"""A mouth hint is a place to look unless it is exact; sure landmarks overrule a far one."""
import numpy as np
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


def _silver_bob():
    """A painted bust with silver hair round the face and two white eyes, each cut in two by a grey iris."""
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 20, 330, 330), fill=(236, 236, 234, 255))           # the hair, as light as a sclera
    draw.ellipse((115, 70, 285, 320), fill=(232, 190, 160, 255))          # the face
    draw.rectangle((60, 330, 340, 400), fill=(20, 20, 20, 255))           # the blazer
    for cx in (162, 238):
        draw.ellipse((cx - 22, 160, cx + 22, 176), fill=(252, 252, 252, 255))
        draw.ellipse((cx - 8, 158, cx + 8, 178), fill=(110, 110, 120, 255))  # the iris cuts the white in two
    return image


def test_an_eyes_hint_keeps_light_hair_out_of_the_eyes():
    """The bug: light hair round the face crossed the eye's rows, so it was taken as a piece of the eye, the eye
    became the whole head and the rig said the face was keyed out."""
    from services.flat_rig_eyes import find_eyes
    pixels = np.array(_silver_bob())
    box, mask = find_eyes(pixels[..., :3], pixels[..., 3], near=(200, 168))
    x0, y0, x1, y1 = box
    assert 135 <= x0 and x1 <= 265 and 155 <= y0 and y1 <= 182, box
    assert mask[168, 145] and mask[168, 178] and not mask[60, 200], "both halves of each eye, none of the hair"


def test_a_blink_closes_both_halves_of_an_eye_its_pupil_cut():
    """The bug: the openings kept the two largest pieces of white, one half of each eye, so one lid closed over half
    an eye and the iris stayed open: the character winked instead of blinking."""
    from services.flat_rig_eyes import eye_openings, find_eyes
    pixels = np.array(_silver_bob())
    _box, mask = find_eyes(pixels[..., :3], pixels[..., 3], near=(200, 168))
    openings = eye_openings(pixels[..., :3], pixels[..., 3], mask, (232, 190, 160))
    for label, (outer, inner) in ((1, (145, 178)), (2, (255, 222))):
        assert openings[168, outer] == label and openings[168, inner] == label, f"eye {label} opens whole"

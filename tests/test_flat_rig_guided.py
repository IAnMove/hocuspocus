"""Face landmarks guide the flat rig, closed lids stay on the face, and ink mouths drop the lower lip."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from PIL import Image, ImageDraw

from services import face_landmarks
from services.character_kit_library import patch_character_kit
from services.flat_rig import (
    LUMA, FlatRigError, _figure_box, draw_ink_mouth, place, rig_character, rig_pose, rig_style,
)
from services.flat_rig_ink import INK_OPENINGS

INK = rig_style({"mouthStyle": "ink"})
SKIN = (205, 140, 70, 255)
LINE = (25, 15, 10, 255)
EYES = ((120, 140, 200, 190), (220, 140, 300, 190))
MOUTH_Y = 305


def _face(eyes=(255, 255, 255, 255), hair=False, shadow=False, rim=False) -> Image.Image:
    """A graphic-novel head: outlined white eyes, a black nose wedge right under them (what the search took for a
    mouth) and the mouth, a pen line well below."""
    image = Image.new("RGBA", (420, 760), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((110, 360, 310, 740), fill=(90, 30, 30, 255))
    draw.ellipse((60, 40, 360, 380), fill=SKIN)
    if hair:
        # A mass of black hair over the left of the face, running into the left eye's outline.
        draw.polygon([(60, 60), (126, 60), (126, 200), (90, 330), (60, 330)], fill=LINE)
    if shadow:
        # A flat black shadow over the right eye socket.
        draw.rectangle((206, 112, 330, 214), fill=LINE)
    for x0, y0, x1, y1 in EYES:
        if rim:
            draw.ellipse((x0, y0, x1, y1), fill=(205, 200, 185, 255))
            draw.ellipse((x0 + 8, y0 + 7, x1 - 8, y1 - 7), fill=eyes)
        else:
            draw.ellipse((x0, y0, x1, y1), fill=eyes)
        draw.ellipse((x0, y0, x1, y1), outline=LINE, width=5)
        draw.ellipse(((x0 + x1) / 2 - 9, y0 + 14, (x0 + x1) / 2 + 9, y0 + 36), fill=LINE)
    draw.polygon([(205, 205), (228, 258), (196, 262)], fill=LINE)
    draw.line((170, MOUTH_Y, 250, MOUTH_Y), fill=LINE, width=6)
    return image


def _landmarks(eyes=0.9, mouth=0.9):
    outline = lambda x0, y0, x1, y1: [[x0, (y0 + y1) / 2], [x0 + (x1 - x0) / 3, y0], [x0 + (x1 - x0) * 2 / 3, y0],
                                      [x1, (y0 + y1) / 2], [x0 + (x1 - x0) * 2 / 3, y1], [x0 + (x1 - x0) / 3, y1]]
    lips = [[170 + 80 * i / 11, MOUTH_Y + 4 * np.sin(np.pi * i / 11)] for i in range(12)]
    return {"eyes": [outline(*EYES[0]), outline(*EYES[1])], "mouth": lips, "scores": {"eyes": eyes, "mouth": mouth}}


def _figure_offset(image):
    """Where the rig's figure crop starts in the pose image."""
    return _figure_box(image)[1][:2]


def test_the_landmarks_put_the_mouth_on_its_line_and_not_on_the_nose():
    face = _face()
    rig = rig_pose(face, INK, None, _landmarks())
    assert rig["guided"] == ["eyes", "mouth"]
    _ox, oy = _figure_offset(face)
    x0, y0, x1, y1 = rig["mouth_box"]
    assert abs((y0 + y1) / 2 + oy - MOUTH_Y) <= 6, "the pen line, not the nose wedge under the eyes"
    assert x1 - x0 >= 60


def test_a_hint_still_wins_over_the_landmarks():
    face = _face()
    hint = {"mouth": [215 / face.width * 100, 245 / face.height * 100]}
    rig = rig_pose(face, INK, hint, _landmarks())
    _ox, oy = _figure_offset(face)
    edge = max(rig["width"], rig["height"])
    mouth_y = rig["height"] / 2 + rig["mouth"]["offsetY"] * edge / 100 + oy
    assert rig["guided"] == ["eyes"] and mouth_y < 270, "the hint, not the landmarks' mouth"


def test_unsure_landmarks_are_not_used():
    assert face_landmarks.guides(_landmarks(eyes=0.2, mouth=0.2)) == {}
    assert set(face_landmarks.guides(_landmarks(eyes=0.9, mouth=0.2))) == {"eyes", "eye_outlines"}
    rig = rig_pose(_face(), INK, None, _landmarks(eyes=0.2, mouth=0.2))
    assert rig["guided"] == []


def test_eyes_without_a_white_are_rigged_from_the_landmarks_outlines():
    face = _face(eyes=(150, 120, 100, 255))
    with pytest.raises(FlatRigError) as error:
        rig_pose(face, INK)
    assert error.value.code == "eyes_not_found"
    rig = rig_pose(face, INK, None, _landmarks())
    ox, oy = _figure_offset(face)
    x0, y0, x1, y1 = rig["eyes_box"]
    assert abs(x0 + ox - EYES[0][0]) <= 15 and abs(x1 + ox - EYES[1][2]) <= 15 and abs(y0 + oy - EYES[0][1]) <= 15


def _closed(rig):
    return np.array(place(rig["image"], rig["blink"], rig["eyes"]))[..., :3].astype(int)


def test_a_closed_eye_beside_black_hair_does_not_paint_the_hair():
    """The bug: the eye's outline joined the hair, so the lid was the whole search window, a skin rectangle."""
    face = _face(hair=True)
    rig = rig_pose(face, INK, None, _landmarks())
    before = np.array(rig["image"])[..., :3].astype(int)
    closed = _closed(rig)
    ox, oy = _figure_offset(face)
    eyes = Image.new("L", face.size, 0)
    for x0, y0, x1, y1 in EYES:
        ImageDraw.Draw(eyes).ellipse((x0 - 8, y0 - 8, x1 + 8, y1 + 8), fill=255)
    near_eyes = np.array(eyes)[oy:oy + before.shape[0], ox:ox + before.shape[1]] > 0
    hair = (before.max(axis=2) < 40) & (np.array(rig["image"])[..., 3] > 200) & ~near_eyes
    painted = hair & (np.abs(closed - before).sum(axis=2) > 60)
    assert painted.sum() < 30, f"{painted.sum()} hair pixels away from the eyes were painted over"
    x0, y0, x1, y1 = rig["eyes_box"]
    assert (closed[y0:y1, x0:x1].min(axis=2) > 235).sum() == 0, "no white shows through"


def test_a_white_with_a_shaded_rim_is_covered_whole():
    """The bug: only the brightest white was found, and the shaded white round it showed round the closed lid."""
    rig = rig_pose(_face(rim=True), INK, None, _landmarks())
    closed = _closed(rig)
    x0, y0, x1, y1 = rig["eyes_box"]
    rim = (np.abs(closed - np.array([205, 200, 185])).sum(axis=2) < 30)
    assert rim.sum() < 20 and (closed.min(axis=2) > 235).sum() == 0


def test_an_eye_in_a_black_shadow_closes_in_the_shadow():
    rig = rig_pose(_face(shadow=True), INK, None, _landmarks())
    closed = _closed(rig)
    ox, oy = _figure_offset(_face(shadow=True))
    rx0, ry0, rx1, ry1 = (v - o for v, o in zip(EYES[1], (ox, oy, ox, oy)))
    lx0, ly0, lx1, ly1 = (v - o for v, o in zip(EYES[0], (ox, oy, ox, oy)))
    right = closed[ry0 + 10:ry1 - 10, rx0 + 10:rx1 - 10]
    left = closed[ly0 + 15:ly1 - 15, lx0 + 15:lx1 - 15]
    assert np.median(right @ LUMA) < 50, "the lid in the shadow is the shadow"
    assert abs(np.median(left @ LUMA) - np.dot(SKIN[:3], LUMA)) < 25, "the lit one is the face colour"


def test_open_ink_mouths_drop_a_lower_lip_stroke_under_the_opening():
    ink, skin = (60, 30, 20, 255), (210, 160, 110)
    for state in INK_OPENINGS:
        solid = (np.array(draw_ink_mouth(state, ink, skin))[..., 3] > 200).astype(np.uint8)
        count, labels = cv2.connectedComponents(solid)
        parts = count - 1
        if state in ("medium", "wide", "round", "tongue"):
            assert parts == 2, state
            tops = sorted(np.nonzero(labels == label)[0].min() for label in (1, 2))
            assert tops[1] > tops[0] + 10, f"{state}: the lip stroke lies under the opening"
        else:
            assert parts == 1, state


def test_the_landmarks_need_their_model_and_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("HOCUS_FACE_LANDMARKS", "0")
    assert face_landmarks.detect(_face()) is None
    monkeypatch.delenv("HOCUS_FACE_LANDMARKS")
    monkeypatch.setattr(face_landmarks, "_model", None)
    monkeypatch.setattr(face_landmarks, "_paths", lambda: None)
    assert face_landmarks.detect(_face()) is None


def test_a_rig_detects_landmarks_on_each_pose_and_reports_them(tmp_path, monkeypatch):
    folder = tmp_path / "cast"
    folder.mkdir()
    _face().save(folder / "captain.png")
    seen = []
    monkeypatch.setattr(face_landmarks, "detect", lambda image: seen.append(image.size) or _landmarks())
    asset = {"id": "captain-base", "name": "captain", "source": "/api/v1/file/captain.png?workspace=cast", "kind": "image",
             "alphaStatus": "transparent", "reviewState": "approved"}
    patch_character_kit(str(folder), "captain", {"id": "captain", "name": "Captain", "style": "cutout", "base": asset,
                                                 "poses": {}, "mouth": {}, "eyes": {}, "anchors": {}}, base_revision=0)
    rigged = rig_character(str(folder), "cast", "captain", base_revision=1, style={"mouthStyle": "ink"})
    assert seen == [(420, 760)]
    assert rigged["poses"]["base"]["landmarks"] == ["eyes", "mouth"]

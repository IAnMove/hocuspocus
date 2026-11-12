"""Face landmarks guide the flat rig, closed lids stay on the face, and ink mouths drop the lower lip."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from PIL import Image, ImageDraw

from services import anime_face_landmarks, face_landmarks
from services.flat_rig_warp import lips_line
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


def _mouth_y(face, rig):
    _ox, oy = _figure_offset(face)
    edge = max(rig["width"], rig["height"])
    return rig["height"] / 2 + rig["mouth"]["offsetY"] * edge / 100 + oy


def test_an_exact_hint_still_wins_over_the_landmarks():
    face = _face()
    hint = {"mouth": [215 / face.width * 100, 245 / face.height * 100], "exact": True}
    rig = rig_pose(face, INK, hint, _landmarks())
    assert rig["guided"] == ["eyes"] and _mouth_y(face, rig) < 270, "the hint, not the landmarks' mouth"
    assert "mouth_hint_ignored" not in rig["warnings"]


def test_a_far_hint_loses_to_sure_landmarks_and_says_so():
    # On the 1x03 an agent's hints put a mouth on a cheek while DWPose had the lips at 0.94.
    face = _face()
    hint = {"mouth": [215 / face.width * 100, 245 / face.height * 100]}
    rig = rig_pose(face, INK, hint, _landmarks())
    assert rig["guided"] == ["eyes", "mouth"] and abs(_mouth_y(face, rig) - MOUTH_Y) <= 6, "the landmarks' mouth"
    assert "mouth_hint_ignored" in rig["warnings"]
    ignored = rig["seeds"]["hint_ignored"]
    assert ignored["hint"] == hint["mouth"] and ignored["far"] and ignored["score"] == 0.9
    # One near the lips gives way to the sure landmarks too, without a warning.
    near = rig_pose(face, INK, {"mouth": [212 / face.width * 100, (MOUTH_Y + 6) / face.height * 100]}, _landmarks())
    assert near["guided"] == ["eyes", "mouth"] and "mouth_hint_ignored" not in near["warnings"]
    # Unsure landmarks (a beard seen from below) do not overrule it.
    unsure = rig_pose(face, INK, hint, _landmarks(mouth=0.6))
    assert _mouth_y(face, unsure) < 270 and "mouth_hint_ignored" not in unsure["warnings"]


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
    assert rigged["poses"]["base"]["eyesSource"] == "whites"
    assert rigged["character"]["anchors"]["base"]["mouthSource"] == "whites"


def _anime_points(eyes=EYES, mouth_y=MOUTH_Y, shift=(0, 0)):
    """28 anime points on this fixture: contour, brows, two eyes, five mouth points."""
    sx, sy = shift

    def eye(box):
        x0, y0, x1, y1 = [v + d for v, d in zip(box, (sx, sy, sx, sy))]
        return [[x0, (y0 + y1) / 2, 0.95], [(2 * x0 + x1) / 3, y0, 0.95], [(x0 + 2 * x1) / 3, y0, 0.95],
                [x1, (y0 + y1) / 2, 0.95], [(x0 + 2 * x1) / 3, y1, 0.95], [(2 * x0 + x1) / 3, y1, 0.95]]

    def brow(box):
        x0, y0, x1, _y1 = box
        y = y0 - 28 + sy
        return [[x0 + sx, y, 0.95], [(x0 + x1) / 2 + sx, y - 6, 0.95], [x1 + sx, y, 0.95]]

    contour = [[80 + sx, 220 + sy, 0.95], [120 + sx, 340 + sy, 0.95], [210 + sx, 400 + sy, 0.95],
               [300 + sx, 340 + sy, 0.95], [340 + sx, 220 + sy, 0.95]]
    mouth = [[170 + sx, mouth_y + sy, 0.95], [190 + sx, mouth_y + 8 + sy, 0.95], [210 + sx, mouth_y + 12 + sy, 0.95],
             [250 + sx, mouth_y + sy, 0.95], [230 + sx, mouth_y + 6 + sy, 0.95]]
    return contour + brow(eyes[0]) + brow(eyes[1]) + eye(eyes[0]) + eye(eyes[1]) + mouth


def test_anime_geometry_reads_eyes_brows_and_the_mouth_line():
    geom = anime_face_landmarks.geometry_from_points(_anime_points())
    assert geom["eyes"][0][2] < geom["eyes"][1][0]
    assert geom["brows"][0][0] < geom["brows"][1][0]
    assert geom["mouth"]["width"] == pytest.approx(80, abs=1)
    assert anime_face_landmarks.lip_contour(geom).shape == (12, 2)
    assert lips_line(anime_face_landmarks.lip_contour(geom)).source == "landmarks"
    assert not anime_face_landmarks.eyes_disagree((118, 138, 302, 192), geom)
    assert anime_face_landmarks.eyes_disagree((40, 130, 400, 210), geom), "a collar wider than 1.5× the eyes"
    assert anime_face_landmarks.eyes_disagree((120, 400, 300, 460), geom)
    assert not anime_face_landmarks.eyes_disagree((190, 155, 230, 175), geom), "a highlight that shares the centre"
    assert anime_face_landmarks.geometry_from_points([[*p[:2], 0.1] for p in _anime_points()]) is None


def test_dark_anime_eyes_take_the_landmark_boxes_and_the_blink_covers_them():
    face = _face(eyes=(36, 24, 28, 255))
    with pytest.raises(FlatRigError) as error:
        rig_pose(face, INK, anime=False)
    assert error.value.code == "eyes_not_found"
    rig = rig_pose(face, INK, anime={"keypoints": _anime_points()})
    assert rig["eyesSource"] == "landmarks" and "eyes_disagree" not in rig["warnings"]
    ox, oy = _figure_offset(face)
    x0, y0, x1, y1 = rig["eyes_box"]
    assert abs(x0 + ox - EYES[0][0]) <= 20 and abs(x1 + ox - EYES[1][2]) <= 20 and abs(y0 + oy - EYES[0][1]) <= 20
    closed = _closed(rig)
    cx, cy = int((EYES[0][0] + EYES[0][2]) / 2 - ox), int((EYES[0][1] + EYES[0][3]) / 2 - oy)
    assert abs(int(closed[cy, cx] @ LUMA) - int(np.dot(SKIN[:3], LUMA))) < 45


def test_landmarks_win_when_the_white_eyes_disagree():
    face = _face()
    rig = rig_pose(face, INK, anime={"keypoints": _anime_points(shift=(0, 180))})
    assert rig["eyesSource"] == "landmarks" and "eyes_disagree" in rig["warnings"]
    _ox, oy = _figure_offset(face)
    assert rig["eyes_box"][1] + oy > EYES[0][3] + 80


def test_agreeing_whites_stay_and_the_brows_are_kept():
    face = _face()
    rig = rig_pose(face, INK, anime={"keypoints": _anime_points()})
    plain = rig_pose(face, INK, anime=False)
    assert rig["eyesSource"] == "whites" and rig["mouthSource"] == "whites"
    assert rig["eyes_box"] == plain["eyes_box"] and rig["mouth_box"] == plain["mouth_box"]
    assert "eyes_disagree" not in rig["warnings"] and "mouth_disagree" not in rig["warnings"]
    assert len(rig["brows"]) == 2 and rig["brows"][0][2] < rig["brows"][1][0]


def test_a_gorthak_tick_does_not_replace_the_painted_mouth():
    """The landmark mouth on Gorthak is a short vertical tick, about 1/10 of the real mouth.

    Landmarks may replace the mouth only when it is at least 0.35 of the eye-pair
    width, centred below the eyes, and the mouth-point scores average at least 0.35.
    """
    face = _face()
    points = _anime_points()
    # Eye centres sit 100 px apart. A tick 8 px wide is under 0.35 of that, on the nose.
    points[23:28] = [[206, 240, 0.9], [210, 232, 0.9], [210, 240, 0.9], [210, 248, 0.9], [214, 240, 0.9]]
    geom = anime_face_landmarks.geometry_from_points(points)
    assert geom["mouth"]["width"] < anime_face_landmarks.MOUTH_WIDTH_OF_EYES * geom["pair_width"]
    assert geom["mouth"]["width"] < 0.15 * 80, "about a tenth of the painted mouth"
    assert not anime_face_landmarks.mouth_plausible(geom)
    high = anime_face_landmarks.geometry_from_points(_anime_points(mouth_y=80))
    assert high["mouth"]["width"] > anime_face_landmarks.MOUTH_WIDTH_OF_EYES * high["pair_width"]
    assert not anime_face_landmarks.mouth_plausible(high), "a wide mouth above the eyes"
    unsure = [[*point[:2], 0.9] for point in _anime_points()]
    for index in range(23, 28):
        unsure[index][2] = 0.05
    low = anime_face_landmarks.geometry_from_points(unsure)
    assert low["mouth"]["score"] < anime_face_landmarks.MOUTH_POINT_SCORE
    assert not anime_face_landmarks.mouth_plausible(low)
    assert anime_face_landmarks.mouth_plausible(anime_face_landmarks.geometry_from_points(_anime_points()))
    rig = rig_pose(face, INK, anime={"keypoints": points})
    plain = rig_pose(face, INK, anime=False)
    assert rig["mouthSource"] == "whites" and rig["mouth_box"] == plain["mouth_box"]
    assert "mouth_landmarks_implausible" in rig["warnings"]
    assert "mouth_not_found" not in rig["warnings"] and "mouth_disagree" not in rig["warnings"]
    assert abs(_mouth_y(face, rig) - MOUTH_Y) <= 12


def test_a_landmark_mouth_is_not_reported_as_missing():
    """Landmarks placed the mouth. That is not the same as finding no mouth at all."""
    face = _face()
    rig = rig_pose(face, INK, anime={"keypoints": _anime_points(mouth_y=520)})
    assert rig["mouthSource"] == "landmarks"
    assert "mouth_not_found" not in rig["warnings"]
    assert "mouth_disagree" in rig["warnings"]


def test_a_disagreeing_mouth_is_placed_on_the_landmark_line_without_a_wipe():
    face = _face()
    rig = rig_pose(face, INK, anime={"keypoints": _anime_points(mouth_y=520)})
    assert rig["mouthSource"] == "landmarks" and rig["wiped"] is False and rig["seeds"]["point"] is None
    assert "mouth_disagree" in rig["warnings"] and "mouth_not_found" not in rig["warnings"]
    assert abs(_mouth_y(face, rig) - 520) <= 30
    assert lips_line(rig["seeds"]["lips"]).source == "landmarks"
    assert rig["seeds"]["lips"].shape == (12, 2)


def test_a_hint_wins_over_disagreeing_anime_landmarks():
    face = _face()
    hint = {"eyes": [210 / face.width * 100, 165 / face.height * 100],
            "mouth": [210 / face.width * 100, MOUTH_Y / face.height * 100], "exact": True}
    rig = rig_pose(face, INK, hint, anime={"keypoints": _anime_points(shift=(0, 180), mouth_y=520)})
    assert rig["eyesSource"] == "hint" and rig["mouthSource"] == "hint"
    assert "eyes_disagree" not in rig["warnings"] and "mouth_disagree" not in rig["warnings"]
    assert abs(_mouth_y(face, rig) - MOUTH_Y) <= 12


def test_without_the_anime_detector_the_rig_matches_today(monkeypatch):
    monkeypatch.setattr(anime_face_landmarks, "detect", lambda image: None)
    face, marks = _face(), _landmarks()
    today = rig_pose(face, INK, None, marks, anime=False)
    missing = rig_pose(face, INK, None, marks)
    assert missing["eyes_box"] == today["eyes_box"] and missing["mouth_box"] == today["mouth_box"]
    assert missing["mouth"] == today["mouth"] and missing["eyes"] == today["eyes"]
    assert missing["warnings"] == today["warnings"] and missing["guided"] == today["guided"]
    assert missing["eyesSource"] == today["eyesSource"] == "whites"
    assert missing["mouthSource"] == today["mouthSource"] == "whites"
    assert "brows" not in missing


def test_turning_anime_landmarks_off_skips_the_detector(monkeypatch):
    monkeypatch.setenv("HOCUS_ANIME_FACE", "0")
    called = []
    monkeypatch.setattr(anime_face_landmarks, "detect", lambda image: called.append(1) or {"keypoints": _anime_points(shift=(0, 180))})
    rig = rig_pose(_face(), INK)
    assert called == [] and rig["eyesSource"] == "whites" and "brows" not in rig


def test_a_missing_engine_does_not_run_the_detector(monkeypatch):
    monkeypatch.setattr(anime_face_landmarks, "_python", lambda: None)
    monkeypatch.setattr(anime_face_landmarks.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("spawned")))
    assert anime_face_landmarks.detect(Image.new("RGBA", (8, 8))) is None


def test_a_failed_detector_warns_and_keeps_today(monkeypatch):
    monkeypatch.setattr(anime_face_landmarks, "detect", lambda image: {"error": "weights missing"})
    face = _face()
    rig = rig_pose(face, INK)
    assert rig["eyesSource"] == "whites" and "anime_landmarks_failed" in rig["warnings"]
    assert rig["eyes_box"] == rig_pose(face, INK, anime=False)["eyes_box"]


def test_an_unsure_brighter_box_loses_to_the_sure_face():
    """Gorthak's wolf buckle outscores his face as a box, and its points are not sure."""
    from services.anime_face.worker import choose_face
    buckle = {"bbox": [0, 1500, 40, 1540, 0.9], "keypoints": [[0, 1500, 0.1]] * 28}
    face = {"bbox": [300, 400, 500, 600, 0.25], "keypoints": [[400, 480, 0.7]] * 28}
    assert choose_face([buckle, face]) is face
    assert choose_face([buckle]) is None
    assert choose_face([]) is None


def test_the_kit_remembers_which_source_placed_the_face(tmp_path, monkeypatch):
    folder = tmp_path / "cast"
    folder.mkdir()
    _face(eyes=(36, 24, 28, 255)).save(folder / "captain.png")
    monkeypatch.setattr(face_landmarks, "detect", lambda image: None)
    monkeypatch.setattr(anime_face_landmarks, "detect", lambda image: {"keypoints": _anime_points()})
    asset = {"id": "captain-base", "name": "captain", "source": "/api/v1/file/captain.png?workspace=cast", "kind": "image",
             "alphaStatus": "transparent", "reviewState": "approved"}
    patch_character_kit(str(folder), "captain", {"id": "captain", "name": "Captain", "style": "cutout", "base": asset,
                                                 "poses": {}, "mouth": {}, "eyes": {}, "anchors": {}}, base_revision=0)
    rigged = rig_character(str(folder), "cast", "captain", base_revision=1, style={"mouthStyle": "ink"})
    pose, anchor = rigged["poses"]["base"], rigged["character"]["anchors"]["base"]
    assert pose["eyesSource"] == anchor["eyesSource"] == "landmarks"
    assert pose["mouthSource"] == anchor["mouthSource"]
    assert len(anchor["brows"]) == 2

"""The flat rig on realistic and graphic-novel faces, placement hints and ink mouths."""
import json

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from services.character_kit_library import patch_character_kit, read_character_kit_library
from services.flat_rig import (
    INK_OPENINGS, INK_SPAN, REALISTIC_MOUTH, SPRITE, STATES, FlatRigError, _dilate, _face_crop, _figure_box, crop_figure,
    draw_ink_mouth, eye_extent, face_realistic, find_eyes, place, rig_character, rig_hints, rig_pose, rig_style,
)
from tests.test_flat_rig import WORKSPACE, _anime_eyes, _code_face, _cutout, _full_body_anime, _small_o_face, _workspace

REAL_SKIN, REAL_INK, BRASS = (214, 166, 112, 255), (26, 18, 14, 255), (120, 90, 30, 255)
LUMA = np.array([0.299, 0.587, 0.114])
INK = rig_style({"mouthStyle": "ink"})


def _realistic_face(mouth=True, eye_bags=True, shadow=True, spectacles=False, moustache=False) -> Image.Image:
    """A bust inked with realistic proportions: small almond eyes looking aside in a wide head, an eye bag and a wrinkle
    under each eye, a nose and nostrils, a flat black shadow down one side of the face and a thin mouth line far below
    the eyes (0.9 of the eye pair's width under the eye line) that runs into the shadow. Options add round spectacles
    and a moustache right over the mouth."""
    image = Image.new("RGBA", (420, 560), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 440, 390, 560), fill=(40, 34, 60, 255))
    draw.ellipse((40, 20, 380, 120), fill=(30, 24, 20, 255))
    draw.ellipse((50, 30, 370, 450), fill=REAL_SKIN)
    if shadow:
        draw.polygon([(300, 210), (372, 210), (372, 450), (250, 450), (268, 362), (294, 300)], fill=REAL_INK)
    for x in (128, 240):
        draw.ellipse((x, 180, x + 60, 196), fill=(250, 248, 240, 255))
        draw.ellipse((x + 6, 180, x + 18, 196), fill=(40, 30, 25, 255))
        draw.arc((x - 2, 175, x + 62, 201), 200, 340, fill=REAL_INK, width=3)
        if eye_bags:
            draw.arc((x - 2, 190, x + 62, 216), 20, 160, fill=REAL_INK, width=3)
            draw.line((x + 8, 226, x + 52, 228), fill=REAL_INK, width=2)
    draw.line((214, 200, 204, 270), fill=REAL_INK, width=2)
    draw.ellipse((192, 276, 206, 284), fill=REAL_INK)
    draw.ellipse((226, 276, 240, 284), fill=REAL_INK)
    if spectacles:
        for cx in (158, 270):
            draw.ellipse((cx - 48, 142, cx + 48, 238), outline=BRASS, width=4)
        draw.line((206, 188, 222, 188), fill=BRASS, width=4)
    if moustache:
        draw.chord((164, 296, 268, 342), 180, 360, fill=REAL_INK)
        for x in range(168, 266, 6):
            draw.line((x, 318, x - 2, 332), fill=REAL_INK, width=2)
    if mouth:
        draw.line([(174, 337), (200, 334), (236, 334), (262, 338), (284, 342)], fill=REAL_INK, width=3, joint="curve")
    return image


def _drawn(with_it: Image.Image, without: Image.Image) -> np.ndarray:
    """Where a feature is drawn, on the cropped figure: the pixels it changes."""
    return np.abs(np.array(crop_figure(with_it)).astype(int) - np.array(crop_figure(without)).astype(int)).sum(axis=2) > 0


def _centre(rig) -> tuple[float, float]:
    edge = max(rig["width"], rig["height"])
    return rig["width"] / 2 + rig["mouth"]["offsetX"] * edge / 100, rig["height"] / 2 + rig["mouth"]["offsetY"] * edge / 100


def _figure_point(image: Image.Image, point) -> tuple[float, float]:
    _, crop = _figure_box(image)
    return point[0] / 100 * image.width - crop[0], point[1] / 100 * image.height - crop[1]


def _eyes(image: Image.Image):
    pixels = np.array(crop_figure(image))
    box, mask = find_eyes(pixels[..., :3], pixels[..., 3])
    return pixels, box, mask


def test_realistic_proportions_are_told_from_the_cartoon_ones():
    for image in (_realistic_face(), _realistic_face(shadow=False), _realistic_face(spectacles=True, moustache=True)):
        pixels, box, mask = _eyes(image)
        assert face_realistic(pixels[..., :3], pixels[..., 3], box, mask) is True
    cartoons = [_cutout(), _cutout(smirk=True), _cutout(touching=True, collar=True), _cutout(sunglasses=True, touching=True),
                _cutout(size=(520, 760)), _anime_eyes(_cutout(eyes=False)), Image.fromarray(_full_body_anime()),
                _small_o_face(nose_dot=True), _code_face()]
    for image in cartoons:
        pixels, box, mask = _eyes(image)
        assert face_realistic(pixels[..., :3], pixels[..., 3], box, mask) is False


@pytest.mark.parametrize("shadow", [True, False])
def test_on_a_realistic_face_the_eye_bags_stay_and_the_mouth_far_below_them_is_wiped(shadow):
    """The bug: the topmost wide mark under the eyes was taken for the mouth. On a realistic face that is an eye bag:
    it was wiped into a smudge under the eye and the mouth was anchored there, far above the painted one."""
    face = _realistic_face(shadow=shadow)
    rig = rig_pose(face, rig_style(None))
    assert rig["realistic"] is True and rig["wiped"] is True and rig["warnings"] == []
    line = _drawn(face, _realistic_face(mouth=False, shadow=shadow))
    x0, y0, x1, y1 = rig["mouth_box"]
    ys, xs = np.nonzero(line)
    assert x0 <= xs.min() + 2 and xs.max() < x1 + 2 and y0 <= ys.min() + 2 and ys.max() < y1 + 2, "the whole painted line"
    assert y1 - y0 < 16, "only the line, not the nose or the chin"
    after = np.array(rig["image"])[..., :3] @ LUMA
    # Beside the black shadow the inpaint blends the shadow in; everywhere else the line is gone.
    shade = _dilate(_drawn(_realistic_face(mouth=False), _realistic_face(mouth=False, shadow=False)), 8)
    assert after[line & ~shade].min() > 120, "no painted mouth is left under the drawn one"
    bags = _drawn(face, _realistic_face(eye_bags=False, shadow=shadow))
    assert np.array_equal(np.array(rig["image"])[bags], np.array(rig["before"])[bags]), "the eye bags are not wiped"
    # The drawn mouth sits on the painted line, 0.9 of the eye pair's width under the eye line. The pair is measured
    # on the whole whites: the eye search cuts a long almond white in two and keeps a half of each eye.
    cx, cy = _centre(rig)
    assert abs(cy - (ys.min() + ys.max()) / 2) <= 4 and x0 <= cx <= x1
    pixels, box, mask = _eyes(face)
    ex0, ey0, ex1, ey1 = eye_extent(pixels[..., :3], pixels[..., 3], box, mask)
    assert ex1 - ex0 > (box[2] - box[0]) * 1.1
    assert 0.8 <= (cy - (ey0 + ey1) / 2) / (ex1 - ex0) <= 1.0


def test_the_review_shows_a_realistic_face_down_to_its_mouth():
    """The enlarged face in the review stopped above a realistic face's mouth, so its wipe could not be checked."""
    rig = rig_pose(_realistic_face(), rig_style(None))
    marked = rig["image"].copy()
    x0, y0, x1, y1 = rig["mouth_box"]
    ImageDraw.Draw(marked).rectangle((x0, y1 - 1, x1, y1), fill=(255, 0, 255, 255))
    crop = np.array(_face_crop(marked, rig))
    assert (np.abs(crop[..., :3].astype(int) - (255, 0, 255)).sum(axis=2) == 0).any()


def test_spectacles_and_a_moustache_stay_and_the_mouth_line_under_the_moustache_is_wiped():
    face = _realistic_face(spectacles=True, moustache=True)
    rig = rig_pose(face, rig_style(None))
    assert rig["realistic"] is True and rig["wiped"] is True
    line = _drawn(face, _realistic_face(spectacles=True, moustache=True, mouth=False))
    _x0, y0, _x1, y1 = rig["mouth_box"]
    ys, _xs = np.nonzero(line)
    assert y0 <= ys.min() + 2 and ys.max() < y1 + 2 and y1 - y0 < 16
    before, after = np.array(rig["before"]), np.array(rig["image"])
    rims = _drawn(face, _realistic_face(moustache=True))
    assert np.array_equal(after[rims], before[rims]), "the spectacles are not touched"
    moustache = _drawn(face, _realistic_face(spectacles=True)) & ~line
    kept = (np.abs(after[..., :3].astype(int) - before[..., :3].astype(int)).sum(axis=2) < 30)[moustache].mean()
    assert kept > 0.9, "the moustache stays (only its edge next to the mouth line is touched by the inpaint)"


def test_a_realistic_face_without_a_painted_mouth_gets_one_placed_where_its_mouth_would_be():
    rig = rig_pose(_realistic_face(mouth=False), rig_style(None))
    assert rig["realistic"] is True and rig["wiped"] is False and rig["warnings"] == ["mouth_not_found"]
    assert np.array_equal(np.array(rig["image"]), np.array(rig["before"])), "the nostrils and the shadow are never wiped"
    pixels, box, mask = _eyes(_realistic_face(mouth=False))
    ex0, ey0, ex1, ey1 = eye_extent(pixels[..., :3], pixels[..., 3], box, mask)
    cx, cy = _centre(rig)
    assert abs(cy - ((ey0 + ey1) / 2 + (ex1 - ex0) * REALISTIC_MOUTH)) <= 1 and abs(cx - (ex0 + ex1) / 2) <= 1


# Hints -----------------------------------------------------------------------

def test_hints_are_points_in_percent_of_each_pose_image():
    assert rig_hints(None) == {}
    assert rig_hints({"base": {"mouth": [50, 41.23456], "eyes": [50.0, 22]}, "wave": None, "nod": {}}) == {
        "base": {"mouth": [50.0, 41.235], "eyes": [50.0, 22.0]}, "wave": None, "nod": None}
    for bad in ([], {"base": []}, {"base": {"nose": [1, 2]}}, {"base": {"mouth": [50]}}, {"base": {"mouth": [101, 5]}},
                {"base": {"mouth": [True, 5]}}, {"base": {"mouth": "50,50"}}, {"base": {"mouth": [float("nan"), 5]}},
                {"": {"mouth": [1, 1]}}):
        with pytest.raises(FlatRigError) as error:
            rig_hints(bad)
        assert error.value.code == "invalid_hints"


def _eye_bags_and_a_low_mouth() -> Image.Image:
    """A cartoon face with an eye bag under each eye and the mouth well below them."""
    image = _cutout(mouth=False)
    draw = ImageDraw.Draw(image)
    for x in (120, 220):
        draw.arc((x, 205, x + 80, 240), 20, 160, fill=(40, 20, 20, 255), width=5)
    draw.line((175, 318, 245, 318), fill=(40, 20, 20, 255), width=5)
    return image


def test_a_mouth_hint_takes_the_mark_there_instead_of_the_one_the_search_would_pick():
    face = _eye_bags_and_a_low_mouth()
    default = rig_pose(face, rig_style(None))
    assert default["mouth_box"][3] < 260, "without a hint an eye bag is taken (cartoon proportions)"
    hinted = rig_pose(face, rig_style(None), {"mouth": [210 / 420 * 100, 318 / 760 * 100]})
    line = _drawn(face, _cutout(mouth=False)) & (np.arange(731)[:, None] > 270)
    ys, xs = np.nonzero(line)
    x0, y0, x1, y1 = hinted["mouth_box"]
    assert x0 <= xs.min() + 2 and xs.max() < x1 + 2 and y0 <= ys.min() + 2 and ys.max() < y1 + 2
    assert y1 - y0 < 12 and hinted["wiped"] is True
    assert (np.array(hinted["image"])[..., :3] @ LUMA)[line].min() > 120


def test_a_mouth_hint_with_no_mark_there_places_the_mouth_at_it_and_wipes_nothing():
    face = _cutout(mouth=False)
    rig = rig_pose(face, rig_style(None), {"mouth": [50, 40]})
    assert rig["wiped"] is False and rig["warnings"] == ["mouth_not_found"]
    assert np.array_equal(np.array(rig["image"]), np.array(rig["before"]))
    assert np.allclose(_centre(rig), _figure_point(face, (50, 40)), atol=1)


def _held_up_high() -> Image.Image:
    """The cutout under a tall staff it holds up: its eyes are below the top 55% of the figure."""
    image = Image.new("RGBA", (420, 1500), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((300, 0, 320, 800), fill=(120, 80, 40, 255))
    image.alpha_composite(_cutout(), (0, 740))
    return image


def test_an_eyes_hint_finds_eyes_where_the_search_does_not_look():
    pose = _held_up_high()
    with pytest.raises(FlatRigError) as error:
        rig_pose(pose, rig_style(None))
    assert error.value.code == "eyes_not_found"
    rig = rig_pose(pose, rig_style(None), {"eyes": [50, 910 / 1500 * 100]})
    x0, y0, x1, y1 = rig["eyes_box"]
    _, crop = _figure_box(pose)
    assert np.abs(np.array((x0 + crop[0], y0 + crop[1], x1 + crop[0], y1 + crop[1])) - (120, 860, 300, 960)).max() <= 1
    assert rig["wiped"] is True and rig["blinks"] is True
    with pytest.raises(FlatRigError) as error:
        rig_pose(pose, rig_style(None), {"eyes": [50, 3]})
    assert error.value.code == "eyes_not_found" and "hint" in str(error.value)


def test_hints_are_kept_in_the_provenance_and_reused_until_cleared(tmp_path):
    folder = _workspace(tmp_path)
    hint = {"mouth": [50, 40]}
    first = rig_character(str(folder), WORKSPACE, "kevin", base_revision=1, hints={"shrug": hint})
    assert first["character"]["provenance"][-1]["hints"] == {"shrug": {"mouth": [50.0, 40.0]}}
    assert first["poses"]["shrug"]["hints"] == {"mouth": [50.0, 40.0]} and "hints" not in first["poses"]["base"]
    assert first["unwipedPoses"] == ["shrug"] and first["poses"]["shrug"]["mouthFound"] is False
    placed = first["poses"]["shrug"]["mouth"]
    again = rig_character(str(folder), WORKSPACE, "kevin", base_revision=2)
    assert again["poses"]["shrug"]["mouth"] == placed, "a re-rig places the pose the same way"
    assert again["character"]["provenance"][-1]["hints"] == {"shrug": {"mouth": [50.0, 40.0]}}
    cleared = rig_character(str(folder), WORKSPACE, "kevin", base_revision=3, hints={"shrug": None})
    assert cleared["character"]["provenance"][-1]["hints"] == {}
    assert cleared["poses"]["shrug"]["mouth"] != placed
    with pytest.raises(FlatRigError) as error:
        rig_character(str(folder), WORKSPACE, "kevin", base_revision=4, hints={"wave": hint})
    assert error.value.code == "unknown_pose"


def test_the_http_route_passes_hints_and_reports_bad_ones(tmp_path):
    from routers.character_kit_library import _bind_character_kit_library_runtime, create_character_kit_library_router

    _workspace(tmp_path)
    _bind_character_kit_library_runtime(workspace_dir=lambda name: str(tmp_path / name),
                                        conflict=lambda exc: HTTPException(status_code=409, detail=str(exc)))
    app = FastAPI()
    app.include_router(create_character_kit_library_router())
    client = TestClient(app)
    path = "/api/v1/character-kits/library/kits/kevin/flat-rig"
    bad = client.post(path, json={"workspace": WORKSPACE, "baseRevision": 1, "hints": {"base": {"mouth": [50, 140]}}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_hints"
    rigged = client.post(path, json={"workspace": WORKSPACE, "baseRevision": 1, "hints": {"shrug": {"mouth": [50, 40]}},
                                     "style": {"mouthStyle": "ink"}})
    assert rigged.status_code == 200, rigged.text
    assert rigged.json()["poses"]["shrug"]["hints"] == {"mouth": [50.0, 40.0]}
    assert client.post(path, json={"workspace": WORKSPACE, "baseRevision": 2,
                                   "style": {"mouthStyle": "crayon"}}).json()["detail"]["code"] == "invalid_style"


# Ink mouths --------------------------------------------------------------------

def test_the_mouth_style_is_paper_unless_ink_is_asked_for():
    assert rig_style(None)["mouthStyle"] == "paper" and INK["mouthStyle"] == "ink"
    with pytest.raises(FlatRigError) as error:
        rig_style({"mouthStyle": "crayon"})
    assert error.value.code == "invalid_style"


def test_ink_mouths_keep_the_painted_mouth_and_are_sized_from_it():
    for face in (_cutout(), _realistic_face(spectacles=True, moustache=True)):
        rig, paper = rig_pose(face, INK), rig_pose(face, rig_style(None))
        assert rig["found"] is True and rig["wiped"] is False and rig["warnings"] == []
        assert np.array_equal(np.array(rig["image"]), np.array(rig["before"])), "the painted mouth is the rest shape"
        x0, _y0, x1, _y1 = rig["mouth_box"]
        edge = max(rig["width"], rig["height"])
        assert abs(rig["mouth"]["scale"] * edge - (x1 - x0) / INK_SPAN * SPRITE[1] / SPRITE[0]) <= 1
        # The blink and the eye anchor are the paper rig's.
        assert rig["eyes"] == paper["eyes"] and np.array_equal(np.array(rig["blink"]), np.array(paper["blink"]))
    assert rig_pose(_cutout(), INK)["ink"] == (40, 20, 20, 255), "the painted mouth's own ink"


def test_ink_sprites_are_openings_in_the_ink_and_closed_draws_nothing():
    ink, skin = (60, 30, 20, 255), (210, 160, 110)
    sprites = {state: np.array(draw_ink_mouth(state, ink, skin)) for state in STATES}
    for state, sprite in sprites.items():
        assert sprite.shape == (320, 512, 4), state
    assert sprites["closed"][..., 3].max() == 0 and sprites["pressed"][..., 3].max() == 0
    widths = {}
    for state in ("small", "medium", "wide", "round", "pucker", "bite", "tongue"):
        solid = sprites[state][..., 3] == 255
        colours = sprites[state][solid][:, :3]
        assert np.abs(np.median(colours, axis=0) - ink[:3]).sum() <= 3, state
        # Hard-edged: a solid shape with at most a pixel of soft edge, no glow or shading.
        assert (sprites[state][..., 3] > 0).sum() - solid.sum() <= solid.sum() * 0.25, state
        light = (colours @ LUMA > 150).sum()
        assert (light > 50) if state in ("wide", "bite") else (light == 0), f"only wide and bite show teeth: {state}"
        assert (colours.min(axis=1) > 235).sum() == 0, f"teeth are the skin toward bone, never white: {state}"
        rows, cols = np.nonzero(solid)
        widths[state] = cols.max() - cols.min() + 1
        # Each opening starts at the painted line (the sprite's middle row) and hangs below it: the upper lip stays.
        assert 160 - 0.08 * SPRITE[0] * INK_SPAN <= rows.min() <= 162 and rows.max() > 170, state
    # The pointed corners thin out to nothing: the solid shape is a few pixels short of the opening's width.
    assert -10 <= widths["wide"] - INK_OPENINGS["wide"][0] * SPRITE[0] * INK_SPAN <= 2
    assert widths["pucker"] < widths["round"] < widths["small"] < widths["medium"] < widths["wide"]


def test_an_ink_opening_hangs_from_the_painted_line_and_is_as_wide_as_it():
    face = _realistic_face(shadow=False)
    rig = rig_pose(face, INK)
    line = _drawn(face, _realistic_face(mouth=False, shadow=False))
    ys, xs = np.nonzero(line)
    talk = np.array(place(rig["image"], draw_ink_mouth("wide", rig["ink"], rig["skin"]), rig["mouth"]))
    opened = (np.abs(talk.astype(int) - np.array(rig["image"]).astype(int)).sum(axis=2) > 60) & ~line
    rows, cols = np.nonzero(opened)
    assert ys.min() - 3 <= rows.min() <= np.median(ys), "the upper lip stays: the opening starts at the painted line"
    assert 0.8 <= (cols.max() - cols.min()) / (xs.max() - xs.min()) <= 1.0


def test_an_ink_rig_saves_openings_in_the_characters_own_ink_and_wipes_nothing(tmp_path):
    folder = tmp_path / WORKSPACE
    folder.mkdir()
    _realistic_face(spectacles=True, moustache=True).save(folder / "monk-keyed.png")
    _realistic_face(mouth=False).save(folder / "monk-turn-keyed.png")
    url = f"/api/v1/file/{{}}?workspace={WORKSPACE}"
    asset = lambda aid, name: {"id": aid, "name": aid, "source": url.format(name), "kind": "image",
                               "alphaStatus": "transparent", "reviewState": "approved"}
    kit = {"id": "monk", "name": "Monk", "style": "cutout", "base": asset("monk-base", "monk-keyed.png"),
           "poses": {"turn": asset("monk-turn", "monk-turn-keyed.png")}, "mouth": {}, "eyes": {}, "anchors": {}}
    patch_character_kit(str(folder), "monk", kit, base_revision=0)
    rigged = rig_character(str(folder), WORKSPACE, "monk", base_revision=1, style={"mouthStyle": "ink"})
    assert rigged["unwipedPoses"] == ["turn"], "only the pose without a painted mouth"
    assert rigged["poses"]["base"] == {**rigged["poses"]["base"], "face": "realistic", "mouthFound": True, "wiped": False}
    saved = read_character_kit_library(str(folder))["kits"]["monk"]
    assert saved["provenance"][-1]["style"]["mouthStyle"] == "ink"
    file = lambda asset: folder / asset["source"].split("/api/v1/file/")[1].split("?")[0]
    assert np.array_equal(np.array(Image.open(file(saved["base"]))), np.array(crop_figure(Image.open(folder / "monk-keyed.png"))))
    closed, wide = (np.array(Image.open(file(saved["mouth"][state]))) for state in ("closed", "wide"))
    assert closed[..., 3].max() == 0
    assert np.abs(np.median(wide[wide[..., 3] == 255][:, :3], axis=0) - REAL_INK[:3]).sum() <= 6
    assert json.loads((folder / ".character-kit-library-v1.json").read_text())["revision"] == 2

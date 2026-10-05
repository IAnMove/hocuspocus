"""A keyed flat cutout becomes a talking Character Kit in one call."""
import json

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageDraw

from services.character_kit_library import CharacterKitRevisionConflict, patch_character_kit, read_character_kit_library
from services.flat_rig import (
    STATES, FlatRigError, _kit_warnings, crop_figure, draw_mouth, find_eyes, find_mouth, rig_character, rig_pose, rig_style,
    skin_textured, stray_marks,
)

SKIN = (246, 214, 170, 255)
WORKSPACE = "cast"


def _full_body_anime(eyes=True):
    image = Image.new("RGBA", (400, 1100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((140, 190, 260, 1080), fill=(25, 45, 70, 255))
    draw.ellipse((150, 50, 250, 170), fill=(246, 204, 145, 255))
    # Bright goggles above the face and a chrome arm must not become the eye pair.
    draw.rectangle((153, 25, 183, 43), fill=(235, 235, 235, 255))
    draw.rectangle((215, 25, 245, 43), fill=(235, 235, 235, 255))
    draw.rectangle((263, 230, 285, 430), fill=(235, 235, 235, 255))
    if eyes:
        for x in (164, 222):
            draw.ellipse((x, 95, x + 14, 118), fill=(224, 224, 212, 255))
            draw.ellipse((x + 4, 99, x + 10, 116), fill=(15, 15, 15, 255))
    return np.array(image)


def test_full_body_small_cream_eyes_avoid_goggles_and_chrome():
    pixels = _full_body_anime()
    box, mask = find_eyes(pixels[..., :3], pixels[..., 3])
    assert 160 <= box[0] < 180 and 220 < box[2] <= 240
    assert 90 <= box[1] < box[3] <= 125
    assert not mask[:50].any() and not mask[200:].any()


def test_full_body_fallback_requires_actual_eyes():
    pixels = _full_body_anime(eyes=False)
    with pytest.raises(FlatRigError, match="Two light eyes"):
        find_eyes(pixels[..., :3], pixels[..., 3])


def test_small_eyes_keep_the_lower_sclera_for_mouth_and_blink_anchors():
    image = Image.fromarray(_full_body_anime(eyes=False))
    draw = ImageDraw.Draw(image)
    for x in (164, 222):
        draw.ellipse((x, 109, x + 14, 132), fill=(224, 224, 212, 255))
        draw.ellipse((x + 4, 112, x + 10, 128), fill=(15, 15, 15, 255))
    pixels = np.array(image)
    box, _ = find_eyes(pixels[..., :3], pixels[..., 3])
    assert box[3] >= 130


def test_small_face_mouth_does_not_merge_with_a_nearby_moustache():
    image = Image.fromarray(_full_body_anime())
    draw = ImageDraw.Draw(image)
    draw.line((151, 139, 249, 139), fill=(110, 110, 105, 255), width=2)
    draw.line((187, 144, 214, 144), fill=(30, 20, 20, 255), width=2)
    pixels = np.array(image)
    box, _, _ = find_mouth(pixels[..., :3], pixels[..., 3], (164, 95, 236, 118))
    assert box[0] >= 185 and box[2] <= 216 and box[1] >= 142


def test_small_eye_rig_keeps_the_nose_and_wipes_the_mouth():
    image = Image.fromarray(_full_body_anime())
    draw = ImageDraw.Draw(image)
    draw.line((200, 123, 200, 132), fill=(30, 20, 20, 255), width=3)
    draw.line((187, 145, 214, 145), fill=(30, 20, 20, 255), width=3)
    rig = rig_pose(image, rig_style(None))
    assert rig["wiped"] is True
    # Coordinates are measured on the cropped figure, so compare the two marks there.
    assert rig["mouth_box"][3] - rig["mouth_box"][1] < 8
    assert np.array(rig["image"])[rig["mouth_box"][1]:rig["mouth_box"][3],
                                    rig["mouth_box"][0]:rig["mouth_box"][2], :3].min() > 100


def _small_o_face(o_mouth=True, nose_dot=False, ring=False) -> Image.Image:
    """The cutout face with a small open «o» mouth, much narrower than a talking mouth, and an optional nose dot
    right under the eyes."""
    image = _cutout(mouth=False)
    draw = ImageDraw.Draw(image)
    if nose_dot:
        draw.ellipse((204, 226, 216, 235), fill=(120, 70, 50, 255))
    if o_mouth:
        draw.ellipse((200, 250, 220, 274), fill=(150, 60, 60, 255) if ring else (60, 20, 25, 255),
                     outline=(40, 20, 20, 255) if ring else None, width=3)
    return image


def _lum(rig, box) -> np.ndarray:
    x0, y0, x1, y1 = box
    return np.array(rig["image"])[y0:y1, x0:x1, :3] @ np.array([0.299, 0.587, 0.114])


@pytest.mark.parametrize("ring", [False, True])
def test_a_small_round_o_mouth_is_found_and_wiped(ring):
    rig = rig_pose(_small_o_face(ring=ring, nose_dot=True), rig_style(None))
    assert rig["wiped"] is True and "mouth_not_found" not in rig["warnings"]
    x0, y0, x1, y1 = rig["mouth_box"]
    assert x1 - x0 < 30 and y1 - y0 < 30, "only the «o», not the nose above it"
    assert _lum(rig, rig["mouth_box"]).min() > 120, "no painted mouth is left to show under the paper mouths"
    # The nose dot right under the eyes stays.
    assert _lum(rig, (x0, rig["eyes_box"][3], x1, y0)).min() < 120


def test_a_small_o_mouth_under_a_nose_stroke_on_a_full_body_figure_is_wiped_and_the_nose_kept():
    image = Image.fromarray(_full_body_anime())
    draw = ImageDraw.Draw(image)
    draw.line((200, 123, 200, 132), fill=(30, 20, 20, 255), width=3)
    draw.ellipse((196, 140, 205, 150), fill=(60, 20, 25, 255))
    rig = rig_pose(image, rig_style(None))
    assert rig["wiped"] is True
    x0, y0, x1, y1 = rig["mouth_box"]
    assert x1 - x0 <= 12 and y1 - y0 <= 12
    assert _lum(rig, rig["mouth_box"]).min() > 100
    assert _lum(rig, (x0, rig["eyes_box"][3], x1, y0)).min() < 80, "the nose stroke above the mouth stays"


def test_a_nose_alone_is_not_taken_for_a_small_mouth():
    # An already rigged pose: its mouth is gone, only the nose is left under the eyes.
    for image in (_small_o_face(o_mouth=False, nose_dot=True), _cutout(mouth=False)):
        rig = rig_pose(image, rig_style(None))
        assert rig["wiped"] is False and rig["warnings"] == ["mouth_not_found"]


def _cutout(mouth=True, eyes=True, size=(420, 760), skin=SKIN, touching=False, collar=False, pen=7, smirk=False,
            sunglasses=False) -> Image.Image:
    """A paper-cutout figure on a transparent background: round head, white eyes, a painted mouth, a body."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((110, 360, 310, 740), fill=(40, 90, 200, 255))
    if collar:
        # A white shirt collar either side of a dark tie: two light blobs side by side, like a pair of eyes.
        draw.polygon([(160, 370), (205, 370), (205, 440)], fill=(255, 255, 255, 255))
        draw.polygon([(215, 370), (260, 370), (215, 440)], fill=(255, 255, 255, 255))
    draw.ellipse((60, 40, 360, 380), fill=skin)
    if eyes:
        for x in ((135, 205) if touching else (120, 220)):
            draw.ellipse((x, 120, x + 80, 220), fill=(255, 255, 255, 255))
            draw.ellipse((x + 30, 160, x + 50, 185), fill=(10, 10, 10, 255))
    if sunglasses:
        # Dark lenses over the lower part of each eye: only the eyes' tops stay white.
        for x in ((135, 205) if touching else (120, 220)):
            draw.ellipse((x - 6, 165, x + 86, 250), fill=(15, 15, 15, 255))
    if mouth:
        draw.arc((150, 260 if sunglasses else 230, 270, 330 if sunglasses else 300), 20, 160,
                 fill=(40, 20, 20, 255) if pen > 3 else (170, 145, 120, 255), width=pen)
    if smirk:
        # A smirk's curled end and a dimple beside it: separate small marks at the mouth's right end.
        draw.line((262, 268, 274, 252), fill=(40, 20, 20, 255), width=5)
        draw.ellipse((280, 262, 287, 269), fill=(60, 35, 30, 255))
    return image


def test_a_pose_gets_its_mouth_wiped_and_anchors_under_the_eyes():
    rig = rig_pose(_cutout(), rig_style({"smile": 0.4}))
    assert rig["wiped"] is True
    pixels = np.array(rig["image"])
    x0, y0, x1, y1 = rig["mouth_box"]
    lum = pixels[y0:y1, x0:x1, :3] @ np.array([0.299, 0.587, 0.114])
    assert lum.min() > 120, "no painted mouth is left to show under the paper mouths"
    assert rig["mouth"]["offsetY"] > rig["eyes"]["offsetY"]
    assert abs(rig["mouth"]["offsetX"]) < 3
    assert 0.02 < rig["mouth"]["scale"] < 0.3 and 0.05 < rig["eyes"]["scale"] < 0.4
    assert rig["blink"].mode == "RGBA" and np.array(rig["blink"])[..., 3].max() == 255


def test_a_face_without_a_painted_mouth_gets_one_placed_and_nothing_wiped():
    rig = rig_pose(_cutout(mouth=False), rig_style(None))
    assert rig["wiped"] is False and rig["mouth_box"] is None
    painted = rig_pose(_cutout(), rig_style(None))
    # Placed where the painted one would be, within a few percent of the figure.
    assert abs(rig["mouth"]["offsetY"] - painted["mouth"]["offsetY"]) < 3


def test_eyes_drawn_touching_are_found_on_the_face_not_on_the_collar():
    rig = rig_pose(_cutout(touching=True, collar=True), rig_style(None))
    x0, y0, x1, y1 = rig["eyes_box"]
    assert y1 < 260 and x1 - x0 > 120, "both eyes, on the head, not the two halves of the shirt"
    assert rig["wiped"] is True


def test_a_thin_pen_line_mouth_is_still_found_and_wiped():
    rig = rig_pose(_cutout(pen=2), rig_style(None))
    assert rig["wiped"] is True and rig["mouth_box"] is not None


def test_a_smirks_curled_end_and_dimple_are_wiped_with_the_mouth():
    rig = rig_pose(_cutout(smirk=True), rig_style(None))
    x0, y0, x1, y1 = rig["mouth_box"]
    assert x1 - x0 > 120, "the curled end and the dimple belong to the mouth"
    pixels = np.array(rig["image"])[y0 - 10:y1 + 10, x0 - 10:x1 + 10, :3]
    assert (pixels @ np.array([0.299, 0.587, 0.114])).min() > 120, "no stray stroke is left beside the drawn mouth"


def test_sunglasses_keep_the_eyes_still_and_their_mouth_is_still_wiped():
    rig = rig_pose(_cutout(sunglasses=True, touching=True), rig_style(None))
    assert rig["blinks"] is False and rig["wiped"] is True
    assert rig_pose(_cutout(), rig_style(None))["blinks"] is True
    # A dark face is not a pair of lenses: a red book cover with eyes still blinks.
    assert rig_pose(_cutout(skin=(115, 22, 26, 255)), rig_style(None))["blinks"] is True


def test_a_mark_left_beside_the_wiped_mouth_is_reported_but_a_moustache_is_not():
    rig = rig_pose(_cutout(), rig_style(None))
    assert rig["warnings"] == []
    pixels = np.array(rig["image"])
    x0, y0, x1, y1 = rig["mouth_box"]
    clean = stray_marks(pixels[..., :3], pixels[..., 3], rig["eyes_box"], rig["mouth_box"])
    dotted = pixels.copy()
    dotted[y0 + 1:y0 + 6, x1 + 4:x1 + 9, :3] = (40, 20, 20)  # a dimple just past the mouth's end
    moustache = pixels.copy()
    moustache[y0 - 30:y0 - 2, x0 - 40:x1 + 40, :3] = (90, 90, 90)  # wider than the box: the character's own
    assert clean is False and stray_marks(dotted[..., :3], dotted[..., 3], rig["eyes_box"], rig["mouth_box"]) is True
    assert stray_marks(moustache[..., :3], moustache[..., 3], rig["eyes_box"], rig["mouth_box"]) is False


def test_eyes_found_much_smaller_than_the_base_pose_are_reported():
    base = {"eyes_box": [100, 200, 280, 300], "height": 1000, "warnings": []}
    collar = {"eyes_box": [150, 440, 250, 520], "height": 1000, "warnings": ["eyes_low"]}
    same = {"eyes_box": [90, 200, 275, 300], "height": 1000, "warnings": []}
    assert _kit_warnings({"base": base, "wave": collar, "nod": same}) == {"wave": ["eyes_low", "eyes_unlike_base"]}


@pytest.mark.parametrize("image, code", [
    (Image.new("RGBA", (200, 200), (0, 0, 0, 0)), "not_keyed"),
    (_cutout(eyes=False), "eyes_not_found"),
    (_cutout(skin=(250, 250, 248, 255)), "face_too_light"),
    (_cutout(skin=(0, 0, 0, 0)), "face_keyed_out"),
])
def test_unusable_poses_say_why(image, code):
    with pytest.raises(FlatRigError) as error:
        rig_pose(image, rig_style(None))
    assert error.value.code == code


def test_every_mouth_state_is_drawn_and_the_style_is_bounded():
    style = rig_style({"smile": -0.5, "smirk": 0.4})
    for state in STATES:
        sprite = np.array(draw_mouth(state, style))
        assert sprite.shape == (320, 512, 4) and sprite[..., 3].max() == 255, state
    screen = np.array(draw_mouth("wide", rig_style({"screen": True})))
    assert screen[..., :3][screen[..., 3] > 200].mean() < 200 or screen[..., 3].max() == 255
    with pytest.raises(FlatRigError) as error:
        rig_style({"smile": 3})
    assert error.value.code == "invalid_style"


def _workspace(tmp_path):
    folder = tmp_path / WORKSPACE
    folder.mkdir()
    _cutout().save(folder / "kevin-keyed.png")
    _cutout(mouth=False).save(folder / "kevin-shrug-keyed.png")
    url = lambda name: f"/api/v1/file/{name}?workspace={WORKSPACE}"
    asset = lambda aid, name: {"id": aid, "name": aid, "source": url(name), "kind": "image",
                               "alphaStatus": "transparent", "reviewState": "approved"}
    kit = {"id": "kevin", "name": "Kevin", "style": "cutout", "base": asset("kevin-base", "kevin-keyed.png"),
           "poses": {"shrug": asset("kevin-shrug", "kevin-shrug-keyed.png")}, "mouth": {}, "eyes": {}, "anchors": {}}
    patch_character_kit(str(folder), "kevin", kit, base_revision=0)
    return folder


def test_a_kit_is_rigged_saved_and_can_be_rigged_again_from_its_original_poses(tmp_path):
    folder = _workspace(tmp_path)
    first = rig_character(str(folder), WORKSPACE, "kevin", base_revision=1, style={"smile": 0.3})
    kit = first["character"]
    assert first["revision"] == 2 and first["unwipedPoses"] == ["shrug"]
    assert first["warnings"] == {"shrug": ["mouth_not_found"]}
    assert sorted(kit["mouth"]) == sorted(STATES) and kit["mouthMapping"]["rest"] == "closed"
    assert kit["eyes"]["blink"]["reviewState"] == "approved"
    assert set(kit["anchors"]) == {"base", "shrug"}
    # Each pose closes its own eyes: a file of its own, next to the kit's (base) blink.
    blinks = {pose: kit["anchors"][pose]["blinkSource"] for pose in ("base", "shrug")}
    assert len(set(blinks.values())) == 2 and all("-blink-" in source for source in blinks.values())
    for source in blinks.values():
        assert (folder / source.split("/api/v1/file/")[1].split("?")[0]).is_file()
    assert kit["base"]["source"] != "/api/v1/file/kevin-keyed.png?workspace=cast"
    for asset in [kit["base"], kit["poses"]["shrug"], kit["eyes"]["blink"], *kit["mouth"].values()]:
        name = asset["source"].split("/api/v1/file/")[1].split("?")[0]
        assert (folder / name).is_file(), name
    assert (folder / first["review"].split("/api/v1/file/")[1].split("?")[0]).is_file()
    provenance = kit["provenance"][-1]
    assert provenance["method"] == "flat-rig"
    assert provenance["sources"]["base"] == "/api/v1/file/kevin-keyed.png?workspace=cast"

    again = rig_character(str(folder), WORKSPACE, "kevin", base_revision=2, style={"smile": -0.3}, pose_ids=["base"])
    assert again["poses"]["base"]["wiped"] is True, "the second rig reads the pose that still has its painted mouth"
    assert again["character"]["provenance"][-1]["sources"]["base"] == provenance["sources"]["base"]
    with pytest.raises(CharacterKitRevisionConflict):
        rig_character(str(folder), WORKSPACE, "kevin", base_revision=2)


def test_a_pose_replaced_after_the_first_rig_is_rigged_from_its_new_image(tmp_path):
    folder = _workspace(tmp_path)
    first = rig_character(str(folder), WORKSPACE, "kevin", base_revision=1)
    assert first["unwipedPoses"] == ["shrug"]
    _cutout().save(folder / "kevin-shrug-v2-keyed.png")
    kit = first["character"]
    kit["poses"]["shrug"] = {**kit["poses"]["shrug"], "source": f"/api/v1/file/kevin-shrug-v2-keyed.png?workspace={WORKSPACE}"}
    patch_character_kit(str(folder), "kevin", kit, base_revision=2)
    again = rig_character(str(folder), WORKSPACE, "kevin", base_revision=3)
    assert again["unwipedPoses"] == [] and again["poses"]["shrug"]["wiped"] is True
    assert again["character"]["provenance"][-1]["sources"]["shrug"].endswith("kevin-shrug-v2-keyed.png?workspace=cast")


def test_a_pose_in_sunglasses_is_saved_without_a_blink(tmp_path):
    folder = _workspace(tmp_path)
    _cutout(sunglasses=True).save(folder / "kevin-cool-keyed.png")
    library = read_character_kit_library(str(folder))
    kit = library["kits"]["kevin"]
    kit["poses"]["cool"] = {**kit["poses"]["shrug"], "id": "kevin-cool", "source": f"/api/v1/file/kevin-cool-keyed.png?workspace={WORKSPACE}"}
    patch_character_kit(str(folder), "kevin", kit, base_revision=library["revision"])
    rigged = rig_character(str(folder), WORKSPACE, "kevin", base_revision=library["revision"] + 1)
    anchors = rigged["character"]["anchors"]
    assert anchors["cool"]["blink"] is False and "blink" not in anchors["base"]
    assert "blinkSource" not in anchors["cool"] and anchors["base"]["blinkSource"].startswith("/api/v1/file/")
    assert rigged["poses"]["cool"]["blinks"] is False


def test_rigging_needs_a_workspace_base_pose(tmp_path):
    folder = _workspace(tmp_path)
    library = read_character_kit_library(str(folder))
    kit = library["kits"]["kevin"]
    kit["base"]["source"] = "https://example.com/kevin.png"
    patch_character_kit(str(folder), "kevin", kit, base_revision=library["revision"])
    with pytest.raises(FlatRigError) as error:
        rig_character(str(folder), WORKSPACE, "kevin", base_revision=library["revision"] + 1)
    assert error.value.code == "unsupported_source"
    with pytest.raises(FlatRigError) as error:
        rig_character(str(folder), WORKSPACE, "nobody", base_revision=0)
    assert error.value.status == 404


def test_the_http_route_rigs_and_reports_errors_with_a_code(tmp_path):
    from routers.character_kit_library import _bind_character_kit_library_runtime, create_character_kit_library_router

    folder = _workspace(tmp_path)
    _bind_character_kit_library_runtime(workspace_dir=lambda name: str(tmp_path / name),
                                        conflict=lambda exc: HTTPException(status_code=409, detail=str(exc)))
    app = FastAPI()
    app.include_router(create_character_kit_library_router())
    client = TestClient(app)
    path = "/api/v1/character-kits/library/kits/kevin/flat-rig"
    rigged = client.post(path, json={"workspace": WORKSPACE, "baseRevision": 1, "poses": ["base"]})
    assert rigged.status_code == 200, rigged.text
    assert rigged.json()["poses"]["base"]["wiped"] is True
    assert client.post(path, json={"workspace": WORKSPACE, "baseRevision": 1}).status_code == 409
    bad = client.post(path, json={"workspace": WORKSPACE, "baseRevision": 2, "style": {"width": 2}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_style"
    assert json.loads((folder / ".character-kit-library-v1.json").read_text())["revision"] == 2


def test_a_pose_blink_covers_its_own_eyes_where_the_base_blink_would_not(tmp_path):
    """The bug: the base blink, scaled by eye height onto a pose whose eyes sit wider, left the sclera showing."""
    from services.flat_rig import place
    wide = _cutout(size=(520, 760))
    base_rig, wide_rig = rig_pose(_cutout(), rig_style(None)), rig_pose(wide, rig_style(None))
    def white_left(rig, blink):
        x0, y0, x1, y1 = rig["eyes_box"]
        closed = np.array(place(rig["image"], blink, rig["eyes"]))[y0:y1, x0:x1, :3]
        return int((closed.min(axis=2) > 235).sum())
    assert white_left(wide_rig, wide_rig["blink"]) == 0, "its own blink closes both eyes"
    assert white_left(wide_rig, wide_rig["blink"]) <= white_left(wide_rig, base_rig["blink"])


IRIS, PUPIL, LID, BROW = (30, 40, 110, 255), (10, 12, 45, 255), (60, 20, 50, 255), (95, 55, 25, 255)


def _anime_eyes(image: Image.Image) -> Image.Image:
    """Anime eyes looking aside: a big dark iris fills most of each eye and touches a thick upper lid, so the white is
    only a crescent beside it; a highlight in the iris, a thin lower lid, and a brow above with skin between."""
    draw = ImageDraw.Draw(image)
    for x in (120, 220):
        opening = (x, 120, x + 80, 220)
        draw.ellipse(opening, fill=(255, 255, 255, 255))
        clip = Image.new("L", image.size, 0)
        ImageDraw.Draw(clip).ellipse(opening, fill=255)
        iris = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(iris).ellipse((x + 26, 112, x + 96, 228), fill=IRIS)
        ImageDraw.Draw(iris).ellipse((x + 46, 145, x + 76, 195), fill=PUPIL)
        image.paste(iris, (0, 0), ImageChops.multiply(iris.split()[3], clip))
        draw.ellipse((x + 40, 138, x + 52, 150), fill=(255, 255, 255, 255))
        draw.arc((x - 4, 116, x + 84, 226), 195, 345, fill=LID, width=14)
        draw.arc(opening, 40, 140, fill=LID, width=3)
        draw.line((x + 4, 96, x + 76, 90), fill=BROW, width=7)
    return image


def test_an_anime_eye_closes_over_its_whole_iris_and_lid_in_the_face_colour():
    """The bug: the blink covered only the white crescent, so the iris, pupil and lid showed through closed eyes, and
    the colour taken around the crescent (iris, lid) came out darker than the face."""
    from services.flat_rig import place
    rig = rig_pose(_anime_eyes(_cutout(eyes=False)), rig_style(None))
    assert rig["blinks"] is True and rig["wiped"] is True
    before = np.array(rig["image"])[..., :3].astype(int)
    closed = np.array(place(rig["image"], rig["blink"], rig["eyes"]))[..., :3].astype(int)
    face = slice(0, rig["eyes_box"][3] + 30)  # the head down to the mouth (the pose is cropped to the figure)
    painted = lambda pixels: (pixels[..., 2] - pixels[..., 1] > 15) & (pixels @ np.array([0.299, 0.587, 0.114]) < 150)
    assert painted(before[face]).sum() > 5000, "the iris, pupil and lid are there with the eyes open"
    assert painted(closed[face]).sum() == 0, "no iris, pupil or lid pixel shows through the closed eyes"
    assert (closed[face].min(axis=2) > 235).sum() == 0, "nor any of the white"
    sprite = np.array(rig["blink"])
    cover = np.median(sprite[sprite[..., 3] == 255][:, :3], axis=0)
    assert np.abs(cover - np.array(SKIN[:3])).sum() <= 12, f"the lids are the face colour, not {cover}"
    brow = np.all(before == BROW[:3], axis=2)
    assert brow.sum() > 500 and np.array_equal(closed[brow], before[brow]), "the brows stay as they are"


def test_a_screen_face_closes_its_light_eyes_in_the_screen_colour_with_a_light_lid():
    """A laptop's face keeps its blink: light eyes on a dark screen, covered in the screen colour."""
    from services.flat_rig import SCREEN_INK, place
    screen = (18, 30, 80, 255)
    image = Image.new("RGBA", (420, 760), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((110, 360, 310, 740), fill=(90, 90, 95, 255))
    draw.rounded_rectangle((50, 40, 370, 360), radius=20, fill=(60, 60, 66, 255))
    draw.rectangle((70, 60, 350, 340), fill=screen)
    for x in (120, 230):
        draw.rounded_rectangle((x, 120, x + 70, 200), radius=18, fill=(240, 245, 255, 255))
        draw.ellipse((x + 25, 140, x + 45, 175), fill=screen)
    rig = rig_pose(image, rig_style({"screen": True}))
    sprite = np.array(rig["blink"])
    assert np.array_equal(np.median(sprite[sprite[..., 3] == 255][:, :3], axis=0), screen[:3])
    lid = np.abs(sprite[..., :3].astype(int) - SCREEN_INK[:3]).sum(axis=2) < 30
    assert (lid & (sprite[..., 3] == 255)).sum() > 100, "a light lid line, not a dark one"
    x0, y0, x1, y1 = rig["eyes_box"]
    lit = lambda frame: int((np.array(frame)[y0:y1, x0:x1, :3].min(axis=2) > 200).sum())
    assert lit(place(rig["image"], rig["blink"], rig["eyes"])) < lit(rig["image"]) * 0.15, "only the lids are light"


def test_a_wide_pair_of_eyes_gets_a_blink_no_wider_than_the_frame_so_video_2d_draws_it_full_size():
    """Video 2D fits a layer into a 16:9 box: a 2.5:1 blink was drawn at ~70% and the sclera showed around the lids."""
    from services.flat_rig import MAX_SPRITE_RATIO, _blink_box
    for image in (_cutout(), _cutout(size=(520, 760))):
        rig = rig_pose(image, rig_style(None))
        blink = rig["blink"]
        assert blink.width / blink.height <= MAX_SPRITE_RATIO + 0.02
        edge = max(rig["width"], rig["height"])
        assert abs(rig["eyes"]["scale"] * edge - blink.height) <= 1, "the anchor height is the sprite height"
    assert _blink_box(100, 200, 350, 260, 1000) == (100, 159, 350, 300)
    assert _blink_box(100, 10, 350, 70, 1000)[1] == 0, "near the top it grows downward instead"
    assert _blink_box(100, 200, 200, 260, 1000) == (100, 200, 200, 260), "a sprite already narrow enough is unchanged"


CODE, GLYPH = (18, 58, 30, 255), (110, 230, 120, 255)


def _code_face(mouth=True, seed=7) -> Image.Image:
    """A face drawn as falling code: columns of light glyph strokes on a dark green face, white eyes and a black slit
    mouth. The gaps between the glyphs are as dark against them as a pen line is against skin."""
    rng = np.random.default_rng(seed)
    image = _cutout(mouth=False, eyes=False, skin=CODE)
    glyphs = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glyphs)
    for x in range(62, 358, 6):
        y = 40 + int(rng.integers(0, 8))
        while y < 380:
            tall = int(rng.integers(4, 11))
            draw.rectangle((x, y, x + 2, y + tall), fill=GLYPH)
            if rng.random() < 0.4:
                draw.rectangle((x, y + tall // 2, x + 4, y + tall // 2 + 1), fill=GLYPH)
            y += tall + int(rng.integers(3, 7))
    head = Image.new("L", image.size, 0)
    ImageDraw.Draw(head).ellipse((60, 40, 360, 380), fill=255)
    image.paste(glyphs, (0, 0), ImageChops.multiply(glyphs.split()[3], head))
    draw = ImageDraw.Draw(image)
    for x in (120, 220):
        draw.ellipse((x, 120, x + 80, 220), fill=(255, 255, 255, 255))
        draw.ellipse((x + 30, 160, x + 50, 185), fill=(10, 10, 10, 255))
    if mouth:
        draw.ellipse((150, 252, 270, 274), fill=(6, 6, 6, 255))
    return image


@pytest.mark.parametrize("screen", [False, True])
def test_a_mouth_painted_on_a_textured_face_is_found_and_wiped_with_the_texture(screen):
    """The bug: on a face made of code glyphs the gaps between the glyphs were taken for marks (and on a screen face,
    the glyphs), so no mouth was found, the painted slit stayed and the animated mouth was drawn under it."""
    rig = rig_pose(_code_face(), rig_style({"screen": screen}))
    assert rig["wiped"] is True and "mouth_not_found" not in rig["warnings"]
    before = np.array(rig["before"])
    slit = (before[..., :3] @ np.array([0.299, 0.587, 0.114]) < 20) & (before[..., 3] > 200)
    slit[:rig["eyes_box"][3]] = False  # the pupils
    ys, xs = np.nonzero(slit)
    x0, y0, x1, y1 = rig["mouth_box"]
    assert abs(x0 - xs.min()) <= 2 and abs(x1 - xs.max() - 1) <= 2 and abs(y0 - ys.min()) <= 2 and abs(y1 - ys.max() - 1) <= 2
    # The animated mouth sits where the painted one was, not under it.
    edge = max(rig["width"], rig["height"])
    assert abs(rig["height"] / 2 + rig["mouth"]["offsetY"] * edge / 100 - (ys.min() + ys.max()) / 2) <= 2
    inside = _lum(rig, rig["mouth_box"])
    assert inside.min() > 30, "no black of the slit is left"
    # The glyphs go on through the wiped box, as varied as the face under it; inpainting smeared them into a smudge.
    below = _lum(rig, (x0, y1 + 20, x1, y1 + 20 + (y1 - y0)))
    assert inside.std() > below.std() * 0.7 and abs(inside.mean() - below.mean()) < below.mean() * 0.25


def test_a_textured_face_without_a_painted_mouth_has_nothing_wiped():
    for screen in (False, True):
        rig = rig_pose(_code_face(mouth=False), rig_style({"screen": screen}))
        assert rig["wiped"] is False and "mouth_not_found" in rig["warnings"]


def test_only_a_textured_face_is_filled_with_its_texture_and_plain_faces_keep_the_inpaint():
    """Lines drawn on a plain face (a smirk, anime lids and brows, a small full-body face) are not a texture."""
    for image, textured in [(_cutout(), False), (_cutout(smirk=True), False), (_anime_eyes(_cutout(eyes=False)), False),
                            (Image.fromarray(_full_body_anime()), False), (_code_face(), True)]:
        pixels = np.array(crop_figure(image))
        box, _ = find_eyes(pixels[..., :3], pixels[..., 3])
        assert skin_textured(pixels[..., :3], pixels[..., 3], box) is textured

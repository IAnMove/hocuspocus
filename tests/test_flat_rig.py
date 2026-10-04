"""A keyed flat cutout becomes a talking Character Kit in one call."""
import json

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from services.character_kit_library import CharacterKitRevisionConflict, patch_character_kit, read_character_kit_library
from services.flat_rig import STATES, FlatRigError, draw_mouth, rig_character, rig_pose, rig_style

SKIN = (246, 214, 170, 255)
WORKSPACE = "cast"


def _cutout(mouth=True, eyes=True, size=(420, 760)) -> Image.Image:
    """A paper-cutout figure on a transparent background: round head, white eyes, a painted mouth, a body."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((110, 360, 310, 740), fill=(40, 90, 200, 255))
    draw.ellipse((60, 40, 360, 380), fill=SKIN)
    if eyes:
        for x in (120, 220):
            draw.ellipse((x, 120, x + 80, 220), fill=(255, 255, 255, 255))
            draw.ellipse((x + 30, 160, x + 50, 185), fill=(10, 10, 10, 255))
    if mouth:
        draw.arc((150, 230, 270, 300), 20, 160, fill=(40, 20, 20, 255), width=7)
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
    assert rig["mouth"]["offsetY"] > rig["eyes"]["offsetY"]


@pytest.mark.parametrize("image, code", [
    (Image.new("RGBA", (200, 200), (0, 0, 0, 0)), "not_keyed"),
    (_cutout(eyes=False), "eyes_not_found"),
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
    assert sorted(kit["mouth"]) == sorted(STATES) and kit["mouthMapping"]["rest"] == "closed"
    assert kit["eyes"]["blink"]["reviewState"] == "approved"
    assert set(kit["anchors"]) == {"base", "shrug"}
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

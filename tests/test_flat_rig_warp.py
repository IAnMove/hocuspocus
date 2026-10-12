"""Warp mouths: each pose talks with its own drawing (flat_rig_warp), per-pose sources on the kit and the preview."""
import base64
import io
import json

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from routers import character_kit_library as router_module
from services import face_landmarks, flat_rig_preview, flat_rig_warp
from services.character_kit_library import normalize_character_kit, patch_character_kit, read_character_kit_library
from services.flat_rig import FlatRigError, rig_character, rig_hints, rig_style
from services.flat_rig_look import kit_look
from services.flat_rig_base import STATES
from services.world3d_talk import talk_block

SKIN = (205, 140, 70, 255)
LINE = (25, 15, 10, 255)
BEARD, STRAND = (70, 45, 28, 255), (150, 118, 84, 255)
MOUTH_Y, MOUTH_X = 305, (170, 250)


def _face(shift=(0, 0), beard=True, moustache=False, fold=True) -> Image.Image:
    """A graphic-novel head: white eyes, a nose wedge, a fold from the nose past the mouth's left corner, the mouth a
    pen line, and a beard of dark hair with light strands under the chin skin."""
    dx, dy = shift
    image = Image.new("RGBA", (440, 780), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((110 + dx, 480 + dy, 330 + dx, 770 + dy), fill=(90, 30, 30, 255))
    draw.ellipse((60 + dx, 40 + dy, 380 + dx, 470 + dy), fill=SKIN)
    for x0, y0, x1, y1 in ((120, 140, 200, 190), (240, 140, 320, 190)):
        draw.ellipse((x0 + dx, y0 + dy, x1 + dx, y1 + dy), fill=(255, 255, 255, 255), outline=LINE, width=5)
        draw.ellipse(((x0 + x1) / 2 - 9 + dx, y0 + 14 + dy, (x0 + x1) / 2 + 9 + dx, y0 + 36 + dy), fill=LINE)
    draw.polygon([(215 + dx, 205 + dy), (238 + dx, 258 + dy), (206 + dx, 262 + dy)], fill=LINE)
    if fold:
        draw.line((168 + dx, 240 + dy, 150 + dx, 330 + dy), fill=LINE, width=4)
    if moustache:
        draw.ellipse((150 + dx, 262 + dy, 270 + dx, 297 + dy), fill=BEARD)
    if beard:
        draw.rectangle((140 + dx, 345 + dy, 280 + dx, 450 + dy), fill=BEARD)
        for x in range(146, 280, 9):
            draw.line((x + dx, 352 + dy, x + dx, 440 + dy), fill=STRAND, width=2)
    draw.line((MOUTH_X[0] + dx, MOUTH_Y + dy, MOUTH_X[1] + dx, MOUTH_Y + dy), fill=LINE, width=6)
    return image


def _lips(shift=(0, 0), low=0.0):
    """DWPose's outer lips round the mouth; ``low`` moves them down (a lower lip found on the beard)."""
    dx, dy = shift
    x0, x1 = MOUTH_X
    upper = [[x0 + (x1 - x0) * i / 6 + dx, MOUTH_Y - 8 * np.sin(np.pi * i / 6) + dy + low] for i in range(1, 6)]
    lower = [[x1 - (x1 - x0) * i / 6 + dx, MOUTH_Y + 10 * np.sin(np.pi * i / 6) + dy + low] for i in range(1, 6)]
    return [[x0 + dx, MOUTH_Y + dy + low], *upper, [x1 + dx, MOUTH_Y + dy + low], *lower]


def _pixels(image):
    return np.array(image.convert("RGBA"))


def _composite(base: np.ndarray, patch: Image.Image, box) -> np.ndarray:
    x0, y0, _side = box
    out = Image.fromarray(base)
    out.alpha_composite(patch, (x0, y0))
    return np.array(out)


def _line(face, **seeds):
    return flat_rig_warp.mouth_line(_pixels(face), **seeds)


def test_the_line_snaps_onto_the_pen_line_not_the_fold_or_the_landmarks_low_guess():
    face = _face()
    line = _line(face, lips=_lips(low=12))
    cx, cy = line.centre
    assert line.found and line.source == "landmarks"
    assert abs(cy - MOUTH_Y) <= 2, "the pen line, not the landmarks' midline 12 px lower"
    assert abs(line.width - (MOUTH_X[1] - MOUTH_X[0])) < 1 and abs(cx - sum(MOUTH_X) / 2) < 1


def test_a_moustache_edge_above_the_mouth_is_not_taken_for_its_line():
    face = _face(moustache=True)
    line = _line(face, lips=_lips(low=-12))
    assert line.found and abs(line.centre[1] - MOUTH_Y) <= 2, "dark on one side only: a moustache's edge"


def test_an_exact_hint_point_is_kept_and_only_snapped_a_little():
    face = _face()
    near = _line(face, point=(210, MOUTH_Y + 4), width=80, exact=True)
    assert near.source == "hint" and near.found and abs(near.centre[1] - MOUTH_Y) <= 2
    # Far from any stroke an exact hint is kept as given: a person placed it.
    far = _line(face, point=(210, 380), width=80, exact=True)
    assert not far.found and abs(far.centre[1] - 380) < 0.5 and far.width == 80
    off = _line(face, point=(210, MOUTH_Y + 22), width=80, exact=True)
    assert not off.found and abs(off.centre[1] - (MOUTH_Y + 22)) < 0.5, "22 px off is where the person put it"


def test_a_hint_typed_without_looking_is_snapped_onto_the_painted_lips():
    # An agent's point 22 px (0.28 mouth widths) under the lips: the line is drawn on the lips, as the landmarks' is.
    off = _line(_face(), point=(210, MOUTH_Y + 22), width=80)
    assert off.source == "hint" and off.found and abs(off.centre[1] - MOUTH_Y) <= 2


def test_a_line_placed_by_unsure_landmarks_or_found_nowhere_is_flagged():
    face = _face()
    sure = _line(face, lips=_lips())
    assert flat_rig_warp.line_warnings(sure, {"lips_score": 0.9}) == []
    assert flat_rig_warp.line_warnings(sure, {"lips_score": 0.39}) == ["mouth_line_unsure"]
    nowhere = _line(face, point=(210, 380), width=80, exact=True)
    assert flat_rig_warp.line_warnings(nowhere, {}) == ["mouth_line_guessed"]


def test_closed_is_the_drawing_unchanged_so_no_seam_shows():
    face = _face()
    pixels = _pixels(face)
    line = _line(face, lips=_lips())
    box, patches = flat_rig_warp.pose_patches(pixels, line)
    closed = np.array(patches["closed"])
    x0, y0, side = box
    assert closed.shape == (side, side, 4), "a square patch"
    crop = pixels[y0:y0 + side, x0:x0 + side]
    shown = closed[..., 3] > 0
    assert shown.any() and (closed[..., :3][shown] == crop[..., :3][shown]).all()
    assert not closed[..., 3][crop[..., 3] < 255].any(), "nothing laid over the see-through outline or background"
    assert (_composite(pixels, patches["closed"], box) == pixels).all()


def test_an_open_mouth_opens_under_the_line_and_between_the_corners():
    face = _face(fold=False)
    pixels = _pixels(face)
    line = _line(face, lips=_lips())
    box, patches = flat_rig_warp.pose_patches(pixels, line)
    wide = _composite(pixels, patches["wide"], box)
    lum = lambda a: a[..., :3].astype(float) @ [0.299, 0.587, 0.114]
    opened = (lum(wide) < 50) & (lum(pixels) > 100)
    opened[MOUTH_Y + 40:] = False      # lower down the beard moving down darkens the skin under it
    ys, xs = np.nonzero(opened)
    drop = round(flat_rig_warp.WARP_STATES["wide"][0] * line.width)
    assert len(xs) > 200
    assert xs.min() >= MOUTH_X[0] - 2 and xs.max() <= MOUTH_X[1] + 2, "inside the mouth's corners"
    assert ys.min() >= MOUTH_Y - 3 and ys.max() <= MOUTH_Y + drop + 4, "under the line, as deep as the jaw drops"
    # Only wide and bite show teeth, under the upper lip; they are muted, never paper white.
    mouth = np.zeros(opened.shape, bool)
    mouth[MOUTH_Y - 3:MOUTH_Y + drop, MOUTH_X[0]:MOUTH_X[1]] = True
    teeth = mouth & (lum(wide) > 150) & (lum(pixels) < 60)
    assert teeth.any() and wide[teeth][:, :3].min(axis=1).max() < 235
    medium = _composite(pixels, patches["medium"], box)
    assert not (mouth & (lum(medium) > 150) & (lum(pixels) < 60)).any()


def test_the_beard_moves_down_with_the_jaw_and_is_not_erased():
    face = _face()
    pixels = _pixels(face)
    line = _line(face, lips=_lips())
    box, patches = flat_rig_warp.pose_patches(pixels, line)
    wide = _composite(pixels, patches["wide"], box)
    drop = round(flat_rig_warp.WARP_STATES["wide"][0] * line.width)

    def strands(a):
        near = np.abs(a[..., :3].astype(int) - STRAND[:3]).sum(axis=2) < 30
        near[:, :195] = near[:, 226:] = False      # the middle of the jaw, which moves whole
        return near
    before, after = strands(pixels), strands(wide)
    # The jaw eases back to still under the beard: its tips are pressed together a little, never torn or smeared.
    assert before.sum() * 0.85 <= after.sum() <= before.sum(), "moved, not smeared or erased"
    assert drop * 0.7 <= np.nonzero(after)[0].mean() - np.nonzero(before)[0].mean() <= drop
    assert not after[:np.nonzero(before)[0].min()].any(), "no strand drawn above where the beard starts"
    # The middle of the jaw is a whole-pixel move: the strands are copied, not resampled.
    rows = slice(370, 400)
    assert (wide[rows.start + drop:rows.stop + drop, 200:220] == pixels[rows, 200:220]).all()


def test_each_state_fades_out_at_the_patch_edge_where_nothing_moves():
    face = _face()
    pixels = _pixels(face)
    line = _line(face, lips=_lips())
    box, patches = flat_rig_warp.pose_patches(pixels, line)
    x0, y0, side = box
    crop = pixels[y0:y0 + side, x0:x0 + side]
    edge = np.zeros((side, side), bool)
    edge[:2], edge[-2:], edge[:, :2], edge[:, -2:] = True, True, True, True
    for state in STATES:
        patch = np.array(patches[state])
        assert (patch[..., 3][edge] <= 10).all(), state
        ring = np.zeros((side, side), bool)
        ring[:int(side * 0.06)] = ring[-int(side * 0.06):] = True
        same = ring & (patch[..., 3] > 0)
        assert (patch[..., :3][same] == crop[..., :3][same]).all(), f"{state}: unmoved where it fades"


def test_warp_style_and_mouth_width_hints_are_validated():
    assert rig_style({"mouthStyle": "warp"})["mouthStyle"] == "warp"
    with pytest.raises(FlatRigError):
        rig_style({"mouthStyle": "clay"})
    assert rig_hints({"base": {"mouth": [40, 30], "mouthWidth": 6.25}}) == {"base": {"mouth": [40.0, 30.0], "mouthWidth": 6.25}}
    for bad in (0, 101, True, "6", [6]):
        with pytest.raises(FlatRigError):
            rig_hints({"base": {"mouthWidth": bad}})


def _kit(folder, poses=("busto",)):
    _face().save(folder / "hero.png")
    for index, pose in enumerate(poses):
        _face(shift=(14 * (index + 1), 22 * (index + 1))).save(folder / f"hero-{pose}.png")
    asset = lambda name: {"id": f"hero-{name}", "name": name, "source": f"/api/v1/file/{name}.png?workspace=cast",
                          "kind": "image", "alphaStatus": "transparent", "reviewState": "approved"}
    patch_character_kit(str(folder), "hero", {"id": "hero", "name": "Hero", "style": "cutout", "base": asset("hero"),
                                              "poses": {pose: asset(f"hero-{pose}") for pose in poses},
                                              "mouth": {}, "eyes": {}, "anchors": {}}, base_revision=0)


def _shifted_lips(image):
    """Landmarks for the test poses: each is the same face moved by a multiple of (14, 22)."""
    rows = np.nonzero(np.array(image.convert("RGBA"))[..., 3].any(axis=1))[0]
    step = (int(rows.min()) - 40) // 22
    return {"eyes": [[[120, 165]] * 6, [[320, 165]] * 6], "mouth": _lips(shift=(14 * step, 22 * step)),
            "scores": {"eyes": 0.1, "mouth": 0.9}}


def test_a_warp_rig_saves_each_poses_own_mouths(tmp_path, monkeypatch):
    folder = tmp_path / "cast"
    folder.mkdir()
    _kit(folder)
    monkeypatch.setattr(face_landmarks, "detect", _shifted_lips)
    rigged = rig_character(str(folder), "cast", "hero", base_revision=1, style={"mouthStyle": "warp"})
    kit = rigged["character"]
    base, busto = kit["anchors"]["base"]["mouthSources"], kit["anchors"]["busto"]["mouthSources"]
    assert set(base) == set(busto) == set(STATES)
    assert not set(base.values()) & set(busto.values()), "cut from each pose's own drawing"
    assert {state: asset["source"] for state, asset in kit["mouth"].items()} == base, "the kit's are the base pose's"
    for pose in ("base", "busto"):
        line = rigged["poses"][pose]["mouthLine"]
        assert line["found"] and line["from"] == "landmarks"
        image = Image.open(folder / ("hero.png" if pose == "base" else "hero-busto.png"))
        assert abs(line["mouth"][1] / 100 * image.height - (MOUTH_Y + (22 if pose == "busto" else 0))) <= 2
        patch = Image.open(folder / kit["anchors"][pose]["mouthSources"]["closed"].split("/api/v1/file/")[1].split("?")[0])
        assert patch.width == patch.height and kit["anchors"][pose]["mouth"]["scale"] > 0
    provenance = kit["provenance"][-1]
    assert provenance["style"]["mouthStyle"] == "warp" and set(provenance["mouthLines"]) == {"base", "busto"}
    stored = read_character_kit_library(str(folder))["kits"]["hero"]
    assert stored["anchors"]["busto"]["mouthSources"] == busto


def test_the_closed_patch_lies_exactly_on_its_pose(tmp_path, monkeypatch):
    folder = tmp_path / "cast"
    folder.mkdir()
    _kit(folder)
    monkeypatch.setattr(face_landmarks, "detect", _shifted_lips)
    kit = rig_character(str(folder), "cast", "hero", base_revision=1, style={"mouthStyle": "warp"})["character"]
    for pose, asset in (("base", kit["base"]), ("busto", kit["poses"]["busto"])):
        image = _pixels(Image.open(folder / asset["source"].split("/api/v1/file/")[1].split("?")[0]))
        anchor = kit["anchors"][pose]["mouth"]
        patch = Image.open(folder / kit["anchors"][pose]["mouthSources"]["closed"].split("/api/v1/file/")[1].split("?")[0])
        edge = max(image.shape[1], image.shape[0])
        side = anchor["scale"] * edge
        x0 = image.shape[1] / 2 + anchor["offsetX"] * edge / 100 - side / 2
        y0 = image.shape[0] / 2 + anchor["offsetY"] * edge / 100 - side / 2
        assert abs(side - patch.width) < 0.05 and abs(x0 - round(x0)) < 0.05 and abs(y0 - round(y0)) < 0.05
        assert (_composite(image, patch, (round(x0), round(y0), patch.width)) == image).all(), pose


def test_a_saved_mouth_hint_with_its_width_places_the_line(tmp_path, monkeypatch):
    folder = tmp_path / "cast"
    folder.mkdir()
    _kit(folder, poses=())
    monkeypatch.setattr(face_landmarks, "detect", lambda image: None)
    image = Image.open(folder / "hero.png")
    hint = {"base": {"mouth": [210 / image.width * 100, (MOUTH_Y + 3) / image.height * 100], "mouthWidth": 70 / image.width * 100}}
    rigged = rig_character(str(folder), "cast", "hero", base_revision=1, style={"mouthStyle": "warp"}, hints=hint)
    line = rigged["poses"]["base"]["mouthLine"]
    assert line["from"] == "hint" and line["found"] and abs(line["mouthWidth"] / 100 * image.width - 70) < 0.5
    assert abs(line["mouth"][1] / 100 * image.height - MOUTH_Y) <= 2
    assert rigged["character"]["provenance"][-1]["hints"]["base"]["mouthWidth"] == round(hint["base"]["mouthWidth"], 3)


def test_pose_mouth_sources_are_validated_on_the_kit():
    kit = {"id": "hero", "name": "Hero", "anchors": {"busto": {"mouth": {"offsetX": 0, "offsetY": 0, "scale": 0.1},
                                                               "mouthSources": {"wide": "/api/v1/file/w.png?workspace=w"}}}}
    assert normalize_character_kit(kit)["anchors"]["busto"]["mouthSources"] == {"wide": "/api/v1/file/w.png?workspace=w"}
    for bad in ({"yell": "/api/v1/file/w.png"}, {"wide": "blob:http://x/1"}, {"wide": "data:image/png;base64,AA"}, {}, ["w.png"]):
        with pytest.raises(ValueError):
            normalize_character_kit({**kit, "anchors": {"busto": {**kit["anchors"]["busto"], "mouthSources": bad}}})


def test_a_video3d_cutout_talks_with_the_poses_own_mouths():
    approved = lambda source: {"source": source, "reviewState": "approved"}
    anchor = {"offsetX": 0, "offsetY": 0, "scale": 0.1}
    kit = {"id": "hero", "name": "Hero", "base": approved("b.png"), "poses": {"busto": approved("p.png"), "new": approved("n.png")},
           "mouth": {"closed": approved("base-closed.png"), "wide": approved("base-wide.png")},
           "anchors": {"base": {"mouth": anchor, "mouthSources": {"closed": "base-closed.png", "wide": "base-wide.png"}},
                       "busto": {"mouth": anchor, "mouthSources": {"closed": "busto-closed.png", "wide": "busto-wide.png"}},
                       "new": {"mouth": anchor}}}
    assert talk_block(kit, [], pose="busto", blink=False)["mouths"] == {"closed": "busto-closed.png", "wide": "busto-wide.png"}
    assert talk_block(kit, [], pose="base", blink=False)["mouths"] == {"closed": "base-closed.png", "wide": "base-wide.png"}
    with pytest.raises(Exception, match="mouth"):
        talk_block(kit, [], pose="new", blink=False)    # never the base pose's face on another pose
    # A drawing put on the kit later is every pose's again.
    kit["mouth"]["wide"] = approved("pack-wide.png")
    assert talk_block(kit, [], pose="busto", blink=False)["mouths"] == {"closed": "busto-closed.png", "wide": "pack-wide.png"}


def _client(folder):
    router_module._bind_character_kit_library_runtime(workspace_dir=lambda workspace: str(folder), conflict=lambda exc: exc)
    app = FastAPI()
    app.include_router(router_module.create_character_kit_library_router())
    return TestClient(app)


def test_a_re_rig_keeps_the_kits_warp_mouths_unless_asked(tmp_path, monkeypatch):
    """A pose added later, or an agent's re-rig, sends no style: the kit stays warp. A key sent wins on its own."""
    folder = tmp_path / "cast"
    folder.mkdir()
    _kit(folder)
    monkeypatch.setattr(face_landmarks, "detect", _shifted_lips)
    first = rig_character(str(folder), "cast", "hero", base_revision=1, style={"mouthStyle": "warp", "smile": 0.4})
    reply = _client(folder).post("/api/v1/character-kits/library/kits/hero/flat-rig",
                                 json={"workspace": "cast", "baseRevision": first["revision"], "poses": ["base", "busto"]})
    assert reply.status_code == 200, reply.text
    again = reply.json()
    assert again["style"]["mouthStyle"] == "warp" and again["style"]["smile"] == 0.4
    assert again["poses"]["busto"]["mouthLine"]["found"] and again["character"]["anchors"]["busto"]["mouthSources"]
    assert again["character"]["provenance"][-1]["style"] == again["style"]
    paper = rig_character(str(folder), "cast", "hero", base_revision=again["revision"], style={"mouthStyle": "paper"})
    assert paper["style"]["mouthStyle"] == "paper" and paper["style"]["smile"] == 0.4
    assert "mouthSources" not in paper["character"]["anchors"]["busto"]


def test_a_kit_made_in_the_graphic_novel_style_rigs_with_warp_mouths(tmp_path, monkeypatch):
    folder = tmp_path / "cast"
    folder.mkdir()
    _kit(folder, poses=())
    library = read_character_kit_library(str(folder))
    made = {**library["kits"]["hero"], "provenance": [{"method": "character-style-create", "style": "graphic-novel"}]}
    revision = patch_character_kit(str(folder), "hero", made, base_revision=library["revision"])["revision"]
    monkeypatch.setattr(face_landmarks, "detect", _shifted_lips)
    rigged = rig_character(str(folder), "cast", "hero", base_revision=revision)
    assert rigged["style"]["mouthStyle"] == "warp" and rigged["character"]["anchors"]["base"]["mouthSources"]


def test_the_kit_look_is_the_last_rig_then_the_style_preset_then_the_defaults():
    preset = lambda style_id: {"method": "character-style-create", "style": style_id}
    rigged = lambda style: {"method": "flat-rig", "style": style}
    assert kit_look({}) == rig_style(None) and kit_look({})["mouthStyle"] == "paper"
    assert kit_look({"provenance": [preset("graphic-novel")]})["mouthStyle"] == "warp"
    assert kit_look({"provenance": [preset("paper-cutout")]})["mouthStyle"] == "paper"
    assert kit_look({"provenance": [preset("unknown")]}) == rig_style(None)
    # The latest decision wins: a kit made in one style and rigged in another keeps the rig's look.
    kit = {"provenance": [preset("graphic-novel"), rigged({"mouthStyle": "ink", "smile": 0.2}), {"method": "lips"}]}
    assert kit_look(kit)["mouthStyle"] == "ink" and kit_look(kit)["smile"] == 0.2
    assert kit_look(kit, {"smile": -0.5}) == {**rig_style({"mouthStyle": "ink"}), "smile": -0.5}
    # A look edited by hand into nonsense is ignored, as saved hints are; the call's own style is still checked.
    assert kit_look({"provenance": [rigged({"mouthStyle": "clay"})]}) == rig_style(None)
    with pytest.raises(FlatRigError):
        kit_look(kit, {"mouthStyle": "clay"})


def test_the_preview_warps_a_pose_at_a_point_and_saves_nothing(tmp_path, monkeypatch):
    folder = tmp_path / "cast"
    folder.mkdir()
    _kit(folder)
    calls = []
    monkeypatch.setattr(face_landmarks, "detect", lambda image: calls.append(image.size) or _shifted_lips(image))
    flat_rig_preview._CACHE.clear()
    before = (folder / ".character-kit-library-v1.json").read_bytes()
    client = _client(folder)
    image = Image.open(folder / "hero-busto.png")
    body = {"workspace": "cast", "pose": "busto", "mouth": [224 / image.width * 100, (MOUTH_Y + 25) / image.height * 100],
            "mouthWidth": 80 / image.width * 100}
    reply = client.post("/api/v1/character-kits/library/kits/hero/flat-rig/preview", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert list(data["states"]) == list(flat_rig_preview.PREVIEW_STATES) and data["from"] == "hint" and data["found"]
    assert abs(data["mouth"][1] / 100 * image.height - (MOUTH_Y + 22)) <= 2, "snapped onto this pose's own line"
    tile = Image.open(io.BytesIO(base64.b64decode(data["states"]["wide"].split(",", 1)[1])))
    assert tile.size == (flat_rig_preview.TILE, flat_rig_preview.TILE)
    # The same pose again only warps: its landmarks are remembered.
    assert client.post("/api/v1/character-kits/library/kits/hero/flat-rig/preview", json=body).status_code == 200
    assert calls == [image.size]
    assert (folder / ".character-kit-library-v1.json").read_bytes() == before
    sheet = client.post("/api/v1/character-kits/library/kits/hero/flat-rig/preview",
                        json={"workspace": "cast", "pose": "base", "sheet": True, "states": ["closed", "wide"]}).json()
    name = sheet["sheet"].split("/api/v1/file/")[1].split("?")[0]
    assert "states" not in sheet and name.startswith(".") and (folder / name).is_file(), "kept out of the media library"
    assert sheet["from"] == "landmarks"
    assert json.loads((folder / ".character-kit-library-v1.json").read_text())["revision"] == 1


def test_the_preview_refuses_unknown_poses_states_and_points(tmp_path, monkeypatch):
    folder = tmp_path / "cast"
    folder.mkdir()
    _kit(folder)
    monkeypatch.setattr(face_landmarks, "detect", lambda image: None)
    client = _client(folder)
    url = "/api/v1/character-kits/library/kits/hero/flat-rig/preview"
    assert client.post(url, json={"workspace": "cast", "pose": "jump"}).json()["detail"]["code"] == "unknown_pose"
    assert client.post(url, json={"workspace": "cast", "pose": "base", "states": ["yell"]}).json()["detail"]["code"] == "invalid_states"
    assert client.post(url, json={"workspace": "cast", "pose": "base", "mouth": [120, 3]}).json()["detail"]["code"] == "invalid_hints"
    assert client.post("/api/v1/character-kits/library/kits/nobody/flat-rig/preview", json={"workspace": "cast"}).status_code == 404

"""Character animations: the catalog, a pose's prompt, the kit field and the sprite sheet built from keyed poses."""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from services import character_animations as animations
from services.character_animations import CharacterAnimationError, build_sheet, catalog, normalize_kit_animations, pose_prompt


def _figure(path: Path, *, legs: tuple[int, int], torso_at: int = 60, height: int = 200, width: int = 140) -> Path:
    """A keyed pose: a head and a trunk centred on ``torso_at`` and two legs reaching to the bottom at the given columns."""
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[10:40, torso_at - 15:torso_at + 15] = (200, 160, 120, 255)  # head
    pixels[40:110, torso_at - 22:torso_at + 22] = (230, 180, 30, 255)  # trunk
    for column in legs:
        pixels[110:height, column - 6:column + 6] = (60, 60, 70, 255)
    Image.fromarray(pixels).save(path)
    return path


def _sheet_of(tmp_path, poses):
    return build_sheet([p.name for p in poses], uploads_root=str(tmp_path / "uploads"), workspace_root=str(tmp_path),
                       workspace="demo", name="walk", output_dir=str(tmp_path))


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "uploads").mkdir()
    return tmp_path


def test_every_animation_has_poses_prompts_and_a_template():
    data = catalog()
    ids = [item["id"] for item in data["animations"]]
    assert len(ids) == len(set(ids)) and {"walk", "run", "wave", "angry", "surprised", "sad", "happy", "embarrassed"} <= set(ids)
    groups = {group["id"] for group in data["groups"]}
    assert groups == {"cycle", "gesture", "expression", "custom"}, "custom is the author's own: the catalog lists none"
    for item in data["animations"]:
        assert item["group"] in groups and item["view"] in data["views"] and item["loop"] in animations.LOOPS
        assert {"en", "es"} <= set(item["title"]) and {"en", "es"} <= set(item["summary"])
        assert 1 <= len(item["poses"]) <= data["sheet"]["maxPoses"]
        assert item["template"] in {"walk-cycle-sheet", "walk-two-pose", "character-reaction"}
        assert item["scaleBy"] in animations.SCALE_BY and item["scaleBy"] == {"front": "base", "bust": "face", "side": "height"}[item["view"]]
        pose_ids = [pose["id"] for pose in item["poses"]]
        assert len(pose_ids) == len(set(pose_ids)) and all(pose["prompt"].strip() and {"en", "es"} <= set(pose["label"]) for pose in item["poses"])
    assert next(item for item in data["animations"] if item["id"] == "walk")["facing"] == "right"
    assert len(next(item for item in data["animations"] if item["id"] == "walk")["poses"]) == 4
    assert len(data["animations"]) <= animations.MAX_ANIMATIONS, "every catalog animation must fit on one kit"


def test_a_pose_prompt_keeps_the_character_and_asks_for_one_pose_on_a_screen():
    built = pose_prompt("walk", "passing", "a detective in a mustard coat", "paper-cutout")
    assert built["screen"] == "green" and built["resolution"] == "896x1152"
    text = built["prompt"]
    assert text.startswith("The same character as the reference image") and "a detective in a mustard coat" in text
    assert "Exact side view" in text and "passing pose" in text and "chroma-key green" in text
    assert "turnaround sheet" in built["negative"]
    assert "mustard coat. Exact side view" in text, "the look the author wrote is a sentence of its own"
    # A green subject is keyed on magenta; no style falls back to the generic identity line.
    assert pose_prompt("wave", "raise", "a lime green jacket")["screen"] == "magenta"
    generic = pose_prompt("angry", "furious", "")
    assert "art style" in generic["prompt"] and "Close-up portrait" in generic["prompt"] and "anger vein" in generic["prompt"]
    # A full-length picture of the character pulls the composition: a bust says what must not be in it, and a cycle does not.
    assert "full body" in generic["negative"] and "full body" not in pose_prompt("walk", "contact")["negative"]
    assert "open mouth" not in generic["negative"] and "open mouth" not in pose_prompt("angry", "furious", "x", "graphic-novel")["negative"], \
        "an expression may open its mouth and show its teeth"
    with pytest.raises(KeyError):
        pose_prompt("walk", "moonwalk")
    with pytest.raises(KeyError):
        pose_prompt("dance", "a")


def test_an_animation_the_author_describes_is_built_like_a_catalog_one():
    built = pose_prompt("my-grin", "pose-1", "Ana, a detective", "paper-cutout", custom={"view": "bust", "text": "Anime expression: a lopsided grin with one eyebrow up"})
    assert built["resolution"] == "1024x1024" and built["screen"] == "green"
    assert built["prompt"].startswith("The same character as the reference image") and "Ana, a detective." in built["prompt"]
    assert "Close-up portrait" in built["prompt"] and "lopsided grin with one eyebrow up." in built["prompt"] and "chroma-key green" in built["prompt"]
    assert "full body" in built["negative"], "a bust asks for no body, like a catalog bust"
    side = pose_prompt("x", "y", custom={"view": "side", "text": "Leaning on a wall."})
    assert side["resolution"] == "896x1152" and "Exact side view" in side["prompt"] and "full body" not in side["negative"]
    for bad in ({"view": "top", "text": "x"}, {"view": "bust", "text": ""}, {"view": "bust", "text": "x" * 601}, {"text": "x"}):
        with pytest.raises(CharacterAnimationError):
            pose_prompt("x", "y", custom=bad)


def _entry(**changes):
    sheet = {"source": "/api/v1/file/walk-sheet.png?workspace=demo", "count": 4, "columns": 4, "rows": 1, "width": 1600, "height": 640,
             "cell": {"width": 400, "height": 640}}
    return {"sheet": sheet, "frames": [{"id": "contact", "source": "/api/v1/file/c.png"}], "fps": 4, "loop": "loop", "facing": "right", **changes}


def test_a_kit_keeps_its_animations_and_drops_what_it_does_not_know():
    kept = normalize_kit_animations({"walk": {**_entry(), "unknown": 1, "prompt": "p", "view": "side"}})
    assert kept["walk"]["reviewState"] == "pending" and "unknown" not in kept["walk"] and kept["walk"]["prompt"] == "p"
    assert kept["walk"]["sheet"]["cell"] == {"width": 400, "height": 640}
    for bad in ({"Walk": _entry()}, {"walk": _entry(loop="forever")}, {"walk": _entry(fps=0)}, {"walk": _entry(facing="up")},
                {"walk": _entry(reviewState="done")}, {"walk": {**_entry(), "sheet": {**_entry()["sheet"], "source": "blob:x"}}},
                {"walk": {**_entry(), "sheet": {**_entry()["sheet"], "count": 99}}}, {"walk": {**_entry(), "sheet": None}}, [], {"walk": 1}):
        with pytest.raises(CharacterAnimationError):
            normalize_kit_animations(bad)
    assert normalize_kit_animations({item["id"]: _entry() for item in catalog()["animations"]})
    with pytest.raises(CharacterAnimationError):
        normalize_kit_animations({f"a{index}": _entry() for index in range(animations.MAX_ANIMATIONS + 1)})


def test_a_custom_animation_keeps_its_title_its_scale_mode_and_the_words_of_each_pose():
    entry = _entry(title="Sonrisa pícara", scaleBy="face", view="bust", frames=[{"id": "pose-1", "source": "/api/v1/file/c.png", "prompt": "A lopsided grin.", "label": "Sonrisa", "extra": 1}])
    kept = normalize_kit_animations({"sonrisa-picara": entry})["sonrisa-picara"]
    assert kept["title"] == "Sonrisa pícara" and kept["scaleBy"] == "face" and kept["frames"] == [{"id": "pose-1", "source": "/api/v1/file/c.png", "prompt": "A lopsided grin.", "label": "Sonrisa"}]
    with pytest.raises(CharacterAnimationError):
        normalize_kit_animations({"x": _entry(scaleBy="width")})
    with pytest.raises(CharacterAnimationError):
        normalize_kit_animations({"x": _entry(frames=[{"id": "p", "source": "/a.png", "prompt": "x" * 601}])})


def test_the_kit_library_stores_animations_and_still_whitelists_the_rest():
    from services.character_kit_library import normalize_character_kit
    kit = normalize_character_kit({"id": "ana", "name": "Ana", "animations": {"walk": _entry()}, "nonsense": True})
    assert kit["animations"]["walk"]["sheet"]["count"] == 4 and "nonsense" not in kit
    assert "animations" not in normalize_character_kit({"id": "ana", "name": "Ana"})


def test_the_sheet_has_equal_cells_one_ground_line_and_a_steady_torso(folder):
    # Legs apart and legs together: the outline's middle moves, the trunk stays at column 60 of its picture.
    wide = _figure(folder / "contact.png", legs=(30, 100))
    narrow = _figure(folder / "passing.png", legs=(55, 70), width=140)
    shifted = _figure(folder / "contact-b.png", legs=(20, 110), torso_at=70, width=160)
    built = _sheet_of(folder, [wide, narrow, wide, shifted])
    spec = catalog()["sheet"]
    assert (built["count"], built["columns"], built["rows"]) == (4, 4, 1)
    cell = built["cell"]
    assert cell["height"] == spec["cellHeight"] and built["width"] == cell["width"] * 4 and built["height"] == cell["height"]
    sheet = np.asarray(Image.open(built["path"]).convert("RGBA"))
    boots, trunks = [], []
    for index in range(4):
        part = sheet[:, index * cell["width"]:(index + 1) * cell["width"]]
        rows = np.nonzero(part[..., 3].max(axis=1) > spec["alphaFloor"])[0]
        boots.append(int(rows[-1]) + 1)
        trunk = part[int(cell["height"] * .3):int(cell["height"] * .45), :, 3]
        columns = np.nonzero(trunk.max(axis=0) > spec["alphaFloor"])[0]
        trunks.append((int(columns[0]) + int(columns[-1])) / 2)
    assert boots == [round(cell["height"] * spec["feet"])] * 4, boots
    assert max(trunks) - min(trunks) <= 2, f"the trunk is where the cell's middle is in every pose: {trunks}"
    assert abs(trunks[0] - cell["width"] / 2) <= 2
    top = np.nonzero(sheet[:, :cell["width"], 3].max(axis=1) > spec["alphaFloor"])[0][0]
    assert abs((boots[0] - top) - spec["cellHeight"] * spec["figure"]) <= 2, "the figure fills `figure` of a cell"


def _gesture(path: Path, *, factor: float, hand: int = 0) -> Path:
    """The same standing body drawn at a size of its own, with a hand raised ``hand`` pixels above the head (before the resize)."""
    pixels = np.zeros((300, 140, 4), dtype=np.uint8)
    pixels[60:90, 55:85] = (200, 160, 120, 255)      # head
    pixels[90:170, 40:100] = (230, 180, 30, 255)     # coat, 60 wide
    pixels[170:260, 45:95] = (60, 60, 70, 255)       # legs
    if hand:
        pixels[60 - hand:60, 100:108] = (200, 160, 120, 255)
    image = Image.fromarray(pixels)
    image.crop(image.getbbox()).resize((round(image.getbbox()[2] - image.getbbox()[0]) and round((image.getbbox()[2] - image.getbbox()[0]) * factor),
                                        round((image.getbbox()[3] - image.getbbox()[1]) * factor))).save(path)
    return path


def _widths(path: str, cells: int, band: tuple[float, float]) -> list[int]:
    """Per cell, the width of the figure in a band of its own height (from its top)."""
    alpha = np.asarray(Image.open(path).convert("RGBA"))[..., 3] > catalog()["sheet"]["alphaFloor"]
    cell = alpha.shape[1] // cells
    found = []
    for index in range(cells):
        part = alpha[:, index * cell:(index + 1) * cell]
        rows = np.nonzero(part.any(axis=1))[0]
        top, height = rows[0], rows[-1] - rows[0] + 1
        columns = np.nonzero(part[top + int(height * band[0]):top + int(height * band[1])].any(axis=0))[0]
        found.append(int(columns[-1] - columns[0] + 1))
    return found


def test_a_gesture_keeps_the_body_one_size_whatever_the_model_drew_and_the_hand_does(folder):
    # Four poses of one body, drawn 8 % smaller, as is, 5 % bigger and 8 % smaller again; two have a hand raised above the head.
    poses = [_gesture(folder / "g0.png", factor=.92), _gesture(folder / "g1.png", factor=1.0, hand=50),
             _gesture(folder / "g2.png", factor=1.05, hand=70), _gesture(folder / "g3.png", factor=.92)]
    by_height = _sheet_of(folder, poses)
    heights = _widths(by_height["path"], 4, (.85, 1.0))
    assert max(heights) - min(heights) >= 12, f"one scale for all keeps the model's own size changes: {heights}"
    by_body = build_sheet([p.name for p in poses], uploads_root=str(folder / "uploads"), workspace_root=str(folder), workspace="demo",
                          name="gesture", output_dir=str(folder), scale_by="base")
    widths = _widths(by_body["path"], 4, (.85, 1.0))
    assert max(widths) - min(widths) <= 4, f"the legs are as wide in every cell (within 4 %): {widths}"
    assert by_body["scaleBy"] == "base" and by_body["cell"]["height"] == catalog()["sheet"]["cellHeight"]
    sheet = np.asarray(Image.open(by_body["path"]).convert("RGBA"))[..., 3] > catalog()["sheet"]["alphaFloor"]
    assert int(np.nonzero(sheet.any(axis=1))[0][0]) >= 0 and int(np.nonzero(sheet.any(axis=1))[0][-1]) + 1 == round(by_body["cell"]["height"] * catalog()["sheet"]["feet"])


def test_a_gesture_with_arms_hanging_and_raised_is_not_scaled_by_the_width_of_its_body(folder):
    # The coat and sleeves are wider with the arms down than with them up; only the legs are the same. Scaling by the whole lower body
    # made the figure with its arms down 20 % smaller than the one cheering (real poses), the legs do not.
    def figure(path, *, arms_down):
        pixels = np.zeros((300, 200, 4), dtype=np.uint8)
        pixels[40:70, 80:110] = (200, 160, 120, 255)           # head
        pixels[70:170, 70:120] = (230, 180, 30, 255)           # coat, 50 wide
        if arms_down:
            pixels[75:165, 50:70] = (230, 180, 30, 255)        # sleeves hanging beside the coat
            pixels[75:165, 120:140] = (230, 180, 30, 255)
        else:
            pixels[0:70, 40:60] = (230, 180, 30, 255)          # arms up
            pixels[0:70, 130:150] = (230, 180, 30, 255)
        pixels[170:290, 75:115] = (60, 60, 70, 255)            # legs, 40 wide
        Image.fromarray(pixels).save(path)
        return path
    poses = [figure(folder / "down.png", arms_down=True), figure(folder / "up.png", arms_down=False)]
    built = build_sheet([p.name for p in poses], uploads_root=str(folder / "uploads"), workspace_root=str(folder), workspace="demo",
                        name="arms", output_dir=str(folder), scale_by="base")
    legs = _widths(built["path"], 2, (.85, 1.0))
    assert abs(legs[0] - legs[1]) <= 2, legs


def test_a_bust_is_scaled_by_the_size_of_its_head_and_falls_back_to_its_height_without_a_face(folder, monkeypatch):
    from services import face_landmarks

    def bust(path, *, head, shoulders):
        pixels = np.zeros((200, 260, 4), dtype=np.uint8)
        pixels[10:10 + head, 130 - head // 2:130 + head // 2] = (30, 30, 40, 255)         # hair and head
        pixels[10 + head:200, 130 - shoulders // 2:130 + shoulders // 2] = (230, 180, 30, 255)
        Image.fromarray(pixels).save(path)
        return path
    # The second pose is framed wider: the same head is smaller in it (and the picture shows more of the body).
    poses = [bust(folder / "close.png", head=120, shoulders=240), bust(folder / "wide.png", head=84, shoulders=170)]

    def fake(image):
        """The head's height: the dark run at the top of the centre column, which ends where the coat begins."""
        pixels = np.asarray(image.convert("RGBA"))[:, image.width // 2 - 1]
        return {"face": {"head": float(next(index for index, pixel in enumerate(pixels) if pixel[0] > 100)), "size": "normal", "pass": "whole"}}

    monkeypatch.setattr(face_landmarks, "detect", fake)
    built = build_sheet([p.name for p in poses], uploads_root=str(folder / "uploads"), workspace_root=str(folder), workspace="demo", name="bust",
                        output_dir=str(folder), scale_by="face")
    assert built["scaleBy"] == built["requestedScaleBy"] == "face" and built["measures"] == [120.0, 84.0]
    sheet = np.asarray(Image.open(built["path"]).convert("RGBA"))
    cell = built["cell"]["width"]
    head_heights = []
    for index in range(2):
        part = sheet[:, index * cell:(index + 1) * cell]
        column = part[:, cell // 2]
        dark = [row for row, pixel in enumerate(column) if pixel[3] > 8 and pixel[0] < 100]
        head_heights.append(len(dark))
    assert abs(head_heights[0] - head_heights[1]) <= 3, f"the head is as big in both cells: {head_heights}"
    # With no face to read, the sheet is joined by height, and says so.
    monkeypatch.setattr(face_landmarks, "detect", lambda image: None)
    fallback = build_sheet([p.name for p in poses], uploads_root=str(folder / "uploads"), workspace_root=str(folder), workspace="demo", name="bust2",
                           output_dir=str(folder), scale_by="face")
    assert fallback["scaleBy"] == "height" and fallback["requestedScaleBy"] == "face"


def test_a_bad_scale_mode_is_refused(folder):
    pose = _figure(folder / "p.png", legs=(40, 80))
    with pytest.raises(CharacterAnimationError, match="scale_by"):
        build_sheet([pose.name], uploads_root=str(folder / "uploads"), workspace_root=str(folder), workspace="demo", scale_by="width")


def test_poses_keep_their_height_relative_to_each_other(folder):
    tall = _figure(folder / "up.png", legs=(40, 80), height=200)
    squat = _figure(folder / "down.png", legs=(40, 80), height=180)
    built = _sheet_of(folder, [tall, squat])
    spec = catalog()["sheet"]
    sheet = np.asarray(Image.open(built["path"]).convert("RGBA"))
    heights = []
    for index in range(2):
        rows = np.nonzero(sheet[:, index * built["cell"]["width"]:(index + 1) * built["cell"]["width"], 3].max(axis=1) > spec["alphaFloor"])[0]
        heights.append(int(rows[-1]) - int(rows[0]) + 1)
    assert heights[0] == pytest.approx(spec["cellHeight"] * spec["figure"], abs=2)
    assert heights[1] / heights[0] == pytest.approx(0.9, abs=0.02), "a crouch stays lower than the stand"


def test_a_sheet_wraps_in_rows_and_a_name_is_never_overwritten(folder):
    poses = [_figure(folder / f"p{index}.png", legs=(40, 80)) for index in range(5)]
    first = _sheet_of(folder, poses)
    second = build_sheet([p.name for p in poses], uploads_root=str(folder / "uploads"), workspace_root=str(folder), workspace="demo",
                         name="walk", columns=3, output_dir=str(folder))
    assert (second["columns"], second["rows"]) == (3, 2) and second["height"] == 2 * second["cell"]["height"]
    assert first["path"] != second["path"] and Path(first["path"]).is_file() and Path(second["path"]).is_file()
    assert second["source"].startswith("/api/v1/file/walk-sheet-") and second["source"].endswith("?workspace=demo")


def test_a_sheet_refuses_what_is_not_a_keyed_pose(folder):
    Image.fromarray(np.zeros((40, 40, 4), dtype=np.uint8)).save(folder / "empty.png")
    with pytest.raises(CharacterAnimationError, match="key it"):
        _sheet_of(folder, [folder / "empty.png"])
    with pytest.raises(CharacterAnimationError):
        build_sheet([], uploads_root=str(folder / "uploads"), workspace_root=str(folder), workspace="demo")
    with pytest.raises(CharacterAnimationError):
        build_sheet(["a.png"] * 13, uploads_root=str(folder / "uploads"), workspace_root=str(folder), workspace="demo")
    with pytest.raises(animations.CharacterKitFaceCleanupError):
        build_sheet(["../etc/passwd.png"], uploads_root=str(folder / "uploads"), workspace_root=str(folder), workspace="demo")


def test_the_http_routes_serve_the_catalog_a_prompt_and_a_sheet(folder):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.character_kit_face import create_character_kit_face_router

    app = FastAPI()
    app.include_router(create_character_kit_face_router(workspace_dir=lambda _: str(folder), uploads_root=lambda: str(folder / "uploads")))
    client, base = TestClient(app), "/api/v1/character-kits/animations"
    assert [item["id"] for item in client.get(f"{base}/catalog").json()["animations"]][:2] == ["walk", "run"]
    made = client.post(f"{base}/prompt", json={"animation": "wave", "pose": "raise", "description": "Ana", "style": "paper-cutout"})
    assert made.status_code == 200 and made.json()["screen"] == "green" and "Ana" in made.json()["prompt"]
    assert client.post(f"{base}/prompt", json={"animation": "dance", "pose": "a"}).status_code == 404
    own = client.post(f"{base}/prompt", json={"animation": "my-grin", "pose": "pose-1", "custom": {"view": "bust", "text": "A lopsided grin"}})
    assert own.status_code == 200 and "lopsided grin" in own.json()["prompt"]
    assert client.post(f"{base}/prompt", json={"animation": "my-grin", "pose": "pose-1", "custom": {"view": "top", "text": "x"}}).status_code == 400
    poses = [_figure(folder / f"pose-{index}.png", legs=(40 + index * 5, 90)) for index in range(3)]
    reply = client.post(f"{base}/sheet", json={"workspace": "demo", "sources": [p.name for p in poses], "name": "Ana wave"})
    body = reply.json()
    assert reply.status_code == 200 and (body["count"], body["columns"]) == (3, 3) and "path" not in body
    assert body["source"].startswith("/api/v1/file/Ana-wave-sheet-") and (folder / body["filename"]).is_file()
    assert client.post(f"{base}/sheet", json={"workspace": "demo", "sources": ["missing.png"]}).status_code in (400, 404)
    assert client.post(f"{base}/sheet", json={"workspace": "demo", "sources": []}).status_code == 422
    Image.fromarray(np.zeros((8, 8, 4), dtype=np.uint8)).save(folder / "blank.png")
    assert client.post(f"{base}/sheet", json={"workspace": "demo", "sources": ["blank.png"]}).status_code == 400


def test_the_catalog_file_is_plain_json_for_the_ui():
    json.loads(animations.CATALOG.read_text(encoding="utf-8"))

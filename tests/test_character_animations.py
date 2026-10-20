"""Character animations: the catalog, a pose's prompt, the kit field and the sprite sheet built from keyed poses."""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from services import character_animations as animations
from services.character_animations import CharacterAnimationError, build_sheet, catalog, normalize_kit_animations, pose_prompt
from services.walk_guides import expected_spread


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
        # A gesture is sized by what it does not move (legs, head); a walk and the other directions by their height.
        by_view = {"front": "base", "bust": "face"}.get(item["view"], "height")
        assert item["scaleBy"] in animations.SCALE_BY and item["scaleBy"] == ("height" if item.get("motion") == "walk" else by_view)
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
    assert normalize_kit_animations({item["id"]: _entry() for item in catalog()["animations"]}), "a kit can keep the whole catalog"
    with pytest.raises(CharacterAnimationError):
        normalize_kit_animations({f"a{index}": _entry() for index in range(animations.MAX_ANIMATIONS + 1)})


def test_who_reviewed_an_animation_and_why_survives_a_save_and_older_data_without_it_stays_valid():
    entry = _entry(reviewState="approved", reviewedBy="agent", reviewNote="  same character,\n one size ", reviewedAt="2026-10-17T10:00:00.000Z")
    kept = normalize_kit_animations({"walk": entry})["walk"]
    assert (kept["reviewState"], kept["reviewedBy"], kept["reviewNote"], kept["reviewedAt"]) == ("approved", "agent", "same character,\n one size", "2026-10-17T10:00:00.000Z")
    assert normalize_kit_animations({"walk": kept})["walk"] == kept, "saving it again changes nothing"
    older = normalize_kit_animations({"walk": _entry(reviewState="approved")})["walk"]
    assert older["reviewState"] == "approved" and not {"reviewedBy", "reviewNote", "reviewedAt"} & set(older)
    assert normalize_kit_animations({"walk": _entry(reviewedBy="person")})["walk"]["reviewedBy"] == "person"
    for bad in (_entry(reviewedBy="robot"), _entry(reviewedBy=1), _entry(reviewNote="x" * 501), _entry(reviewedAt="x" * 81)):
        with pytest.raises(CharacterAnimationError):
            normalize_kit_animations({"walk": bad})


def test_a_custom_animation_keeps_its_title_its_scale_mode_and_the_words_of_each_pose():
    entry = _entry(title="Sonrisa pícara", scaleBy="face", view="bust", frames=[{"id": "pose-1", "source": "/api/v1/file/c.png", "prompt": "A lopsided grin.", "label": "Sonrisa", "extra": 1}])
    kept = normalize_kit_animations({"sonrisa-picara": entry})["sonrisa-picara"]
    assert kept["title"] == "Sonrisa pícara" and kept["scaleBy"] == "face" and kept["frames"] == [{"id": "pose-1", "source": "/api/v1/file/c.png", "prompt": "A lopsided grin.", "label": "Sonrisa"}]
    grouped = normalize_kit_animations({"sonrisa-picara": _entry(group="expression")})["sonrisa-picara"]
    assert grouped["group"] == "expression"
    with pytest.raises(CharacterAnimationError):
        normalize_kit_animations({"x": _entry(group="mood")})
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


# ----- five directions, the twelve-pose walk and the data contract (services/character_animation_directions.py) -----

def _walker(path: Path, phase: int, *, height: int = 200, flip: bool = False) -> Path:
    """A keyed walker whose two legs and one arm are different in each of the twelve phases: the legs are as far apart as the profile
    walk of ``services/walk_guides.py`` has them at that phase, the dark one on the near side in the first half of the cycle."""
    pixels = np.zeros((height, 150, 4), dtype=np.uint8)
    wide = round(expected_spread("side", phase / 12) * (height - 10))
    start = (150 - wide) // 2
    near, far = (start, start + wide - 12) if phase < 6 else (start + wide - 12, start)
    pixels[10:40, 55:85] = (20 + 18 * phase, 160, 120, 255)  # the head's red says which pose it is
    pixels[40:110, 48:92] = (230, 180, 30, 255)
    pixels[110:height - 4 * (phase % 6), near:near + 12] = (30, 30, 40, 255)  # a dark leg, lifted a little more in each phase
    pixels[110:height, far:far + 12] = (235, 235, 245, 255)  # and a light one
    pixels[45:50 + 8 * phase, 94:108] = (200, 160, 120, 255)  # an arm that reaches lower in each phase
    image = Image.fromarray(pixels)
    (image.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if flip else image).save(path)
    return path


def _walk_sheet(folder: Path, name: str = "walk", *, heights: dict[int, int] | None = None, same: dict[int, int] | None = None, flip: bool = False) -> dict:
    """Twelve walker poses joined into a 6 x 2 sheet. ``heights``: phase -> picture height; ``same``: phase -> the phase it copies."""
    poses = [_walker(folder / f"{name}-{index}.png", (same or {}).get(index, index), height=(heights or {}).get(index, 200), flip=flip) for index in range(12)]
    return build_sheet([pose.name for pose in poses], uploads_root=str(folder / "uploads"), workspace_root=str(folder), workspace="demo", name=name,
                       columns=6, output_dir=str(folder))


def test_the_catalog_has_five_directions_each_with_a_twelve_pose_walk_at_twelve_frames_a_second():
    data = catalog()
    for view in ("front34", "back34", "back"):
        spec = data["custom"]["views"][view]
        assert view in data["views"] and spec["resolution"] == "896x1152" and spec["scaleBy"] == "height" and spec["facing"] in ("right", "front")
    assert [data["custom"]["views"][view]["facing"] for view in ("front34", "back34", "back")] == ["right", "right", "front"], "a back view looks neither left nor right"
    walks = {item["dir"]: item for item in data["animations"] if item.get("motion") == "walk" and len(item["poses"]) == 12}
    assert {direction: item["id"] for direction, item in walks.items()} == {"side": "walk-12", "front": "walk-front", "front34": "walk-front34", "back34": "walk-back34", "back": "walk-back"}
    for direction, item in walks.items():
        assert item["group"] == "cycle" and item["fps"] == 12 and item["loop"] == "loop" and item["template"] == "walk-cycle-sheet" and item["scaleBy"] == "height"
        assert item["view"] == direction and item["columns"] == 6 and set(item["checks"]) == {"height", "repeats", "mirror", "gait"}
        assert item["guide"] == "walk", "every pose of a walk is drawn over its guide"
        assert len({pose["id"] for pose in item["poses"]}) == 12 == len({pose["prompt"] for pose in item["poses"]}), "twelve different drawings"
    # The old four-pose walk stays as it was, and says what it is.
    walk = next(item for item in data["animations"] if item["id"] == "walk")
    assert len(walk["poses"]) == 4 and walk["fps"] == 4 and (walk["motion"], walk["dir"]) == ("walk", "side") and "checks" not in walk
    assert walk["guide"] == "walk" and data["guide"]["style"] in data["guide"]["text"]
    idles = {item["dir"] for item in data["animations"] if item.get("motion") == "idle"}
    assert idles == {"front", "side", "front34", "back34", "back"}
    assert all(len(item["poses"]) == 2 for item in data["animations"] if item.get("motion") == "idle")
    sets = data["sets"]
    assert [step["animation"] for step in sets["walk-directions"]["sheets"]] == ["walk-12", "walk-front34", "walk-front", "walk-back34", "walk-back"]
    assert [step["animation"] for step in sets["walk-12"]["sheets"]] == ["walk-12"]
    known = {item["id"] for item in data["animations"]}
    for name, spec in sets.items():
        ids = [step["animation"] for step in spec["sheets"]]
        assert set(ids) <= known and len(ids) == len(set(ids)), name
        assert all(step.get("reference") in (None, *ids[:index]) for index, step in enumerate(spec["sheets"])), "a sheet is drawn after the one it takes as a reference"


def test_the_prompts_of_the_new_directions_say_which_way_the_character_faces():
    side = pose_prompt("walk-12", "contact-a", "a detective")
    assert "Exact side view" in side["prompt"] and "heel of the boot just touching the ground" in side["prompt"] and side["resolution"] == "896x1152"
    front34 = pose_prompt("walk-front34", "passing-b", "a detective")["prompt"]
    assert "Three-quarter front view" in front34 and "toward the viewer and to the viewer's right" in front34
    back = pose_prompt("walk-back", "contact-a", "a detective")
    assert "from behind" in back["prompt"] and "no face" in back["prompt"] and "face" in back["negative"] and "viewer's left" in back["prompt"]
    assert "Three-quarter back view" in pose_prompt("walk-back34", "up-a")["prompt"]
    # Opposite arms: the leg that leads is the one whose arm swings back.
    assert "leg nearest the viewer stretched forward" in pose_prompt("walk-12", "contact-a")["prompt"]
    assert "far leg stretched forward" in pose_prompt("walk-12", "contact-b")["prompt"] and "far arm swinging back" in pose_prompt("walk-12", "contact-b")["prompt"]
    for item in catalog()["animations"]:
        if item.get("motion"):
            assert all(pose_prompt(item["id"], pose["id"], "x")["prompt"] for pose in item["poses"])


def test_a_custom_animation_takes_up_to_twelve_poses_in_any_of_the_directions():
    assert animations.MAX_CUSTOM_POSES == 12 and catalog()["sheet"]["maxPoses"] == 12
    assert set(animations.CUSTOM_VIEWS) == {"bust", "front", "side", "front34", "back34", "back"}
    twelve = animations.animation_def("my-turn", custom={"title": "Giro", "view": "back34", "poses": [f"pose {number}" for number in range(12)]})
    assert len(twelve["poses"]) == 12 and twelve["view"] == "back34" and twelve["scaleBy"] == "height" and twelve["facing"] == "right"
    with pytest.raises(CharacterAnimationError):
        animations.animation_def("my-turn", custom={"title": "Giro", "view": "back", "poses": [f"pose {number}" for number in range(13)]})
    built = pose_prompt("my-turn", "pose-1", "x", custom={"view": "back", "text": "Looking over the shoulder"})
    assert "from behind" in built["prompt"] and built["resolution"] == "896x1152"


def test_the_contract_motion_and_dir_is_read_from_the_animation_or_deduced_from_its_view_and_id():
    from services import character_animation_directions as directions
    assert directions.DIRS == ("side", "front", "front34", "back34", "back") and directions.MOTIONS == ("walk", "idle")
    # Written on the animation: that is the contract.
    assert directions.contract_of("walk-front34", {"motion": "walk", "dir": "front34"}) == {"motion": "walk", "dir": "front34"}
    # Missing: dir from the view (side, front and the three new ones), motion from a cycle whose id starts with walk or idle.
    assert directions.contract_of("walk", {"view": "side", "group": "cycle"}) == {"motion": "walk", "dir": "side"}
    assert directions.contract_of("idle", {"view": "front", "group": "cycle"}) == {"motion": "idle", "dir": "front"}
    assert directions.contract_of("walk-back34", {"view": "back34", "group": "cycle"}) == {"motion": "walk", "dir": "back34"}
    assert directions.contract_of("wave", {"view": "front", "group": "gesture"}) == {"dir": "front"}, "a gesture is no motion"
    assert directions.contract_of("run", {"view": "side", "group": "cycle"}) == {"dir": "side"}, "only walk and idle are motions"
    assert directions.contract_of("angry", {"view": "bust", "group": "expression"}) == {}, "a bust looks no way"
    assert directions.contract_of("walk-mine", {"view": "side", "group": "custom"}) == {"dir": "side"}, "a custom id that says walk is not a cycle"
    assert directions.contract_of("walk-12", None) == {"motion": "walk", "dir": "side"}, "a catalog id with no stored entry reads the catalog"
    assert directions.contract_of("unknown", None) == {}
    # What is stored wins over what the id suggests, and a value off the list is ignored.
    assert directions.contract_of("walk", {"view": "side", "dir": "back", "motion": "idle"}) == {"motion": "idle", "dir": "back"}
    assert directions.contract_of("walk", {"view": "side", "dir": "up", "motion": "fly"}) == {"motion": "walk", "dir": "side"}


def test_a_kit_keeps_motion_and_dir_and_refuses_what_is_off_the_list():
    kept = normalize_kit_animations({"walk-12": _entry(motion="walk", dir="side", view="side")})["walk-12"]
    assert (kept["motion"], kept["dir"]) == ("walk", "side")
    assert "motion" not in normalize_kit_animations({"walk": _entry()})["walk"], "older data stays as it was"
    for bad in (_entry(motion="run"), _entry(dir="left"), _entry(dir=3)):
        with pytest.raises(CharacterAnimationError):
            normalize_kit_animations({"walk-12": bad})


def test_a_kit_keeps_the_left_facing_sheet_and_the_mouth_and_eye_anchors_of_a_direction_sheet():
    """The directional billboard engine reads ``dir: *_r`` (a sheet that looks left, which beats the mirror) and per-sheet ``mouth`` and
    ``eyes`` anchors ({offsetX, offsetY, scale, rotation?} in % of the long side of the cell); a kit says ``asymmetric`` for a badge on one side."""
    anchors = {"offsetX": 1.5, "offsetY": -2, "scale": 0.9}
    kept = normalize_kit_animations({"walk-12": _entry(motion="walk", dir="side_r", view="side", mouth=anchors, eyes={**anchors, "rotation": 3})})["walk-12"]
    assert kept["dir"] == "side_r" and kept["mouth"] == anchors and kept["eyes"] == {**anchors, "rotation": 3}
    for name in ("front34_r", "back34_r"):
        assert normalize_kit_animations({"walk-12": _entry(dir=name)})["walk-12"]["dir"] == name
    for bad in (_entry(dir="front_r"), _entry(dir="back_r"), _entry(mouth="open"), _entry(mouth={"offsetX": "a", "offsetY": 0, "scale": 1}),
                _entry(eyes={"offsetX": 0, "offsetY": 0})):
        with pytest.raises(CharacterAnimationError):
            normalize_kit_animations({"walk-12": bad})
    assert "mouth" not in normalize_kit_animations({"walk": _entry()})["walk"], "older data stays as it was"


def test_the_approved_twelve_pose_walk_comes_before_the_four_pose_one():
    from services import character_animation_directions as directions

    def made(state, count=4, **extra):
        return _entry(reviewState=state, sheet={**_entry()["sheet"], "count": count}, **extra)
    both = {"walk": made("approved"), "walk-12": made("approved", 12)}
    assert directions.walk_sheet(both)[0] == "walk-12"
    assert directions.walk_sheet({**both, "walk-12": made("pending", 12)})[0] == "walk", "a pending sheet is never played"
    assert directions.walk_sheet({"walk-12": made("rejected", 12)}) is None and directions.walk_sheet({}) is None
    assert directions.walk_sheet({"walk": made("approved")})[0] == "walk"
    pool = {"walk-front34": made("approved", 12, dir="front34", motion="walk"), "walk-back": made("approved", 12, dir="back", motion="walk"), "walk": made("approved")}
    assert [name for name, _entry_ in directions.sheets_for(pool, "walk", "front34")] == ["walk-front34"]
    assert [name for name, _entry_ in directions.sheets_for(pool, "walk", "side")] == ["walk"], "a walk with no dir stored is a side walk"
    assert directions.sheets_for(pool, "idle", "side") == []


def test_twelve_poses_join_into_a_six_by_two_sheet_whose_cells_read_in_order(folder):
    built = _walk_sheet(folder)
    assert (built["count"], built["columns"], built["rows"]) == (12, 6, 2)
    cell = built["cell"]
    assert built["width"] == cell["width"] * 6 and built["height"] == cell["height"] * 2
    sheet = np.asarray(Image.open(built["path"]).convert("RGBA"))
    reds = []
    for index in range(12):
        row, column = divmod(index, 6)
        part = sheet[row * cell["height"]:(row + 1) * cell["height"], column * cell["width"]:(column + 1) * cell["width"]]
        solid = part[..., 3] > catalog()["sheet"]["alphaFloor"]
        assert solid.any(), f"cell {index} holds a figure"
        top = int(np.nonzero(solid.any(axis=1))[0][0])
        head = part[top + 6:top + 10][solid[top + 6:top + 10]]
        reds.append(int(head[:, 0].mean()))
    assert all(abs(red - (20 + 18 * phase)) <= 3 for phase, red in enumerate(reds)), f"the cells follow the order of the poses: {reds}"


def _checks(built: dict, animation_id: str = "walk-12", siblings=()) -> dict[str, dict]:
    from services.character_animation_checks import sheet_checks
    return {check["id"]: check for check in sheet_checks(built, animations.animation(animation_id), siblings=siblings)}


def test_a_twelve_pose_walk_passes_the_cycle_checks_when_the_figures_are_one_size_and_no_pose_repeats(folder):
    checks = _checks(_walk_sheet(folder))
    assert all(check["ok"] for check in checks.values()), {key: check for key, check in checks.items() if not check["ok"]}
    assert {"figure_height", "repeated_poses", "ground_line", "cell_count"} <= set(checks)
    assert checks["figure_height"]["limit"] == 0.03 and checks["repeated_poses"]["value"] == 1 and checks["repeated_poses"]["limit"] == 2
    assert "direction_mirror" in checks and checks["direction_mirror"]["ok"], "a kit with no other direction has nothing to repeat"


def test_a_pose_drawn_a_tenth_smaller_fails_the_same_height_check_and_a_hair_of_difference_does_not(folder):
    small = _checks(_walk_sheet(folder, "small", heights={5: 170}))
    assert not small["figure_height"]["ok"] and small["figure_height"]["value"] > 0.03
    near = _checks(_walk_sheet(folder, "near", heights={5: 196}))
    assert near["figure_height"]["ok"] and near["figure_height"]["value"] <= 0.03


def test_the_same_drawing_in_more_than_two_cells_in_a_row_fails_and_two_in_a_row_does_not(folder):
    twice = _checks(_walk_sheet(folder, "twice", same={4: 3}))
    assert twice["repeated_poses"]["ok"] and twice["repeated_poses"]["value"] == 2
    thrice = _checks(_walk_sheet(folder, "thrice", same={4: 3, 5: 3}))
    assert not thrice["repeated_poses"]["ok"] and thrice["repeated_poses"]["value"] == 3 and "3 cells" in thrice["repeated_poses"]["detail"]
    apart = _checks(_walk_sheet(folder, "apart", same={6: 0, 7: 1}))
    assert apart["repeated_poses"]["ok"], "the same drawing far apart in the cycle is allowed"


def test_a_walk_whose_poses_have_the_legs_of_another_moment_or_another_side_fails_the_gait_check(folder):
    good = _checks(_walk_sheet(folder, "gait-good"))["walk_gait"]
    assert good["ok"] and good["limit"] == 0.15
    shuffled = _checks(_walk_sheet(folder, "gait-shuffled", same={3: 0, 9: 6}))["walk_gait"]
    assert not shuffled["ok"] and "cell(s) 4, 10" in shuffled["detail"], "a passing pose drawn as a full stride is the wrong moment"
    turned = _checks(_walk_sheet(folder, "gait-turned"), "walk-back")["walk_gait"]
    assert not turned["ok"], "the strides of a profile are not a walk seen from behind"


def test_the_mirror_of_one_direction_is_not_another_direction_of_the_same_kit(folder):
    first = _walk_sheet(folder, "front34")
    mirror = _walk_sheet(folder, "back34", flip=True)
    other = _walk_sheet(folder, "back", same={index: (index * 5) % 12 for index in range(12)})
    sibling = {"id": "walk-front34", "dir": "front34", "path": first["path"]}
    copied = _checks(mirror, "walk-back34", siblings=[sibling])["direction_mirror"]
    assert not copied["ok"] and copied["value"] == 1 and "walk-front34" in copied["detail"] and "mirror" in copied["detail"]
    same = _checks(_walk_sheet(folder, "twin"), "walk-back", siblings=[sibling])["direction_mirror"]
    assert not same["ok"] and "walk-front34 (same drawing)" in same["detail"]
    assert _checks(other, "walk-back", siblings=[sibling])["direction_mirror"]["ok"], "a different drawing of the cycle is fine"
    own = {"id": "walk-back34", "dir": "back34", "path": mirror["path"]}
    assert _checks(mirror, "walk-back34", siblings=[own])["direction_mirror"]["ok"], "a sheet is not compared with itself"
    unreadable = {"id": "walk-front", "dir": "front", "path": str(folder / "missing.png")}
    assert _checks(other, "walk-back", siblings=[unreadable])["direction_mirror"]["ok"], "a sheet that cannot be read is not a failure"


def test_the_cycle_checks_run_only_on_the_animations_that_ask_for_them(folder):
    four = [_figure(folder / f"p{index}.png", legs=(30 + index, 100 - index)) for index in range(4)]
    built = _sheet_of(folder, four)
    ids = set(_checks(built, "walk"))
    assert not ids & {"figure_height", "repeated_poses", "direction_mirror"}, "the old walk is checked as it always was"

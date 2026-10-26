"""A parametric 2D blob face is a Character Kit whose anchors are the pixels that were drawn."""
from __future__ import annotations

import hashlib
import io

from PIL import Image

from services.blob_face import POSES, composite_mouth, face_kit, paste_anchor, save_face_kit
from services.flat_rig import MAPPING, STATES
from services.flat_rig_base import INK, _anchor


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _interior_height(image: Image.Image, anchor: dict) -> int:
    """Rows of the mouth opening (cavity, teeth, tongue) inside the anchor box, not the ink line."""
    edge = max(image.size)
    height = anchor["scale"] * edge
    width = height * (512 / 320)
    left = int(image.width / 2 + anchor["offsetX"] * edge / 100 - width / 2)
    top = int(image.height / 2 + anchor["offsetY"] * edge / 100 - height / 2)
    pixels = image.load()
    rows = set()
    for y in range(max(0, top), min(image.height, top + int(height) + 2)):
        for x in range(max(0, left), min(image.width, left + int(width) + 2)):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 128:
                continue
            if (red - INK[0]) ** 2 + (green - INK[1]) ** 2 + (blue - INK[2]) ** 2 < 48 ** 2:
                continue
            rows.add(y)
    return (max(rows) - min(rows) + 1) if rows else 0


def _ink_near(image: Image.Image, anchor: dict) -> tuple[float, float]:
    edge = max(image.size)
    cx = image.width / 2 + anchor["offsetX"] * edge / 100
    cy = image.height / 2 + anchor["offsetY"] * edge / 100
    pixels = image.load()
    total = weight_x = weight_y = 0
    for y in range(int(cy) - 90, int(cy) + 90):
        for x in range(int(cx) - 120, int(cx) + 120):
            if not (0 <= x < image.width and 0 <= y < image.height):
                continue
            red, green, blue, alpha = pixels[x, y]
            if alpha < 128:
                continue
            if (red - INK[0]) ** 2 + (green - INK[1]) ** 2 + (blue - INK[2]) ** 2 >= 48 ** 2:
                continue
            total += 1
            weight_x += x
            weight_y += y
    assert total > 20, "the mouth ink is at the anchor"
    return weight_x / total, weight_y / total


def test_the_same_traits_draw_the_same_face_and_the_nine_mouths_differ():
    traits = {"eyes": "oval", "moustache": "walrus", "freckles": True, "mouth": "paper"}
    first, second = face_kit(traits), face_kit(traits)
    assert _png(first["poses"]["neutral"]) == _png(second["poses"]["neutral"])
    mouths = [_png(first["mouths"][state]) for state in STATES]
    assert len(set(mouths)) == 9
    poses = [_png(first["poses"][pose]) for pose in POSES]
    assert len(set(poses)) == 8
    assert first["mouthMapping"] == MAPPING


def test_anchors_are_the_drawn_mouth_and_wide_and_medium_open_at_least_40px():
    kit = face_kit({"eyes": {"shape": "wide", "size": 1.1, "separation": 1.05}, "brows": "thick", "nose": "none"})
    for pose in POSES:
        cx, cy, size = kit["layout"][pose]["mouth"]
        assert kit["anchors"][pose]["mouth"] == _anchor(cx, cy, size, 1024, 1024)
        assert kit["anchors"][pose]["eyes"] == _anchor(512, 512, 1024, 1024, 1024)
    neutral = kit["anchors"]["neutral"]["mouth"]
    for state in ("wide", "medium"):
        shot = composite_mouth(kit["poses"]["neutral"], kit["mouths"][state], neutral)
        found_x, found_y = _ink_near(shot, neutral)
        edge = 1024
        expect_x = 512 + neutral["offsetX"] * edge / 100
        expect_y = 512 + neutral["offsetY"] * edge / 100
        displayed = neutral["scale"] * edge
        # The anchor is the sprite centre. A wide D mouth puts more ink on the lower lip, below that centre.
        assert abs(found_x - expect_x) < 14 and abs(found_y - expect_y) < displayed * 0.2
        assert shot.getpixel((int(expect_x), int(expect_y)))[3] > 40
        assert _interior_height(shot, neutral) >= 40
    # The helper the renderer uses is the same placement the anchor describes.
    blank = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    paste_anchor(blank, kit["mouths"]["closed"], neutral)
    assert _ink_near(blank, neutral)


def test_save_face_kit_is_a_library_kit_with_eight_poses_and_a_blink(tmp_path):
    workspace = tmp_path / "studio"
    workspace.mkdir()
    saved = save_face_kit(str(workspace), "studio", {"glasses": "round", "freckles": True, "mouth": "ink", "stubble": True}, name="Pecas")
    character = saved["character"]
    assert saved["kit_id"] == character["id"]
    assert set(saved["poses"]) == set(POSES)
    assert set(character["mouth"]) == set(STATES)
    assert all(character["mouth"][state]["reviewState"] == "approved" for state in STATES)
    assert character["eyes"]["blink"]["reviewState"] == "approved"
    assert character["mouthMapping"]["A"] == "wide"
    for pose in POSES:
        assert character["anchors"][pose]["blinkSource"].startswith("/api/v1/file/")
        assert character["poses"][pose]["width"] == 1024
    again = save_face_kit(str(workspace), "studio", {"glasses": "round", "freckles": True, "mouth": "ink", "stubble": True}, name="Pecas")
    assert again["kit_id"] == saved["kit_id"]
    assert again["revision"] == saved["revision"] + 1
    assert hashlib.sha256(saved["preview"].encode()).hexdigest()

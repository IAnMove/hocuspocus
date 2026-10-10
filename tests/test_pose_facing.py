"""Which way a pose looks: read on its face (or body) by DWPose, or said by its kit, and kept by the flat rig."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from PIL import Image, ImageDraw

from services import face_landmarks, pose_facing
from services.character_kit_library import normalize_character_kit, patch_character_kit, read_character_kit_library
from services.flat_rig import rig_character


def _face(turn: float, head: float = 200.0) -> np.ndarray:
    """68 face points of a head ``head`` px wide whose nose sits ``turn`` jaw widths off the middle (negative: left)."""
    cx, cy = 300.0, 260.0
    points = np.zeros((68, 2))
    angles = np.linspace(np.pi, 0, 17)
    points[0:17] = np.stack([cx + head / 2 * np.cos(angles), cy + head / 2 * np.sin(angles) * 0.9], 1)
    points[17:27] = np.stack([np.linspace(cx - head * 0.35, cx + head * 0.35, 10), np.full(10, cy - head * 0.45)], 1)
    points[27:36] = (cx + turn * head, cy)
    points[36:48] = np.stack([np.linspace(cx - head * 0.3, cx + head * 0.3, 12), np.full(12, cy - head * 0.2)], 1)
    points[48:68] = (cx, cy + head * 0.25)
    return points


def _body(nose_x: float, right=200.0, left=400.0, score=0.9) -> np.ndarray:
    body = np.zeros((18, 3))
    body[:, 2] = score
    body[0], body[2], body[5] = (nose_x, 260, score), (right, 420, score), (left, 420, score)
    return body


def _model(monkeypatch, face_points, face_score=0.9, body=None):
    """DWPose as ``face_landmarks`` sees it: one figure, sure of its face, no head pass."""
    monkeypatch.setattr(face_landmarks, "_wholebody", lambda: object())
    monkeypatch.setattr(face_landmarks, "_whole_pass", lambda model, bgr: (
        face_points, np.full(68, face_score), _body(300.0) if body is None else body))


def _blank() -> Image.Image:
    return Image.new("RGBA", (600, 900), (0, 0, 0, 0))


@pytest.mark.parametrize("turn, facing", [(-0.3, "left"), (0.28, "right"), (0.03, "front"), (-0.06, "front")])
def test_the_head_turn_is_read_from_the_nose_against_the_jaw_line(monkeypatch, turn, facing):
    _model(monkeypatch, _face(turn))
    found = pose_facing.detect(_blank())
    assert found["facing"] == facing and found["source"] == "face"
    assert found["yaw"] == pytest.approx(turn, abs=0.01)
    assert 0 < found["confidence"] <= 0.9


def test_a_guessed_face_leaves_it_to_the_body_and_a_guessed_body_to_nobody(monkeypatch):
    _model(monkeypatch, _face(0.3), face_score=0.1, body=_body(380.0))
    found = pose_facing.detect(_blank())
    assert found["facing"] == "right" and found["source"] == "body" and found["confidence"] < 0.7
    _model(monkeypatch, _face(0.3), face_score=0.1, body=_body(380.0, score=0.1))
    assert pose_facing.detect(_blank()) is None
    # A bust's collar read as both shoulders: too narrow for a body to say anything.
    _model(monkeypatch, _face(0.3), face_score=0.1, body=_body(300.0, right=295.0, left=305.0))
    assert pose_facing.detect(_blank()) is None


def test_without_the_model_or_with_a_failing_one_the_facing_is_unknown(monkeypatch):
    monkeypatch.setenv("HOCUS_FACE_LANDMARKS", "0")
    assert pose_facing.detect(_blank()) is None
    monkeypatch.delenv("HOCUS_FACE_LANDMARKS")

    def broken(_image):
        raise RuntimeError("onnx session died")
    monkeypatch.setattr(face_landmarks, "detect", broken)
    assert pose_facing.detect(_blank()) is None, "a facing is advice: it never breaks a render"
    assert pose_facing.from_landmarks(None) is None and pose_facing.from_landmarks({"eyes": [], "scores": {}}) is None


def test_a_file_is_read_once_while_it_is_unchanged(tmp_path, monkeypatch):
    pose_facing._CACHE.clear()
    path = tmp_path / "pose.png"
    _blank().save(path)
    seen = []
    monkeypatch.setattr(pose_facing, "detect", lambda image: seen.append(image.size) or {"facing": "left"})
    assert pose_facing.detect_file(str(path), cached_only=True) is None and seen == []
    assert pose_facing.detect_file(str(path)) == {"facing": "left"}
    assert pose_facing.detect_file(str(path)) == {"facing": "left"} and len(seen) == 1
    Image.new("RGBA", (300, 300), (0, 0, 0, 0)).save(path)
    pose_facing.detect_file(str(path))
    assert seen == [(600, 900), (300, 300)], "a new image is read again"
    assert pose_facing.detect_file(str(tmp_path / "missing.png")) is None


def test_the_kits_own_facing_wins_over_the_detection(tmp_path, monkeypatch):
    pose_facing._CACHE.clear()
    _blank().save(tmp_path / "ines.png")
    monkeypatch.setattr(pose_facing, "detect", lambda image: {"facing": "right", "confidence": 0.8, "source": "face"})
    source = "/api/v1/file/ines.png?workspace=cast"
    kit = {"base": {"source": source}, "poses": {"ordena": {"source": source, "facing": "left"}, "gone": {"source": "/api/v1/file/no.png"}}}
    assert pose_facing.kit_pose_facing(kit, "ordena", str(tmp_path)) == {"facing": "left", "confidence": 1.0, "source": "kit"}
    assert pose_facing.kit_pose_facing(kit, "base", str(tmp_path))["facing"] == "right"
    assert pose_facing.kit_pose_facing(kit, "base") is None, "without the workspace only the kit can say"
    assert pose_facing.kit_pose_facing(kit, "gone", str(tmp_path)) is None and pose_facing.kit_pose_facing(kit, "nope") is None
    assert pose_facing.kit_facings(kit, str(tmp_path)) == {"base": "right", "ordena": "left"}
    assert pose_facing.workspace_path("/api/v1/file/../../etc/passwd", str(tmp_path)) is None


def test_a_kit_pose_keeps_a_facing_and_refuses_another_word():
    asset = {"id": "p", "name": "p", "source": "/api/v1/file/p.png"}
    kit = normalize_character_kit({"id": "ines", "name": "Inés", "base": {**asset, "facing": "front"},
                                   "poses": {"ordena": {**asset, "facing": "left"}, "busto": {**asset, "facing": None}}})
    assert kit["base"]["facing"] == "front" and kit["poses"]["ordena"]["facing"] == "left"
    assert "facing" not in kit["poses"]["busto"], "null clears it"
    with pytest.raises(ValueError, match="facing must be left, right or front"):
        normalize_character_kit({"id": "ines", "name": "Inés", "poses": {"ordena": {**asset, "facing": "up"}}})


def _cutout() -> Image.Image:
    image = Image.new("RGBA", (420, 760), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((110, 360, 310, 740), fill=(40, 90, 200, 255))
    draw.ellipse((60, 40, 360, 380), fill=(246, 214, 170, 255))
    for x in (120, 220):
        draw.ellipse((x, 120, x + 80, 220), fill=(255, 255, 255, 255))
        draw.ellipse((x + 30, 160, x + 50, 185), fill=(10, 10, 10, 255))
    draw.arc((150, 230, 270, 300), 20, 160, fill=(40, 20, 20, 255), width=7)
    return image


def test_the_flat_rig_stores_each_poses_facing_and_keeps_one_set_by_hand(tmp_path, monkeypatch):
    folder = tmp_path / "cast"
    folder.mkdir()
    _cutout().save(folder / "kevin.png")
    _cutout().save(folder / "kevin-wave.png")
    url = lambda name: f"/api/v1/file/{name}?workspace=cast"
    asset = lambda aid, name: {"id": aid, "name": aid, "source": url(name), "kind": "image", "alphaStatus": "transparent",
                               "reviewState": "approved"}
    patch_character_kit(str(folder), "kevin", {"id": "kevin", "name": "Kevin", "style": "cutout", "base": asset("b", "kevin.png"),
                                               "poses": {"wave": asset("w", "kevin-wave.png")}, "mouth": {}, "eyes": {},
                                               "anchors": {}}, base_revision=0)
    contour = [[float(x), 200.0] for x in np.linspace(100, 300, 17)]
    turned = {"nose": [[140.0, 190.0]] * 9, "contour": contour, "scores": {"nose": 0.9, "contour": 0.9}}
    monkeypatch.setattr(face_landmarks, "detect", lambda image: turned)
    rigged = rig_character(str(folder), "cast", "kevin", base_revision=1)
    assert rigged["poses"]["base"]["facing"]["facing"] == "left" and rigged["poses"]["wave"]["facing"]["source"] == "face"
    kit = rigged["character"]
    assert kit["base"]["facing"] == "left" and kit["poses"]["wave"]["facing"] == "left"
    assert kit["provenance"][-1]["facings"] == {"base": "left", "wave": "left"}
    # The user says the wave pose looks right; a later rig keeps that and updates the rest.
    kit["poses"]["wave"]["facing"] = "right"
    library = patch_character_kit(str(folder), "kevin", kit, base_revision=rigged["revision"])
    turned["nose"] = [[260.0, 190.0]] * 9
    again = rig_character(str(folder), "cast", "kevin", base_revision=library["revision"])
    assert again["character"]["poses"]["wave"]["facing"] == "right", "a facing set by hand is kept"
    assert again["character"]["base"]["facing"] == "right", "a detected one follows the new detection"
    monkeypatch.setattr(face_landmarks, "detect", lambda image: None)
    last = rig_character(str(folder), "cast", "kevin", base_revision=again["revision"], pose_ids=["base"])
    assert "facing" not in last["character"]["base"] and "facing" not in last["poses"]["base"]
    assert read_character_kit_library(str(folder))["kits"]["kevin"]["poses"]["wave"]["facing"] == "right"

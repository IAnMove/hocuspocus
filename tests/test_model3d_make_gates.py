"""What ``model3d.anime.make`` and ``model3d.blob.make`` say about what went quietly wrong, and the style registry that advertises them."""
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from services import blob_face, blob_face_relief
from services.anime_make import STYLES, make_character, resolve_traits
from services.blob_builder import BlobTraitsError
from services.blob_make import build_body, resolve_request, write_body
from services.character_3d_styles import PLANNED_LIMIT, STYLES as REGISTRY
from services.make_gates import humanoid_report, picture_notes, pictures_gate, relief_gate, with_gates
from services.real_character_recipe import INPUT_FIELDS as REAL_FIELDS, resolve_input


def _painted(size):
    """A picture with real detail: a gradient with noise, far from one colour."""
    rng = np.random.default_rng(7)
    width, height = size
    ramp = np.linspace(40, 200, width, dtype=np.float32)[None, :, None] * np.ones((height, 1, 3), dtype=np.float32)
    return Image.fromarray(np.clip(ramp + rng.normal(0, 25, (height, width, 3)), 0, 255).astype(np.uint8))


def _codes(notes):
    return [item["code"] for item in notes]


def test_the_rig_notes_and_confidence_are_in_the_reply_of_the_blob_body(tmp_path):
    traits, clips = resolve_request({"preset": "sailor", "clips": ["idle"]})
    body = build_body(traits, clips)
    body["sidecar"]["warnings"] = ["neck_not_found", "short_legs"]
    body["sidecar"]["confidence"] = 0.7
    result = write_body(tmp_path, "studio", "Salty", "intent-1", body)
    assert result["humanoid"] == {"warnings": ["neck_not_found", "short_legs"], "confidence": 0.7}
    written = json.loads((tmp_path / result["rigged_file"]).with_suffix(".humanoid.json").read_text(encoding="utf-8"))
    assert written["warnings"] == result["humanoid"]["warnings"], "the reply and the file beside the GLB say the same"
    result["humanoid"]["warnings"].append("changed")
    assert body["sidecar"]["warnings"] == ["neck_not_found", "short_legs"], "the reply is a copy: the sidecar is not touched"


def test_a_rig_without_notes_gives_an_empty_list_and_a_missing_confidence_is_left_out():
    assert humanoid_report({"warnings": [], "confidence": 1.0}) == {"warnings": [], "confidence": 1.0}
    assert humanoid_report({}) == {"warnings": []}


def test_the_relief_is_reported_only_for_a_real_body_with_a_head_picture(monkeypatch, tmp_path):
    missing = tmp_path / "ckpts" / "depth" / "depth_anything_v2_vitb.pth"
    monkeypatch.setattr(blob_face_relief, "CHECKPOINT", missing)
    assert relief_gate({"style": "anime", "texture_head": None}, None) == {}
    assert relief_gate({"style": "real", "texture_head": None}, None) == {}
    assert relief_gate({"style": "voxel", "texture_head": None}, None) == {}
    assert relief_gate({"style": "real", "texture_head": "head.png"}, lambda x, y: 0.0) == {"relief": "applied", "warnings": []}
    skipped = relief_gate({"style": "real", "texture_head": "head.png"}, None)
    assert skipped["relief"] == "skipped" and _codes(skipped["warnings"]) == ["relief_skipped"]
    message = skipped["warnings"][0]["message"]
    assert "ckpts/depth/depth_anything_v2_vitb.pth" in message and "face stays flat" in message
    assert str(tmp_path) not in message, "no absolute path leaks into a reply that is stored in the journal"


@pytest.mark.parametrize("size, expected", [
    ((2048, 1024), []), ((1800, 1000), []), ((2200, 1000), []), ((1024, 1024), ["picture_not_2_to_1"]),
    ((1700, 1000), ["picture_not_2_to_1"]), ((2300, 1000), ["picture_not_2_to_1"]), ((1024, 2048), ["picture_not_2_to_1"]),
])
def test_a_picture_that_is_not_about_two_to_one_is_noted(size, expected):
    assert _codes(picture_notes("texture", "body.png", _painted(size))) == expected


def test_a_flat_picture_is_noted_and_a_painted_one_is_not():
    flat = picture_notes("texture_head", "head.png", Image.new("RGB", (2048, 1024), (120, 90, 70)))
    assert _codes(flat) == ["picture_flat"] and flat[0]["file"] == "head.png"
    nearly = Image.new("RGB", (2048, 1024), (120, 90, 70))
    nearly.putpixel((5, 5), (121, 90, 70))
    assert _codes(picture_notes("texture", "x.png", nearly)) == ["picture_flat"]
    assert picture_notes("texture", "x.png", _painted((2048, 1024))) == []
    both = picture_notes("texture", "x.png", Image.new("RGB", (500, 500), (9, 9, 9)))
    assert _codes(both) == ["picture_not_2_to_1", "picture_flat"]
    assert pictures_gate({"texture": "a.png", "texture_head": None}, _painted((2048, 1024)), None) == []


def test_with_gates_keeps_the_replys_own_notes_first_and_always_lists_warnings():
    assert with_gates({"a": 1}) == {"a": 1, "warnings": []}
    merged = with_gates({"a": 1, "warnings": [{"code": "x", "message": "m"}]}, {"relief": "skipped", "warnings": [{"code": "y", "message": "n"}]}, {})
    assert merged["relief"] == "skipped" and _codes(merged["warnings"]) == ["x", "y"]


def _real_workspace(monkeypatch, head_size=(2048, 1024), body_size=(2048, 1024)):
    """A workspace with two pictures, a stub face kit (the program face takes seconds and is not under test) and no depth model."""
    monkeypatch.setattr(blob_face, "save_face_kit", lambda *a, **k: {"kit_id": "anime-test", "poses": {}, "preview": "", "face": {}})
    monkeypatch.setattr(blob_face_relief, "CHECKPOINT", blob_face_relief.CHECKPOINT.with_name("not_there.pth"))
    folder = Path(tempfile.mkdtemp())
    _painted(body_size).save(folder / "body.png")
    _painted(head_size).save(folder / "head.png")
    return folder


def _real(folder, **traits):
    return make_character(folder, "studio", "Real", "i-real", {"style": "real", "gender": "man", "texture": "body.png", **traits})


def test_a_real_body_says_the_relief_was_skipped_and_why(monkeypatch):
    folder = _real_workspace(monkeypatch)
    made = _real(folder, texture_head="head.png")
    assert made["relief"] == "skipped" and _codes(made["warnings"]) == ["relief_skipped"]
    assert "not_there.pth" in made["warnings"][0]["message"]
    assert isinstance(made["humanoid"]["warnings"], list) and 0 < made["humanoid"]["confidence"] <= 1
    assert made["texture_file"] == "body.png" and made["face_pose_file"].endswith("-face-pose.png")


def test_a_real_body_says_the_relief_was_applied_when_the_depth_model_answers(monkeypatch):
    folder = _real_workspace(monkeypatch)

    def sampler(*_args, **_kwargs):
        relief = lambda x, y: 0.0
        relief.yaw = 40.0
        return relief

    monkeypatch.setattr(blob_face_relief, "relief_from_picture", sampler)
    made = _real(folder, texture_head="head.png")
    assert made["relief"] == "applied" and made["warnings"] == []


def test_the_pictures_of_a_real_body_are_noted_before_the_relief(monkeypatch):
    folder = _real_workspace(monkeypatch, head_size=(1024, 1024))
    Image.new("RGB", (2048, 1024), (30, 30, 30)).save(folder / "body.png")
    made = _real(folder, texture_head="head.png")
    assert _codes(made["warnings"]) == ["picture_flat", "picture_not_2_to_1", "relief_skipped"]
    assert [item.get("file") for item in made["warnings"]] == ["body.png", "head.png", None]


def test_a_real_body_with_only_a_body_picture_has_no_relief_field(monkeypatch):
    made = _real(_real_workspace(monkeypatch))
    assert "relief" not in made and made["warnings"] == []


def test_a_blocky_skin_is_square_by_design_and_is_not_noted():
    folder = Path(tempfile.mkdtemp())
    Image.new("RGB", (64, 64), (200, 30, 30)).save(folder / "skin.png")
    made = make_character(folder, "studio", "Red", "i-red", {"style": "voxel", "texture": "skin.png"})
    assert made["warnings"] == [] and "relief" not in made
    assert set(made["humanoid"]) <= {"warnings", "confidence"}


def test_every_style_that_is_not_planned_names_a_make_recipe_the_operation_accepts():
    checked = 0
    for key, style in REGISTRY.items():
        if style["status"] == "planned":
            continue
        recipe = style["make"]
        if style["operation"] == "model3d.anime.make":
            assert recipe["style"] in STYLES, key
            assert resolve_traits({"style": recipe["style"]})["style"] == recipe["style"], key
        elif style["operation"] == "model3d.real.make":
            assert {"outfit_prompt", "face_prompt"} <= set(recipe) <= set(REAL_FIELDS), key
            concrete = {field: value.split("|")[0] if "|" in value else "Plain clothes." for field, value in recipe.items()}
            assert resolve_input(concrete, None)["gender"] == "man", key   # the recipe as written is accepted by its own operation
        else:
            assert resolve_request({"traits": {"family": recipe["family"]}})[0]["family"] == recipe["family"], key
        checked += 1
    assert checked >= 6


def test_a_planned_style_is_marked_so_nobody_calls_it_and_the_operation_does_refuse_it():
    planned = {key: style for key, style in REGISTRY.items() if style["status"] == "planned"}
    assert {"ps1", "clay", "toon_real"} <= set(planned)
    for key, style in planned.items():
        assert style["limits"][0] == PLANNED_LIMIT and "not callable" in PLANNED_LIMIT, key
        with pytest.raises(BlobTraitsError) as refused:
            resolve_traits({"style": style["make"]["style"]})
        assert refused.value.code == "invalid_style", key


def test_the_real_style_entry_no_longer_says_it_cannot_talk():
    entry = REGISTRY["real"]
    text = json.dumps([entry["face"], entry["limits"], entry["next"], REGISTRY["anime"]["next"]]).lower()
    assert "no expressions" not in text and "lipsync mouths yet" not in text and "a photo face kit with warped mouths and blink" not in text
    assert "warped mouths" in entry["face"] and "only the mouth" in " ".join(entry["limits"])

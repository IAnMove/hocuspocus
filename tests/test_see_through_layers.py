"""See-through layers for the flat rig. The real worker is not run: tests replace ``decompose_image``."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from services import install_catalog, resource_scheduler, runtime_profiles as profiles
from services.character_kit_library import normalize_character_kit, patch_character_kit, read_character_kit_library
from services.flat_rig import _figure_box, rig_character
from services.flat_rig_base import FlatRigError
from services.flat_rig_look import rig_style
from services.see_through.worker import canvas_to_source, publish_layers
from services.see_through_layers import apply_face_layers
from services.series_commands import OPERATIONS
from services.tool_sidecars import rig_sidecars
from services import see_through_layers

WORKSPACE = "cast"


def _figure(mouth: bool = True) -> Image.Image:
    """A keyed figure whose white eyes sit high. Layer eyes in the fake sit lower, on the cheeks."""
    image = Image.new("RGBA", (420, 760), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((110, 360, 310, 740), fill=(40, 90, 200, 255))
    draw.ellipse((60, 40, 360, 380), fill=(230, 190, 160, 255))
    for x in (120, 220):
        draw.ellipse((x, 100, x + 80, 200), fill=(255, 255, 255, 255))
        draw.ellipse((x + 30, 140, x + 50, 165), fill=(10, 10, 10, 255))
    if mouth:
        draw.arc((150, 230, 270, 300), 20, 160, fill=(40, 20, 20, 255), width=7)
    return image


def _layers(image: Image.Image, pose: str) -> dict:
    """Source-aligned stand-in for the worker: eyes below the white blobs, a mouth on the painted one."""
    def blank():
        return Image.new("RGBA", image.size, (0, 0, 0, 0))
    eyes, iris, lash = blank(), blank(), blank()
    ImageDraw.Draw(eyes).ellipse((130, 250, 190, 310), fill=(255, 255, 255, 255))
    ImageDraw.Draw(eyes).ellipse((230, 250, 290, 310), fill=(255, 255, 255, 255))
    ImageDraw.Draw(iris).ellipse((150, 270, 170, 295), fill=(20, 20, 20, 255))
    ImageDraw.Draw(iris).ellipse((250, 270, 270, 295), fill=(20, 20, 20, 255))
    ImageDraw.Draw(lash).rectangle((130, 248, 290, 254), fill=(0, 0, 0, 255))
    images = {"eyewhite": eyes, "irides": iris, "eyelash": lash}
    missing: list[str] = []
    if pose == "shrug":
        missing.append("mouth")
    else:
        mouth = blank()
        ImageDraw.Draw(mouth).rectangle((150, 240, 270, 280), fill=(40, 20, 20, 255))
        images["mouth"] = mouth
    return {"images": images, "missing": missing}


def _workspace(tmp_path: Path, shrug: bool = True) -> Path:
    folder = tmp_path / WORKSPACE
    folder.mkdir()
    _figure().save(folder / "gorthak-keyed.png")
    url = lambda name: f"/api/v1/file/{name}?workspace={WORKSPACE}"
    asset = lambda aid, name: {"id": aid, "name": aid, "source": url(name), "kind": "image",
                               "alphaStatus": "transparent", "reviewState": "approved"}
    kit = {"id": "gorthak", "name": "Gorthak", "style": "cutout", "base": asset("gorthak-base", "gorthak-keyed.png"),
           "poses": {}, "mouth": {}, "eyes": {}, "anchors": {}}
    if shrug:
        _figure(mouth=False).save(folder / "gorthak-shrug-keyed.png")
        kit["poses"]["shrug"] = asset("gorthak-shrug", "gorthak-shrug-keyed.png")
    patch_character_kit(str(folder), "gorthak", kit, base_revision=0)
    return folder


def _patch_worker(monkeypatch):
    calls: list[str] = []

    def fake(image, pose):
        calls.append(pose)
        return _layers(image, pose)

    monkeypatch.setattr(see_through_layers, "installed", lambda: True)
    monkeypatch.setattr(see_through_layers, "decompose_image", fake)
    return calls


def _names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def test_a_normal_rig_does_not_call_see_through_or_store_face_source(tmp_path, monkeypatch):
    calls = _patch_worker(monkeypatch)
    folder = _workspace(tmp_path, shrug=False)
    rigged = rig_character(str(folder), WORKSPACE, "gorthak", base_revision=1, style={"mouthStyle": "warp"})
    assert calls == []
    assert "faceSource" not in rigged["style"]
    assert "layers" not in rigged["character"]["anchors"]["base"]


def test_layers_place_the_blink_and_the_mouth_and_a_rerig_keeps_them(tmp_path, monkeypatch):
    calls = _patch_worker(monkeypatch)
    acquired: list[str] = []
    real = resource_scheduler.coordinator.acquire

    def spy(lane, *args, **kwargs):
        acquired.append(lane.key)
        return real(lane, *args, **kwargs)

    monkeypatch.setattr(resource_scheduler.coordinator, "acquire", spy)
    folder = _workspace(tmp_path)
    plain = rig_character(str(folder), WORKSPACE, "gorthak", base_revision=1, style={"mouthStyle": "warp"})
    assert calls == [] and acquired == []
    rigged = rig_character(str(folder), WORKSPACE, "gorthak", base_revision=plain["revision"],
                           style={"mouthStyle": "warp", "faceSource": "layers"})
    assert calls == ["base", "shrug"] and acquired == ["local_gpu:0"]
    assert rigged["style"]["faceSource"] == "layers"
    assert rigged["character"]["anchors"]["base"]["eyes"]["offsetY"] > plain["character"]["anchors"]["base"]["eyes"]["offsetY"]
    _assert_blink_covers_layer_eyes(folder, rigged)
    line = rigged["poses"]["base"]["mouthLine"]
    assert abs(line["mouth"][0] - 50) < 8 and abs(line["mouth"][1] - 34.2) < 8
    assert abs(line["mouthWidth"] - 28.6) < 8
    assert "layer_missing_mouth" in rigged["warnings"]["shrug"]
    assert "layer_missing_mouth" not in rigged["warnings"].get("base", [])
    layers = rigged["character"]["anchors"]["base"]["layers"]
    assert set(layers) >= {"eyewhite", "irides", "eyelash", "mouth"}
    rig_sidecars(rigged, workspace=WORKSPACE, kit_id="gorthak", folder=str(folder), request={})
    name = layers["eyewhite"].split("/api/v1/file/", 1)[1].split("?", 1)[0]
    assert (folder / name).is_file()
    assert json.loads((folder / name).with_suffix(".meta.json").read_text())["params"]["role"].endswith("eyewhite")
    again = rig_character(str(folder), WORKSPACE, "gorthak", base_revision=rigged["revision"])
    assert again["style"]["faceSource"] == "layers"
    assert calls == ["base", "shrug", "base", "shrug"]


def _assert_blink_covers_layer_eyes(folder: Path, rigged: dict) -> None:
    """The lid anchor sits on the layer eyes (source y 250–310), not on the white blobs (source y 100–200)."""
    _cleaned, crop = _figure_box(_figure())
    anchor = rigged["character"]["anchors"]["base"]["eyes"]
    pose = next(folder.glob("kit-gorthak-base-rig-*.png"))
    with Image.open(pose) as image:
        edge = max(image.size)
        cy = image.height / 2 + anchor["offsetY"] * edge / 100 + crop[1]
    assert 250 <= cy <= 330
    assert cy > 220


def test_a_user_mouth_hint_is_not_replaced_by_the_layer(tmp_path, monkeypatch):
    _patch_worker(monkeypatch)
    folder = _workspace(tmp_path, shrug=False)
    rigged = rig_character(str(folder), WORKSPACE, "gorthak", base_revision=1,
                           style={"mouthStyle": "warp", "faceSource": "layers"},
                           hints={"base": {"mouth": [12, 12], "mouthWidth": 8, "exact": True}})
    saved = rigged["character"]["provenance"][-1]["hints"]["base"]
    assert saved["mouth"] == [12, 12] and saved["mouthWidth"] == 8 and saved["exact"] is True


def test_missing_eye_layers_keep_the_guessed_blink():
    rig = {"warnings": [], "blink": "keep", "eyes": {"offsetY": -10}, "blinks": True, "width": 10, "height": 10,
           "frame": (0, 0, 10, 10), "mouth": {"offsetY": 1}, "skin": (1, 2, 3)}
    apply_face_layers(
        {"base": rig},
        {"base": {"images": {}, "missing": ["eyewhite", "irides", "eyelash", "mouth"], "mouth_box": None}},
        {"mouthStyle": "paper", "screen": False}, {})
    assert rig["blink"] == "keep"
    assert rig["warnings"] == ["layer_missing_eyewhite", "layer_missing_irides", "layer_missing_eyelash", "layer_missing_mouth"]


def test_layers_without_the_component_leave_the_kit_unchanged(tmp_path):
    folder = _workspace(tmp_path, shrug=False)
    before = _names(folder)
    revision = read_character_kit_library(str(folder))["revision"]
    with pytest.raises(FlatRigError) as error:
        rig_character(str(folder), WORKSPACE, "gorthak", base_revision=revision, style={"faceSource": "layers"})
    assert error.value.code == "see_through_not_installed"
    assert "Settings > Installation" in str(error.value)
    assert _names(folder) == before
    assert read_character_kit_library(str(folder))["revision"] == revision


def test_layers_on_windows_are_refused_even_when_the_files_exist(tmp_path, monkeypatch):
    folder = _workspace(tmp_path, shrug=False)
    before = _names(folder)
    monkeypatch.setattr(see_through_layers.sys, "platform", "win32")
    monkeypatch.setattr(see_through_layers, "installed", lambda: True)
    with pytest.raises(FlatRigError) as error:
        rig_character(str(folder), WORKSPACE, "gorthak", base_revision=1, style={"faceSource": "layers"})
    assert error.value.code == "see_through_unsupported"
    assert "Linux" in str(error.value)
    assert _names(folder) == before


def test_face_source_is_layers_or_absent():
    with pytest.raises(FlatRigError) as error:
        rig_style({"faceSource": "nope"})
    assert error.value.code == "invalid_style"
    assert "faceSource" not in rig_style(None)
    assert rig_style({"faceSource": "layers"})["faceSource"] == "layers"
    assert OPERATIONS["characters.rig.flat"][0]["style"]["properties"]["faceSource"] == {"enum": ["detect", "layers"]}


def test_the_catalog_marks_see_through_linux_only_and_records_both_licences():
    component = install_catalog.get("see_through")
    engine = profiles.catalog()["engines"]["see_through"]
    assert component.platforms == ("linux",) and engine["platforms"] == ["linux"]
    assert "Apache-2.0" in component.license and "OpenRAIL++" in component.license
    assert component.as_dict()["license"] == component.license
    assert "license" not in install_catalog.get("sam").as_dict()
    assert component.estimated_bytes == 12 * 1024 ** 3
    assert (Path(__file__).resolve().parents[1] / component.script).is_file()
    assert engine["source"]["revision"] == "df019de5129d6c4b406587a14c3501669441a783"
    assert "See-through" in engine["unsupportedReason"] and "Optional" not in engine["unsupportedReason"]
    linux = profiles.select_profiles("linux", "x64", "nvidia", "580.82.09")["engines"]["see_through"]
    windows = profiles.select_profiles("win32", "x64", "nvidia", "580.82.09")["engines"]["see_through"]
    assert linux["supported"] is True and windows["supported"] is False


def test_canvas_pixels_return_to_the_source_after_the_square_pad():
    canvas = np.zeros((6, 6, 4), np.uint8)
    canvas[0, 1] = (9, 8, 7, 255)
    source = canvas_to_source(canvas, 4, 6, 6)
    assert source.shape == (6, 4, 4)
    assert tuple(int(v) for v in source[0, 0]) == (9, 8, 7, 255)


def test_a_transparent_class_is_missing_and_a_spaced_name_is_kept(tmp_path):
    canvas = tmp_path / "canvas"
    canvas.mkdir()
    Image.new("RGBA", (6, 6), (0, 0, 0, 0)).save(canvas / "mouth.png")
    hair = np.zeros((6, 6, 4), np.uint8)
    hair[0, 1] = (1, 2, 3, 255)
    Image.fromarray(hair).save(canvas / "front hair.png")
    manifest = publish_layers(canvas, tmp_path / "out", 4, 6, "base", resolution=6)
    assert "mouth" in manifest["missing"] and manifest["classes"]["front hair"].endswith(".png")
    assert json.loads((tmp_path / "out" / "layers.json").read_text())["space"] == "source"
    with Image.open(tmp_path / "out" / manifest["classes"]["front hair"]) as image:
        assert image.getpixel((0, 0)) == (1, 2, 3, 255)


def test_saved_layer_urls_round_trip_and_a_blob_is_refused():
    kit = {"id": "lola", "name": "Lola", "style": "cutout",
           "base": {"id": "b", "name": "Lola", "source": "/api/v1/file/b.png?workspace=w", "reviewState": "approved"},
           "poses": {}, "mouth": {}, "eyes": {},
           "anchors": {"base": {"mouth": {"offsetX": 0, "offsetY": -20, "scale": 0.05, "rotation": 0},
                                "layers": {"eyewhite": "/api/v1/file/eye.png?workspace=w", "front hair": "/api/v1/file/hair.png?workspace=w"}}}}
    restored = normalize_character_kit(kit)["anchors"]["base"]["layers"]
    assert restored["front hair"].endswith("hair.png?workspace=w")
    kit["anchors"]["base"]["layers"]["eyewhite"] = "blob:http://x/1"
    with pytest.raises(ValueError, match="persistent"):
        normalize_character_kit(kit)

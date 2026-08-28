import json

import pytest

from services.character_kit_library import (
    CharacterKitRevisionConflict,
    delete_character_kit,
    empty_character_kit_library,
    normalize_character_kit,
    patch_character_kit,
    read_character_kit_library,
)


def asset(asset_id="luma-base", source="2026-luma.png"):
    return {
        "id": asset_id,
        "name": asset_id,
        "source": source,
        "kind": "image",
        "alphaStatus": "transparent",
        "reviewState": "approved",
    }


def kit():
    return {
        "version": 1,
        "id": "luma",
        "name": "Luma",
        "style": "cutout",
        "identityReference": asset("luma-ref"),
        "base": asset(),
        "poses": {"point": asset("luma-point", "luma-point.png")},
        "mouth": {"closed": asset("mouth-closed", "mouth-closed.png"), "wide": asset("mouth-wide", "mouth-wide.png")},
        "eyes": {"blink": asset("eyes-blink", "eyes-blink.png")},
        "anchors": {"base": {"mouth": {"offsetX": 1.5, "offsetY": -2, "scale": .12, "rotation": 0}}},
        "provenance": [{"method": "hocuspocus-image", "prompt": "paper cutout girl"}],
    }


def test_character_kit_normalizes_reusable_assets_and_pose_anchor():
    normalized = normalize_character_kit(kit())
    assert normalized["mouth"]["wide"]["reviewState"] == "approved"
    assert normalized["anchors"]["base"]["mouth"]["offsetX"] == 1.5
    assert normalized["provenance"][0]["method"] == "hocuspocus-image"


def test_character_kit_normalizes_per_state_mouth_anchors_with_legacy_fallback():
    value = kit()
    value["anchors"]["base"]["mouthStates"] = {
        "wide": {"offsetX": 3, "offsetY": -4, "scale": .2, "rotation": 1},
        "round": {"offsetX": 2, "offsetY": -5, "scale": .18, "rotation": 0},
    }
    normalized = normalize_character_kit(value)
    assert normalized["anchors"]["base"]["mouth"]["offsetX"] == 1.5
    assert normalized["anchors"]["base"]["mouthStates"]["wide"]["offsetX"] == 3


def test_character_kit_rejects_unknown_mouth_state_anchor():
    value = kit()
    value["anchors"]["base"]["mouthStates"] = {
        "smile": {"offsetX": 0, "offsetY": 0, "scale": .2, "rotation": 0},
    }
    with pytest.raises(ValueError, match="invalid mouth states"):
        normalize_character_kit(value)


def test_character_kit_rejects_browser_only_sources():
    value = kit()
    value["base"]["source"] = "blob:http://localhost/transient"
    with pytest.raises(ValueError, match="persistent source"):
        normalize_character_kit(value)


def test_character_kit_library_is_atomic_and_revision_guarded(tmp_path):
    first = patch_character_kit(tmp_path, "luma", kit(), base_revision=0)
    assert first["revision"] == 1
    assert read_character_kit_library(tmp_path)["kits"]["luma"]["name"] == "Luma"
    with pytest.raises(CharacterKitRevisionConflict):
        patch_character_kit(tmp_path, "luma", kit(), base_revision=0)
    assert not list(tmp_path.glob("*.tmp"))


def test_character_kit_delete_preserves_other_kits(tmp_path):
    first = patch_character_kit(tmp_path, "luma", kit(), base_revision=0)
    other = {**kit(), "id": "brin", "name": "Brin"}
    second = patch_character_kit(tmp_path, "brin", other, base_revision=first["revision"])
    final = delete_character_kit(tmp_path, "luma", base_revision=second["revision"])
    assert set(final["kits"]) == {"brin"}
    assert final["activeId"] == "brin"
    stored = json.loads((tmp_path / ".character-kit-library-v1.json").read_text())
    assert stored["revision"] == 3


def test_empty_library_has_stable_contract():
    assert empty_character_kit_library() == {"version": 1, "revision": 0, "activeId": "", "kits": {}}

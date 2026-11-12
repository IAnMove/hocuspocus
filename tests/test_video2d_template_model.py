"""Template preparation follows the 2026-10-12 model: aliases, retired ids, one slot vocabulary, choice and text
controls, video backgrounds and the cutout alpha warning (docs/development/VIDEO2D_TEMPLATE_MODEL.md)."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest

from services.video2d_compile import CompileError, command_handlers, execute, has_transparency, prepare_template

ROOT = Path(__file__).resolve().parents[1]
TSX = ROOT / "ui" / "node_modules" / "tsx" / "dist" / "cli.mjs"
CATALOG = json.loads((ROOT / "app" / "shared" / "scene_templates.json").read_text(encoding="utf-8"))
PICTURE = "/api/v1/file/a.png"
PLATE = "/api/v1/file/plate.png"
MERGES = {
    "cinema-isolation": ("cinema-establishing", {"mood": "lonely"}),
    "music-parallax": ("cinema-tracking", {"atmosphere": "streaks"}),
    "music-stage": ("music-pulse", {"camera": "sweep"}),
    "music-finale": ("music-pulse", {"camera": "open", "atmosphere": "confetti"}),
    "music-chorus": ("music-pulse", {"camera": "beat", "atmosphere": "confetti"}),
    "music-satellite-swarm": ("music-orbit", {"bounce": "off"}),
    "music-ricochet-pass": ("music-pinball", {"bouncer": "prop"}),
    "space-shield": ("space-broadside", {"outcome": "shield"}),
    "space-explosion": ("space-broadside", {"outcome": "explode"}),
}


def _assets(card: str) -> dict[str, str]:
    """A durable picture for every slot the card has (sources differ: the choreographies want distinct assets)."""
    entry = next(item for item in CATALOG["entries"] if item["id"] == card)
    return {slot["id"]: f"/api/v1/file/{card}-{slot['id']}.png" for slot in entry["slots"]}


def _code(data: dict) -> str:
    try:
        prepare_template(data)
    except CompileError as error:
        return error.code
    return "prepared"


def _png(mode: str, color, kind: str = "PNG") -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new(mode, (4, 4), color).save(buffer, kind)
    return buffer.getvalue()


def test_the_catalog_lists_47_cards_and_the_contract_aliases():
    assert len(CATALOG["entries"]) == 48
    assert {alias: (row["card"], row["preset"]) for alias, row in CATALOG["aliases"].items()} == MERGES
    assert sorted(CATALOG["retired"]) == ["lyric-vertical", "trailer-teaser"]
    ids = {entry["id"] for entry in CATALOG["entries"]}
    assert not ids & (set(MERGES) | set(CATALOG["retired"]))


@pytest.mark.parametrize(("alias", "merge"), sorted(MERGES.items()))
def test_an_alias_prepares_as_its_card_with_the_preset(alias, merge):
    card, preset = merge
    prepared = prepare_template({"templateId": alias, "assets": _assets(card)})
    assert prepared["card"] == card and prepared["alias"] == alias
    assert prepared["request"]["templateId"] == alias
    for key, value in preset.items():
        assert prepared["request"]["controls"][key] == value
    caller = next(iter(preset))
    other = next(option for option in next(e for e in CATALOG["entries"] if e["id"] == card)["controls"][caller]["options"] if option != preset[caller])
    overridden = prepare_template({"templateId": alias, "assets": _assets(card), "controls": {caller: other}})
    assert overridden["request"]["controls"][caller] == other, "the caller's value wins over the preset"


def test_a_retired_id_fails_before_node_with_what_to_use_instead(monkeypatch):
    monkeypatch.setattr("services.video2d_compile.spawn_bridge", lambda payload: pytest.fail(str(payload)))
    with pytest.raises(CompileError) as caught:
        execute({"version": 1, "operation": "scenes.template.compile", "input": {"templateId": "trailer-teaser", "assets": {}}})
    assert caught.value.code == "template_retired"
    assert caught.value.extra == {"use_instead": ["title-card", "trailer-slam"]}
    assert "title-card" in str(caught.value)


def test_the_mcp_error_carries_use_instead():
    import asyncio

    from fastapi import HTTPException

    handle = command_handlers()["scenes.template.compile"]
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handle({"version": 1, "input": {"templateId": "lyric-vertical"}}))
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "template_retired"
    assert caught.value.detail["use_instead"] == ["scenes.lyrics.import"]


def test_old_slot_names_translate_once_by_card_and_conflicts_fail():
    two_shot = prepare_template({"templateId": "cinema-two-shot", "assets": {"hero": PICTURE, "plate": PLATE, "prop": "/api/v1/file/b.png"}})
    assert two_shot["request"]["assets"] == {"subject_1": PICTURE, "background": PLATE, "subject_2": "/api/v1/file/b.png"}
    orbit = prepare_template({"templateId": "space-orbit", "assets": {"hero": PICTURE, "plate": PLATE, "prop": "/api/v1/file/p.png"}})
    assert set(orbit["request"]["assets"]) == {"subject_1", "background", "prop_1"}
    assert _code({"templateId": "cinema-establishing", "assets": {"hero": PICTURE, "subject_1": PICTURE, "plate": PLATE}}) == "slot_alias_conflict"
    assert _code({"templateId": "cinema-establishing", "assets": {"subject_1": PICTURE, "plate": PLATE, "background": PLATE}}) == "slot_alias_conflict"
    assert _code({"templateId": "cinema-establishing", "assets": {"subject_1": PICTURE, "background": PLATE, "prop": PICTURE}}) == "template_bad_asset"


def test_choice_and_text_controls_are_checked_like_the_typescript_compile():
    pulse = {"templateId": "music-pulse", "assets": _assets("music-pulse")}
    assert prepare_template({**pulse, "controls": {"camera": "beat"}})["request"]["controls"]["camera"] == "beat"
    assert prepare_template(pulse)["request"]["controls"]["drift"] == 0.5
    for bad in ({"camera": "dolly"}, {"camera": 3}, {"drift": 1.5}, {"drift": "0.5"}, {"mood": "calm"}):
        assert _code({**pulse, "controls": bad}) == "template_bad_control", bad
    history = {"templateId": "documentary-history", "assets": _assets("documentary-history")}
    assert prepare_template({**history, "controls": {"caption": "🎞" * 80}})["request"]["controls"]["caption"] == "🎞" * 80
    assert _code({**history, "controls": {"caption": "x" * 81}}) == "template_bad_control"
    assert _code({**history, "controls": {"caption": 7}}) == "template_bad_control"
    assert prepare_template(history)["request"]["controls"]["yearTo"] == "1968"


def test_a_choice_can_require_a_slot():
    pinball = {"templateId": "music-pinball", "assets": {"subject_1": PICTURE, "background": PLATE}}
    assert _code(pinball) == "prepared"
    assert _code({**pinball, "controls": {"bouncer": "prop"}}) == "template_missing_slot"
    assert _code({"templateId": "music-ricochet-pass", "assets": pinball["assets"]}) == "template_missing_slot"


def test_a_background_may_be_a_looping_video_and_ships_may_be_pictures():
    assert prepare_template({"templateId": "music-spiral-exit", "assets": {"subject_1": PICTURE, "background": "/api/v1/file/sea.mp4"}})
    assert _code({"templateId": "music-spiral-exit", "assets": {"subject_1": "/api/v1/file/dance.mp4", "background": PLATE}}) == "template_bad_asset"
    assert _code({"templateId": "documentary-history", "assets": {"subject_1": PICTURE, "background": "/api/v1/file/sea.webm"}}) == "template_bad_asset"
    assert _code({"templateId": "documentary-history", "assets": {"subject_1": "/api/v1/file/a.glb", "background": PLATE}}) == "template_bad_asset"
    assert _code({"templateId": "space-chase", "assets": {"subject_1": PICTURE, "background": PLATE, "prop_1": "/api/v1/file/rival.glb"}}) == "prepared"


def test_transparency_is_read_from_the_pixels(tmp_path):
    (tmp_path / "cut.png").write_bytes(_png("RGBA", (255, 0, 0, 0)))
    (tmp_path / "opaque.png").write_bytes(_png("RGBA", (255, 0, 0, 255)))
    (tmp_path / "photo.jpg").write_bytes(_png("RGB", (255, 0, 0), "JPEG"))
    folder = lambda name: str(tmp_path)  # noqa: E731
    assert has_transparency("/api/v1/file/cut.png?workspace=default", folder) is True
    assert has_transparency("/api/v1/file/opaque.png", folder) is False
    assert has_transparency("/api/v1/file/photo.jpg?workspace=default", folder) is False
    assert has_transparency("/api/v1/file/missing.png", folder) is None
    assert has_transparency("/api/v1/file/../outside.png", folder) is None
    assert has_transparency("https://example.com/a.png", folder) is None, "never fetched"
    inline = "data:image/png;base64," + base64.b64encode(_png("RGB", (0, 0, 0))).decode()
    assert has_transparency(inline, folder) is False


def test_cutout_without_alpha_warns_for_choreography_subjects_only(tmp_path, monkeypatch):
    (tmp_path / "cut.png").write_bytes(_png("RGBA", (0, 0, 0, 0)))
    (tmp_path / "photo.jpg").write_bytes(_png("RGB", (9, 9, 9), "JPEG"))
    folder = lambda name: str(tmp_path)  # noqa: E731
    duel = {"templateId": "music-orbit-duel", "assets": {"subject_1": "/api/v1/file/cut.png", "subject_2": "/api/v1/file/photo.jpg", "background": "/api/v1/file/photo.jpg"}}
    warnings = prepare_template(duel, workspace_dir=folder)["warnings"]
    assert [(item["code"], item["slot"]) for item in warnings] == [("cutout_without_alpha", "subject_2")]
    cinema = {"templateId": "cinema-establishing", "assets": {"subject_1": "/api/v1/file/photo.jpg", "background": "/api/v1/file/photo.jpg"}}
    assert prepare_template(cinema, workspace_dir=folder)["warnings"] == []

    seen = {}

    def fake_bridge(payload):
        seen["payload"] = payload
        return {"ok": True, "result": {"document": {"version": 1, "layers": [{"id": "background"}]}, "warnings": ["title moved"]}}

    monkeypatch.setattr("services.video2d_compile.spawn_bridge", fake_bridge)
    compact = execute({"version": 1, "operation": "scenes.template.compile", "input": duel}, workspace_dir=folder)
    assert compact["result"]["warningCodes"] == ["cutout_without_alpha", "title moved"]
    assert "warnings" not in seen["payload"]["input"]
    full = execute({"version": 1, "operation": "scenes.template.compile", "input": {**duel, "full": True}}, workspace_dir=folder)
    assert full["result"]["warnings"] == [
        {"code": "cutout_without_alpha", "slot": "subject_2", "message": full["result"]["warnings"][0]["message"]}, {"code": "title moved"}], "one shape"


@pytest.mark.skipif(not TSX.is_file(), reason="ui node_modules is not installed")
@pytest.mark.parametrize("template_id", ["music-chorus", "space-explosion", "music-satellite-swarm", "city-postcard"])
def test_python_and_typescript_resolve_the_same_card_and_controls(template_id):
    """Python resolves the alias and every control; the TypeScript compile records the same card and values."""
    card = CATALOG["aliases"].get(template_id, {}).get("card", template_id)
    data = {"templateId": template_id, "assets": _assets(card)}
    prepared = prepare_template(data)
    document = execute({"version": 1, "operation": "scenes.template.compile", "input": {**data, "full": True}})["result"]["document"]
    narrative = document["narrative"]
    assert narrative["templateId"] == prepared["card"]
    assert narrative["controls"].get("alias") == prepared["alias"]
    for key, value in prepared["request"]["controls"].items():
        assert narrative["controls"][key] == value, key

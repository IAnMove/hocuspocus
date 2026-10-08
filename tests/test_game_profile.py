"""The game profile names real tools, and the bible stays small."""
import json

from services.game_commands import command_catalog
from services.game_guide import build_bible, guide_text
from services.mcp_profiles import GAME_TOOLS, PROFILES

_EXTERNAL = {
    "generation.image", "generation.video", "generation.sfx", "generation.music", "generation.speech",
    "studio.key", "qa.accent",
    "jobs.wait", "jobs.leftovers", "jobs.resume", "jobs.discard", "jobs.cancel",
    "characters.list", "characters.get", "characters.save", "characters.rig.check",
    "model3d.generate", "model3d.status", "model3d.rig", "model3d.rig.status", "model3d.animate",
    "media.options", "scenes.assets.inspect",
}


def test_the_game_profile_names_real_game_tools():
    names = {item["name"] for item in command_catalog()}
    game_tools = {name for name in PROFILES["game"]["tools"] if name.startswith("game.")}
    assert game_tools <= names, game_tools - names
    assert game_tools == names
    assert PROFILES["game"]["tools"] == GAME_TOOLS
    assert GAME_TOOLS - names == _EXTERNAL
    assert "Never approve" in PROFILES["game"]["instructions"]
    guide = guide_text()
    assert "game.style.approve" in guide and "check: true" in guide and "game.export" in guide
    assert "Never approve" in guide and "rerender" in guide and "Measure one asset" in guide


def test_bible_stays_under_6kb_with_500_assets():
    assets = [
        {"id": f"item-{index:03d}", "kind": "sprite", "status": "review", "description": "x" * 400}
        for index in range(500)
    ]
    game = {
        "id": "bosque", "title": "Bosque encantado", "revision": 4,
        "style": {
            "preset": "pixel-16", "approval": "draft", "traits": "flat colors",
            "palette": ["#111111", "#eeeeee"], "paletteMode": "locked",
            "pixel": {"enabled": True, "spriteHeight": 48, "tile": 16, "colors": 16, "outline": "dark-1px"},
            "audio": {"genre": "chiptune", "instruments": "square", "bpm": [90, 140], "musicLufs": -16},
            "references": [{"assetId": "heroe", "attemptId": "a1"}],
        },
        "assets": assets,
    }
    bible = build_bible(game)
    assert len(json.dumps(bible, ensure_ascii=False).encode()) <= 6144
    assert bible["counts"]["sprite"]["review"] == 500
    assert len(bible["awaitingApproval"]) == 40
    assert bible["awaitingMore"] == 460
    assert bible["style"]["preset"] == "pixel-16"
    assert bible["style"]["pixel"]["tile"] == 16
    assert bible["references"] == [{"assetId": "heroe", "attemptId": "a1"}]
    assert "description" not in bible["awaitingApproval"][0]


def test_bible_names_the_assets_in_review_even_behind_many_pending():
    assets = [{"id": f"item-{index:03d}", "kind": "sprite", "status": "pending"} for index in range(60)]
    assets.append({"id": "heroe", "kind": "character", "status": "review"})
    bible = build_bible({"id": "bosque", "style": {}, "assets": assets})
    assert bible["awaitingApproval"] == [{"id": "heroe", "kind": "character", "status": "review"}]
    assert bible["awaitingMore"] == 0
    assert bible["counts"]["sprite"]["pending"] == 60


def test_guide_and_doc_describe_the_current_services():
    from pathlib import Path

    guide = guide_text()
    for fact in ("-a1", "already_running", "game_exists", "revision_conflict", "seed", "presets", "unknown_option", "invalid_spec", "waiting_dependency"):
        assert fact in guide, fact
    doc = (Path(__file__).resolve().parents[1] / "docs" / "agents" / "GAME_ASSETS_MCP.md").read_text(encoding="utf-8")
    assert "Reuse the same intent" not in doc and "or `jobs.wait`" not in doc
    assert "already_running" in doc and "game_exists" in doc and "-a1" in doc
    assert "already_running" in PROFILES["game"]["instructions"]

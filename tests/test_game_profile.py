"""The game profile names real tools, and the bible stays small."""
import json

from services.game_commands import command_catalog
from services.game_guide import build_bible, guide_text
from services.mcp_profiles import GAME_TOOLS, PROFILES

_EXTERNAL = {
    "generation.image", "generation.video", "generation.sfx", "generation.music", "generation.speech",
    "studio.key",
    "jobs.wait", "jobs.leftovers", "jobs.resume", "jobs.discard",
    "characters.list", "characters.get", "characters.save",
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

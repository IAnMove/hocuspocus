"""Fingerprints that mark a game asset stale."""
from services.game_inputs import GENERATOR_VERSION, asset_inputs, stale_assets

NOW = "2026-10-06T12:00:00Z"


def _asset(**overrides):
    asset = {
        "id": "heroe", "kind": "character", "spec": {"role": "player"}, "description": "knight",
        "notes": "", "dependsOn": [], "status": "approved", "locked": False,
        "approvedAttemptId": "a1", "attempts": [{"id": "a1", "inputs": "", "decision": "approved"}],
    }
    asset.update(overrides)
    return asset


def _game(asset):
    return {
        "style": {
            "preset": "pixel-16", "traits": "flat colors", "negative": "photo", "palette": ["#112233"],
            "paletteMode": "locked", "pixel": {"spriteHeight": 48}, "light": "top-left", "screen": "auto",
            "references": [], "model3d": {"maxTriangles": 3000}, "audio": {"genre": "chiptune"},
        },
        "assets": [asset],
    }


def test_digest_is_stable_and_short():
    game = _game(_asset())
    assert asset_inputs(game, game["assets"][0]) == asset_inputs(game, game["assets"][0])
    assert len(asset_inputs(game, game["assets"][0])) == 16


def test_digest_tracks_style_dependency_and_generator():
    game = _game(_asset())
    original = asset_inputs(game, game["assets"][0])
    game["style"]["traits"] = "other traits"
    assert asset_inputs(game, game["assets"][0]) != original
    game["style"]["traits"] = "flat colors"
    game["assets"][0]["dependsOn"] = ["slime"]
    game["assets"].append({"id": "slime", "approvedAttemptId": "b2"})
    assert asset_inputs(game, game["assets"][0]) != original
    assert GENERATOR_VERSION["character"] == 1


def test_stale_assets_skip_locked_and_pending():
    asset = _asset()
    game = _game(asset)
    asset["attempts"][0]["inputs"] = asset_inputs(game, asset)
    assert stale_assets(game) == []
    game["style"]["traits"] = "changed"
    assert stale_assets(game) == ["heroe"]
    asset["locked"] = True
    assert stale_assets(game) == []
    asset["locked"] = False
    asset["status"] = "pending"
    assert stale_assets(game) == []
    asset["status"] = "rejected"
    asset["approvedAttemptId"] = None
    asset["attempts"][0]["decision"] = "rejected"
    asset["attempts"][0]["inputs"] = "old"
    assert stale_assets(game) == ["heroe"]
    assert NOW

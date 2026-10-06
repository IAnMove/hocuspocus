"""Estimate source falls from defaults to the J0 trial, then to history."""
import json

from services.game_estimate import DEFAULTS, NAME, estimate, record, seconds_for
from services.game_library import create_game, normalize_game

NOW = "2026-10-06T12:00:00Z"


def test_defaults_then_history(tmp_path):
    assert seconds_for(tmp_path, "image", trial=None) == (DEFAULTS["image"], "defaults")
    record(tmp_path, "image", 10)
    seconds, source = seconds_for(tmp_path, "image", trial=None)
    assert source == "history(1)"
    assert seconds == 10
    record(tmp_path, "image", 30)
    assert seconds_for(tmp_path, "image", trial=None) == (30, "history(2)")
    for value in range(35):
        record(tmp_path, "sfx", value)
    stored = json.loads((tmp_path / NAME).read_text(encoding="utf-8"))
    assert stored["sfx"] == [float(value) for value in range(5, 35)]
    assert seconds_for(tmp_path, "sfx", trial=None) == (20, "history(30)")


def test_empty_history_uses_the_trial_median():
    _library, game = create_game({}, {"id": "bosque", "title": "Bosque"}, now=NOW)
    character = next(asset for asset in normalize_game(
        {"id": "bosque", "title": "Bosque", "assets": [{"id": "heroe", "kind": "character"}]}, now=NOW,
    )["assets"])
    report = estimate(None, game, [character])
    # StillGenerator.estimate already returns one image step per candidate (3). 3 * 22.4s.
    assert report["source"] == "trial"
    assert report["minutes"] == 1.1
    assert report["byKind"]["character"] == 1.12
    animation = {"id": "heroe-walk", "kind": "animation", "candidates": 1, "spec": {"method": "h3", "character": "heroe", "action": "walk"}}
    animated = estimate(None, game, [animation])
    assert animated["source"] == "trial"
    assert animated["minutes"] == 5.1

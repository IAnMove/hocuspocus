"""Estimate source falls from defaults to the J0 trial, then to history."""
import json

from services.game_estimate import DEFAULTS, NAME, TRIAL, estimate, read_timings, record, record_run, seconds_for
from services.game_generators import REGISTRY
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


class _Steps:
    def __init__(self, counts):
        self.counts = counts

    def estimate(self, _game, _asset):
        return dict(self.counts)


def test_a_finished_asset_records_one_step_not_the_whole_asset(tmp_path, monkeypatch):
    _library, game = create_game({}, {"id": "bosque", "title": "Bosque"}, now=NOW)
    monkeypatch.setitem(REGISTRY, "item", _Steps({"image": 3}))
    coin = {"id": "moneda", "kind": "item", "spec": {}}
    record_run(tmp_path, game, coin, 90)
    assert read_timings(tmp_path)["image"] == [30.0]
    # The next estimate for the same asset is the time it really took, not 3 x 90 s.
    assert estimate(tmp_path, game, [coin])["minutes"] == 1.5
    monkeypatch.setitem(REGISTRY, "model3d", _Steps({"image": 1, "3d": 1}))
    chest = {"id": "cofre", "kind": "model3d", "spec": {}}
    elapsed = 2 * (TRIAL["image"] + TRIAL["3d"])
    record_run(tmp_path / "mixed", game, chest, elapsed)
    stored = read_timings(tmp_path / "mixed")
    assert stored["image"] == [round(2 * TRIAL["image"], 3)]
    assert stored["3d"] == [round(2 * TRIAL["3d"], 3)]
    assert estimate(tmp_path / "mixed", game, [chest])["minutes"] == round(elapsed / 60.0, 1)


def test_a_generator_that_cannot_read_the_spec_falls_back(monkeypatch):
    class Broken:
        def estimate(self, _game, _asset):
            raise ValueError("invalid literal for int()")

    _library, game = create_game({}, {"id": "bosque", "title": "Bosque"}, now=NOW)
    monkeypatch.setitem(REGISTRY, "item", Broken())
    report = estimate(None, game, [{"id": "moneda", "kind": "item", "candidates": "many"}])
    assert report["byKind"]["item"] == round(TRIAL["image"] / 60.0, 3)


def test_retro_sfx_costs_no_gpu_step(monkeypatch):
    from services.game_estimate import steps_for

    class Retro:
        def estimate(self, _game, _asset):
            return {}

    retro = {"id": "salto", "kind": "sfx", "spec": {"engine": "retro", "variants": 3}}
    monkeypatch.setitem(REGISTRY, "sfx", Retro())
    assert steps_for({}, retro) == {}
    monkeypatch.delitem(REGISTRY, "sfx")
    assert steps_for({}, retro) == {}
    assert steps_for({}, {**retro, "spec": {"engine": "mmaudio", "variants": 3}}) == {"sfx": 3}

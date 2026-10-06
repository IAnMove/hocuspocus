"""Prompt order and reference selection. No GPU."""
from __future__ import annotations

from services.game_prompts import build, refs_for, screen_for


def _attempt(attempt_id, path, decision="approved"):
    return {"id": attempt_id, "decision": decision, "status": "ok", "files": {"main": path}}


def _asset(asset_id, kind="sprite", **extra):
    body = {"id": asset_id, "kind": kind, "description": "", "tags": [], "spec": {}, "attempts": []}
    body.update(extra)
    return body


def _game(assets, references):
    return {
        "id": "bosque",
        "style": {
            "preset": "pixel-16",
            "traits": "16-bit pixel art",
            "negative": "blur, photo",
            "paletteMode": "locked",
            "screen": "magenta",
            "references": references,
        },
        "assets": assets,
    }


def test_build_keeps_the_fixed_order_and_the_rejection_note():
    asset = _asset(
        "heroe", "character", description="short bronze knight", spec={"role": "boss"},
        attempts=[{"id": "a1", "decision": "rejected", "note": "make the cape red"}],
    )
    game = _game([asset], [])
    prompt, negative = build(game, asset)
    indexes = [
        prompt.index("16-bit pixel art"),
        prompt.index("full body character"),
        prompt.index("short bronze knight"),
        prompt.index("boss character"),
        prompt.index("flat solid magenta background, no shadow, no floor"),
        prompt.index("Fix: make the cape red"),
    ]
    assert indexes == sorted(indexes)
    assert "blur, photo" in negative
    assert "text, watermark, frame, border" in negative


def test_the_view_rule_is_not_repeated_after_the_preset_phrase():
    character = _asset("heroe", "character", description="knight")
    prompt, _negative = build(_game([character], []), character)
    for part in ("side view", "facing right", "full body", "centered"):
        assert prompt.count(part) == 1, part
    sprite = _asset("salto", "sprite", description="knight")
    prompt, _negative = build(_game([sprite], []), sprite)
    assert prompt.count("side view") == 1
    assert prompt.count("full body") == 1
    assert "centered" in prompt
    game = _game([sprite], [])
    game["style"]["preset"] = "lowpoly-ps1"
    prompt, _negative = build(game, sprite)
    assert prompt.count("side view") == 1
    assert "full body, centered" in prompt


def test_spec_fields_reach_the_prompt():
    cases = [
        (_asset("heroe", "character", spec={"role": "npc"}), "non-player character"),
        (_asset("salto", "sprite", spec={"pose": "mid-air jump"}), "pose: mid-air jump"),
        (_asset("barra", "ui", spec={"element": "bar"}), "horizontal bar"),
        (_asset("moneda", "icon", spec={"frame": "round"}), "inside a round frame"),
    ]
    for asset, phrase in cases:
        prompt, _negative = build(_game([asset], []), asset)
        assert phrase in prompt, asset["kind"]
    plain = _asset("moneda", "icon", spec={"frame": "none"})
    prompt, _negative = build(_game([plain], []), plain)
    assert "inside a" not in prompt


def test_screen_auto_follows_the_description():
    asset = _asset("heroe", "character", description="a green cape")
    game = _game([asset], [])
    game["style"]["screen"] = "auto"
    assert screen_for(game, asset) == "magenta"
    asset["description"] = "a red cape"
    assert screen_for(game, asset) == "green"
    game["style"]["screen"] = "magenta"
    assert screen_for(game, asset) == "magenta"


def test_refs_keep_order_cap_and_skip_rejected():
    assets = []
    references = []
    for index in range(9):
        path = f"style-{index}.png"
        assets.append(_asset(f"s{index}", approvedAttemptId="a1", attempts=[_attempt("a1", path)]))
        references.append({"assetId": f"s{index}", "attemptId": "a1"})
    assets.append(_asset("rejected", approvedAttemptId="bad", attempts=[_attempt("bad", "no.png", decision="rejected")]))
    references.append({"assetId": "rejected", "attemptId": "bad"})
    assets.append(_asset("hero", "character", approvedAttemptId="a1", attempts=[_attempt("a1", "hero.png")]))
    assets.append(_asset("other", "sprite", approvedAttemptId="a1", attempts=[_attempt("a1", "other.png")], tags=["red"]))
    pose = _asset("pose", "sprite", spec={"character": "hero"}, tags=["red"])
    assets.append(pose)
    found = refs_for(_game(assets, references), pose)
    assert found[:9] == [f"style-{index}.png" for index in range(9)]
    assert found[9] == "hero.png"
    assert len(found) == 10
    assert "no.png" not in found
    assert "other.png" not in found

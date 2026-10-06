"""Game library normalization, revisions, and atomic writes."""
import json
import re

import pytest

from services.game_inputs import asset_inputs
from services.game_library import (
    GameConflictError,
    GameValidationError,
    add_attempt,
    approve_attempt,
    create_game,
    lock_asset,
    normalize_game,
    preset_catalog,
    read_library,
    update_game,
    upsert_assets,
    write_library,
)

NOW = "2026-10-06T12:00:00Z"
BRANDS = (
    "nintendo", "sega", "sony", "playstation", "xbox", "gameboy", "game boy", "snes", "nes",
    "famicom", "genesis", "mega drive", "mario", "zelda", "pokemon", "pokémon", "sonic",
    "capcom", "konami", "square enix", "final fantasy", "ghibli", "disney", "pixar", "atari",
    "commodore", "amiga", "doom", "quake", "minecraft", "fortnite", "street fighter",
    "megaman", "mega man", "castlevania", "metroid", "kirby", "halo", "blizzard", "ubisoft",
    "namco", "bandai", "fromsoftware", "miyazaki", "kojima", "ps1", "psx", "n64",
)


def _library():
    library, _game = create_game({}, {"id": "bosque", "title": "Bosque encantado"}, now=NOW)
    return library


def test_kind_defaults_and_walk_action():
    raw = {
        "id": "bosque", "title": "Bosque",
        "assets": [
            {"id": "heroe", "kind": "character", "name": "Héroe"},
            {"id": "heroe-walk", "kind": "animation", "spec": {"character": "heroe", "action": "andar"}},
            {"id": "moneda", "kind": "item"},
            {"id": "icono", "kind": "icon"},
            {"id": "boton", "kind": "ui"},
            {"id": "hierba", "kind": "tile"},
            {"id": "suelo", "kind": "tileset"},
            {"id": "cielo", "kind": "background"},
            {"id": "boom", "kind": "vfx"},
            {"id": "salto", "kind": "sfx"},
            {"id": "tema", "kind": "music"},
            {"id": "fanfarria", "kind": "jingle"},
            {"id": "voz", "kind": "voice", "spec": {"character": "heroe", "lines": ["vamos"]}},
            {"id": "cofre", "kind": "model3d"},
            {"id": "heroe3d", "kind": "character3d", "spec": {"character": "heroe"}},
            {"id": "pose", "kind": "sprite", "spec": {"character": "heroe", "pose": "wave"}},
        ],
    }
    game = normalize_game(raw, now=NOW)
    by_id = {asset["id"]: asset for asset in game["assets"]}
    assert game["style"]["preset"] == "pixel-16"
    assert game["style"]["screen"] == "auto"
    assert game["style"]["pixel"]["spriteHeight"] == 48
    assert by_id["heroe"]["spec"] == {"role": "player", "heightPx": 48, "facing": "right"}
    assert by_id["heroe"]["candidates"] == 3
    assert by_id["heroe"]["status"] == "pending"
    walk = by_id["heroe-walk"]
    assert walk["spec"]["action"] == "walk"
    assert walk["spec"]["frames"] == 8
    assert walk["spec"]["fps"] == 12
    assert walk["spec"]["loop"] is True
    assert walk["spec"]["method"] == "h3"
    assert walk["spec"]["mirror"] is True
    assert walk["dependsOn"] == ["heroe"]
    assert by_id["moneda"]["spec"]["sizePx"] == 32
    assert by_id["boton"]["spec"]["nineSlice"] is True
    assert by_id["suelo"]["spec"]["layout"] == "platform-3x3"
    assert by_id["cielo"]["spec"]["method"] == "separate"
    assert by_id["voz"]["dependsOn"] == ["heroe"]
    assert by_id["heroe3d"]["spec"]["profile"] == "humanoid"


def test_dependency_cycle_is_rejected():
    raw = {"id": "bosque", "title": "Bosque", "assets": [
        {"id": "a", "kind": "sprite", "spec": {"character": "b"}},
        {"id": "b", "kind": "sprite", "spec": {"character": "a"}},
    ]}
    with pytest.raises(GameValidationError) as caught:
        normalize_game(raw, now=NOW)
    assert caught.value.code == "dependency_cycle"


def test_style_change_stales_unlocked_assets_only():
    library = _library()
    library, game = upsert_assets(library, "bosque", [
        {"id": "heroe", "kind": "character"},
        {"id": "slime", "kind": "character", "spec": {"role": "enemy"}},
    ], False, now=NOW)
    for asset_id in ("heroe", "slime"):
        digest = asset_inputs(game, next(item for item in game["assets"] if item["id"] == asset_id))
        library, _asset = add_attempt(library, "bosque", asset_id, {
            "id": "a1", "status": "ok", "inputs": digest, "createdAt": NOW,
        }, now=NOW)
        library, _asset = approve_attempt(library, "bosque", asset_id, "a1", now=NOW)
        game = next(item for item in library["games"] if item["id"] == "bosque")
    library, _asset = lock_asset(library, "bosque", "slime", True, now=NOW)
    game = next(item for item in library["games"] if item["id"] == "bosque")
    library, updated = update_game(
        library, "bosque", {"style": {"traits": "flat colors, thick outline"}}, game["revision"], now=NOW,
    )
    by_id = {asset["id"]: asset for asset in updated["assets"]}
    assert updated["style"]["approval"] == "draft"
    assert updated["style"]["revision"] == 2
    assert by_id["heroe"]["status"] == "stale"
    assert by_id["slime"]["status"] == "approved"
    assert by_id["slime"]["locked"] is True


def test_old_revision_conflicts():
    library = _library()
    with pytest.raises(GameConflictError):
        update_game(library, "bosque", {"title": "Otro"}, 0, now=NOW)


def test_prune_keeps_the_approved_attempt():
    library, game = upsert_assets(_library(), "bosque", [{"id": "heroe", "kind": "character"}], False, now=NOW)
    library, _asset = add_attempt(library, "bosque", "heroe", {"id": "keep", "status": "ok", "createdAt": NOW}, now=NOW)
    library, _asset = approve_attempt(library, "bosque", "heroe", "keep", now=NOW)
    for index in range(12):
        library, asset = add_attempt(library, "bosque", "heroe", {
            "id": f"r{index}", "status": "ok", "decision": "rejected", "createdAt": NOW,
        }, now=NOW)
    ids = [item["id"] for item in asset["attempts"]]
    assert "keep" in ids
    assert len(ids) == 12
    assert game["id"] == "bosque"


def test_failed_replace_leaves_the_library_intact(tmp_path, monkeypatch):
    write_library(tmp_path, {"games": []}, now=NOW)
    path = tmp_path / ".game-library-v1.json"
    original = path.read_text(encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("services.game_library.os.replace", boom)
    with pytest.raises(OSError):
        write_library(tmp_path, {"games": [{"id": "bosque", "title": "Bosque"}]}, now=NOW)
    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("*.tmp")) == []
    assert read_library(tmp_path)["games"] == []


def test_presets_do_not_name_brands():
    assert {preset["id"] for preset in preset_catalog()} == {
        "pixel-8", "pixel-16", "pixel-4tone", "cartoon-flat", "hand-painted", "anime-cel", "lowpoly-ps1", "toon-3d",
    }
    for preset in preset_catalog():
        if preset["pixel"]["enabled"]:
            assert len(preset["palette"]) == preset["pixel"]["colors"] or preset["id"] == "pixel-4tone"
        scanned = json.dumps({
            "label": preset["label"], "traits": preset["traits"], "negative": preset["negative"],
            "kindPrompts": preset["kindPrompts"], "audio": preset["audio"],
            "paletteSource": preset["paletteSource"],
        }, ensure_ascii=False).lower()
        for word in BRANDS:
            assert re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", scanned) is None, word
    four = next(preset for preset in preset_catalog() if preset["id"] == "pixel-4tone")
    assert four["palette"] == ["#0d1f12", "#1f4d32", "#5aaf62", "#d7f5c5"]

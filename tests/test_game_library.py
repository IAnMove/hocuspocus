"""Game library normalization, revisions, and atomic writes."""
import json
import re

import pytest

from services.game_inputs import asset_inputs
from services.game_library import (
    MAX_ID,
    GameConflictError,
    GameValidationError,
    add_attempt,
    approve_attempt,
    approve_style,
    create_game,
    lock_asset,
    normalize_game,
    preset_catalog,
    read_library,
    reject_attempt,
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


def _bosque(library):
    return next(item for item in library["games"] if item["id"] == "bosque")


def _by_id(game):
    return {asset["id"]: asset for asset in game["assets"]}


def _approve(library, asset_id, attempt_id):
    """Add an ok attempt with the current digest and approve it."""
    game = _bosque(library)
    digest = asset_inputs(game, _by_id(game)[asset_id])
    library, _asset = add_attempt(library, "bosque", asset_id, {"id": attempt_id, "status": "ok", "inputs": digest, "createdAt": NOW}, now=NOW)
    library, _asset = approve_attempt(library, "bosque", asset_id, attempt_id, now=NOW)
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


def test_reject_keeps_approved_status_while_another_attempt_is_approved():
    library, _game = upsert_assets(_library(), "bosque", [{"id": "heroe", "kind": "character"}], False, now=NOW)
    library = _approve(library, "heroe", "a1")
    library, _asset = add_attempt(library, "bosque", "heroe", {"id": "a2", "status": "ok"}, now=NOW)
    library, asset = reject_attempt(library, "bosque", "heroe", "a2", "too dark", now=NOW)
    assert (asset["status"], asset["approvedAttemptId"]) == ("approved", "a1")
    library, asset = reject_attempt(library, "bosque", "heroe", "a1", "off model", now=NOW)
    assert (asset["status"], asset["approvedAttemptId"]) == ("rejected", None)


def test_approve_moves_the_decision_and_stales_dependents_until_unlocked():
    library, _game = upsert_assets(_library(), "bosque", [
        {"id": "heroe", "kind": "character"},
        {"id": "heroe-walk", "kind": "animation", "spec": {"character": "heroe", "action": "walk"}},
        {"id": "voz", "kind": "voice", "spec": {"character": "heroe", "lines": ["vamos"]}},
    ], False, now=NOW)
    for asset_id, attempt_id in (("heroe", "a1"), ("heroe-walk", "w1"), ("voz", "v1")):
        library = _approve(library, asset_id, attempt_id)
    library, _asset = lock_asset(library, "bosque", "heroe-walk", True, now=NOW)
    library, _asset = add_attempt(library, "bosque", "heroe", {"id": "a2", "status": "ok", "inputs": "other"}, now=NOW)
    library, heroe = approve_attempt(library, "bosque", "heroe", "a2", now=NOW)
    by_id = _by_id(_bosque(library))
    assert heroe["status"] == "approved"
    assert [(item["id"], item["decision"]) for item in heroe["attempts"]] == [("a1", None), ("a2", "approved")]
    assert by_id["voz"]["status"] == "stale"
    assert by_id["heroe-walk"]["status"] == "approved"
    library, walk = lock_asset(library, "bosque", "heroe-walk", False, now=NOW)
    assert walk["status"] == "stale"


def test_reference_assets_do_not_stale_when_the_style_is_approved():
    library, _game = upsert_assets(_library(), "bosque", [{"id": "heroe", "kind": "character"}], False, now=NOW)
    library = _approve(library, "heroe", "a1")
    library, game = approve_style(library, "bosque", [{"assetId": "heroe", "attemptId": "a1"}], _bosque(library)["revision"], now=NOW)
    assert game["style"]["references"] == [{"assetId": "heroe", "attemptId": "a1"}]
    assert _by_id(game)["heroe"]["status"] == "approved"


def test_preset_change_applies_the_new_preset_defaults(monkeypatch):
    library, _game = create_game({}, {"id": "bosque", "title": "Bosque", "style": {
        "preset": "pixel-16", "traits": "custom", "paletteMode": "free", "light": "top", "screen": "green",
    }}, now=NOW)
    eight = next(preset for preset in preset_catalog() if preset["id"] == "pixel-8")
    library, game = update_game(library, "bosque", {"style": {"preset": "pixel-8"}}, 1, now=NOW)
    style = game["style"]
    assert (style["preset"], style["traits"], style["palette"]) == ("pixel-8", eight["traits"], eight["palette"])
    assert style["pixel"]["spriteHeight"] == eight["pixel"]["spriteHeight"]
    assert style["audio"]["genre"] == eight["audio"]["genre"]
    assert (style["paletteMode"], style["light"], style["screen"], style["revision"]) == ("free", "top", "green", 2)
    _library2, game = update_game(library, "bosque", {"style": {"preset": "pixel-16", "traits": "mine"}}, 2, now=NOW)
    assert game["style"]["traits"] == "mine"
    loud = [{**preset, "audio": {**preset["audio"], "musicLufs": -14}} for preset in preset_catalog()]
    monkeypatch.setattr("services.game_library.preset_catalog", lambda: loud)
    assert normalize_game({"id": "bosque"}, now=NOW)["style"]["audio"]["musicLufs"] == -14


def test_replace_keeps_relisted_assets_and_follows_the_new_order():
    library, _game = upsert_assets(_library(), "bosque", [
        {"id": "heroe", "kind": "character"}, {"id": "slime", "kind": "character"}, {"id": "moneda", "kind": "item"},
    ], False, now=NOW)
    library = _approve(library, "heroe", "a1")
    library, _asset = lock_asset(library, "bosque", "slime", True, now=NOW)
    library, game = upsert_assets(library, "bosque", [
        {"id": "slime", "kind": "character"}, {"id": "heroe", "kind": "character"}, {"id": "cofre", "kind": "item"},
    ], True, now=NOW)
    by_id = _by_id(game)
    assert [asset["id"] for asset in game["assets"]] == ["slime", "heroe", "cofre"]
    assert (by_id["heroe"]["status"], by_id["heroe"]["approvedAttemptId"]) == ("approved", "a1")
    assert [item["id"] for item in by_id["heroe"]["attempts"]] == ["a1"]
    assert by_id["slime"]["locked"] is True


def test_game_ids_reserve_routes_and_windows_names_and_stay_short():
    for wanted in ("presets", "produce", "con", "lpt9"):
        with pytest.raises(GameValidationError) as caught:
            create_game({}, {"id": wanted}, now=NOW)
        assert caught.value.code == "reserved_id"
    with pytest.raises(GameValidationError) as caught:
        create_game({}, {"id": "a" * (MAX_ID + 1)}, now=NOW)
    assert caught.value.code == "invalid_slug"
    with pytest.raises(GameValidationError) as caught:
        upsert_assets(_library(), "bosque", [{"id": "nul", "kind": "item"}], False, now=NOW)
    assert caught.value.code == "reserved_id"
    assert create_game({}, {"title": "Presets"}, now=NOW)[1]["id"] == "presets-2"
    assert create_game({}, {"title": "CON"}, now=NOW)[1]["id"] == "con-juego"
    title = "Un viaje muy largo por el bosque encantado de las mil y una noches sin fin"
    library, game = create_game({}, {"title": title}, now=NOW)
    assert len(game["id"]) <= MAX_ID and not game["id"].endswith("-")
    assert re.sub(r"[^a-z]+", "-", title.lower()).startswith(f"{game['id']}-")
    _library2, again = create_game(library, {"title": title}, now=NOW)
    assert again["id"].endswith("-2") and len(again["id"]) <= MAX_ID


def test_explicit_existing_id_conflicts_and_title_ids_get_a_suffix():
    library = _library()
    with pytest.raises(GameConflictError) as caught:
        create_game(library, {"id": "bosque", "title": "Otro"}, now=NOW)
    assert caught.value.code == "game_exists"
    library, game = create_game(library, {"title": "Bosque"}, now=NOW)
    assert game["id"] == "bosque-2"


def test_non_finite_numbers_and_non_dict_style_are_rejected():
    for value in (float("inf"), float("nan")):
        with pytest.raises(GameValidationError) as caught:
            normalize_game({"id": "bosque", "style": {"pixel": {"spriteHeight": value}}}, now=NOW)
        assert caught.value.code == "out_of_range"
        with pytest.raises(GameValidationError):
            normalize_game({"id": "bosque", "assets": [{"id": "salto", "kind": "sfx", "seconds": value}]}, now=NOW)
    with pytest.raises(GameValidationError) as caught:
        update_game(_library(), "bosque", {"style": "pixel-8"}, 1, now=NOW)
    assert caught.value.code == "invalid_style"


def test_failed_attempts_are_pruned_oldest_first():
    library, _game = upsert_assets(_library(), "bosque", [{"id": "heroe", "kind": "character"}], False, now=NOW)
    library = _approve(library, "heroe", "keep")
    for index in range(13):
        library, asset = add_attempt(library, "bosque", "heroe", {"id": f"f{index}", "status": "failed"}, now=NOW)
    ids = [item["id"] for item in asset["attempts"]]
    assert ids == ["keep", *(f"f{index}" for index in range(2, 13))]


def test_spec_keeps_an_optional_seed():
    library, game = upsert_assets(_library(), "bosque", [
        {"id": "heroe", "kind": "character", "spec": {"seed": 42}},
        {"id": "moneda", "kind": "item", "seed": 7},
        {"id": "cielo", "kind": "background"},
    ], False, now=NOW)
    by_id = _by_id(game)
    assert (by_id["heroe"]["spec"]["seed"], by_id["moneda"]["spec"]["seed"]) == (42, 7)
    assert "seed" not in by_id["cielo"]["spec"]
    assert _by_id(normalize_game(game, now=NOW))["heroe"]["spec"]["seed"] == 42
    for seed, code in ((-1, "out_of_range"), (float("inf"), "out_of_range"), (1.5, "invalid_seed"), ("7", "invalid_seed")):
        with pytest.raises(GameValidationError) as caught:
            upsert_assets(library, "bosque", [{"id": "cofre", "kind": "item", "seed": seed}], False, now=NOW)
        assert caught.value.code == code


def test_attempt_with_the_same_id_replaces_in_place():
    library, _game = upsert_assets(_library(), "bosque", [{"id": "heroe", "kind": "character"}], False, now=NOW)
    for attempt in ({"id": "aaa", "status": "ok"}, {"id": "bbb", "status": "failed"}, {"id": "ccc", "status": "ok"}, {"id": "bbb", "status": "ok"}):
        library, asset = add_attempt(library, "bosque", "heroe", attempt, now=NOW)
    assert [(item["id"], item["status"]) for item in asset["attempts"]] == [("aaa", "ok"), ("bbb", "ok"), ("ccc", "ok")]
    _library2, asset = approve_attempt(library, "bosque", "heroe", "bbb", now=NOW)
    assert asset["approvedAttemptId"] == "bbb"

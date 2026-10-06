"""Asset list grammar, checks, and library apply."""
from services.game_estimate import estimate
from services.game_library import create_game, normalize_game, read_library
from services.game_list import (
    EXAMPLE_LIST, apply, check, commit_list, parse_csv, parse_json, parse_json_report, parse_lines, parse_report,
)

NOW = "2026-10-06T12:00:00Z"


def _game(**raw):
    library, game = create_game({}, {"id": "bosque", "title": "Bosque encantado", **raw}, now=NOW)
    return library, game


def _core(items):
    return [(item["kind"], item["id"], item["description"], item["spec"]) for item in items]


def test_example_list_expands_to_eighteen_assets():
    items = parse_lines(EXAMPLE_LIST)
    kinds = [item["kind"] for item in items]
    assert len(items) == 18
    assert kinds.count("character") == 2
    assert kinds.count("animation") == 9
    assert {item["id"] for item in items if item["kind"] == "animation"} == {
        "heroe-idle", "heroe-walk", "heroe-jump", "heroe-attack", "heroe-hurt", "heroe-death",
        "slime-idle", "slime-jump", "slime-death",
    }
    by_id = {item["id"]: item for item in items}
    assert by_id["heroe"]["spec"]["role"] == "player"
    assert by_id["slime"]["spec"]["role"] == "enemy"
    assert by_id["moneda"]["spec"]["anim"] == {"action": "spin", "frames": 8}
    assert by_id["bosque"]["spec"]["layers"] == 3
    assert by_id["boton"]["spec"]["nineSlice"] is True
    assert by_id["explosion"]["spec"]["frames"] == 12
    assert by_id["salto"]["spec"]["variants"] == 3
    assert by_id["nivel1"]["spec"]["loopSeconds"] == 60
    library, game = _game()
    assert check(game, items) == []
    stored_library, stored = apply(game, items, False, now=NOW)
    assert len(stored["assets"]) == 18
    walk = next(asset for asset in stored["assets"] if asset["id"] == "heroe-walk")
    assert walk["spec"]["action"] == "walk"
    assert walk["dependsOn"] == ["heroe"]
    assert walk["status"] == "pending"
    assert estimate(None, game, items)["source"] == "trial"
    assert stored_library["games"][0]["id"] == "bosque"
    assert library["games"][0]["assets"] == []


def test_spanish_aliases_and_item_motion():
    text = "\n".join([
        "personaje guardian: grande | jefe",
        "animación caballero: reposo, caminar | método tira",
        "objeto llave: dorada | anim flotar | 6 frames",
        "icono corazon: rojo",
        "fondo cielo: amplio | capas 2",
        "efecto chispa: breve | 4 frames",
        "sonido golpe: seco | variantes 2 | retro",
        "música tema: calma | bucle 30 s | bpm 90",
        "voz narrador: hola",
        "modelo3d cofre: caja",
        "personaje3d estatua: piedra",
        "ui marco: borde | 9-slice",
        "tileset suelo: tierra",
        "# comentario",
        "",
    ])
    by_id = {item["id"]: item for item in parse_lines(text)}
    assert by_id["guardian"]["spec"]["role"] == "boss"
    assert by_id["caballero-idle"]["kind"] == "animation"
    assert by_id["caballero-walk"]["spec"]["method"] == "strip"
    assert by_id["llave"]["spec"]["anim"] == {"action": "bob", "frames": 6}
    assert by_id["corazon"]["kind"] == "icon"
    assert by_id["cielo"]["spec"]["layers"] == 2
    assert by_id["chispa"]["spec"]["frames"] == 4
    assert by_id["golpe"]["spec"]["variants"] == 2
    assert by_id["golpe"]["spec"]["engine"] == "retro"
    assert by_id["tema"]["kind"] == "music"
    assert by_id["tema"]["spec"] == {"loopSeconds": 30, "bpm": 90}
    assert by_id["narrador"]["kind"] == "voice"
    assert by_id["cofre"]["kind"] == "model3d"
    assert by_id["estatua"]["kind"] == "character3d"
    assert by_id["marco"]["spec"]["nineSlice"] is True
    assert by_id["suelo"]["kind"] == "tileset"


def test_line_errors_come_back_together():
    text = "\n".join([
        "nope cosa: nada",
        "anim heroe: volar, idle",
        "anim fantasma: idle",
        "personaje heroe: uno",
        "personaje heroe: dos",
    ])
    _library, game = _game()
    items, found = parse_report(text)
    problems = [*found, *check(game, items)]
    assert [(item["line"], item["code"]) for item in problems] == [
        (1, "unknown_kind"),
        (2, "unknown_action"),
        (3, "missing_character"),
        (5, "duplicate_id"),
    ]
    assert {item["id"] for item in items} == {"heroe-idle", "fantasma-idle", "heroe"}


def test_csv_and_json_match():
    lines = "personaje heroe: caballero bajito | jugador\nobjeto moneda: moneda de oro | anim girar | 8 frames\n"
    csv_text = "\n".join([
        "kind,id,name,description,options",
        "character,heroe,Heroe,caballero bajito,jugador",
        "item,moneda,Moneda,moneda de oro,anim girar | 8 frames",
    ])
    payload = [
        {"kind": "character", "id": "heroe", "name": "Heroe", "description": "caballero bajito", "options": "jugador"},
        {"kind": "item", "id": "moneda", "name": "Moneda", "description": "moneda de oro", "options": "anim girar | 8 frames"},
    ]
    assert _core(parse_lines(lines)) == _core(parse_csv(csv_text)) == _core(parse_json(payload))


def test_size_grid_count_character_and_layered_model():
    _library, game = _game()
    off_grid = parse_lines("tile hierba: cesped | tamaño 15")
    assert check(game, off_grid)[0]["code"] == "size_not_on_grid"
    painted = normalize_game({"id": "bosque", "title": "Bosque", "style": {"preset": "cartoon-flat"}}, now=NOW)
    assert check(painted, off_grid) == []
    too_many = [{"id": f"item-{index}", "kind": "item", "spec": {}, "line": index} for index in range(MAX_PLUS)]
    assert check(game, too_many)[-1]["code"] == "too_many_assets"
    present = normalize_game({"id": "bosque", "title": "Bosque", "assets": [{"id": "heroe", "kind": "character"}]}, now=NOW)
    animation = parse_lines("anim heroe: idle")
    assert check(present, animation) == []
    assert any(item["code"] == "missing_character" for item in check(game, animation))
    layered = [{"id": "cielo", "kind": "background", "spec": {"method": "layered"}, "line": 4}]
    assert check(game, layered, models=["qwen_image_21"])[0]["code"] == "model_not_installed"
    assert check(game, layered, models=["qwen_image_layered_20B"]) == []
    assert check(game, layered) == []


def test_commit_writes_the_game_and_leaves_other_games(tmp_path):
    library, _stored = _game()
    _library, other = create_game(library, {"id": "otro", "title": "Otro"}, now=NOW)
    from services.game_library import write_library
    write_library(tmp_path, _library, now=NOW)
    stored = commit_list(str(tmp_path), "bosque", parse_lines("objeto moneda: oro"), False, now=NOW)
    assert [asset["id"] for asset in stored["assets"]] == ["moneda"]
    written = read_library(str(tmp_path))
    assert {game["id"] for game in written["games"]} == {"bosque", "otro"}
    assert other["id"] == "otro"



def test_mistyped_options_are_reported_not_dropped():
    items, problems = parse_report("objeto moneda: oro | 8 frame\nsfx salto: corto | variants 3 | retro\nanim heroe: idle | 6 frame")
    assert [(item["line"], item["code"]) for item in problems] == [
        (1, "unknown_option"), (2, "unknown_option"), (3, "unknown_option"),
    ]
    assert "'8 frame'" in problems[0]["message"]
    by_id = {item["id"]: item for item in items}
    assert by_id["salto"]["spec"] == {"engine": "retro"}
    assert set(by_id) == {"moneda", "salto", "heroe-idle"}


def test_bad_json_specs_become_problems():
    items, problems = parse_json_report([
        {"kind": "item", "id": "a", "spec": "x"},
        {"kind": "item", "id": "b", "spec": [1]},
        {"kind": "item", "id": "c", "spec": {}, "candidates": "many"},
        {"kind": "item", "id": "d", "spec": {}, "candidates": True},
        {"kind": "item", "id": "e", "spec": None, "candidates": 2},
    ])
    assert [(item["line"], item["code"]) for item in problems] == [
        (1, "invalid_spec"), (2, "invalid_spec"), (3, "invalid_spec"), (4, "invalid_spec"),
    ]
    assert [(item["id"], item["spec"], item["candidates"]) for item in items] == [("e", {}, 2)]
    _library, game = _game()
    odd = [{"id": "heroe-idle", "kind": "animation", "spec": {"character": [1], "action": "idle"}, "line": 1}]
    assert [item["code"] for item in check(game, odd)] == ["invalid_spec"]


MAX_PLUS = 501

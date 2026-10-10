"""Parse a game asset list and check it before anything is generated.

Lines, CSV and JSON become the same asset dicts. ``check`` reports every
problem together. Nothing here approves an asset or calls the GPU.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from typing import Any

from services.game_library import (
    SCHEMA,
    MAX_ASSETS,
    KINDS,
    GameNotFoundError,
    read_library,
    resolve_action,
    upsert_assets,
    write_library,
)

EXAMPLE_LIST = """\
personaje heroe: caballero bajito con armadura de bronce y capa roja | jugador
anim heroe: idle, andar, saltar, atacar, herido, morir
personaje slime: babosa verde gelatinosa | enemigo
anim slime: idle, saltar, morir
objeto moneda: moneda de oro | anim girar | 8 frames
tileset hierba: suelo de hierba sobre tierra
fondo bosque: bosque al atardecer | capas 3
ui boton: botón de madera | 9-slice
efecto explosion: explosión pequeña con chispas | 12 frames
sfx salto: salto corto y ligero | variantes 3
musica nivel1: tema alegre de bosque | bucle 60 s
"""

STYLE_SAMPLES = (
    {"id": "style-sample-character", "kind": "character", "name": "Style sample", "description": "Style sample character"},
    {"id": "style-sample-item", "kind": "item", "name": "Style sample", "description": "Style sample item"},
    {"id": "style-sample-tile", "kind": "tile", "name": "Style sample", "description": "Style sample tile"},
    {"id": "style-sample-background", "kind": "background", "name": "Style sample", "description": "Style sample background"},
)

_LAYERED_MODEL = "qwen_image_layered_20B"
_MAX_CANDIDATES = 8  # the produce endpoint accepts 1..8
_LINE = re.compile(r"^(?P<kind>\S+)\s+(?P<id>\S+)\s*:\s*(?P<body>.*)$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_KINDS = {
    "personaje": "character", "character": "character",
    "sprite": "sprite",
    "anim": "animation", "animacion": "animation", "animation": "animation",
    "objeto": "item", "item": "item",
    "icono": "icon", "icon": "icon",
    "ui": "ui",
    "tile": "tile",
    "tileset": "tileset",
    "fondo": "background", "background": "background",
    "efecto": "vfx", "vfx": "vfx",
    "sfx": "sfx", "sonido": "sfx",
    "musica": "music", "music": "music",
    "jingle": "jingle",
    "voz": "voice", "voice": "voice",
    "modelo3d": "model3d", "model3d": "model3d",
    "personaje3d": "character3d", "character3d": "character3d",
}
_ROLES = {"jugador": "player", "enemigo": "enemy", "npc": "npc", "jefe": "boss"}
_ITEM_ANIM = {"girar": "spin", "flotar": "bob", "glow": "glow"}
_NEEDS_CHARACTER = {"animation", "voice"}
_NUMBERED = (
    (re.compile(r"variantes (\d+)$"), "variants"),
    (re.compile(r"capas (\d+)$"), "layers"),
    (re.compile(r"(\d+) frames$"), "frames"),
    (re.compile(r"tamano (\d+)$"), "size"),
    (re.compile(r"bucle (\d+)\s*s$"), "loop"),
    (re.compile(r"bpm (\d+)$"), "bpm"),
    (re.compile(r"metodo (tira|h3)$"), "method"),
    (re.compile(r"anim (girar|flotar|glow)$"), "anim"),
)


def parse_lines(text: str) -> list[dict[str, Any]]:
    items, _problems = parse_report(text)
    return items


def parse_report(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Valid assets, plus every line problem. Line numbers are 1-based."""
    items: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    for line_no, raw in enumerate(str(text or "").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        found, failed = _parse_line(stripped, line_no)
        items.extend(found)
        problems.extend(failed)
    return items, problems


def parse_csv(text: str) -> list[dict[str, Any]]:
    items, _problems = parse_csv_report(text)
    return items


def parse_csv_report(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reader = csv.DictReader(io.StringIO(text or ""))
    fields = reader.fieldnames or []
    if "kind" not in fields or "id" not in fields:
        return [], [_problem(1, "invalid_line", "CSV needs kind and id columns")]
    items: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    for line_no, row in enumerate(reader, start=2):
        found, failed = _row(row.get("kind"), row.get("id"), row.get("description") or "", _option_list(row.get("options")), line_no, name=row.get("name") or None)
        items.extend(found)
        problems.extend(failed)
    return items, problems


def parse_json(items: Any) -> list[dict[str, Any]]:
    found, _problems = parse_json_report(items)
    return found


def parse_json_report(items: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = items if isinstance(items, list) else []
    if not isinstance(items, list):
        return [], [_problem(1, "invalid_line", "JSON items must be a list")]
    found: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    for line_no, raw in enumerate(rows, start=1):
        parsed, failed = _from_mapping(raw, line_no)
        found.extend(parsed)
        problems.extend(failed)
    return found, problems


def check(game: dict[str, Any], items: list[dict[str, Any]], models: Any = None, *, replace: bool = False) -> list[dict[str, Any]]:
    """Every problem in the list. ``models`` is omitted to skip the install check."""
    known = _characters(game, items)
    problems: list[dict[str, Any]] = []
    for item in items:
        problems.extend(_item_problems(game, item, known, models))
    problems.extend(_duplicates(items))
    count = _count_problem(game, items, replace)
    if count:
        problems.append(count)
    return problems


def apply(game: dict[str, Any], items: list[dict[str, Any]], replace: bool, *, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Insert the items with J1 ``upsert_assets``. The caller writes the library."""
    library = {"schema": SCHEMA, "version": 1, "games": [game]}
    cleaned = [{key: value for key, value in item.items() if key != "line"} for item in items]
    return upsert_assets(library, game["id"], cleaned, bool(replace), now=now)


def commit_list(workspace_dir: str, game_id: str, items: list[dict[str, Any]], replace: bool, *, now: str) -> dict[str, Any]:
    """Apply ``items`` and write the workspace library. Other games stay put."""
    library = read_library(workspace_dir)
    game = next((item for item in library.get("games") or [] if item.get("id") == game_id), None)
    if game is None:
        raise GameNotFoundError("game_not_found")
    _updated, stored = apply(game, items, replace, now=now)
    games = [stored if item.get("id") == game_id else item for item in library.get("games") or []]
    written = write_library(workspace_dir, {"schema": SCHEMA, "version": 1, "games": games}, now=now)
    return next(item for item in written["games"] if item["id"] == game_id)


def _parse_line(stripped: str, line_no: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    match = _LINE.match(stripped)
    if match is None:
        return _bad_shape(stripped, line_no)
    body, options = _split_body(match.group("body"))
    return _row(match.group("kind"), match.group("id"), body, options, line_no)


def _bad_shape(stripped: str, line_no: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    token = stripped.split()[0]
    if _kind(token) is None:
        return [], [_problem(line_no, "unknown_kind", f"Unknown asset kind '{token}'")]
    return [], [_problem(line_no, "invalid_line", "Expected '<kind> <id>: <description>'")]


def _row(kind_token: Any, asset_id: Any, description: str, options: list[str], line_no: int, name: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if _kind(kind_token) == "animation" and _is_action_list(description):
        return _actions(str(asset_id or ""), description, options, line_no)
    return _one(kind_token, asset_id, description, options, line_no, name=name)


def _from_mapping(raw: Any, line_no: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        return [], [_problem(line_no, "invalid_line", "Each item must be an object")]
    if "spec" in raw and "options" not in raw:
        return _specified(raw, line_no)
    return _row(raw.get("kind"), raw.get("id"), str(raw.get("description") or ""), _option_list(raw.get("options")), line_no, name=raw.get("name"))


def _specified(raw: dict[str, Any], line_no: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kind = _kind(raw.get("kind"))
    if kind is None:
        return [], [_problem(line_no, "unknown_kind", f"Unknown asset kind '{raw.get('kind')}'")]
    slug = _slug_id(str(raw.get("id") or ""))
    if not slug:
        return [], [_problem(line_no, "invalid_line", "The asset id is empty")]
    problem = _spec_problem(raw, line_no)
    if problem:
        return [], [problem]
    item: dict[str, Any] = {
        "id": slug, "kind": kind, "name": raw.get("name") or slug,
        "description": str(raw.get("description") or ""), "spec": dict(raw.get("spec") or {}), "line": line_no,
    }
    if raw.get("candidates") is not None:
        item["candidates"] = raw["candidates"]
    return [item], []


def _spec_problem(raw: dict[str, Any], line_no: int) -> dict[str, Any] | None:
    spec = raw.get("spec")
    if spec is not None and not isinstance(spec, dict):
        return _problem(line_no, "invalid_spec", "spec must be an object")
    count = raw.get("candidates")
    if count is None:
        return None
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= _MAX_CANDIDATES:
        return _problem(line_no, "invalid_spec", f"candidates must be a whole number from 1 to {_MAX_CANDIDATES}")
    return None


def _one(kind_token: Any, asset_id: Any, description: str, options: list[str], line_no: int, name: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kind = _kind(kind_token)
    if kind is None:
        return [], [_problem(line_no, "unknown_kind", f"Unknown asset kind '{kind_token}'")]
    slug = _slug_id(str(asset_id or ""))
    if not slug:
        return [], [_problem(line_no, "invalid_line", "The asset id is empty")]
    spec: dict[str, Any] = {}
    problems = _apply_options(spec, kind, options, line_no)
    label = name.strip() if isinstance(name, str) and name.strip() else slug
    return [{"id": slug, "kind": kind, "name": label, "description": description.strip(), "spec": spec, "line": line_no}], problems


def _actions(character: str, body: str, options: list[str], line_no: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    slug = _slug_id(character)
    if not slug:
        return [], [_problem(line_no, "invalid_line", "The character id is empty")]
    shared: dict[str, Any] = {}
    problems = _apply_options(shared, "animation", options, line_no)
    items: list[dict[str, Any]] = []
    for token in [part.strip() for part in body.split(",") if part.strip()]:
        action = resolve_action(token)
        if action is None:
            problems.append(_problem(line_no, "unknown_action", f"Unknown action '{token}'"))
            continue
        spec = {**shared, "character": slug, "action": action["id"]}
        items.append({
            "id": f"{slug}-{action['id']}", "kind": "animation", "name": action["id"],
            "description": token, "spec": spec, "line": line_no,
        })
    return items, problems


def _is_action_list(body: str) -> bool:
    parts = [part.strip() for part in body.split(",")]
    return bool(parts) and all(part and " " not in part for part in parts)


def _split_body(raw: str) -> tuple[str, list[str]]:
    parts = [part.strip() for part in raw.split("|")]
    return parts[0], [part for part in parts[1:] if part]


def _option_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _apply_options(spec: dict[str, Any], kind: str, options: list[str], line_no: int) -> list[dict[str, Any]]:
    """Apply every option. A typo such as ``8 frame`` is reported, not dropped."""
    problems = []
    for option in options:
        if not _apply_option(spec, kind, option):
            problems.append(_problem(line_no, "unknown_option", f"Unknown option '{option}'"))
    return problems


def _apply_option(spec: dict[str, Any], kind: str, text: str) -> bool:
    folded = _fold(text)
    if folded in _ROLES:
        spec["role"] = _ROLES[folded]
        return True
    if folded in {"9-slice", "9slice"}:
        spec["nineSlice"] = True
        return True
    if folded == "retro":
        spec["engine"] = "retro"
        return True
    if folded == "multivista":
        spec["multiview"] = True
        return True
    return _apply_numbered(spec, kind, folded)


def _apply_numbered(spec: dict[str, Any], kind: str, folded: str) -> bool:
    for pattern, key in _NUMBERED:
        match = pattern.fullmatch(folded)
        if match:
            _store_option(spec, kind, key, match.group(1))
            return True
    return False


def _store_option(spec: dict[str, Any], kind: str, key: str, raw: str) -> None:
    if key == "size":
        _store_size(spec, kind, int(raw))
        return
    if key == "loop":
        spec["loopSeconds"] = int(raw)
        return
    if key == "method":
        spec["method"] = "strip" if raw == "tira" else "h3"
        return
    if key == "anim":
        spec["anim"] = {"action": _ITEM_ANIM[raw], "frames": int(spec.get("frames") or 8)}
        return
    if key == "frames" and isinstance(spec.get("anim"), dict):
        spec["anim"]["frames"] = int(raw)
    spec[key] = int(raw) if key in {"variants", "layers", "frames", "bpm"} else raw


def _store_size(spec: dict[str, Any], kind: str, value: int) -> None:
    if kind in {"character", "sprite", "background", "ui"}:
        spec["heightPx"] = value
        return
    spec["sizePx"] = value


def _item_problems(game: dict[str, Any], item: dict[str, Any], known: set[str], models: Any) -> list[dict[str, Any]]:
    if item.get("kind") not in KINDS:
        return [_problem(item.get("line") or 0, "unknown_kind", f"Unknown asset kind '{item.get('kind')}'")]
    found = [problem for problem in (
        _action_problem(item), _character_problem(item, known), _size_problem(game, item), _model_problem(item, models),
    ) if problem]
    return found


def _action_problem(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("kind") != "animation":
        return None
    action = (item.get("spec") or {}).get("action")
    if resolve_action(str(action or "")) is None:
        return _problem(item.get("line") or 0, "unknown_action", f"Unknown action '{action}'")
    return None


def _character_problem(item: dict[str, Any], known: set[str]) -> dict[str, Any] | None:
    spec = item.get("spec") or {}
    character = spec.get("character")
    if item.get("kind") in _NEEDS_CHARACTER and not character:
        return _problem(item.get("line") or 0, "missing_character", "This asset needs a character")
    if character and not isinstance(character, str):
        return _problem(item.get("line") or 0, "invalid_spec", "character must be an asset id")
    if character and character not in known:
        return _problem(item.get("line") or 0, "missing_character", f"Character '{character}' is not in the game or the list")
    return None


def _size_problem(game: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    pixel = ((game.get("style") or {}).get("pixel") or {})
    if not pixel.get("enabled") or item.get("kind") == "background":
        return None
    tile = int(pixel.get("tile") or 0)
    if tile <= 1:
        return None
    spec = item.get("spec") or {}
    for key in ("sizePx", "heightPx", "widthPx"):
        value = spec.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value % tile != 0:
            return _problem(item.get("line") or 0, "size_not_on_grid", f"{key} {value} is not a multiple of the {tile}px grid")
    return None


def _model_problem(item: dict[str, Any], models: Any) -> dict[str, Any] | None:
    installed = _model_ids(models)
    if installed is None:
        return None
    spec = item.get("spec") or {}
    if item.get("kind") == "background" and spec.get("method") == "layered" and _LAYERED_MODEL not in installed:
        return _problem(item.get("line") or 0, "model_not_installed", f"{_LAYERED_MODEL} is not installed")
    return None


def _duplicates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    problems = []
    for item in items:
        asset_id = item.get("id")
        if not asset_id or item.get("kind") not in KINDS:
            continue
        if asset_id in seen:
            problems.append(_problem(item.get("line") or 0, "duplicate_id", f"Duplicate asset id '{asset_id}'"))
        else:
            seen.add(str(asset_id))
    return problems


def _count_problem(game: dict[str, Any], items: list[dict[str, Any]], replace: bool) -> dict[str, Any] | None:
    existing = [] if replace else [asset.get("id") for asset in game.get("assets") or [] if asset.get("id")]
    incoming = [item.get("id") for item in items if item.get("id") and item.get("kind") in KINDS]
    if len(set([*existing, *incoming])) > MAX_ASSETS:
        return _problem(0, "too_many_assets", f"A game holds at most {MAX_ASSETS} assets")
    return None


def _characters(game: dict[str, Any], items: list[dict[str, Any]]) -> set[str]:
    found = set()
    for asset in [*(game.get("assets") or []), *items]:
        if isinstance(asset, dict) and asset.get("kind") == "character" and asset.get("id"):
            found.add(asset["id"])
    return found


def _model_ids(models: Any) -> set[str] | None:
    if models is None:
        return None
    if isinstance(models, str):
        return {models}
    if isinstance(models, (list, tuple, set)):
        return {str(item) for item in models}
    if not isinstance(models, dict):
        return set()
    found: set[str] = set()
    local = models.get("local") if isinstance(models.get("local"), dict) else {}
    for item in local.get("image") or []:
        _add_model(found, item)
    for key in ("models", "installed"):
        for item in models.get(key) or []:
            _add_model(found, item)
    return found


def _add_model(found: set[str], item: Any) -> None:
    if isinstance(item, str):
        found.add(item)
    elif isinstance(item, dict) and item.get("id"):
        found.add(str(item["id"]))


def _kind(token: Any) -> str | None:
    return _KINDS.get(_fold(str(token or "")))


def _fold(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return ascii_text.strip().lower()


def _slug_id(value: str) -> str:
    text = _fold(value)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text if _SLUG.match(text) else ""


def _problem(line: int, code: str, message: str) -> dict[str, Any]:
    return {"line": line, "code": code, "message": message}

"""Workspace game library for Recursos para videojuegos.

The on-disk file is ``<workspace>/.game-library-v1.json``. Writes follow
``series_library.write_series_library``: a temp file, fsync, then ``os.replace``.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import unicodedata
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.game_inputs import stale_assets

GAME_LIBRARY_FILENAME = ".game-library-v1.json"
SCHEMA = "hocuspocus.game-library"
MAX_BYTES = 50 * 1024 * 1024
MAX_ASSETS = 500
MAX_ATTEMPTS = 12
MAX_ID = 64
KINDS = (
    "character", "sprite", "animation", "item", "icon", "ui", "tile", "tileset",
    "background", "vfx", "sfx", "music", "jingle", "voice", "model3d", "character3d",
)
STATUSES = ("pending", "generating", "review", "approved", "rejected", "failed", "stale")
GENRES = ("platformer", "topdown", "other")
VIEWS = ("side", "topdown")
ROLES = ("player", "enemy", "npc", "boss")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_SHARED = Path(__file__).resolve().parents[1] / "shared"
_CANDIDATES = {
    "character": 3, "sprite": 2, "animation": 1, "item": 3, "icon": 3, "ui": 2,
    "tile": 2, "tileset": 2, "background": 2, "vfx": 1, "sfx": 1, "music": 2,
    "jingle": 2, "voice": 1, "model3d": 2, "character3d": 1,
}
_EDITORIAL = ("name", "description", "tags", "spec", "notes", "candidates")
# Folder names that Windows refuses, and game ids that collide with static routes.
_RESERVED_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"{port}{n}" for port in ("com", "lpt") for n in range(1, 10))})
_RESERVED_GAME_IDS = frozenset({"presets", "produce"})
# Style keys a preset fills in; a new preset drops them so its own defaults apply.
_PRESET_KEYS = ("traits", "negative", "palette", "pixel", "model3d", "audio")


class GameConflictError(ValueError):
    """Optimistic revision does not match the stored game, or the game id is taken."""

    def __init__(self, message: str = "revision conflict", code: str = "revision_conflict") -> None:
        self.code = code
        super().__init__(message)


class GameValidationError(ValueError):
    """The game document is not valid. ``problems`` is a list of ``{code, ...}``."""

    def __init__(self, code: str, problems: list[dict[str, Any]] | None = None, message: str | None = None) -> None:
        self.code = code
        self.problems = problems or [{"code": code, "message": message or code}]
        super().__init__(message or code)


class GameNotFoundError(Exception):
    """A game or an asset is not in the library."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def empty_library() -> dict[str, Any]:
    return {"schema": SCHEMA, "version": 1, "games": []}


@lru_cache(maxsize=1)
def action_catalog() -> list[dict[str, Any]]:
    payload = json.loads((_SHARED / "game_actions.json").read_text(encoding="utf-8"))
    return list(payload["actions"])


@lru_cache(maxsize=1)
def preset_catalog() -> list[dict[str, Any]]:
    payload = json.loads((_SHARED / "game_style_presets.json").read_text(encoding="utf-8"))
    return list(payload["presets"])


def resolve_action(name: str) -> dict[str, Any] | None:
    key = str(name or "").strip().lower()
    if not key:
        return None
    for action in action_catalog():
        names = {action["id"], *(str(alias).lower() for alias in action.get("aliases") or [])}
        if key in names:
            return action
    return None


def _preset(preset_id: str) -> dict[str, Any]:
    for preset in preset_catalog():
        if preset["id"] == preset_id:
            return preset
    raise GameValidationError("unknown_preset", [{"code": "unknown_preset", "preset": preset_id}])


def _problem(code: str, **detail: Any) -> GameValidationError:
    return GameValidationError(code, [{"code": code, **detail}])


def _slug(value: Any, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) > MAX_ID or not _SLUG.match(text):
        raise _problem("invalid_slug", field=field, value=value)
    if text in _RESERVED_NAMES:
        raise _problem("reserved_id", field=field, value=text)
    return text


def _truncate(text: str) -> str:
    if len(text) <= MAX_ID:
        return text
    head = text[: MAX_ID + 1]
    return head.rsplit("-", 1)[0] if "-" in head else text[:MAX_ID]


def _slugify(title: str) -> str:
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    text = _truncate(re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")) or "juego"
    return f"{text}-juego" if text in _RESERVED_NAMES else text


def _text(value: Any, fallback: str = "") -> str:
    return value.strip() if isinstance(value, str) else fallback


def _int(value: Any, fallback: int, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    if isinstance(value, float) and not math.isfinite(value):
        raise _problem("out_of_range", value=str(value), minimum=minimum)
    number = int(value)
    if number < minimum:
        raise _problem("out_of_range", value=number, minimum=minimum)
    return number


def _bool(value: Any, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _problem("invalid_list")
    return [item.strip() for item in value if item.strip()]


def _palette(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _problem("invalid_palette", value=value)
    colors: list[str] = []
    problems: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str) and _HEX.match(item):
            colors.append(item.lower())
        else:
            problems.append({"code": "invalid_palette", "value": item})
    if problems:
        raise GameValidationError("invalid_palette", problems)
    return colors


def _choice(value: Any, allowed: tuple[str, ...], fallback: str, code: str) -> str:
    if value is None:
        return fallback
    if value not in allowed:
        raise _problem(code, value=value)
    return str(value)


def _pixel(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": _bool(raw.get("enabled"), bool(fallback.get("enabled", True))),
        "spriteHeight": _int(raw.get("spriteHeight"), int(fallback.get("spriteHeight", 48)), 1),
        "tile": _int(raw.get("tile"), int(fallback.get("tile", 16)), 1),
        "colors": _int(raw.get("colors"), int(fallback.get("colors", 16)), 1),
        "outline": _choice(raw.get("outline", fallback.get("outline")), ("dark-1px", "black-1px", "none"), "dark-1px", "invalid_outline"),
        "dither": _choice(raw.get("dither", fallback.get("dither")), ("none", "ordered"), "none", "invalid_dither"),
    }


def _model3d(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        "maxTriangles": _int(raw.get("maxTriangles"), int(fallback.get("maxTriangles", 3000)), 1),
        "texture": _int(raw.get("texture"), int(fallback.get("texture", 512)), 1),
        "look": _text(raw.get("look"), str(fallback.get("look") or "toon")) or "toon",
    }


def _audio(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    bpm = raw.get("bpm", fallback.get("bpm") or [90, 140])
    if not isinstance(bpm, list) or len(bpm) != 2:
        raise _problem("invalid_bpm", value=bpm)
    return {
        "genre": _text(raw.get("genre"), str(fallback.get("genre") or "")),
        "instruments": _text(raw.get("instruments"), str(fallback.get("instruments") or "")),
        "bpm": [_int(bpm[0], 90, 1), _int(bpm[1], 140, 1)],
        "musicLufs": _int(raw.get("musicLufs"), int(fallback.get("musicLufs", -16)), -70),
        "sfxPeakDb": _int(raw.get("sfxPeakDb"), int(fallback.get("sfxPeakDb", -1)), -60),
        "sampleRate": _int(raw.get("sampleRate"), int(fallback.get("sampleRate", 48000)), 1),
    }


def normalize_style(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    preset = _preset(str(source.get("preset") or "pixel-16"))
    pixel_raw = source.get("pixel") if isinstance(source.get("pixel"), dict) else {}
    model_raw = source.get("model3d") if isinstance(source.get("model3d"), dict) else {}
    audio_raw = source.get("audio") if isinstance(source.get("audio"), dict) else {}
    palette = _palette(source["palette"]) if "palette" in source else _palette(preset.get("palette") or [])
    return {
        "revision": _int(source.get("revision"), 1, 1),
        "approval": _choice(source.get("approval"), ("draft", "approved"), "draft", "invalid_approval"),
        "approvedAt": source.get("approvedAt") if isinstance(source.get("approvedAt"), str) else None,
        "preset": preset["id"],
        "traits": _text(source.get("traits"), preset.get("traits") or ""),
        "negative": _text(source.get("negative"), preset.get("negative") or ""),
        "palette": palette,
        "paletteMode": _choice(source.get("paletteMode"), ("locked", "free"), "locked", "invalid_palette_mode"),
        "pixel": _pixel(pixel_raw, preset.get("pixel") or {}),
        "light": _choice(source.get("light"), ("top-left", "top", "front"), "top-left", "invalid_light"),
        "screen": _choice(source.get("screen"), ("auto", "green", "magenta"), "auto", "invalid_screen"),
        "references": _references(source.get("references")),
        "model3d": _model3d(model_raw, preset.get("model3d") or {}),
        "audio": _audio(audio_raw, {"musicLufs": -16, "sfxPeakDb": -1, "sampleRate": 48000, **(preset.get("audio") or {})}),
        "qa": _qa(source.get("qa")),
    }


def _qa(raw: Any) -> dict[str, bool]:
    """Vision stays on unless the style sets ``qa.vision`` to false."""
    source = raw if isinstance(raw, dict) else {}
    vision = source.get("vision")
    return {"vision": vision if isinstance(vision, bool) else True}


def _references(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _problem("invalid_references")
    found: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise _problem("invalid_references")
        asset_id = item.get("assetId", item.get("asset_id"))
        attempt_id = item.get("attemptId", item.get("attempt_id"))
        found.append({"assetId": _slug(asset_id, field="assetId"), "attemptId": _text(attempt_id)})
        if not found[-1]["attemptId"]:
            raise _problem("invalid_references", assetId=found[-1]["assetId"])
    return found


def _spec_character(raw: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    height = int(game["style"]["pixel"]["spriteHeight"])
    return {
        "role": _choice(raw.get("role"), ROLES, "player", "invalid_role"),
        "heightPx": _int(raw.get("heightPx"), height, 1),
        "facing": _choice(raw.get("facing"), ("right",), "right", "invalid_facing"),
        **({"kitId": _text(raw.get("kitId"))} if _text(raw.get("kitId")) else {}),
    }


def _spec_sprite(raw: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    height = int(game["style"]["pixel"]["spriteHeight"])
    spec: dict[str, Any] = {"pose": _text(raw.get("pose")), "heightPx": _int(raw.get("heightPx"), height, 1)}
    character = _optional_slug(raw.get("character"))
    if character:
        spec["character"] = character
    return spec


def _spec_animation(raw: dict[str, Any], _game: dict[str, Any]) -> dict[str, Any]:
    action = resolve_action(str(raw.get("action") or "idle"))
    if action is None:
        raise _problem("unknown_action", action=raw.get("action"))
    character = _optional_slug(raw.get("character"))
    if not character:
        raise _problem("missing_character", action=action["id"])
    from services.game_generators.animation import method_for
    return {
        "character": character,
        "action": action["id"],
        "frames": _int(raw.get("frames"), int(action["frames"]), 1),
        "fps": _int(raw.get("fps"), int(action["fps"]), 1),
        "loop": _bool(raw.get("loop"), bool(action["loop"])),
        "method": _choice(raw.get("method"), ("h3", "strip"), method_for(action["id"]), "invalid_method"),
        "mirror": _bool(raw.get("mirror"), True),
    }


def _item_anim(raw: dict[str, Any]) -> dict[str, Any] | None:
    anim = raw.get("anim")
    if anim is None:
        return None
    if isinstance(anim, str):
        name, frames = anim, raw.get("frames")
    elif isinstance(anim, dict):
        name, frames = anim.get("action") or anim.get("name"), anim.get("frames")
    else:
        raise _problem("invalid_anim")
    action = _choice(name, ("spin", "bob", "glow"), "spin", "invalid_anim")
    return {"action": action, "frames": _int(frames, 8, 1)}


def _spec_item(raw: dict[str, Any], _game: dict[str, Any]) -> dict[str, Any]:
    spec: dict[str, Any] = {"sizePx": _int(raw.get("sizePx"), 32, 1)}
    anim = _item_anim(raw)
    if anim:
        spec["anim"] = anim
    return spec


def _spec_icon(raw: dict[str, Any], _game: dict[str, Any]) -> dict[str, Any]:
    return {
        "sizePx": _int(raw.get("sizePx"), 32, 1),
        "frame": _choice(raw.get("frame"), ("none", "round", "square"), "none", "invalid_frame"),
    }


def _spec_ui(raw: dict[str, Any], _game: dict[str, Any]) -> dict[str, Any]:
    return {
        "element": _choice(raw.get("element"), ("button", "panel", "bar", "frame", "cursor"), "button", "invalid_element"),
        "widthPx": _int(raw.get("widthPx"), 96, 1),
        "heightPx": _int(raw.get("heightPx"), 32, 1),
        "nineSlice": _bool(raw.get("nineSlice"), True),
    }


def _spec_tile(raw: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    return {"sizePx": _int(raw.get("sizePx"), int(game["style"]["pixel"]["tile"]), 1), "variants": _int(raw.get("variants"), 1, 1)}


def _spec_tileset(raw: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    return {
        "layout": _choice(raw.get("layout"), ("platform-3x3",), "platform-3x3", "invalid_layout"),
        "sizePx": _int(raw.get("sizePx"), int(game["style"]["pixel"]["tile"]), 1),
    }


def _spec_background(raw: dict[str, Any], _game: dict[str, Any]) -> dict[str, Any]:
    return {
        "widthPx": _int(raw.get("widthPx"), 640, 1),
        "heightPx": _int(raw.get("heightPx"), 360, 1),
        "layers": _int(raw.get("layers"), 3, 1),
        "loopX": _bool(raw.get("loopX"), True),
        "method": _choice(raw.get("method"), ("separate", "layered"), "separate", "invalid_method"),
    }


def _spec_vfx(raw: dict[str, Any], _game: dict[str, Any]) -> dict[str, Any]:
    return {
        "effect": _text(raw.get("effect")),
        "frames": _int(raw.get("frames"), 12, 1),
        "fps": _int(raw.get("fps"), 18, 1),
        "sizePx": _int(raw.get("sizePx"), 64, 1),
        "blend": _choice(raw.get("blend"), ("add", "alpha"), "add", "invalid_blend"),
    }


def _seconds(raw: dict[str, Any], fallback: float) -> float:
    value = raw.get("seconds", fallback)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < float(value) < math.inf:
        raise _problem("invalid_seconds", value=str(value))
    return float(value)


_RETRO_WORDS = (
    ("pickup", ("pickup", "recoger", "moneda", "coin")),
    ("jump", ("jump", "salto", "saltar")),
    ("laser", ("laser",)),
    ("hit", ("hit", "golpe", "impacto")),
    ("powerup", ("powerup", "mejora", "potencia")),
    ("blip", ("blip",)),
)


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _retro_preset(raw: dict[str, Any]) -> str:
    """Earliest keyword in the description, name, id or trigger, accents folded."""
    blob = _fold(" ".join(str(raw.get(key) or "") for key in ("description", "name", "id", "trigger")))
    found = ""
    at = len(blob) + 1
    for preset, words in _RETRO_WORDS:
        for word in words:
            match = re.search(rf"\b{re.escape(word)}\b", blob)
            if match and match.start() < at:
                found = preset
                at = match.start()
    return found


def _pixel_preset(game: dict[str, Any]) -> bool:
    return str((game.get("style") or {}).get("preset") or "").startswith("pixel-")


def _sfx_payload(raw: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Keyword fields live on the asset. A nested spec does not replace them."""
    merged = dict(spec)
    for key in ("id", "name", "description"):
        if key not in merged and _text(raw.get(key)):
            merged[key] = raw.get(key)
    return merged


def _spec_sfx(raw: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    omitted = raw.get("engine") in (None, "")
    engine = _choice(raw.get("engine"), ("mmaudio", "retro"), "mmaudio", "invalid_engine")
    detected = _retro_preset(raw)
    if omitted and _pixel_preset(game) and detected:
        engine = "retro"
    spec: dict[str, Any] = {
        "variants": _int(raw.get("variants"), 3, 1),
        "seconds": _seconds(raw, 1.0),
        "engine": engine,
    }
    preset = _text(raw.get("retroPreset")) or (detected if engine == "retro" else "")
    if preset:
        spec["retroPreset"] = preset
    if _text(raw.get("trigger")):
        spec["trigger"] = _text(raw.get("trigger"))
    return spec


def _spec_music(raw: dict[str, Any], _game: dict[str, Any]) -> dict[str, Any]:
    spec: dict[str, Any] = {"loopSeconds": _int(raw.get("loopSeconds"), 60, 1), "mood": _text(raw.get("mood"))}
    if raw.get("bpm") is not None:
        spec["bpm"] = _int(raw.get("bpm"), 120, 1)
    return spec


def _spec_jingle(raw: dict[str, Any], _game: dict[str, Any]) -> dict[str, Any]:
    return {
        "seconds": _int(raw.get("seconds"), 4, 1),
        "mood": _choice(raw.get("mood"), ("victory", "defeat", "levelup", "custom"), "victory", "invalid_mood"),
    }


def _spec_voice(raw: dict[str, Any], _game: dict[str, Any]) -> dict[str, Any]:
    character = _optional_slug(raw.get("character"))
    if not character:
        raise _problem("missing_character")
    spec: dict[str, Any] = {"character": character, "lines": _string_list(raw.get("lines"))}
    if _text(raw.get("traits")):
        spec["traits"] = _text(raw.get("traits"))
    return spec


def _spec_model(raw: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    model = game["style"]["model3d"]
    return {
        "maxTriangles": _int(raw.get("maxTriangles"), int(model["maxTriangles"]), 1),
        "texture": _int(raw.get("texture"), int(model["texture"]), 1),
        "multiview": _bool(raw.get("multiview"), False),
    }


def _spec_character3d(raw: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    profiles = ("humanoid", "quadruped", "flying", "prop", "vehicle", "serpentine")
    spec: dict[str, Any] = {
        "profile": _choice(raw.get("profile"), profiles, "humanoid", "invalid_profile"),
        "clips": _string_list(raw.get("clips")),
    }
    character = _optional_slug(raw.get("character"))
    if character:
        spec["character"] = character
    spec.update({key: value for key, value in _spec_model(raw, game).items() if key != "multiview"})
    return spec


_SPECS = {
    "character": _spec_character, "sprite": _spec_sprite, "animation": _spec_animation,
    "item": _spec_item, "icon": _spec_icon, "ui": _spec_ui, "tile": _spec_tile,
    "tileset": _spec_tileset, "background": _spec_background, "vfx": _spec_vfx,
    "sfx": _spec_sfx, "music": _spec_music, "jingle": _spec_jingle, "voice": _spec_voice,
    "model3d": _spec_model, "character3d": _spec_character3d,
}


def _seed(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _problem("invalid_seed", value=value)
    number = _int(value, 0, 0)
    if number != value:
        raise _problem("invalid_seed", value=value)
    return number


def _spec(kind: str, raw: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    source = raw.get("spec") if isinstance(raw.get("spec"), dict) else raw
    if kind == "sfx" and source is not raw:
        source = _sfx_payload(raw, source)
    spec = _SPECS[kind](source, game)
    if source.get("seed") is not None:
        spec["seed"] = _seed(source["seed"])
    return spec


def _optional_slug(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    return _slug(text, field="character")


def _depends_on(spec: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key in ("character", "source"):
        value = spec.get(key)
        if isinstance(value, str) and value and value not in found:
            found.append(value)
    return found


_FILE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _attempt_files(value: Any) -> dict[str, str]:
    """Workspace-relative POSIX paths under plain keys. The export writes these names into a zip."""
    if not isinstance(value, dict):
        return {}
    files: dict[str, str] = {}
    for key, path in value.items():
        text = path.replace("\\", "/") if isinstance(path, str) else ""
        parts = text.split("/")
        if (not _FILE_KEY.match(str(key)) or not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text)
                or any(part in ("", "..") for part in parts)):
            raise _problem("invalid_attempt_file", key=str(key)[:80], path=str(path)[:200])
        files[str(key)] = text
    return files


def _attempt(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not _text(raw.get("id")):
        raise _problem("invalid_attempt")
    return {
        "id": _text(raw.get("id")),
        "createdAt": _text(raw.get("createdAt")),
        "status": _choice(raw.get("status"), ("ok", "failed"), "ok", "invalid_attempt"),
        "inputs": _text(raw.get("inputs")),
        "files": _attempt_files(raw.get("files")),
        "metrics": copy.deepcopy(raw.get("metrics")) if isinstance(raw.get("metrics"), dict) else {},
        "warnings": copy.deepcopy(raw.get("warnings")) if isinstance(raw.get("warnings"), list) else [],
        "provenance": copy.deepcopy(raw.get("provenance")) if isinstance(raw.get("provenance"), dict) else {"steps": []},
        "decision": raw.get("decision") if raw.get("decision") in ("approved", "rejected") else None,
        "note": _text(raw.get("note")),
    }


def _prunable(attempt: dict[str, Any], approved_id: str | None) -> bool:
    return attempt.get("id") != approved_id and (attempt.get("decision") == "rejected" or attempt.get("status") == "failed")


def _prune_attempts(attempts: list[dict[str, Any]], approved_id: str | None) -> list[dict[str, Any]]:
    """Drop the oldest rejected or failed attempts beyond ``MAX_ATTEMPTS``; never the approved one."""
    kept = list(attempts)
    while len(kept) > MAX_ATTEMPTS:
        index = next((i for i, item in enumerate(kept) if _prunable(item, approved_id)), None)
        if index is None:
            break
        del kept[index]
    return kept


def normalize_asset(raw: dict[str, Any], game: dict[str, Any], *, now: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _problem("invalid_asset")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise _problem("unknown_kind", kind=kind)
    spec = _spec(str(kind), raw, game)
    approved = raw.get("approvedAttemptId")
    approved_id = _text(approved) or None
    return {
        "id": _slug(raw.get("id"), field="id"),
        "kind": kind,
        "name": _text(raw.get("name"), str(raw.get("id"))),
        "description": _text(raw.get("description")),
        "tags": _string_list(raw.get("tags")),
        "spec": spec,
        "dependsOn": _depends_on(spec),
        "candidates": _int(raw.get("candidates"), _CANDIDATES[str(kind)], 1),
        "status": _choice(raw.get("status"), STATUSES, "pending", "invalid_status"),
        "locked": _bool(raw.get("locked"), False),
        "notes": _text(raw.get("notes")),
        "attempts": _prune_attempts([_attempt(item) for item in raw.get("attempts") or []], approved_id),
        "approvedAttemptId": approved_id,
        "createdAt": _text(raw.get("createdAt"), now),
        "updatedAt": _text(raw.get("updatedAt"), now),
    }


def _cycles(assets: list[dict[str, Any]]) -> None:
    graph = {asset["id"]: list(asset.get("dependsOn") or []) for asset in assets}
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node: str, stack: list[str]) -> None:
        if node in visiting:
            raise GameValidationError("dependency_cycle", [{"code": "dependency_cycle", "ids": [*stack, node]}])
        if node in visited or node not in graph:
            return
        visiting.add(node)
        for dep in graph[node]:
            walk(dep, [*stack, node])
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        walk(node, [])


def _style_signature(style: dict[str, Any]) -> str:
    kept = {key: style.get(key) for key in ("preset", "traits", "negative", "palette", "paletteMode", "pixel", "light", "screen", "model3d", "audio", "references")}
    return json.dumps(kept, sort_keys=True, default=str)


def normalize_game(raw: dict[str, Any], *, now: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _problem("invalid_game")
    style = normalize_style(raw.get("style") if isinstance(raw.get("style"), dict) else {})
    draft = {"style": style}
    assets = [normalize_asset(item, draft, now=now) for item in raw.get("assets") or []]
    if len(assets) > MAX_ASSETS:
        raise _problem("too_many_assets", count=len(assets))
    ids = [asset["id"] for asset in assets]
    if len(ids) != len(set(ids)):
        raise _problem("duplicate_id")
    _cycles(assets)
    return {
        "id": _slug(raw.get("id"), field="id"),
        "title": _text(raw.get("title"), str(raw.get("id"))),
        "revision": _int(raw.get("revision"), 0, 0),
        "createdAt": _text(raw.get("createdAt"), now),
        "updatedAt": _text(raw.get("updatedAt"), now),
        "genre": _choice(raw.get("genre"), GENRES, "platformer", "invalid_genre"),
        "view": _choice(raw.get("view"), VIEWS, "side", "invalid_view"),
        "style": style,
        "assets": assets,
        "exports": copy.deepcopy(raw.get("exports")) if isinstance(raw.get("exports"), list) else [],
    }


def normalize_library(value: Any, *, now: str) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    games = []
    seen: set[str] = set()
    for item in raw.get("games") or []:
        game = normalize_game(item, now=now)
        if game["id"] in seen:
            raise _problem("duplicate_id", id=game["id"])
        seen.add(game["id"])
        games.append(game)
    return {"schema": SCHEMA, "version": 1, "games": games}


def library_path(workspace_dir: str) -> str:
    return os.path.join(workspace_dir, GAME_LIBRARY_FILENAME)


def read_library(workspace_dir: str) -> dict[str, Any]:
    path = library_path(workspace_dir)
    if not os.path.isfile(path):
        return empty_library()
    with open(path, "r", encoding="utf-8") as handle:
        return normalize_library(json.load(handle), now="")


def write_library(workspace_dir: str, value: Any, *, now: str = "") -> dict[str, Any]:
    library = normalize_library(value, now=now)
    encoded = json.dumps(library, ensure_ascii=False, indent=2)
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise _problem("too_large")
    os.makedirs(workspace_dir, exist_ok=True)
    path = library_path(workspace_dir)
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            if os.path.isfile(temporary):
                os.remove(temporary)
        except OSError:
            pass
    return library


def _bump(game: dict[str, Any], now: str) -> dict[str, Any]:
    updated = copy.deepcopy(game)
    updated["revision"] = int(updated.get("revision") or 0) + 1
    updated["updatedAt"] = now
    return updated


def _replace(library: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    games = [game if item.get("id") == game["id"] else copy.deepcopy(item) for item in library.get("games") or []]
    if game["id"] not in {item.get("id") for item in library.get("games") or []}:
        games.append(game)
    return {"schema": SCHEMA, "version": 1, "games": games}


def _game(library: dict[str, Any], game_id: str) -> dict[str, Any]:
    for game in library.get("games") or []:
        if game.get("id") == game_id:
            return copy.deepcopy(game)
    raise GameNotFoundError("game_not_found")


def _asset(game: dict[str, Any], asset_id: str) -> dict[str, Any]:
    for asset in game.get("assets") or []:
        if asset.get("id") == asset_id:
            return asset
    raise GameNotFoundError("asset_not_found")


def _check_revision(game: dict[str, Any], base_revision: int | None) -> None:
    if base_revision is not None and int(base_revision) != int(game["revision"]):
        raise GameConflictError()


def _apply_stale(game: dict[str, Any], *, keep: str | None = None) -> dict[str, Any]:
    """Mark stale assets; ``keep`` is an asset whose human decision must not be overridden."""
    stale = set(stale_assets(game)) - {keep}
    updated = copy.deepcopy(game)
    for asset in updated["assets"]:
        if asset["id"] in stale:
            asset["status"] = "stale"
    return updated


def _unique_id(taken: set[Any], wanted: str) -> str:
    candidate, suffix = wanted, 2
    while candidate in taken:
        tail = f"-{suffix}"
        candidate = f"{wanted[: MAX_ID - len(tail)].rstrip('-')}{tail}"
        suffix += 1
    return candidate


def _new_game_id(library: dict[str, Any], payload: dict[str, Any]) -> str:
    """An explicit id must be free; a title-derived id gets a numeric suffix instead."""
    taken = {game.get("id") for game in library.get("games") or []}
    if not payload.get("id"):
        return _unique_id(taken | _RESERVED_GAME_IDS, _slugify(_text(payload.get("title"), "juego")))
    wanted = _slug(payload["id"], field="id")
    if wanted in _RESERVED_GAME_IDS:
        raise _problem("reserved_id", field="id", value=wanted)
    if wanted in taken:
        raise GameConflictError(f"game {wanted} already exists", code="game_exists")
    return wanted


def create_game(library: dict[str, Any], raw: dict[str, Any], *, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = dict(raw or {})
    payload["id"] = _new_game_id(library, payload)
    payload["revision"] = 0
    game = _bump(normalize_game(payload, now=now), now)
    game["createdAt"] = now
    return _replace(library, game), game


def _merge_style(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    style = copy.deepcopy(current)
    if "preset" in patch and patch["preset"] != style.get("preset"):
        for key in _PRESET_KEYS:
            style.pop(key, None)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(style.get(key), dict):
            style[key] = {**style[key], **copy.deepcopy(value)}
        else:
            style[key] = copy.deepcopy(value)
    return style


def _merge_patch(game: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(game)
    for key in ("title", "genre", "view"):
        if key in patch:
            merged[key] = patch[key]
    if "style" in patch:
        if not isinstance(patch["style"], dict):
            raise _problem("invalid_style", value=str(patch["style"]))
        merged["style"] = _merge_style(merged["style"], patch["style"])
    return merged


def update_game(library: dict[str, Any], game_id: str, patch: dict[str, Any], base_revision: int, *, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
    game = _game(library, game_id)
    _check_revision(game, base_revision)
    before = _style_signature(game["style"])
    merged = _merge_patch(game, patch or {})
    merged["assets"] = game["assets"]
    merged["exports"] = game["exports"]
    merged["revision"] = game["revision"]
    merged["createdAt"] = game["createdAt"]
    normalized = normalize_game(merged, now=now)
    if "style" in (patch or {}) and _style_signature(normalized["style"]) != before:
        normalized["style"]["approval"] = "draft"
        normalized["style"]["approvedAt"] = None
        normalized["style"]["revision"] = int(game["style"]["revision"]) + 1
        normalized = _apply_stale(normalized)
    else:
        normalized["style"]["approval"] = game["style"]["approval"]
        normalized["style"]["approvedAt"] = game["style"]["approvedAt"]
        normalized["style"]["revision"] = game["style"]["revision"]
    updated = _bump(normalized, now)
    return _replace(library, updated), updated


def delete_game(library: dict[str, Any], game_id: str) -> dict[str, Any]:
    _game(library, game_id)
    games = [copy.deepcopy(item) for item in library.get("games") or [] if item.get("id") != game_id]
    return {"schema": SCHEMA, "version": 1, "games": games}


def _store_asset(game: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    assets = [asset if item["id"] == asset["id"] else item for item in game["assets"]]
    if asset["id"] not in {item["id"] for item in game["assets"]}:
        assets.append(asset)
    if len(assets) > MAX_ASSETS:
        raise _problem("too_many_assets", count=len(assets))
    _cycles(assets)
    updated = copy.deepcopy(game)
    updated["assets"] = assets
    return updated


def _edit_asset(previous: dict[str, Any], raw: dict[str, Any], game: dict[str, Any], now: str) -> dict[str, Any]:
    """Merge the editable keys of ``raw`` into ``previous``; attempts, approval and lock stay."""
    merged = copy.deepcopy(previous)
    merged.update({key: raw[key] for key in _EDITORIAL if key in raw})
    asset = normalize_asset(merged, game, now=now)
    asset["createdAt"] = previous["createdAt"]
    return asset


def upsert_assets(library: dict[str, Any], game_id: str, items: list[dict[str, Any]], replace: bool, *, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Insert or edit ``items``. ``replace`` drops assets missing from ``items`` and follows their order."""
    game = _game(library, game_id)
    if replace:
        listed = {raw.get("id") for raw in items}
        game["assets"] = [item for item in game["assets"] if item["id"] in listed]
    order: list[str] = []
    for raw in items:
        previous = next((item for item in game["assets"] if item["id"] == raw.get("id")), None)
        asset = normalize_asset(raw, game, now=now) if previous is None else _edit_asset(previous, raw, game, now)
        game = _store_asset(game, asset)
        order.append(asset["id"])
    if replace:
        rank = {asset_id: index for index, asset_id in enumerate(order)}
        game["assets"].sort(key=lambda item: rank.get(item["id"], len(rank)))
    game = _apply_stale(_bump(game, now))
    return _replace(library, game), game


def update_asset(library: dict[str, Any], game_id: str, asset_id: str, patch: dict[str, Any], base_revision: int, *, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
    game = _game(library, game_id)
    _check_revision(game, base_revision)
    asset = _edit_asset(_asset(game, asset_id), patch or {}, game, now)
    game = _apply_stale(_bump(_store_asset(game, asset), now))
    return _replace(library, game), _asset(game, asset_id)


def _put_attempt(attempts: list[dict[str, Any]], attempt: dict[str, Any]) -> list[dict[str, Any]]:
    """Append ``attempt``, or replace the one with the same id in place (a resumed batch reuses ids)."""
    if all(item["id"] != attempt["id"] for item in attempts):
        return [*attempts, attempt]
    return [attempt if item["id"] == attempt["id"] else item for item in attempts]


def add_attempt(library: dict[str, Any], game_id: str, asset_id: str, attempt: dict[str, Any], *, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
    game = _game(library, game_id)
    asset = _asset(game, asset_id)
    asset["attempts"] = _prune_attempts(_put_attempt(asset["attempts"], _attempt(attempt)), asset.get("approvedAttemptId"))
    asset["updatedAt"] = now
    game = _bump(_store_asset(game, asset), now)
    return _replace(library, game), _asset(game, asset_id)


def _attempt_of(asset: dict[str, Any], attempt_id: str) -> dict[str, Any]:
    for attempt in asset["attempts"]:
        if attempt["id"] == attempt_id:
            return attempt
    raise GameNotFoundError("attempt_not_found")


def approve_attempt(library: dict[str, Any], game_id: str, asset_id: str, attempt_id: str, *, now: str, base_revision: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    game = _game(library, game_id)
    _check_revision(game, base_revision)
    asset = _asset(game, asset_id)
    attempt = _attempt_of(asset, attempt_id)
    if attempt["status"] != "ok":
        raise _problem("attempt_not_ok", attemptId=attempt_id)
    for other in asset["attempts"]:
        if other.get("decision") == "approved":
            other["decision"] = None
    attempt["decision"] = "approved"
    asset["approvedAttemptId"] = attempt_id
    asset["status"] = "approved"
    asset["updatedAt"] = now
    game = _apply_stale(_bump(_store_asset(game, asset), now), keep=asset_id)
    return _replace(library, game), _asset(game, asset_id)


def reject_attempt(library: dict[str, Any], game_id: str, asset_id: str, attempt_id: str, note: str, *, now: str, base_revision: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not _text(note):
        raise _problem("note_required")
    game = _game(library, game_id)
    _check_revision(game, base_revision)
    asset = _asset(game, asset_id)
    attempt = _attempt_of(asset, attempt_id)
    attempt["decision"] = "rejected"
    attempt["note"] = _text(note)
    if asset.get("approvedAttemptId") == attempt_id:
        asset["approvedAttemptId"] = None
    asset["status"] = "approved" if asset.get("approvedAttemptId") else "rejected"
    asset["updatedAt"] = now
    game = _apply_stale(_bump(_store_asset(game, asset), now), keep=asset_id)
    return _replace(library, game), _asset(game, asset_id)


def lock_asset(library: dict[str, Any], game_id: str, asset_id: str, locked: bool, *, now: str, base_revision: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    game = _game(library, game_id)
    _check_revision(game, base_revision)
    asset = _asset(game, asset_id)
    asset["locked"] = bool(locked)
    asset["updatedAt"] = now
    game = _bump(_store_asset(game, asset), now)
    if not locked:
        game = _apply_stale(game)
    return _replace(library, game), _asset(game, asset_id)


def _reference_attempt(game: dict[str, Any], ref: dict[str, str]) -> None:
    asset = _asset(game, ref["assetId"])
    attempt = _attempt_of(asset, ref["attemptId"])
    if attempt["status"] != "ok":
        raise _problem("reference_not_ok", assetId=ref["assetId"], attemptId=ref["attemptId"])


def approve_style(library: dict[str, Any], game_id: str, references: list[dict[str, Any]], base_revision: int, *, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
    game = _game(library, game_id)
    _check_revision(game, base_revision)
    normalized = _references(references)
    for ref in normalized:
        _reference_attempt(game, ref)
    game["style"]["references"] = normalized
    game["style"]["approval"] = "approved"
    game["style"]["approvedAt"] = now
    game["style"]["revision"] = int(game["style"]["revision"]) + 1
    game = _apply_stale(_bump(game, now))
    return _replace(library, game), game


def mark_stale(library: dict[str, Any], game_id: str, *, now: str) -> tuple[dict[str, Any], dict[str, Any]]:
    game = _bump(_apply_stale(_game(library, game_id)), now)
    return _replace(library, game), game

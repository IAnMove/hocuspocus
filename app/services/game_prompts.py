"""Prompt, screen colour and reference order for a game asset.

The prompt is assembled in a fixed order: style traits, the preset phrase for
the kind, the description, the spec phrase (character role, sprite pose, icon
frame, UI element), the generator extra, the side-view rule for a character
(only the parts the preset phrase does not already say), the flat screen
sentence, then the latest rejection note. References stay at ten or fewer and
never point at a rejected attempt.
"""
from __future__ import annotations

from services.character_styles import screen_for as character_screen
from services.game_library import preset_catalog


_VIEW = ("side view", "facing right", "full body", "centered")
_ROLE = {
    "player": "player character",
    "enemy": "enemy character",
    "npc": "non-player character",
    "boss": "boss character",
}
_ELEMENT = {
    "button": "button",
    "panel": "panel",
    "bar": "horizontal bar",
    "frame": "empty frame",
    "cursor": "pointer cursor",
}
_ICON_FRAME = {"round": "inside a round frame", "square": "inside a square frame"}
_NEGATIVE = "text, watermark, frame, border"
_MAX_REFS = 10


def _style(game: dict) -> dict:
    style = game.get("style")
    return style if isinstance(style, dict) else {}


def _preset(style: dict) -> dict:
    preset_id = str(style.get("preset") or "")
    for preset in preset_catalog():
        if preset.get("id") == preset_id:
            return preset
    return {}


def screen_for(game: dict, asset: dict) -> str:
    """``style.screen``, or the character-style screen when that value is ``auto``."""
    chosen = str(_style(game).get("screen") or "auto")
    if chosen != "auto":
        return chosen
    return character_screen(str(asset.get("description") or ""))


def _fix_note(asset: dict) -> str:
    note = ""
    for attempt in asset.get("attempts") or []:
        if attempt.get("decision") == "rejected" and str(attempt.get("note") or "").strip():
            note = str(attempt["note"]).strip()
    return f"Fix: {note}" if note else ""


def _spec_phrase(kind: str, spec: dict) -> str:
    """The spec fields that change the picture, as prompt words."""
    if kind == "character":
        return _ROLE.get(str(spec.get("role") or ""), "")
    if kind == "sprite":
        pose = str(spec.get("pose") or "").strip()
        return f"pose: {pose}" if pose else ""
    if kind == "ui":
        return _ELEMENT.get(str(spec.get("element") or ""), "")
    if kind == "icon":
        return _ICON_FRAME.get(str(spec.get("frame") or ""), "")
    return ""


def _view(kind: str, kind_prompt: str) -> str:
    """The side-view rule, without the parts the preset phrase already says."""
    if kind not in {"character", "sprite"}:
        return ""
    said = kind_prompt.lower()
    return ", ".join(part for part in _VIEW if part not in said)


def build(game: dict, asset: dict, kind_extra: str = "", *, chroma: bool = True) -> tuple[str, str]:
    """Return ``(prompt, negative)``. ``chroma`` is off for a full-frame sky layer."""
    style = _style(game)
    kind = str(asset.get("kind") or "")
    kind_prompt = str((_preset(style).get("kindPrompts") or {}).get(kind) or "")
    screen = screen_for(game, asset)
    spec = asset.get("spec") if isinstance(asset.get("spec"), dict) else {}
    parts = [
        str(style.get("traits") or ""),
        kind_prompt,
        str(asset.get("description") or ""),
        _spec_phrase(kind, spec),
        kind_extra,
        _view(kind, kind_prompt),
        f"flat solid {screen} background, no shadow, no floor" if chroma else "",
        _fix_note(asset),
    ]
    prompt = ", ".join(part.strip().strip(",") for part in parts if str(part).strip())
    negative = str(style.get("negative") or "").strip()
    negative = f"{negative}, {_NEGATIVE}" if negative else _NEGATIVE
    return prompt, negative


def _assets(game: dict) -> list[dict]:
    return [item for item in (game.get("assets") or []) if isinstance(item, dict)]


def _by_id(game: dict, asset_id: str) -> dict | None:
    for asset in _assets(game):
        if asset.get("id") == asset_id:
            return asset
    return None


def _attempt(asset: dict, attempt_id: str) -> dict | None:
    for attempt in asset.get("attempts") or []:
        if attempt.get("id") == attempt_id:
            return attempt
    return None


def _usable_file(attempt: dict | None) -> str | None:
    if not isinstance(attempt, dict):
        return None
    if attempt.get("decision") == "rejected" or attempt.get("status") == "failed":
        return None
    files = attempt.get("files") or {}
    path = files.get("main") or files.get("rawKey")
    return str(path) if path else None


def _approved_file(asset: dict | None) -> str | None:
    if not isinstance(asset, dict) or not asset.get("approvedAttemptId"):
        return None
    return _usable_file(_attempt(asset, str(asset["approvedAttemptId"])))


def _push(found: list[str], path: str | None) -> None:
    if path and path not in found and len(found) < _MAX_REFS:
        found.append(path)


def _style_refs(game: dict, found: list[str]) -> None:
    for item in _style(game).get("references") or []:
        if len(found) >= _MAX_REFS:
            return
        if isinstance(item, str):
            _push(found, item)
            continue
        if not isinstance(item, dict):
            continue
        asset = _by_id(game, str(item.get("assetId") or ""))
        if asset is None:
            continue
        _push(found, _usable_file(_attempt(asset, str(item.get("attemptId") or ""))))


def _same_kind(game: dict, asset: dict, found: list[str]) -> None:
    tags = set(asset.get("tags") or [])
    ranked = []
    for other in _assets(game):
        if other.get("id") == asset.get("id") or other.get("kind") != asset.get("kind"):
            continue
        path = _approved_file(other)
        if not path or path in found:
            continue
        shared = len(tags & set(other.get("tags") or []))
        ranked.append((shared, str(other.get("updatedAt") or ""), path))
    ranked.sort(key=lambda item: item[1], reverse=True)
    ranked.sort(key=lambda item: item[0], reverse=True)
    for _shared, _when, path in ranked[:3]:
        _push(found, path)


def refs_for(game: dict, asset: dict) -> list[str]:
    """Up to ten files: style anchors, the approved character, then three of the same kind."""
    found: list[str] = []
    _style_refs(game, found)
    character_id = str((asset.get("spec") or {}).get("character") or "")
    if character_id:
        _push(found, _approved_file(_by_id(game, character_id)))
    _same_kind(game, asset, found)
    return found

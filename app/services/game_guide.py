"""Bible an agent reads before it produces a game pack.

The bible is a summary. Listing every asset would pass 6 KB once a game holds
hundreds of them, so counts carry the inventory and only the first assets that
still need a human decision are named. That is ``review``: a pending, failed
or stale asset waits for production, not for a person, and must not push a
reviewable asset out of the short list.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

GUIDE_PATH = Path(__file__).resolve().parents[1] / "shared" / "game_agent_guide.md"
_AWAITING = {"review"}
_AWAITING_CAP = 40


def guide_text() -> str:
    return GUIDE_PATH.read_text(encoding="utf-8")


def build_bible(game: dict[str, Any]) -> dict[str, Any]:
    """Style, counts by kind and status, references, and what still needs approval."""
    style = game.get("style") if isinstance(game.get("style"), dict) else {}
    assets = [item for item in game.get("assets") or [] if isinstance(item, dict)]
    counts: dict[str, dict[str, int]] = {}
    awaiting: list[dict[str, Any]] = []
    waiting = 0
    for asset in assets:
        kind = str(asset.get("kind") or "unknown")
        status = str(asset.get("status") or "pending")
        bucket = counts.setdefault(kind, {})
        bucket[status] = bucket.get(status, 0) + 1
        if status not in _AWAITING:
            continue
        waiting += 1
        if len(awaiting) < _AWAITING_CAP:
            awaiting.append({"id": asset.get("id"), "kind": kind, "status": status})
    return {
        "id": game.get("id"),
        "title": game.get("title"),
        "revision": game.get("revision"),
        "style": _style(style),
        "references": _references(style),
        "counts": counts,
        "awaitingApproval": awaiting,
        "awaitingMore": max(0, waiting - len(awaiting)),
    }


def _style(style: dict[str, Any]) -> dict[str, Any]:
    pixel = style.get("pixel") if isinstance(style.get("pixel"), dict) else {}
    palette = style.get("palette") if isinstance(style.get("palette"), list) else []
    audio = style.get("audio") if isinstance(style.get("audio"), dict) else {}
    return {
        "preset": style.get("preset"),
        "approval": style.get("approval"),
        "traits": str(style.get("traits") or "")[:500],
        "palette": [str(color) for color in palette[:64]],
        "paletteMode": style.get("paletteMode"),
        "pixel": {
            "enabled": bool(pixel.get("enabled")),
            "spriteHeight": pixel.get("spriteHeight"),
            "tile": pixel.get("tile"),
            "colors": pixel.get("colors"),
            "outline": pixel.get("outline"),
        },
        "audio": {key: audio.get(key) for key in ("genre", "instruments", "bpm", "musicLufs")},
    }


def _references(style: dict[str, Any]) -> list[Any]:
    references = style.get("references")
    if not isinstance(references, list):
        return []
    return references[:20]

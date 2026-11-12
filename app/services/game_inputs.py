"""Fingerprints for game assets.

An approved or rejected asset becomes stale when this digest no longer matches
the digest stored on its attempt. The shape follows ``series_take_inputs``.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

GENERATOR_VERSION: dict[str, int] = {
    "character": 1,
    "sprite": 1,
    "animation": 1,
    "item": 1,
    "icon": 1,
    "ui": 1,
    "tile": 1,
    "tileset": 1,
    "background": 1,
    "vfx": 1,
    "sfx": 1,
    "music": 1,
    "jingle": 1,
    "voice": 1,
    "model3d": 1,
    "character3d": 1,
}

_STYLE_KEYS = ("preset", "traits", "negative", "palette", "paletteMode", "pixel", "light", "screen")
_MODEL_KINDS = frozenset({"model3d", "character3d"})
_AUDIO_KINDS = frozenset({"sfx", "music", "jingle", "voice"})


def _references(style: dict[str, Any], asset_id: Any) -> list[Any]:
    """Style references, minus the asset's own entry: approving it as a reference must not stale it."""
    return [ref for ref in style.get("references") or [] if not (isinstance(ref, dict) and ref.get("assetId") == asset_id)]


def asset_inputs(game: dict[str, Any], asset: dict[str, Any]) -> str:
    """16-hex sha1 of everything a generator reads for this asset."""
    style = game.get("style") if isinstance(game.get("style"), dict) else {}
    by_id = {item.get("id"): item for item in game.get("assets") or [] if isinstance(item, dict)}
    kind = asset.get("kind")
    style_payload = {key: style.get(key) for key in _STYLE_KEYS}
    if kind in _MODEL_KINDS:
        style_payload["model3d"] = style.get("model3d")
    if kind in _AUDIO_KINDS:
        style_payload["audio"] = style.get("audio")
    payload = {
        "kind": kind,
        "spec": asset.get("spec"),
        "description": asset.get("description"),
        "notes": asset.get("notes"),
        "style": style_payload,
        "dependsOn": {
            dep: (by_id.get(dep) or {}).get("approvedAttemptId")
            for dep in asset.get("dependsOn") or []
        },
        "references": _references(style, asset.get("id")),
        "generator": GENERATOR_VERSION.get(str(kind), 0),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha1(encoded).hexdigest()[:16]


def _stored_inputs(asset: dict[str, Any]) -> str | None:
    attempts = [item for item in asset.get("attempts") or [] if isinstance(item, dict)]
    approved = asset.get("approvedAttemptId")
    if asset.get("status") == "approved" and approved:
        match = next((item for item in attempts if item.get("id") == approved), None)
        return None if match is None else match.get("inputs")
    decided = [item for item in attempts if item.get("decision") in ("approved", "rejected")]
    if not decided:
        return None
    return decided[-1].get("inputs")


def stale_assets(game: dict[str, Any]) -> list[str]:
    """Approved or rejected assets, not locked, whose stored digest differs."""
    found: list[str] = []
    for asset in game.get("assets") or []:
        if not isinstance(asset, dict) or asset.get("locked"):
            continue
        if asset.get("status") not in ("approved", "rejected"):
            continue
        if _stored_inputs(asset) != asset_inputs(game, asset):
            found.append(str(asset.get("id")))
    return found

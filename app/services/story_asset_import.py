"""Schemas and validation for Story Lab's review-first smart asset importer."""

from __future__ import annotations

from typing import Any


ASSET_KINDS = ("world", "location", "character", "prop", "style", "ignore")
MAX_IMPORT_ASSETS = 24


def asset_import_schema(count: int) -> dict[str, Any]:
    count = max(1, min(MAX_IMPORT_ASSETS, int(count)))
    item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "index": {"type": "integer", "minimum": 0, "maximum": count - 1},
            "kind": {"type": "string", "enum": list(ASSET_KINDS)},
            "targetId": {"type": "string"},
            "name": {"type": "string", "minLength": 1},
            "description": {"type": "string", "minLength": 1},
            "visualPrompt": {"type": "string", "minLength": 1},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": [
            "index", "kind", "targetId", "name", "description",
            "visualPrompt", "confidence", "reason",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "assets": {
                "type": "array", "items": item,
                "minItems": count, "maxItems": count,
            },
        },
        "required": ["assets"],
    }


def validate_asset_import_result(result: Any, count: int) -> list[dict[str, Any]]:
    if not isinstance(result, dict) or not isinstance(result.get("assets"), list):
        raise ValueError("Asset analysis did not return an assets array")
    raw_assets = result["assets"]
    if len(raw_assets) != count:
        raise ValueError(f"Asset analysis returned {len(raw_assets)} items; {count} were required")
    by_index: dict[int, dict[str, Any]] = {}
    for raw in raw_assets:
        if not isinstance(raw, dict):
            raise ValueError("Asset analysis contains a non-object item")
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Asset analysis contains an invalid index") from exc
        if index < 0 or index >= count or index in by_index:
            raise ValueError(f"Asset analysis contains duplicate/out-of-range index {index}")
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in ASSET_KINDS:
            raise ValueError(f"Asset {index + 1} has unsupported kind {kind!r}")
        name = str(raw.get("name") or "").strip()
        description = str(raw.get("description") or "").strip()
        visual_prompt = str(raw.get("visualPrompt") or "").strip()
        if not name or not description or not visual_prompt:
            raise ValueError(f"Asset {index + 1} is missing name, description or visualPrompt")
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence"))))
        except (TypeError, ValueError):
            confidence = 0.0
        by_index[index] = {
            "index": index,
            "kind": kind,
            "targetId": str(raw.get("targetId") or "").strip(),
            "name": name[:200],
            "description": description[:4000],
            "visualPrompt": visual_prompt[:4000],
            "confidence": confidence,
            "reason": str(raw.get("reason") or "").strip()[:1000],
        }
    return [by_index[index] for index in range(count)]

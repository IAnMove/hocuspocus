"""Short MCP replies: ids, a one-line description, and counts.

Full documents stay available when the caller passes detail or full.
"""

from __future__ import annotations

from typing import Any

_NAME_KEYS = ("name", "title", "label", "family", "labelKey")
_DESCRIPTION_KEYS = ("description", "visualIntent", "licenseNote", "summary", "blurb", "selector_help")
_LINE = 160


def one_line(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    line = " ".join(value.split())
    return line[:_LINE]


def _first(entry: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        text = one_line(entry.get(key))
        if text:
            return text
    return ""


def _counts(entry: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, value in entry.items():
        if key in {"id", "name", "title", "description", "visualIntent"}:
            continue
        if isinstance(value, (list, dict)):
            counts[key] = len(value)
    return counts


def summarize_entry(entry: dict) -> dict[str, Any]:
    """One catalog row without nested control schemas."""
    name = _first(entry, _NAME_KEYS) or one_line(entry.get("id"))
    return {
        "id": entry.get("id"),
        "name": name,
        "description": _first(entry, _DESCRIPTION_KEYS),
        "counts": _counts(entry),
    }


def _ids(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [
        item["id"]
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def _codes(items: Any) -> list[str]:
    codes: list[str] = []
    for item in items or []:
        if isinstance(item, dict) and isinstance(item.get("code"), str):
            codes.append(item["code"])
        elif isinstance(item, str) and item:
            codes.append(item)
    return codes


def compact_scene(document: Any, warnings: Any = None, *, errors: Any = None, saved: bool | None = None) -> dict[str, Any]:
    """Layer ids, text ids, warning codes, duration, and frame size."""
    doc = document if isinstance(document, dict) else {}
    summary: dict[str, Any] = {
        "layerIds": _ids(doc.get("layers")),
        "textIds": _ids(doc.get("texts")),
        "warningCodes": _codes(warnings),
        "duration": doc.get("duration"),
        "size": {"width": doc.get("width"), "height": doc.get("height")},
    }
    if errors is not None:
        summary["errorCodes"] = _codes(errors)
    if saved is not None:
        summary["saved"] = saved
    return summary


def compact_compile(name: str, shaped: dict) -> dict[str, Any]:
    if name == "scenes.template.compile":
        return compact_scene(shaped.get("document"), shaped.get("warnings"))
    if name == "scenes.text.template":
        texts = shaped.get("texts") if isinstance(shaped.get("texts"), list) else []
        return {
            "layerIds": [],
            "textIds": _ids(texts),
            "warningCodes": [],
            "duration": None,
            "size": {"width": None, "height": None},
            "textCount": len(texts),
        }
    lyrics = shaped.get("lyrics") if isinstance(shaped.get("lyrics"), dict) else {}
    lines = lyrics.get("lines") if isinstance(lyrics.get("lines"), list) else []
    return {
        "layerIds": [],
        "textIds": _ids(lines),
        "warningCodes": [],
        "duration": lyrics.get("duration"),
        "size": {"width": None, "height": None},
        "lineCount": len(lines),
    }


def summarize_model(model: dict) -> dict[str, Any]:
    description = one_line(model.get("description")) or one_line(model.get("selector_help"))
    counts: dict[str, int] = {}
    requirements = model.get("resource_requirements")
    if isinstance(requirements, (list, dict)):
        counts["requirements"] = len(requirements)
    group = model.get("shared_cache_group")
    if isinstance(group, list):
        counts["sharedCache"] = len(group)
    director = model.get("director")
    if isinstance(director, dict):
        counts["director"] = len(director)
    return {
        "id": model.get("model_type") or model.get("id"),
        "name": one_line(model.get("name")) or one_line(model.get("model_type")),
        "description": description,
        "counts": counts,
    }


def summarize_model_catalog(payload: dict) -> dict[str, Any]:
    models = payload.get("models") if isinstance(payload.get("models"), list) else []
    families = payload.get("families") if isinstance(payload.get("families"), list) else []
    by_family: dict[Any, int] = {}
    for model in models:
        if isinstance(model, dict):
            family = model.get("family")
            by_family[family] = by_family.get(family, 0) + 1
    return {
        "counts": {"models": len(models), "families": len(families)},
        "families": [
            {
                "id": item.get("id"),
                "name": one_line(item.get("label")) or one_line(item.get("id")),
                "description": one_line(item.get("label")),
                "counts": {"models": by_family.get(item.get("id"), 0)},
            }
            for item in families
            if isinstance(item, dict)
        ],
        "models": [summarize_model(item) for item in models if isinstance(item, dict)],
    }

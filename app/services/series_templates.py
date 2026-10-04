"""Series templates: a cast, locations, canon and a 2D pilot to start from.

``app/shared/series_templates.json`` keeps each text as ``{"es": ..., "en": ...}``.
``build_series`` resolves one language and returns a new, valid series
project (with its pilot episode) that the normal create path stores. The
characters have descriptions but no Character Kit yet: the one-click
character flow makes them, then the pilot renders on the server.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.series_library import create_series_episode, create_series_project, normalize_series_project

_PATH = Path(__file__).resolve().parents[1] / "shared" / "series_templates.json"
LANGUAGES = {"es": ("Español", "Español de España"), "en": ("English", "English")}
_FIELDS = ("logline", "premise", "genre", "tone", "audience", "visualStyle", "characterVisualStyle", "cameraLanguage",
           "defaultEpisodeDurationSeconds", "characters", "locations", "soundDesign")


class SeriesTemplateError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        self.status = status
        super().__init__(message)


@lru_cache(maxsize=1)
def _templates() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(_PATH.read_text(encoding="utf-8"))["templates"])


def _pick(value: Any, language: str) -> Any:
    """Resolve every ``{"es", "en"}`` text to one language."""
    if isinstance(value, dict):
        if value and set(value) <= set(LANGUAGES):
            return value.get(language) or value.get("en") or next(iter(value.values()))
        return {key: _pick(item, language) for key, item in value.items()}
    if isinstance(value, list):
        return [_pick(item, language) for item in value]
    return value


def _language(language: str | None) -> str:
    return language if language in LANGUAGES else "es"


def list_templates(language: str | None = None) -> list[dict[str, Any]]:
    """Short cards: id, title, description and what the template brings."""
    lang = _language(language)
    cards = []
    for template in _templates():
        series = template["series"]
        cards.append({"id": template["id"], "title": _pick(template["title"], lang), "description": _pick(template["description"], lang),
                      "characters": [_pick(item["name"], lang) for item in series.get("characters") or []],
                      "locations": [_pick(item["name"], lang) for item in series.get("locations") or []],
                      "pilotShots": len((series.get("pilot") or {}).get("shots") or [])})
    return cards


def build_series(template_id: str, workspace: str, *, title: str = "", language: str | None = None) -> dict[str, Any]:
    """A new series from a template, in ``language`` (es/en), with its pilot episode."""
    template = next((item for item in _templates() if item["id"] == template_id), None)
    if template is None:
        raise SeriesTemplateError(f"Unknown series template {template_id}", status=404)
    lang = _language(language)
    body = _pick(copy.deepcopy(template["series"]), lang)
    series = create_series_project(workspace, title=title.strip() or _pick(template["title"], lang))
    content, spoken = LANGUAGES[lang]
    series.update({key: body[key] for key in _FIELDS if key in body})
    series.update({"language": content, "spokenLanguage": spoken, "allowedProductionMethods": ["animation_2d", "generated_video"],
                   "template": {"id": template_id, "language": lang}})
    series["canon"] = {**series["canon"], **(body.get("canon") or {})}
    series = normalize_series_project(series, series["id"], workspace)
    pilot = body.get("pilot") or {}
    if pilot:
        episode = create_series_episode(series, None, title=pilot.get("title") or "Pilot", premise=pilot.get("premise") or "",
                                        script=pilot.get("script") or [], shots=pilot.get("shots") or [])
        series["episodesById"][episode["id"]] = episode
        series["seasons"][0]["episodeOrder"].append(episode["id"])
    return normalize_series_project(series, series["id"], workspace)

"""Classify assembled gallery results (not the clips that compose them)."""
from __future__ import annotations

import json
from typing import Any

RESULT_KINDS = ("music_video", "trailer", "series_episode", "chapter")
CHAPTER_FILTER_KINDS = ("series_episode", "chapter")


def is_assembled_mix(name: str) -> bool:
    filename = str(name or "").lower()
    return (
        "multiclip" in filename
        or filename.endswith("_mv.mp4")
        or "_series_assembly" in filename
        or filename.endswith("_movie.mp4")
        or filename.endswith("_rejoin_multiclip.mp4")
    )


def _explicit_kind(*sources: dict[str, Any]) -> str | None:
    for source in sources:
        kind = str(
            source.get("result_kind")
            or source.get("production_kind")
            or source.get("story_production_kind")
            or ""
        ).strip()
        if kind == "chapter":
            return "chapter"
        if kind in RESULT_KINDS:
            return kind
        if kind in {"episode", "capitulo", "capítulo"}:
            return "chapter"
    return None


def classify_output_result_kind(
    name: str,
    params: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Return a mix kind, or None for a component clip / other file."""
    filename = str(name or "").lower()
    params = params if isinstance(params, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    explicit = _explicit_kind(params, metadata)
    if explicit and is_assembled_mix(filename):
        return explicit
    if "_series_assembly." in filename or filename.endswith("_series_assembly.mp4"):
        return "series_episode"
    if not is_assembled_mix(filename):
        return None
    if explicit:
        return explicit
    for source in (params, metadata):
        pipeline_type = str(source.get("pipeline_type") or "").strip()
        if pipeline_type == "music_video":
            return "music_video"
        if pipeline_type == "series_episode":
            return "series_episode"
        if pipeline_type in {"short_film_story", "short_film_audio"}:
            return "chapter"
    blob = json.dumps({"params": params, "metadata": metadata}, ensure_ascii=False).lower()
    if "mandatory trailer arc" in blob or "cinematic story trailer" in blob:
        return "trailer"
    if filename.endswith("_mv.mp4") or "videoclip" in blob or "music video" in blob:
        return "music_video"
    if "multiclip" in filename and str(params.get("director_pipeline_id") or "").strip():
        if str(params.get("pipeline_type") or "") in {"short_film_story", "short_film_audio"}:
            return "chapter"
        return "music_video"
    if "multiclip" in filename:
        return "chapter"
    return None


def result_kind_matches_filter(kind: str | None, wanted: str) -> bool:
    wanted_kind = str(wanted or "").strip()
    actual = str(kind or "").strip()
    if not wanted_kind or not actual:
        return False
    if wanted_kind == "series_episode":
        return actual in CHAPTER_FILTER_KINDS
    return actual == wanted_kind


def result_kind_for_pipeline(params: dict[str, Any] | None) -> str | None:
    """Tag a Director concat from the live pipeline params."""
    params = params if isinstance(params, dict) else {}
    production = str(params.get("production_kind") or params.get("story_production_kind") or "").strip()
    if production == "trailer":
        return "trailer"
    if production in RESULT_KINDS:
        return production
    pipeline_type = str(params.get("pipeline_type") or "")
    if pipeline_type == "music_video":
        return "music_video"
    scene = str(params.get("scene_description") or "").lower()
    if "cinematic story trailer" in scene or "mandatory trailer arc" in scene:
        return "trailer"
    if pipeline_type in {"short_film_story", "short_film_audio"}:
        return "chapter"
    return None

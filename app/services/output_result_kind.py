"""Classify assembled gallery results (not the clips that compose them)."""
from __future__ import annotations

import glob
import json
import os
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


# A production (production.run) exports its cut through the Video Editor under its title, so neither the file name nor
# the sidecar says it is the music video: the gallery's Videoclips section never showed one. Its own state does
# (``<id>.production.json``: ``format`` and ``final``, which a re-export updates). Only that file counts: the
# animatics and intermediate exports of the same montage are not the cut.
PRODUCTION_KINDS = {"music_video": "music_video", "trailer": "trailer", "full_story": "chapter"}
_PRODUCTION_CACHE: dict[str, tuple[float, str | None, str]] = {}


def _production_cut(path: str) -> tuple[str | None, str]:
    """``(kind, final)`` of one production state file, cached by its mtime."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None, ""
    cached = _PRODUCTION_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1], cached[2]
    try:
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        state = {}
    state = state if isinstance(state, dict) else {}
    # Productions made before ``format`` existed are music videos: that is what production.run makes.
    kind = PRODUCTION_KINDS.get(str(state.get("format") or "music_video"))
    final = os.path.basename(state["final"]) if isinstance(state.get("final"), str) else ""
    _PRODUCTION_CACHE[path] = (mtime, kind, final)
    return kind, final


def production_cuts(out_dir: str) -> dict[str, str]:
    """The workspace's finished production cuts: file name → result kind."""
    cuts: dict[str, str] = {}
    for path in glob.glob(os.path.join(out_dir, "*.production.json")):
        kind, final = _production_cut(path)
        if kind and final:
            cuts[final] = kind
    return cuts


def production_result_kind(name: str, params: dict[str, Any] | None, cuts: dict[str, str]) -> str | None:
    """The kind of a production's finished cut, else None (``params`` is kept for the listing's call shape)."""
    return cuts.get(os.path.basename(str(name or "")))

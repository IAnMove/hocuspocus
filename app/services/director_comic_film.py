"""Comic-film canvas and locked-panel alignment.

These helpers stay outside ``director_video_strategy`` so a comic pass can
keep the offered canvas and repeat a split panel image without growing that
hotspot. Timing still lives next to ``adapt_bounded_timeline``.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from services.director_video_strategy import _normalize_director_h3_resolution


def _director_model_is_h3(
    model_def: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> bool:
    architecture = str(
        model_def.get("architecture") or model_def.get("base_model_type") or ""
    ).lower()
    model_type = str(
        model_def.get("model_type") or profile.get("model_type") or ""
    ).lower()
    return (
        architecture.startswith("minimax_h3")
        or model_type.startswith("minimax_h3")
        or bool(profile.get("is_minimax_h3"))
    )


def resolve_comic_output_resolution(
    video_params: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    model_def: Mapping[str, Any] | None,
) -> str:
    """Keep the canvas the comic UI offered.

    An explicit pixel size that the selected model publishes wins over a
    stale execution profile. H3's 540p default is 960x544; it must not
    replace a requested 1280x704 canvas. When the request is empty, the
    saved profile is the canvas PRE should show.
    """

    video_params = dict(video_params or {})
    profile = dict(profile or {})
    model_def = dict(model_def or {})
    requested = (
        str(video_params.get("resolution") or "")
        .strip()
        .lower()
        .replace("×", "x")
        .replace(" ", "")
    )
    profile_resolution = (
        str(profile.get("normalized_resolution") or "")
        .strip()
        .lower()
        .replace("×", "x")
        .replace(" ", "")
    )
    if re.fullmatch(r"\d+x\d+", requested):
        if _director_model_is_h3(model_def, profile):
            return _normalize_director_h3_resolution(requested, model_def)
        return requested
    if re.fullmatch(r"\d+x\d+", profile_resolution):
        return profile_resolution
    return "1280x704"


def repeat_locked_sources(
    items: Sequence[Any],
    plans: Sequence[Mapping[str, Any]],
) -> list[Any]:
    """Repeat each source when a locked shot is split, and never drop one.

    ``adapt_bounded_timeline`` records the pre-adapt index on every shot.
    A merged music cut keeps the first source. A comic panel that had to be
    split above the hardware maximum repeats that same panel image.
    """

    sources = list(items or [])
    if not sources or not plans:
        return sources
    aligned: list[Any] = []
    for index, plan in enumerate(plans):
        raw = plan.get("_director_source_clip_indices")
        source_index = index
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and raw:
            try:
                source_index = int(raw[0])
            except (TypeError, ValueError):
                source_index = index
        if source_index < 0 or source_index >= len(sources):
            source_index = min(max(index, 0), len(sources) - 1)
        item = sources[source_index]
        aligned.append(copy.deepcopy(item) if isinstance(item, dict) else item)
    return aligned

"""Foley for a generated or imported take: sound made from its picture, laid at the cut.

A rendered shot's ``foley`` is mixed into its take before the import. A video
take is not rendered, so its foley is a sound layer instead:
``series.episode.render_native`` (and so ``series.episode.produce``) runs
``generation.sfx`` (MMAudio) with the shot's take as the video guide and keeps
the sound as ``foley-<episode>-<shot>-<key>.wav``. The key depends on the take's
file and the prompt, so the same take and prompt reuse the file, a new take or
prompt makes a new one, and the volume (relative to the dialogue) is applied at
the cut by ``series_take_sound``. The take itself is never changed.
"""
from __future__ import annotations

import os
from typing import Any

from services.series_shot_foley import file_digest, foley_keys, normalize_foley

VIDEO_METHODS = frozenset({"generated_video", "imported_video"})
_DIGESTS: dict[tuple[str, int, int], str] = {}


def shot_foley(shot: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return normalize_foley(shot.get("foley"))
    except ValueError:
        return None


def video_take(series: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any] | None:
    """The asset of the shot's approved take, else of its newest completed one."""
    assets = series.get("assets") if isinstance(series.get("assets"), dict) else {}
    attempts = [item for item in shot.get("attempts") or [] if isinstance(item, dict) and item.get("status") == "completed"]
    approved = [item for item in attempts if item.get("id") == shot.get("approvedAttemptId")]
    for attempt in approved or list(reversed(attempts)):
        for asset_id in attempt.get("outputAssetIds") or []:
            asset = assets.get(str(asset_id))
            if isinstance(asset, dict) and asset.get("kind") == "video" and asset.get("uri"):
                return asset
    return None


def take_file(asset: dict[str, Any]) -> str:
    """The take's path inside its workspace (an asset ``uri`` names ``outputs/...`` or ``assets/...``)."""
    uri = str(asset.get("uri") or "")
    return uri[len("outputs/"):] if uri.startswith("outputs/") else uri


def wants_video_foley(shot: dict[str, Any]) -> bool:
    """A generated or imported shot with a foley prompt and a finished take to follow."""
    return shot.get("productionMethod") in VIDEO_METHODS and shot_foley(shot) is not None and any(
        isinstance(item, dict) and item.get("status") == "completed" for item in shot.get("attempts") or [])


def _digest(path: str) -> str:
    stat = os.stat(path)
    key = (path, stat.st_size, int(stat.st_mtime_ns))
    if key not in _DIGESTS:
        if len(_DIGESTS) > 256:
            _DIGESTS.clear()
        _DIGESTS[key] = file_digest(path)
    return _DIGESTS[key]


def sound_stem(episode_id: str, shot_id: str) -> str:
    return f"foley-{episode_id}-{shot_id}"[:120]


def sound_name(take_path: str, episode_id: str, shot_id: str, foley: dict[str, Any]) -> str:
    """The workspace file the foley of this take and prompt is kept in."""
    return f"{sound_stem(episode_id, shot_id)}-{foley_keys(_digest(take_path), foley)[0]}.wav"


def missing_video_foley(series: dict[str, Any], episode: dict[str, Any], root: str) -> list[str]:
    """Video shots whose foley has not been made for the take they show."""
    missing = []
    for shot in sorted(episode.get("shots") or [], key=lambda value: value.get("order", 0)):
        if not wants_video_foley(shot):
            continue
        asset = video_take(series, shot)
        path = os.path.join(root, take_file(asset)) if asset else ""
        if not path or not os.path.isfile(path):
            continue
        if not os.path.isfile(os.path.join(root, sound_name(path, episode["id"], shot["id"], shot_foley(shot) or {}))):
            missing.append(shot["id"])
    return missing


__all__ = ["VIDEO_METHODS", "missing_video_foley", "shot_foley", "sound_name", "sound_stem", "take_file", "video_take",
           "wants_video_foley"]

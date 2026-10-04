"""Ordered Series Lab episode assembly helpers."""

from __future__ import annotations

import copy
from typing import Any


def _scene_filename(asset: dict[str, Any]) -> str:
    """A 2D take's scene document, which holds the exact line timing for subtitles."""
    metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
    value = metadata.get("sceneFilename")
    return value if isinstance(value, str) else ""


def episode_assembly_plan(series: dict[str, Any], episode: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one approved video per shot in deterministic episode order."""
    assets = series.get("assets") if isinstance(series.get("assets"), dict) else {}
    shots = [item for item in episode.get("shots", []) if isinstance(item, dict)]
    if not shots:
        raise ValueError("The episode has no shots to join")
    plan: list[dict[str, Any]] = []
    for shot in sorted(shots, key=lambda item: (int(item.get("order") or 0), str(item.get("id") or ""))):
        approved_id = str(shot.get("approvedAttemptId") or "")
        if not approved_id:
            raise ValueError(f"Approve shot {shot.get('order')} before joining the episode")
        attempt = next((
            value for value in shot.get("attempts", [])
            if isinstance(value, dict) and str(value.get("id") or "") == approved_id
        ), None)
        if not attempt or attempt.get("status") != "completed":
            raise ValueError(f"Shot {shot.get('order')} does not have a completed approved attempt")
        asset = next((
            assets.get(str(asset_id)) for asset_id in attempt.get("outputAssetIds", [])
            if isinstance(assets.get(str(asset_id)), dict)
            and assets[str(asset_id)].get("kind") == "video"
        ), None)
        if not asset:
            raise ValueError(f"Shot {shot.get('order')} approved attempt has no video asset")
        item = {
            "shotId": str(shot.get("id") or ""),
            "shotOrder": int(shot.get("order") or 0),
            "attemptId": approved_id,
            "assetId": str(asset.get("id") or ""),
            "uri": str(asset.get("uri") or ""),
        }
        scene_filename = _scene_filename(asset)
        if scene_filename:
            item["sceneFilename"] = scene_filename
        plan.append(item)
    return copy.deepcopy(plan)

"""Stable comic shot identity and PRE fingerprint.

Seeds, PRE diffs and resume must key off the same shot id. Helpers that
touch files stay on ``director_pipeline`` and are reached via the host.
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from services.director.pipeline_locks import _pipeline_host


def _comic_shot(params: dict, index: int) -> dict:
    shots = params.get("comic_shots") or []
    return (
        shots[index]
        if index < len(shots) and isinstance(shots[index], dict)
        else {}
    )


def _stable_comic_shot_id(
    params: dict,
    index: int,
    plan: Optional[dict] = None,
) -> str:
    """Resolve the stable identity used for seeds, edits and PRE diffs."""
    plan = plan or {}
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    shot = _comic_shot(params, index)
    for source in (plan, metadata, shot):
        for key in ("shot_id", "primary_source_panel_id", "panel_id", "id"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
        panel_ids = source.get("source_panel_ids")
        if isinstance(panel_ids, list) and panel_ids:
            values = [
                str(item).strip()
                for item in panel_ids
                if str(item).strip()
            ]
            if values:
                return "+".join(values)
    page = shot.get("page_number")
    panel = shot.get("panel_number")
    return f"comic-shot-{page or 0}-{panel or index + 1}"


def _comic_shot_seed(
    params: dict,
    index: int,
    plan: Optional[dict] = None,
) -> int:
    """Derive a reproducible seed from master seed and stable shot ID."""
    host = _pipeline_host()
    plan = plan or {}
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    shot = _comic_shot(params, index)
    for source in (plan, metadata, shot):
        try:
            explicit = int(source.get("seed"))
        except (TypeError, ValueError):
            continue
        if explicit >= 0:
            return explicit
    master = host._normalise_master_seed(params)
    shot_id = _stable_comic_shot_id(params, index, plan)
    digest = hashlib.sha256(f"{master}:{shot_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def _comic_preflight_fingerprint(
    params: dict,
    clip_plans: list[dict],
    planned_clips: list[dict],
    clip_images: Optional[list[str]] = None,
    out_dir: Optional[str] = None,
) -> str:
    """Fingerprint every input that can change what Comic PRE promises."""
    host = _pipeline_host()
    source_paths = params.get("provided_clip_image_paths") or []
    prepared = [
        host._file_identity(os.path.join(out_dir or "", str(filename or "")))
        for filename in (clip_images or [])
    ]
    contract = {
        "comic_id": params.get("comic_id"),
        "master_seed": host._normalise_master_seed(params),
        "video_model": params.get("video_model"),
        "video_params": params.get("video_params") or {},
        "video_loras": params.get("video_loras") or {},
        "video_image_fit": params.get("video_image_fit"),
        "comic_motion_fidelity": params.get("comic_motion_fidelity"),
        "comic_end_frame_mode": params.get("comic_end_frame_mode"),
        "comic_shots": params.get("comic_shots") or [],
        "clip_plans": clip_plans,
        "planned_clips": planned_clips,
        "sources": [host._file_identity(path) for path in source_paths],
        "prepared": prepared,
    }
    return host._json_fingerprint(contract)

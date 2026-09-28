"""Publish an exported video to a platform preset. CPU FFmpeg only."""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from services.publish_presets import (
    PublishPresetError,
    collect_warnings,
    encode_args,
    measure_loudnorm,
    render_publish,
)
from services.video_editor import extract_frame


def _checked(body: dict) -> dict:
    try:
        return collect_warnings(
            preset=str(body.get("preset") or ""),
            width=int(body.get("width") or 0),
            height=int(body.get("height") or 0),
            duration=float(body.get("duration") or 0),
            overlays=body.get("overlays") if isinstance(body.get("overlays"), list) else [],
            premium=bool(body.get("premium")),
        )
    except PublishPresetError as exc:
        raise HTTPException(exc.status, {"code": "publish_preset", "message": str(exc)}) from exc


def publish_file(
    body: dict,
    *,
    resolve_source: Callable[[str, str], str],
    workspace_dir: Callable[[str], str],
) -> dict:
    warnings = _checked(body)
    source = resolve_source(str(body.get("source") or ""), str(body.get("workspace") or ""))
    folder = workspace_dir(str(body.get("workspace") or ""))
    os.makedirs(folder, exist_ok=True)
    preset = str(body.get("preset"))
    stem = os.path.splitext(os.path.basename(source))[0][:48] or "publish"
    name = f"{stem}_{preset}.mp4"
    destination = os.path.join(folder, name)
    measured = measure_loudnorm(source) if body.get("loudnorm") else None
    try:
        render_publish(source, destination, preset, premium=bool(body.get("premium")), loudnorm=measured)
    except PublishPresetError as exc:
        raise HTTPException(exc.status, {"code": "publish_preset", "message": str(exc)}) from exc
    thumbnail = os.path.splitext(destination)[0] + ".png"
    extract_frame(destination, thumbnail, 0.0)
    sidecar = {
        "preset": preset,
        "premium": bool(body.get("premium")),
        "args": encode_args(preset, premium=bool(body.get("premium"))),
        "warnings": warnings,
        "loudnorm": measured,
    }
    sidecar_name = os.path.splitext(name)[0] + ".publish.json"
    with open(os.path.join(folder, sidecar_name), "w", encoding="utf-8") as handle:
        json.dump(sidecar, handle, ensure_ascii=False, indent=2)
    return {
        "file": name,
        "url": f"/api/v1/file/{name}",
        "thumbnail": os.path.basename(thumbnail),
        "sidecar": sidecar_name,
        "warnings": warnings,
        "loudnorm": measured,
    }


def create_publish_router(*, resolve_source: Callable[[str, str], str], workspace_dir: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/video-editor/publish-check")
    def publish_check(body: dict):
        return {"warnings": _checked(body), "args": encode_args(str(body.get("preset") or ""), premium=bool(body.get("premium")))}

    @router.post("/api/v1/video-editor/publish")
    def publish_video(body: dict):
        return publish_file(body, resolve_source=resolve_source, workspace_dir=workspace_dir)

    return router

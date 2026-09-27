"""CPU song shorten. It never enters the generation queue."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from services.song_shorten import SongShortenError, load_and_shorten, remap_montage, suggest_keep, write_wav


def command_catalog() -> list[dict]:
    payload = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
            "source": {"type": "string", "minLength": 1, "maxLength": 2000},
            "keep": {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
            "duration_max": {"type": "number", "minimum": 1, "maximum": 3600},
            "analysis": {"type": "object"},
            "montage": {"type": "object"},
            "preview": {"type": "boolean"},
        },
        "required": ["workspace", "source"],
    }
    return [{
        "name": "audio.shorten",
        "version": 1,
        "domain": "audio",
        "mutation": True,
        "description": ("Shorten a workspace WAV on the CPU. keep is [[start, end], ...] in original seconds; "
                        "omitting it suggests ranges from analysis or from the file (drop a repeated chorus, "
                        "shorten bridges). preview returns the snapped time map without writing. Never uses the GPU queue."),
        "inputSchema": {"type": "object", "additionalProperties": False,
                        "properties": {"version": {"type": "integer", "const": 1}, "input": payload},
                        "required": ["version", "input"]},
    }]


def _payload(arguments: dict) -> dict:
    if not isinstance(arguments, dict) or arguments.get("version") != 1 or not isinstance(arguments.get("input"), dict):
        raise SongShortenError("Use version 1 and an input object")
    payload = arguments["input"]
    if "workspace" not in payload or "source" not in payload:
        raise SongShortenError("workspace and source are required")
    return payload


def shorten_request(payload: dict, *, resolve_source: Callable[[str, str], str], workspace_dir: Callable[[str], str]) -> dict:
    source = resolve_source(str(payload.get("source") or ""), str(payload.get("workspace") or ""))
    if not os.path.isfile(source):
        raise SongShortenError("Audio file was not found", status=404)
    duration_max = float(payload.get("duration_max") or 180)
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else None
    keep = payload.get("keep")
    if not keep:
        if analysis is None:
            from services.audio_analysis import analyze
            raw = analyze(source, transcribe=False)
            analysis = raw.to_dict() if hasattr(raw, "to_dict") else _analysis_dict(raw)
        suggestion = suggest_keep(analysis, duration_max)
        if payload.get("preview") or not payload.get("write", True):
            return {"keep": suggestion, "preview": True}
        keep = suggestion
    audio, sample_rate, time_map = load_and_shorten(source, keep, snap=True)
    result = {"time_map": time_map, "sample_rate": sample_rate, "duration": round(len(audio) / sample_rate, 6)}
    if isinstance(payload.get("montage"), dict):
        montage, report = remap_montage(payload["montage"], time_map)
        result["montage"] = montage
        result["report"] = report
    if payload.get("preview"):
        result["preview"] = True
        return result
    folder = workspace_dir(str(payload["workspace"]))
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(source))[0][:40] or "song"
    name = f"{time.strftime('%Y-%m-%d-%Hh%Mm%Ss')}_{stem}_short.wav"
    destination = os.path.join(folder, name)
    write_wav(destination, audio, sample_rate)
    result.update({"file": name, "url": f"/api/v1/file/{name}", "keep": keep})
    return result


def _analysis_dict(raw) -> dict:
    sections = []
    for section in getattr(raw, "sections", []) or []:
        sections.append({
            "start": getattr(section, "start", None),
            "end": getattr(section, "end", None),
            "label": getattr(section, "label", ""),
            "energy": getattr(section, "energy", 0),
        })
    return {"duration": getattr(raw, "duration", 0), "sections": sections, "bpm": getattr(raw, "bpm", 0)}


def create_audio_shorten_router(*, resolve_source: Callable[[str, str], str], workspace_dir: Callable[[str], str]) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/audio/shorten")
    def shorten_audio_route(body: dict):
        try:
            return shorten_request(body, resolve_source=resolve_source, workspace_dir=workspace_dir)
        except SongShortenError as exc:
            raise HTTPException(exc.status, {"code": "song_shorten", "message": str(exc)}) from exc

    return router


def command_handlers(resolve_source: Callable[[str, str], str], workspace_dir: Callable[[str], str]):
    async def handle(arguments: dict) -> dict:
        from fastapi import HTTPException
        try:
            result = shorten_request(_payload(arguments), resolve_source=resolve_source, workspace_dir=workspace_dir)
        except SongShortenError as exc:
            raise HTTPException(exc.status, {"code": "song_shorten", "message": str(exc)}) from exc
        return {"version": 1, "status": "completed", "operation": "audio.shorten", "result": result}

    return {"audio.shorten": handle}

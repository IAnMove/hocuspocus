"""Assemble the finished montage and export the contact sheet."""
from __future__ import annotations

import subprocess
from typing import Any

from services.production_control import sleep_until
from services.production_package import attach_origins
from services.production_scene_ops import contact_sheet_filter
from services.production_scene_retry import skip_montage
from services.production_state import failure_reason
from services.production_trailer_audio import attach as attach_trailer_audio


def _host():
    import services.music_production as host
    return host


def _refuse(code: str, message: str):
    from services.music_production import ProductionError
    raise ProductionError(code, message)


def _clip_rows(production: Any) -> list[dict]:
    scenes = production.state["scenes"]
    rows = []
    for key, _start, _end in production.state["segments"]:
        scene = scenes.get(key) or {}
        if not scene.get("file"):
            continue
        rows.append({"id": key, "name": key, "source": f"/api/v1/file/{scene['file']}?workspace={production.ws}",
                     "trimStart": 0, "trimEnd": scene["dur"], "muted": True, "fit": "fill", "transition": "none"})
    return rows


def _document(production: Any, spec: dict, score: dict) -> dict:
    montage = {"version": 1, "name": spec["title"], "width": 1920, "height": 1080, "fps": 24,
               "clips": _clip_rows(production), "audioCues": [], "overlays": [],
               "soundtrack": {"source": f"/api/v1/file/{production.state['song']['file']}?workspace={production.ws}",
                              "trimStart": 0, "trimEnd": score["duration"], "volume": 1.0, "loop": False}}
    attach_origins(montage, production.state.get("scene_docs") or {}, production.id)
    return attach_trailer_audio(production, spec, montage)


def _save(production: Any, montage: dict) -> None:
    body: dict[str, Any] = {"workspace": production.ws, "montage": montage}
    if production.state.get("montage_file"):
        current = (production.mcp("montages.get", {"version": 1, "input": {"workspace": production.ws, "file": production.state["montage_file"]}}).get("result") or {})
        revision = current.get("revision") or (current.get("montage") or {}).get("revision")
        if revision:
            body.update(file=production.state["montage_file"], expected_revision=revision)
    saved = production.mcp("montages.save", {"version": 1, "intent_id": f"{production.id}-montage-{int(_host().time.time())}", "input": body})
    if "result" not in saved:
        _refuse("montage_failed", __import__("json").dumps(saved)[:300])
    production.state["montage_file"] = saved["result"]["file"]


def _poll(production: Any, job_id: str) -> dict:
    while True:
        status = production.mcp("montages.export.status", {"version": 1, "input": {"workspace": production.ws, "job_id": job_id}})
        status = (status.get("result") or status).get("job", status)
        # montages.export queues a Video Editor job. cancelled is terminal there
        # (user cancel or resource scheduler); polling only completed/failed hangs.
        if status.get("status") in ("completed", "failed", "cancelled", "discarded", "error"):
            return status
        sleep_until(getattr(production, "_cancel", None), 4, _host().time.sleep)


def _contact(production: Any, score: dict) -> None:
    if not production.state.get("final"):
        return
    sheet = f"{production.id}-contact.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(production.root / production.state["final"]),
                    "-vf", contact_sheet_filter(score["duration"]), "-frames:v", "1", str(production.root / sheet)])
    production.state["contact_sheet"] = sheet


def montage(production: Any, spec: dict) -> None:
    if skip_montage(production.state):
        return
    score = production.score()
    _save(production, _document(production, spec, score))
    job = production.mcp("montages.export", {"version": 1, "intent_id": f"{production.id}-export-{int(_host().time.time())}",
                                              "input": {"workspace": production.ws, "file": production.state["montage_file"]}})["result"]["job"]
    status = _poll(production, job["job_id"])
    # start_export pre-fills filename when the job is created. A failed
    # render still carries that planned name; only a completed export is a video.
    if not isinstance(status, dict) or status.get("status") != "completed" or not status.get("filename"):
        reason = failure_reason(status) if isinstance(status, dict) else "export job lost"
        _refuse("montage_failed", reason)
    production.state["final"] = status["filename"]
    _contact(production, score)
    from services.production_smoothness import note_outputs
    note_outputs(production, "final")
    production.log(f"montage: {status.get('status')}")

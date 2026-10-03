"""Place an audio-driven clip on the song score.

``clip.align`` reads the score (lines with t0/t1, and beats) and the song time
the clip was driven from. Frame 0 of the file stays at that time (``sourceStart``).
``trimStart``/``trimEnd`` are the media in/out a Video 2D layer or a Montage clip
needs so playback stays inside that section. Lip-sync is ``qa.lipsync`` when that
module is installed; this command does not estimate a lag itself.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

OPERATION = "clip.align"
MAX_SCORE_BYTES = 2 * 1024 * 1024
_WORKSPACE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)")
_REQUIRED = ("workspace", "clip", "score_file", "range_start")


class ClipAlignError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def command_catalog() -> list[dict[str, Any]]:
    payload = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
            "clip": {"type": "string", "minLength": 1, "maxLength": 300},
            "score_file": {"type": "string", "minLength": 1, "maxLength": 300},
            "range_start": {
                "type": "number",
                "minimum": 0,
                "maximum": 36000,
                "description": "Song time, in seconds, that drove frame 0 of the clip.",
            },
        },
        "required": list(_REQUIRED),
    }
    return [{
        "name": OPERATION,
        "version": 1,
        "domain": "qa",
        "mutation": False,
        "description": (
            "Place a driven clip on the song. Returns trimStart and trimEnd (media in/out, "
            "seconds) so the used frames stay inside the score section, sourceStart (song "
            "time of frame 0), sync, and verdict. Montage clips use trimStart/trimEnd; a "
            "Video 2D layer uses the same trim plus sourceStart. sync is 0 and verdict is "
            "unreliable when qa.lipsync is not installed. No model call and no GPU."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "input": payload,
            },
            "required": ["version", "input"],
        },
    }]


def command_handlers(
    workspace_dir: Callable[[str], str],
    probe_duration: Callable[[str], float] | None = None,
    measure: Callable[..., Any] | None = None,
) -> dict[str, Callable[[Any], Any]]:
    probe = probe_duration or probe_duration_seconds

    async def handle(arguments: Any) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(
                run_align, arguments, workspace_dir=workspace_dir, probe_duration=probe, measure=measure,
            )
        except ClipAlignError as exc:
            raise HTTPException(exc.status, {
                "code": exc.code, "message": exc.message, "retryable": False,
            }) from exc
        return {"version": 1, "status": "completed", "operation": OPERATION, "result": result}

    return {OPERATION: handle}


def run_align(
    arguments: Any,
    *,
    workspace_dir: Callable[[str], str],
    probe_duration: Callable[[str], float],
    measure: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    payload = _payload(arguments)
    root = _root(workspace_dir, payload["workspace"])
    clip = _workspace_file(root, payload["clip"])
    score = _load_score(_workspace_file(root, payload["score_file"]))
    _require_lines(score)
    beats = _beat_times(score)
    range_start = _range_start(payload["range_start"])
    section = _section_at(score, range_start)
    duration = _duration(probe_duration, str(clip))
    trim_start, trim_end = _trim_inside(section, range_start, duration)
    sync = _sync(score, root, clip, range_start, measure)
    return _placement(range_start, trim_start, trim_end, beats, sync)


def probe_duration_seconds(path: str) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15, check=False,
        )
        value = float((result.stdout or "").strip())
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ClipAlignError("duration_unavailable", "Could not read the clip duration") from exc
    if not math.isfinite(value) or value <= 0:
        raise ClipAlignError("duration_unavailable", "Could not read the clip duration")
    return value


def _payload(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict) or arguments.get("version") != 1:
        raise ClipAlignError("invalid_command", "Use version 1 and an input object.")
    payload = arguments.get("input")
    if not isinstance(payload, dict):
        raise ClipAlignError("invalid_command", "Use version 1 and an input object.")
    missing = [key for key in _REQUIRED if key not in payload]
    if missing:
        raise ClipAlignError("invalid_command", "workspace, clip, score_file, and range_start are required.")
    return payload


def _root(workspace_dir: Callable[[str], str], name: Any) -> Path:
    if not isinstance(name, str) or not _WORKSPACE.fullmatch(name):
        raise ClipAlignError("invalid_workspace", "Use an explicit valid output workspace")
    try:
        folder = workspace_dir(name)
    except (OSError, ValueError, HTTPException) as exc:
        raise ClipAlignError("invalid_workspace", "Use an explicit valid output workspace") from exc
    if not isinstance(folder, str) or not folder:
        raise ClipAlignError("invalid_workspace", "Use an explicit valid output workspace")
    root = Path(folder).resolve()
    if not root.is_dir():
        raise ClipAlignError("invalid_workspace", "Use an explicit valid output workspace")
    return root


def _relative(name: Any) -> Path:
    if not isinstance(name, str) or not name.strip() or len(name) > 300:
        raise ClipAlignError("invalid_path", "clip and score_file must be workspace-relative paths")
    path = Path(name.strip())
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ClipAlignError("invalid_path", "clip and score_file must be workspace-relative paths")
    return path


def _workspace_file(root: Path, name: Any) -> Path:
    path = (root / _relative(name)).resolve()
    if root != path and root not in path.parents:
        raise ClipAlignError("invalid_path", "clip and score_file must stay inside the workspace")
    if not path.is_file():
        raise ClipAlignError("file_not_found", "File is not in the workspace", 404)
    return path


def _load_score(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ClipAlignError("file_not_found", "Score file is not readable", 404) from exc
    if len(raw) > MAX_SCORE_BYTES:
        raise ClipAlignError("invalid_score", "Score file is too large")
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClipAlignError("invalid_score", "Score file is not JSON") from exc
    if not isinstance(loaded, dict):
        raise ClipAlignError("invalid_score", "Score file must be a JSON object")
    return loaded


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _span_bounds(span: dict[str, Any]) -> tuple[float, float]:
    start, end = _finite(span.get("t0")), _finite(span.get("t1"))
    if start is None or end is None or end <= start:
        raise ClipAlignError("invalid_score", "Each score span needs t0 < t1")
    return start, end


def _require_lines(score: dict[str, Any]) -> None:
    lines = score.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ClipAlignError("invalid_score", "Score lines must list t0 and t1")
    for line in lines:
        if not isinstance(line, dict):
            raise ClipAlignError("invalid_score", "Score lines must list t0 and t1")
        _span_bounds(line)


def _beat_times(score: dict[str, Any]) -> list[float]:
    beats = score.get("beats")
    if not isinstance(beats, list) or not beats:
        raise ClipAlignError("invalid_score", "Score beats must be a non-empty list of times")
    times: list[float] = []
    for beat in beats:
        value = beat.get("t", beat.get("time")) if isinstance(beat, dict) else beat
        number = _finite(value)
        if number is None:
            raise ClipAlignError("invalid_score", "Score beats must be finite times")
        times.append(number)
    return times


def _spans(score: dict[str, Any]) -> list[dict[str, Any]]:
    sections = score.get("sections")
    if isinstance(sections, list) and sections:
        return [item for item in sections if isinstance(item, dict)]
    lines = score.get("lines")
    if not isinstance(lines, list):
        return []
    return [item for item in lines if isinstance(item, dict)]


def _section_at(score: dict[str, Any], range_start: float) -> dict[str, float]:
    found: dict[str, float] | None = None
    for span in _spans(score):
        try:
            start, end = _span_bounds(span)
        except ClipAlignError:
            continue
        if start <= range_start < end:
            found = {"t0": start, "t1": end}
            if start == range_start:
                break
    if found is None:
        raise ClipAlignError("section_not_found", "No score section contains range_start")
    return found


def _range_start(value: Any) -> float:
    number = _finite(value)
    if number is None or number < 0 or number > 36000:
        raise ClipAlignError("invalid_command", "range_start must be a song time in seconds")
    return number


def _duration(probe: Callable[[str], float], path: str) -> float:
    try:
        value = probe(path)
    except ClipAlignError:
        raise
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
        raise ClipAlignError("duration_unavailable", "Could not read the clip duration") from exc
    number = _finite(value)
    if number is None or number <= 0:
        raise ClipAlignError("duration_unavailable", "Could not read the clip duration")
    return number


def _trim_inside(section: dict[str, float], range_start: float, duration: float) -> tuple[float, float]:
    """Media in/out whose song window is the overlap of the clip and the section."""
    start = max(range_start, section["t0"])
    end = min(range_start + duration, section["t1"])
    trim_start = round(max(0.0, start - range_start), 3)
    trim_end = round(min(duration, max(0.0, end - range_start)), 3)
    if trim_end - trim_start <= 0.001:
        raise ClipAlignError("clip_outside_section", "The clip does not overlap the section")
    return trim_start, trim_end


def _anchor_beat(beats: list[float], played_start: float) -> float | None:
    prior = [beat for beat in beats if beat <= played_start + 1e-6]
    if not prior:
        return None
    return round(max(prior), 3)


def _placement(
    range_start: float,
    trim_start: float,
    trim_end: float,
    beats: list[float],
    sync: dict[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "trimStart": trim_start,
        "trimEnd": trim_end,
        "sourceStart": round(range_start, 3),
        "sync": sync["sync"],
        "verdict": sync["verdict"],
    }
    beat = _anchor_beat(beats, range_start + trim_start)
    if beat is not None:
        body["beat"] = beat
    if sync.get("reason"):
        body["reason"] = sync["reason"]
    return body


def _import_measure() -> Callable[..., Any] | None:
    try:
        from services.lipsync_qa import measure
    except ImportError:
        return None
    return measure


def _sync_fields(measured: Any) -> dict[str, Any]:
    if not isinstance(measured, dict) or measured.get("verdict") not in {"ok", "retake", "unreliable"}:
        return {"sync": 0.0, "verdict": "unreliable", "reason": "lipsync_unavailable"}
    verdict = measured["verdict"]
    lag = _finite(measured.get("suggested_sync_s"))
    if verdict != "ok" or lag is None:
        return {"sync": 0.0, "verdict": verdict}
    return {"sync": round(lag, 3), "verdict": verdict}


def _sync(
    score: dict[str, Any],
    root: Path,
    clip: Path,
    range_start: float,
    measure: Callable[..., Any] | None,
) -> dict[str, Any]:
    loader = measure if measure is not None else _import_measure()
    if loader is None:
        return {"sync": 0.0, "verdict": "unreliable", "reason": "lipsync_unavailable"}
    audio_name = score.get("vocals_file") if isinstance(score.get("vocals_file"), str) else score.get("audio")
    if not isinstance(audio_name, str) or not audio_name:
        return {"sync": 0.0, "verdict": "unreliable", "reason": "lipsync_audio_missing"}
    try:
        audio = _workspace_file(root, audio_name)
        measured = loader(str(clip), str(audio), float(range_start))
    except ClipAlignError:
        return {"sync": 0.0, "verdict": "unreliable", "reason": "lipsync_audio_missing"}
    except Exception:
        return {"sync": 0.0, "verdict": "unreliable", "reason": "lipsync_unavailable"}
    return _sync_fields(measured)

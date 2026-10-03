"""ffmpeg probes for one exported file.

Findings are warnings. A fail verdict does not block export or ask for confirmation.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

OPERATION = "qa.export"
TARGET_LUFS = -14.0
TOO_QUIET_LU = 8.0
CLIP_PEAK_DB = -0.5
FAIL_CODES = frozenset({
    "black", "frozen", "clipping", "too_quiet", "camera_jump", "duration_drift", "fps_drift",
})
WATCH_CODES = frozenset({"silence"})
ALLOW = frozenset({"still", "dark"})

_BLACK = re.compile(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)")
_FREEZE_START = re.compile(r"freeze_start:\s*([0-9.]+)")
_FREEZE_END = re.compile(r"freeze_end:\s*([0-9.]+)")
_FREEZE_DUR = re.compile(r"freeze_duration:\s*([0-9.]+)")
_SCD = re.compile(r"lavfi\.scd\.score:\s*([0-9.]+).*lavfi\.scd\.time:\s*([0-9.]+)")
_SILENCE_START = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)")
_PEAK = re.compile(r"Peak level dB:\s*(-?[0-9.]+)")
_LUFS = re.compile(r"I:\s*(-?[0-9.]+)\s+LUFS")
_VIDEO_FILTER = "blackdetect=d=0.05:pic_th=0.98:pix_th=0.10,freezedetect=n=-60dB:d=1.5,scdet=threshold=10"
_AUDIO_FILTER = "silencedetect=n=-50dB:d=0.4,astats=metadata=1:reset=0,ebur128"


class ExportQaError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def ffmpeg_bin() -> str | None:
    return os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")


def ffprobe_bin() -> str | None:
    return os.environ.get("FFPROBE_BINARY") or shutil.which("ffprobe")


def duration_tolerance(expected_fps: int | None) -> float:
    """Same window as ``validate_scene_recording_output``."""
    return max(0.05, 1 / max(1, int(expected_fps or 30)))


def remember_on_task(registry: Any, intent_id: str, report: dict) -> bool:
    """Store the probe on the task so the export receipt can show it."""
    entry = registry.command_admission(intent_id)
    if entry is None:
        return False
    task = registry.get(entry["task_id"]) or {}
    metadata = dict(task.get("metadata") or {})
    metadata["qa"] = report
    registry.update(entry["task_id"], metadata=metadata)
    return True


def probe(
    path: str,
    *,
    shots: list[dict] | None = None,
    target_lufs: float = TARGET_LUFS,
    expected_duration: float | None = None,
    expected_fps: int | None = None,
) -> dict[str, Any]:
    """Run the file probes. Never raises for a bad picture or a bad mix."""
    ffmpeg, ffprobe = ffmpeg_bin(), ffprobe_bin()
    if not ffmpeg or not ffprobe or not os.path.isfile(path):
        return _unreliable("probe_unavailable")
    try:
        media = _media(path, ffprobe)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return _unreliable("probe_failed")
    duration = float(media.get("duration") or 0.0)
    fps = float(media.get("fps") or expected_fps or 25.0)
    windows = _shots(shots, duration)
    warnings: list[dict[str, Any]] = []
    measured: dict[str, Any] = {"duration": round(duration, 3), "fps": round(fps, 3)}
    if media.get("video"):
        try:
            warnings.extend(_video_warnings(path, ffmpeg, windows, fps))
        except (OSError, subprocess.TimeoutExpired):
            return _unreliable("probe_failed")
    if media.get("audio"):
        try:
            audio_warnings, levels = _audio_warnings(path, ffmpeg, windows, float(target_lufs))
        except (OSError, subprocess.TimeoutExpired):
            return _unreliable("probe_failed")
        warnings.extend(audio_warnings)
        measured.update(levels)
    warnings.extend(_timing_warnings(media, expected_duration, expected_fps))
    return {"verdict": _verdict(warnings), "warnings": warnings, "measured": measured}


def command_catalog() -> list[dict[str, Any]]:
    shot = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "start": {"type": "number", "minimum": 0},
            "end": {"type": "number", "minimum": 0},
            "slot": {"type": "string", "minLength": 1, "maxLength": 80},
            "allow": {"type": "array", "items": {"type": "string", "enum": ["still", "dark"]}},
        },
    }
    return [{
        "name": OPERATION,
        "version": 1,
        "domain": "production",
        "mutation": False,
        "description": (
            "Probe one exported file with ffmpeg. Verdict is ok, watch, fail, or unreliable. "
            "Warnings use code, t, optional slot, detail, and evidence. A fail only warns: "
            "export is never blocked. intentional still and dark intervals are listed in shots.allow. "
            "target_lufs defaults to -14. When intent_id matches an export admission, the same "
            "report is stored on that task and shown as receipt.qa."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["version", "input"],
            "properties": {
                "version": {"type": "integer", "const": 1},
                "input": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["workspace", "file"],
                    "properties": {
                        "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
                        "file": {"type": "string", "minLength": 1, "maxLength": 300},
                        "intent_id": {"type": "string", "minLength": 1, "maxLength": 160},
                        "target_lufs": {"type": "number", "minimum": -70, "maximum": 0},
                        "expected_duration": {"type": "number", "exclusiveMinimum": 0, "maximum": 36000},
                        "expected_fps": {"type": "integer", "minimum": 1, "maximum": 120},
                        "shots": {"type": "array", "maxItems": 80, "items": shot},
                    },
                },
            },
        },
    }]


def command_handlers(
    workspace_dir: Callable[[str], str],
    record: Callable[[str, str, dict], Any] | None = None,
) -> dict[str, Callable[[Any], Any]]:
    async def handle(arguments: Any) -> dict[str, Any]:
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool

        try:
            data = _input(arguments)
            root = Path(workspace_dir(data["workspace"])).resolve()
            path = _inside(root, data["file"])
        except ExportQaError as error:
            raise HTTPException(error.status, {
                "code": error.code, "message": error.message, "retryable": False,
            }) from error

        def run() -> dict[str, Any]:
            report = probe(
                str(path),
                shots=data.get("shots"),
                target_lufs=float(data.get("target_lufs", TARGET_LUFS)),
                expected_duration=data.get("expected_duration"),
                expected_fps=data.get("expected_fps"),
            )
            intent = data.get("intent_id")
            if record is not None and isinstance(intent, str) and intent:
                record(data["workspace"], intent, report)
            return report

        return {
            "version": 1,
            "status": "completed",
            "operation": OPERATION,
            "result": await run_in_threadpool(run),
        }

    return {OPERATION: handle}


def _unreliable(reason: str) -> dict[str, Any]:
    return {"verdict": "unreliable", "warnings": [], "measured": {}, "reason": reason}


def _verdict(warnings: list[dict[str, Any]]) -> str:
    codes = {item["code"] for item in warnings}
    if codes & FAIL_CODES:
        return "fail"
    if codes & WATCH_CODES:
        return "watch"
    return "ok"


def _warning(code: str, t: float, detail: str, evidence: dict, slot: str | None) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "t": round(float(t), 3), "detail": detail, "evidence": evidence}
    if slot:
        item["slot"] = slot
    return item


def _shots(raw: list[dict] | None, duration: float) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        return [{"start": 0.0, "end": max(duration, 0.0), "allow": (), "slot": None}]
    windows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start") or 0)
            end = float(item["end"]) if item.get("end") is not None else duration
        except (TypeError, ValueError):
            continue
        allow = item.get("allow") if isinstance(item.get("allow"), list) else []
        slot = item.get("slot") if isinstance(item.get("slot"), str) else None
        windows.append({
            "start": start,
            "end": end,
            "allow": tuple(token for token in allow if token in ALLOW),
            "slot": slot,
        })
    return windows or [{"start": 0.0, "end": max(duration, 0.0), "allow": (), "slot": None}]


def _allowed(start: float, end: float, windows: list[dict], token: str) -> bool:
    for shot in windows:
        if token not in shot["allow"]:
            continue
        if start >= shot["start"] - 0.05 and end <= shot["end"] + 0.05:
            return True
    return False


def _open_shot(t: float, windows: list[dict], fps: float) -> dict | None:
    margin = 1.0 / max(fps, 1.0)
    for shot in windows:
        if shot["start"] + margin < t < shot["end"] - margin:
            return shot
    return None


def _slot_at(t: float, windows: list[dict]) -> str | None:
    for shot in windows:
        if shot["start"] - 0.05 <= t <= shot["end"] + 0.05:
            return shot["slot"]
    return None


def _media(path: str, ffprobe: str) -> dict[str, Any]:
    import json
    result = _run(ffprobe, ["-v", "error", "-print_format", "json", "-show_streams", "-show_format", path])
    if result.returncode != 0:
        raise ValueError("ffprobe failed")
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        raise ValueError("ffprobe returned no streams")
    video = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"), None)
    audio = any(isinstance(item, dict) and item.get("codec_type") == "audio" for item in streams)
    format_data = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    raw_duration = None
    if isinstance(video, dict):
        raw_duration = video.get("duration") or format_data.get("duration")
    else:
        raw_duration = format_data.get("duration")
    try:
        duration = float(raw_duration or 0)
    except (TypeError, ValueError):
        duration = 0.0
    fps = _ratio(str(video.get("r_frame_rate") or "")) if isinstance(video, dict) else None
    return {"video": video is not None, "audio": audio, "duration": duration, "fps": fps}


def _ratio(value: str) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        return float(value)
    except ValueError:
        return None


def _run(binary: str, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [binary, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def _message(line: str) -> str:
    end = line.rfind("]")
    if end >= 0:
        return line[end + 1:].strip()
    return line.strip()


def _video_warnings(path: str, ffmpeg: str, windows: list[dict], fps: float) -> list[dict[str, Any]]:
    result = _run(ffmpeg, ["-hide_banner", "-i", path, "-vf", _VIDEO_FILTER, "-an", "-f", "null", "-"])
    if result.returncode != 0:
        raise OSError("video probe failed")
    lines = result.stderr.splitlines()
    found = [*_black_warnings(lines, windows), *_freeze_warnings(lines, windows), *_jump_warnings(lines, windows, fps)]
    return found


def _black_warnings(lines: list[str], windows: list[dict]) -> list[dict[str, Any]]:
    found = []
    for line in lines:
        match = _BLACK.search(_message(line))
        if match is None:
            continue
        start, end, duration = (float(match.group(index)) for index in (1, 2, 3))
        if _allowed(start, end, windows, "dark"):
            continue
        found.append(_warning(
            "black", start, f"{duration:.3f}s black",
            {"start": start, "end": end, "duration": duration}, _slot_at(start, windows),
        ))
    return found


def _freeze_warnings(lines: list[str], windows: list[dict]) -> list[dict[str, Any]]:
    found = []
    pending: dict[str, float] | None = None
    for line in lines:
        msg = _message(line)
        start = _FREEZE_START.search(msg)
        if start is not None:
            pending = {"start": float(start.group(1))}
            continue
        if pending is None:
            continue
        duration = _FREEZE_DUR.search(msg)
        end = _FREEZE_END.search(msg)
        if duration is not None:
            pending["duration"] = float(duration.group(1))
        if end is None:
            continue
        pending["end"] = float(end.group(1))
        start_s = pending["start"]
        end_s = pending["end"]
        span = pending.get("duration", end_s - start_s)
        pending = None
        if _allowed(start_s, end_s, windows, "still"):
            continue
        found.append(_warning(
            "frozen", start_s, f"{span:.3f}s frozen",
            {"start": start_s, "end": end_s, "duration": span}, _slot_at(start_s, windows),
        ))
    return found


def _jump_warnings(lines: list[str], windows: list[dict], fps: float) -> list[dict[str, Any]]:
    found = []
    for line in lines:
        match = _SCD.search(_message(line))
        if match is None:
            continue
        score, t = float(match.group(1)), float(match.group(2))
        shot = _open_shot(t, windows, fps)
        if shot is None:
            continue
        found.append(_warning(
            "camera_jump", t, f"scene score {score:.1f}",
            {"score": score, "t": t}, shot["slot"],
        ))
    return found


def _audio_warnings(
    path: str, ffmpeg: str, windows: list[dict], target_lufs: float,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    result = _run(ffmpeg, ["-hide_banner", "-i", path, "-af", _AUDIO_FILTER, "-vn", "-f", "null", "-"])
    if result.returncode != 0:
        raise OSError("audio probe failed")
    lines = result.stderr.splitlines()
    levels: dict[str, float] = {}
    peaks = [float(item.group(1)) for line in lines if (item := _PEAK.search(_message(line)))]
    if peaks:
        levels["peak_db"] = max(peaks)
    loudness = _integrated(lines)
    if loudness is not None:
        levels["lufs"] = loudness
    found = _silence_warnings(lines, windows)
    if levels.get("peak_db", -99) >= CLIP_PEAK_DB:
        found.append(_warning("clipping", 0.0, f"peak {levels['peak_db']:.2f} dBFS", {"peak_db": levels["peak_db"]}, None))
    if loudness is not None and loudness <= target_lufs - TOO_QUIET_LU:
        found.append(_warning(
            "too_quiet", 0.0, f"{loudness:.1f} LUFS vs {target_lufs:.1f}",
            {"lufs": loudness, "target_lufs": target_lufs}, None,
        ))
    return found, levels


def _integrated(lines: list[str]) -> float | None:
    found = None
    for line in lines:
        msg = _message(line)
        if not msg.startswith("I:"):
            continue
        match = _LUFS.search(msg)
        if match is not None:
            found = float(match.group(1))
    return found


def _silence_warnings(lines: list[str], windows: list[dict]) -> list[dict[str, Any]]:
    found = []
    start: float | None = None
    for line in lines:
        msg = _message(line)
        opened = _SILENCE_START.search(msg)
        if opened is not None:
            start = float(opened.group(1))
            continue
        closed = _SILENCE_END.search(msg)
        if closed is None or start is None:
            continue
        end, duration = float(closed.group(1)), float(closed.group(2))
        t = start
        start = None
        if _allowed(t, end, windows, "still"):
            continue
        found.append(_warning(
            "silence", t, f"{duration:.3f}s silence",
            {"start": t, "end": end, "duration": duration}, _slot_at(t, windows),
        ))
    return found


def _timing_warnings(
    media: dict[str, Any], expected_duration: float | None, expected_fps: int | None,
) -> list[dict[str, Any]]:
    found = []
    duration = float(media.get("duration") or 0.0)
    fps = media.get("fps")
    if expected_duration is not None and expected_duration > 0:
        allowed = duration_tolerance(expected_fps)
        if duration <= 0 or abs(duration - float(expected_duration)) > allowed:
            found.append(_warning(
                "duration_drift", 0.0,
                f"{duration:.3f}s vs {float(expected_duration):.3f}s",
                {"duration": round(duration, 3), "expected": float(expected_duration)},
                None,
            ))
    if expected_fps is not None and isinstance(fps, float) and abs(fps - int(expected_fps)) > 0.51:
        found.append(_warning(
            "fps_drift", 0.0, f"{fps:.3f} fps vs {int(expected_fps)}",
            {"fps": round(fps, 3), "expected": int(expected_fps)}, None,
        ))
    return found


def _input(arguments: Any) -> dict[str, Any]:
    data = arguments.get("input") if isinstance(arguments, dict) else None
    version = arguments.get("version") if isinstance(arguments, dict) else None
    if version != 1 or not isinstance(data, dict):
        raise ExportQaError("invalid_command", "Use version 1 with input.workspace and input.file")
    workspace, name = data.get("workspace"), data.get("file")
    if not isinstance(workspace, str) or not workspace or not isinstance(name, str) or not name:
        raise ExportQaError("invalid_command", "Use version 1 with input.workspace and input.file")
    if ".." in Path(name).parts or name.startswith(("/", "\\")):
        raise ExportQaError("path_not_allowed", "file must stay inside the workspace")
    return data


def _inside(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if root != path and root not in path.parents:
        raise ExportQaError("path_not_allowed", "file must stay inside the workspace")
    if not path.is_file():
        raise ExportQaError("media_not_found", f"{name} is not a workspace file", status=404)
    return path

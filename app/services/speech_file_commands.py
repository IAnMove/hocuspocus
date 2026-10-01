"""Workspace audio windows to native Rhubarb cues, without a browser or GPU."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from services.scene3d_speech import SpeechAnalysisError, SpeechAnalysisUnavailable, analyze_voice

OPERATION = "audio.mouth_cues"


class VoiceWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workspace: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    file: str = Field(min_length=1, max_length=300)
    start: float = Field(default=0, ge=0, le=600, allow_inf_nan=False)
    duration: float = Field(gt=0, le=90, allow_inf_nan=False)
    dialogue: str = Field(default="", max_length=4000)
    language: str = Field(default="", max_length=16)


def freeze_window(arguments, workspace_dir):
    try:
        if not isinstance(arguments, dict) or set(arguments) != {"version", "input"} or type(arguments["version"]) is not int or arguments["version"] != 1:
            raise ValueError("Use version 1 and input")
        window = VoiceWindow.model_validate(arguments["input"])
        if window.start + window.duration > 600 or "\x00" in window.dialogue:
            raise ValueError("Invalid analysis window or dialogue")
        if Path(window.file).name != window.file or "\\" in window.file:
            raise ValueError("Use an exact workspace audio filename")
        root = Path(workspace_dir(window.workspace)).resolve()
        source = (root / window.file).resolve()
        if root not in source.parents or not source.is_file():
            raise ValueError("Audio not found in the workspace")
        if source.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("Use an audio source up to 32 MB")
        return window, source, root
    except (ValueError, ValidationError, OSError) as exc:
        raise HTTPException(422, {"code": "invalid_command", "message": "Use a workspace audio file and a finite window up to 90 seconds.", "retryable": False}) from exc


def _probe_duration(source):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source)],
                            capture_output=True, timeout=30, check=True)
    duration = float(json.loads(result.stdout)["format"]["duration"])
    if not math.isfinite(duration) or not 0 < duration <= 600:
        raise SpeechAnalysisError("Use an audio source up to 600 seconds.")
    return duration


def _window_wav(source, start, duration):
    result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", str(start), "-i", str(source),
                             "-t", str(duration), "-vn", "-threads", "2", "-ac", "1", "-ar", "16000",
                             "-acodec", "pcm_s16le", "-f", "wav", "-"],
                            capture_output=True, timeout=120, check=True)
    # ffmpeg's non-seekable WAV header uses unknown sizes. Freeze a bounded PCM
    # header before handing it to the same validator used by the Studio editor.
    import io
    import wave
    with wave.open(io.BytesIO(result.stdout), "rb") as decoded:
        pcm = decoded.readframes(round(duration * 16000))
    output = io.BytesIO()
    with wave.open(output, "wb") as normalized:
        normalized.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        normalized.writeframes(pcm)
    return output.getvalue()


def analyze_window(window, source, root):
    duration = min(window.duration, _probe_duration(source) - window.start)
    if duration <= 0:
        raise SpeechAnalysisError("The analysis window begins after the audio ends.")
    result = analyze_voice(_window_wav(source, window.start, duration), dialogue=window.dialogue, language=window.language)
    # Global source-clock cues can be shared by all shots with speech.offset=t0.
    result["mouthCues"] = [{**cue, "start": round(cue["start"] + window.start, 5),
                           "end": round(cue["end"] + window.start, 5)} for cue in result["mouthCues"]]
    result.update(source=window.file, start=window.start, duration=duration)
    identity = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:24]
    filename = f"mouth-cues-{identity}.json"
    (root / filename).write_text(json.dumps(result), encoding="utf-8")
    return {**result, "file": filename, "url": f"/api/v1/file/{filename}?workspace={window.workspace}"}


def command_catalog():
    return [{"name": OPERATION, "description": "Analyze a workspace voice window (up to 90 seconds) with the installed local Rhubarb engine, on CPU. Accepts ordinary audio formats and returns durable native mouth cues on the source clock. Use isolated vocals from audio.analyze for singing; no downloads or synthetic voice.",
             "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "input"],
                             "properties": {"version": {"type": "integer", "const": 1}, "input": VoiceWindow.model_json_schema()}}}]


def command_handlers(workspace_dir):
    async def handle(arguments):
        from services import resource_scheduler
        window, source, root = freeze_window(arguments, workspace_dir)

        def run():
            with resource_scheduler.coordinator.acquire(resource_scheduler.cpu_lane("speech-analysis"),
                                                        task_id=f"mouth-cues-{uuid.uuid4().hex}", description="Local mouth cues"):
                return analyze_window(window, source, root)

        try:
            result = await run_in_threadpool(run)
        except SpeechAnalysisUnavailable as exc:
            raise HTTPException(503, {"code": "speech_unavailable", "message": str(exc), "retryable": True}) from exc
        except (SpeechAnalysisError, subprocess.SubprocessError, OSError, ValueError, KeyError) as exc:
            raise HTTPException(422, {"code": "speech_analysis_failed", "message": "Audio could not be decoded or analyzed.", "retryable": False}) from exc
        return {"version": 1, "operation": OPERATION, "status": "completed", "result": result}

    return {OPERATION: handle}

"""MCP setup and source-clock phonemes through the app's native CPU speech lane."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from services import phoneme_runtime, resource_scheduler
from services.scene3d_speech import SpeechAnalysisUnavailable, validate_voice_wav
from services.speech_analysis_cache import remember
from services.speech_file_commands import VoiceWindow, freeze_window, _probe_duration, _window_wav

SETUP = "audio.phonemes.setup"
CUES = "audio.phoneme_cues"


def _setup_input(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"version", "input"} or type(arguments["version"]) is not int or arguments["version"] != 1:
        raise ValueError("Use version 1 and input")
    data = arguments["input"]
    if not isinstance(data, dict) or set(data) - {"install"} or type(data.get("install", False)) is not bool:
        raise ValueError("Use input.install as an explicit boolean")
    return data.get("install", False)


def _worker(pcm, dialogue, language):
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"}
    env.pop("HOCUS_MCP_TOKEN", None)
    body = {"pcm": base64.b64encode(pcm).decode(), "dialogue": dialogue,
            "language": "en-us" if language.lower() == "en" else language or "en-us"}
    result = subprocess.run([sys.executable, "-m", "services.phoneme_worker"],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            input=json.dumps(body).encode(), capture_output=True, timeout=360, check=False)
    if result.returncode:
        raise RuntimeError("CPU phoneme alignment failed; check the local runtime and transcript.")
    return result.stdout


def analyze_window(window, source, root):
    if not phoneme_runtime.capabilities()["installed"]:
        raise SpeechAnalysisUnavailable("Install the optional engine with audio.phonemes.setup input.install=true first.")
    duration = min(window.duration, _probe_duration(source) - window.start)
    if duration <= 0:
        raise ValueError("The window begins after the audio ends.")
    pcm = _window_wav(source, window.start, duration)
    validate_voice_wav(pcm)
    material = {"kind": "phoneme-alignment-v1", "audio": hashlib.sha256(pcm).hexdigest(),
                "revision": phoneme_runtime.REVISION, "dialogue": window.dialogue, "language": window.language}
    result = json.loads(remember(material, lambda: _worker(pcm, window.dialogue, window.language), ".json"))
    for key in ("mouthCues", "phonemes"):
        for item in result[key]:
            for time in ("start", "end", "emission_end"):
                if time in item:
                    item[time] = round(item[time] + window.start, 5)
    result.update(source=window.file, start=window.start, dialogue=window.dialogue, language=window.language)
    identity = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:24]
    filename = f"phoneme-cues-{identity}.json"
    (root / filename).write_text(json.dumps(result), encoding="utf-8")
    return {**result, "file": filename, "url": f"/api/v1/file/{filename}?workspace={window.workspace}"}


def command_catalog():
    return [{"name": SETUP, "description": "Read offline CPU phoneme-engine status; install=true explicitly downloads a pinned, checksum-verified 1.26 GB optional model. Never downloads during analysis.",
             "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "input"],
                             "properties": {"version": {"const": 1, "type": "integer"}, "input": {"type": "object", "additionalProperties": False,
                                 "properties": {"install": {"type": "boolean", "default": False}}}}}},
            {"name": CUES, "description": "CPU acoustic phonemes for a workspace voice window, with optional exact transcript CTC alignment. Returns timed vowels/consonants, confidence and native mouth cues on the source clock. Use isolated singing vocals, review low confidence, and keep soundtrack timing unchanged.",
             "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "input"],
                             "properties": {"version": {"const": 1, "type": "integer"}, "input": VoiceWindow.model_json_schema()}}}]


def command_handlers(workspace_dir):
    async def setup(arguments):
        try:
            install = _setup_input(arguments)
            if install:
                def work():
                    with resource_scheduler.coordinator.acquire(resource_scheduler.cpu_lane("speech-install"), task_id=f"phoneme-install-{uuid.uuid4().hex}"):
                        return phoneme_runtime.install()
                result = await run_in_threadpool(work)
            else:
                result = phoneme_runtime.capabilities()
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(422, {"code": "phoneme_setup_failed", "message": str(exc), "retryable": True}) from exc
        return {"version": 1, "operation": SETUP, "status": "completed", "result": result}

    async def cues(arguments):
        window, source, root = freeze_window(arguments, workspace_dir)
        def work():
            with resource_scheduler.coordinator.acquire(resource_scheduler.cpu_lane("speech-analysis"), task_id=f"phoneme-{uuid.uuid4().hex}"):
                return analyze_window(window, source, root)
        try:
            result = await run_in_threadpool(work)
        except SpeechAnalysisUnavailable as exc:
            raise HTTPException(503, {"code": "speech_unavailable", "message": str(exc), "retryable": True}) from exc
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise HTTPException(422, {"code": "phoneme_alignment_failed", "message": str(exc), "retryable": False}) from exc
        return {"version": 1, "operation": CUES, "status": "completed", "result": result}
    return {SETUP: setup, CUES: cues}

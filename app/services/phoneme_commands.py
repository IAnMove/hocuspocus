"""MCP setup and source-clock phonemes through the app's native CPU speech lane."""
from __future__ import annotations

import subprocess

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from services.scene3d_speech import SpeechAnalysisUnavailable
from services.speech_alignment import setup_phonemes
from services.speech_file_commands import VoiceWindow, freeze_window, analyze_window as shared_window

SETUP = "audio.phonemes.setup"
CUES = "audio.phoneme_cues"


def _setup_input(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"version", "input"} or type(arguments["version"]) is not int or arguments["version"] != 1:
        raise ValueError("Use version 1 and input")
    data = arguments["input"]
    if not isinstance(data, dict) or set(data) - {"install"} or type(data.get("install", False)) is not bool:
        raise ValueError("Use input.install as an explicit boolean")
    return data.get("install", False)


def analyze_window(window, source, root):
    if window.engine == "rhubarb":
        raise ValueError("audio.phoneme_cues requires the phoneme engine")
    return shared_window(window.model_copy(update={"engine": "phoneme"}), source, root, "phoneme-cues")


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
            result = await run_in_threadpool(setup_phonemes, install)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(422, {"code": "phoneme_setup_failed", "message": str(exc), "retryable": True}) from exc
        return {"version": 1, "operation": SETUP, "status": "completed", "result": result}

    async def cues(arguments):
        window, source, root = freeze_window(arguments, workspace_dir)
        try:
            result = await run_in_threadpool(analyze_window, window, source, root)
        except SpeechAnalysisUnavailable as exc:
            raise HTTPException(503, {"code": "speech_unavailable", "message": str(exc), "retryable": True}) from exc
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise HTTPException(422, {"code": "phoneme_alignment_failed", "message": str(exc), "retryable": False}) from exc
        return {"version": 1, "operation": CUES, "status": "completed", "result": result}
    return {SETUP: setup, CUES: cues}

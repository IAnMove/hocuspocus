"""Bounded, offline Rhubarb analysis. No model downloads or cloud calls."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import wave

from services.speech_analysis_cache import analysis_material, remember

MAX_BYTES = 3_000_000
_LOCK = threading.BoundedSemaphore(1)


class SpeechAnalysisError(ValueError):
    pass


class SpeechAnalysisUnavailable(RuntimeError):
    pass


def rhubarb_executable() -> str | None:
    configured = os.environ.get("RHUBARB_EXECUTABLE", "")
    if configured:
        candidate = Path(configured)
        return str(candidate) if candidate.is_absolute() and candidate.is_file() else None
    from services.install_speech_tools import bundled_executable
    bundled = bundled_executable()
    return shutil.which("rhubarb") or (str(bundled) if bundled.is_file() else None)


def validate_voice_wav(data: bytes) -> float:
    if len(data) > MAX_BYTES:
        raise SpeechAnalysisError("Use a mono 16 kHz PCM WAV of up to 90 seconds.")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames = audio.getnframes()
            duration = frames / audio.getframerate()
            if audio.getnchannels() != 1 or audio.getframerate() != 16000 or audio.getsampwidth() != 2 or audio.getcomptype() != "NONE" or not 0 < duration <= 90:
                raise SpeechAnalysisError("Use a mono 16 kHz PCM WAV of up to 90 seconds.")
            if len(audio.readframes(frames)) != frames * 2:
                raise SpeechAnalysisError("Truncated WAV.")
            return duration
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        raise SpeechAnalysisError("Invalid PCM WAV.") from exc


def analyze_voice(data: bytes, isolate_vocals: bool = False, dialogue: str = "", language: str = "") -> dict:
    duration = validate_voice_wav(data)
    executable = rhubarb_executable()
    if not executable:
        raise SpeechAnalysisUnavailable("Rhubarb is not installed. Set RHUBARB_EXECUTABLE or put rhubarb on PATH; you can also import a cues JSON or use volume analysis.")
    isolation = None
    if isolate_vocals:
        from services.vocal_isolation import isolation_key_material
        isolation = isolation_key_material()
    recognizer = "pocketSphinx" if language.lower().split('-')[0] == "en" else "phonetic"
    options = {"recognizer": recognizer, "extendedShapes": "GHX", "threads": 2}
    if dialogue:
        options["dialogue"] = dialogue
    material = analysis_material(
        data, duration, isolate_vocals, executable,
        options, isolation)
    payload = remember(material, lambda: json.dumps(_analyze_uncached(data, duration, isolate_vocals, executable, recognizer, dialogue)).encode(), ".json")
    return json.loads(payload)


def _analyze_uncached(data: bytes, duration: float, isolate_vocals: bool, executable: str, recognizer: str = "phonetic", dialogue: str = "") -> dict:
    if not _LOCK.acquire(blocking=False):
        raise SpeechAnalysisUnavailable("Another local speech analysis is running. Try again shortly.")
    try:
        if isolate_vocals:
            from services.vocal_isolation import isolate_voice
            data = isolate_voice(data)
        cues = _rhubarb_mouth_cues(executable, data, duration, recognizer, dialogue)
        return {"mouthCues": cues, "recognizer": recognizer, "duration": duration,
                "analysisSource": "isolated-vocals" if isolate_vocals else "original"}
    finally:
        _LOCK.release()


def _rhubarb_mouth_cues(executable: str, data: bytes, duration: float, recognizer: str = "phonetic", dialogue: str = "") -> list:
    # Keep diagnostic files: never delete user audio or imported assets.
    folder = Path(tempfile.mkdtemp(prefix="hocuspocus-speech-"))
    source, output = folder / "voice.wav", folder / "cues.json"
    source.write_bytes(data)
    arguments = []
    if dialogue:
        transcript = folder / "dialogue.txt"
        transcript.write_text(dialogue, encoding="utf-8")
        arguments = ["--dialogFile", str(transcript)]
    try:
        completed = subprocess.run(
            [executable, "--threads", "2", "--quiet", "-r", recognizer,
             "--extendedShapes", "GHX", "-f", "json", "-o", str(output), *arguments, str(source)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=90, check=False, shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise SpeechAnalysisUnavailable("Local speech analysis failed or timed out.") from exc
    if completed.returncode or not output.is_file() or output.stat().st_size > 2_000_000:
        raise SpeechAnalysisUnavailable("Local speech analysis produced no valid result.")
    try:
        return _accepted_mouth_cues(json.loads(output.read_text(encoding="utf-8"))["mouthCues"], duration)
    except (KeyError, ValueError, TypeError, OSError) as exc:
        raise SpeechAnalysisUnavailable("Local speech analysis produced invalid cues.") from exc


def _accepted_mouth_cues(cues, duration: float) -> list:
    if not isinstance(cues, list) or len(cues) > 10000:
        raise ValueError("Invalid cues")
    previous = 0.0
    for cue in cues:
        start, end = float(cue["start"]), float(cue["end"])
        if cue["value"] not in "ABCDEFGHX" or len(cue["value"]) != 1 or not previous <= start < end <= duration + .1:
            raise ValueError("Invalid cue")
        previous = end
    return cues

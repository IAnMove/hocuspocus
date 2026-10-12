"""Measure a spoken take without listening: what it says, how high and how fast.

During the Uncanny Valley production every designed or cloned voice was
checked by hand with the same three numbers: a Whisper transcript against
the script (word error rate, with numbers spelled the same way on both
sides), the median pitch, and the speaking pace. A description that asked
for a male voice sometimes came back at 220 Hz, and a clone sometimes
dropped a word; these numbers caught both. They inform and warn; they never
block.

Transcription runs on the CPU (Whisper small, int8) on the audio lane.
"""
from __future__ import annotations

import os
import re
import threading
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from services.speech_language import spoken_language_code
from services.speech_text_es import merge_names, token_error_rate, wer_threshold
from services.voice_pitch import pitch_notice

OPERATION = "qa.speech"
CKPTS = Path(__file__).resolve().parents[1] / "ckpts"
MAX_WER = 0.15
PACE_RANGE = (1.6, 4.6)
MAX_EDGE_SILENCE = 0.6
_lock = threading.Lock()
_model: Any = None
_PERCENT = {"en": "percent", "es": "por ciento", "fr": "pour cent", "de": "prozent", "it": "per cento", "pt": "por cento"}


def _spell_numbers(text: str, language: str) -> str:
    """``97%`` and ``ninety-seven percent`` must compare equal."""
    text = re.sub(r"(\d)\s*%", lambda match: f"{match.group(1)} {_PERCENT.get(language, 'percent')}", text)
    try:
        from num2words import num2words
    except ImportError:
        return text

    def spell(match: re.Match[str]) -> str:
        digits = match.group(0).replace(",", "")
        try:
            return f" {num2words(int(digits), lang=language)} "
        except (NotImplementedError, OverflowError, ValueError):
            return match.group(0)
    return re.sub(r"\d[\d,]*", spell, text)


def words(text: str, language: str = "en") -> list[str]:
    """Lower case, no accents or punctuation, numbers spelled out, hyphens split."""
    text = unicodedata.normalize("NFKD", _spell_numbers(str(text or ""), language).lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9 ]+", " ", text.replace("-", " ")).split()


def word_error_rate(reference: str, hypothesis: str, language: str = "en") -> float:
    ref, hyp = words(reference, language), words(hypothesis, language)
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, start=1):
        current = [i] + [0] * len(hyp)
        for j, hyp_word in enumerate(hyp, start=1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref_word != hyp_word))
        previous = current
    return previous[-1] / max(1, len(ref))


def _whisper() -> Any:
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            snapshots = CKPTS / "whisper" / "models--Systran--faster-whisper-small" / "snapshots"
            local = next(snapshots.iterdir(), None) if snapshots.is_dir() else None
            _model = WhisperModel(str(local) if local else "small", device="cpu", compute_type="int8",
                                  download_root=str(CKPTS / "whisper"), cpu_threads=max(2, (os.cpu_count() or 4) // 2))
        return _model


def _load(path: str) -> tuple[np.ndarray, int]:
    import librosa
    audio, rate = librosa.load(path, sr=16000, mono=True)
    return audio, rate


def _transcribe(audio: np.ndarray, language: str) -> str:
    code = language if re.fullmatch(r"[a-z]{2}", language or "") else None
    segments, _info = _whisper().transcribe(audio, language=code, beam_size=1)
    return " ".join(segment.text.strip() for segment in segments).strip()


def _median_pitch(audio: np.ndarray, rate: int) -> float | None:
    import librosa
    f0, voiced, _ = librosa.pyin(audio, fmin=60, fmax=400, sr=rate, frame_length=1024)
    values = f0[voiced & ~np.isnan(f0)] if f0 is not None else np.array([])
    return round(float(np.median(values)), 1) if len(values) else None


def _edges(audio: np.ndarray, rate: int) -> tuple[float, float]:
    loud = np.nonzero(np.abs(audio) > 0.01)[0]
    if not len(loud):
        return 0.0, 0.0
    return round(loud[0] / rate, 2), round((len(audio) - loud[-1]) / rate, 2)


def _warnings(result: dict[str, Any], pitch_range: list[float] | None) -> list[str]:
    found = []
    if result["wer"] > result["wer_threshold"]:
        found.append(f"The transcript differs from the text (word error rate {result['wer']:.2f})")
    pitch = result["medianPitchHz"]
    if pitch_range and pitch is not None and not pitch_range[0] <= pitch <= pitch_range[1]:
        found.append(f"Median pitch {pitch:.0f} Hz is outside {pitch_range[0]:.0f}–{pitch_range[1]:.0f} Hz")
    if not PACE_RANGE[0] <= result["wordsPerSecond"] <= PACE_RANGE[1]:
        found.append(f"Pace {result['wordsPerSecond']:.1f} words/s is outside {PACE_RANGE[0]}–{PACE_RANGE[1]}")
    if max(result["leadSilence"], result["trailSilence"]) > MAX_EDGE_SILENCE:
        found.append("More than 0.6 s of silence at the start or end")
    return found


def _compared(text: str, transcript: str, code: str, names: list[str] | None) -> tuple[float, float, float]:
    """``(wer, wer_raw, wer_threshold)``. Spanish compares sounds and proper names."""
    raw = word_error_rate(text, transcript, code or "en")
    spanish = code == "es"
    if not spanish:
        return raw, raw, MAX_WER
    reference = words(text, "es")
    heard = words(transcript, "es")
    wer = token_error_rate(merge_names(reference, names), merge_names(heard, names))
    return wer, raw, wer_threshold(len(reference), spanish=True, floor=MAX_WER)


def measure_speech(path: str, text: str, language: str = "", *, pitch_range: list[float] | None = None,
                   names: list[str] | None = None, load: Callable = _load, transcribe: Callable = _transcribe,
                   pitch: Callable = _median_pitch) -> dict[str, Any]:
    """Transcript, word error rate, median pitch, pace and edge silence for one take."""
    # No language: the expected text tells es/en, so numbers are spelled and heard in that language.
    code = str(spoken_language_code(language or "", text) or "").split("-")[0].lower()
    audio, rate = load(path)
    duration = len(audio) / rate
    lead, trail = _edges(audio, rate)
    transcript = transcribe(audio, code)
    spoken = max(0.1, duration - lead - trail)
    wer, raw, threshold = _compared(text, transcript, code, names)
    result = {
        "transcript": transcript, "wer": round(wer, 3), "wer_raw": round(raw, 3),
        "wer_threshold": round(threshold, 3),
        "medianPitchHz": pitch(audio, rate), "duration": round(duration, 2),
        "wordsPerSecond": round(len(words(text, code or "en")) / spoken, 2),
        "leadSilence": lead, "trailSilence": trail,
    }
    result["warnings"] = _warnings(result, pitch_range)
    notice = pitch_notice(result["medianPitchHz"], pitch_range)
    if notice:
        result["pitch_out_of_range"] = notice
    return result


def command_catalog() -> list[dict[str, Any]]:
    return [{
        "name": OPERATION,
        "mutation": False,
        "description": ("Check a spoken take against its text without listening: Whisper transcript, word error rate "
                        "(numbers and percentages compared spelled out), median pitch in Hz, words per second and silence "
                        "at both ends, plus warnings. Spanish equates b/v, seseo and close proper names and raises "
                        "wer_threshold for up to four words; wer_raw keeps the older count. names lists people, places "
                        "and pronunciation keys. file is a workspace audio file; language a code or label "
                        "(es, English, Español). pitch_range [min, max] Hz warns when the median falls outside, for "
                        "example [85, 165] for a low male voice. CPU lane; measures only, never blocks."),
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "input"], "properties": {
            "version": {"type": "integer", "const": 1},
            "input": {"type": "object", "additionalProperties": False, "required": ["workspace", "file", "text"], "properties": {
                "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
                "file": {"type": "string", "minLength": 1, "maxLength": 300},
                "text": {"type": "string", "minLength": 1, "maxLength": 4000},
                "language": {"type": "string", "maxLength": 40},
                "names": {"type": "array", "maxItems": 80, "items": {"type": "string", "minLength": 1, "maxLength": 80}},
                "pitch_range": {"type": "array", "minItems": 2, "maxItems": 2,
                                "items": {"type": "number", "minimum": 40, "maximum": 600}},
            }},
        }},
    }]


def _name_list(value: Any) -> list[str]:
    from fastapi import HTTPException
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise HTTPException(422, {"code": "invalid_command", "message": "names must be a list of strings", "retryable": False})
    return [item.strip() for item in value]


def _workspace_file(root: Path, name: str) -> Path:
    from fastapi import HTTPException
    name = re.sub(r"^/api/v1/file/", "", name.split("?")[0])
    path = (root / name).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, {"code": "file_not_found", "message": f"{name} is not a workspace file", "retryable": False})
    return path


def command_handlers(workspace_dir: Callable[[str], str]) -> dict[str, Callable[[Any], Any]]:
    async def handle(arguments: Any) -> dict[str, Any]:
        import uuid
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool
        from services import resource_scheduler
        data = (arguments or {}).get("input") if isinstance(arguments, dict) else None
        if not isinstance(data, dict) or not all(isinstance(data.get(key), str) for key in ("workspace", "file", "text")):
            raise HTTPException(422, {"code": "invalid_command", "message": "Use version 1 with input.workspace, file and text", "retryable": False})
        path = _workspace_file(Path(workspace_dir(data["workspace"])).resolve(), data["file"])
        pitch_range = data.get("pitch_range") if isinstance(data.get("pitch_range"), list) else None
        names = _name_list(data.get("names")) if "names" in data else None

        def run() -> dict[str, Any]:
            with resource_scheduler.coordinator.acquire(resource_scheduler.cpu_lane("audio-analysis"),
                                                        task_id=f"speech-qa-{uuid.uuid4().hex}", description="Speech check"):
                return measure_speech(str(path), data["text"], str(data.get("language") or ""),
                                      pitch_range=pitch_range, names=names)
        return {"version": 1, "status": "completed", "operation": OPERATION, "result": await run_in_threadpool(run)}

    return {OPERATION: handle}

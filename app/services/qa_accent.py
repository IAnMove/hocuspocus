"""Measure Castilian θ on a spoken take. The result warns; it never blocks.

Phonemes come from the wav2vec2 model in ``phoneme_runtime`` (the same weights
the lip-sync uses). Recognition is free, not forced onto the script: a forced
alignment would label the expected phonemes and hide a seseo. The transcript
pass is used only for times: each θ letter is timed by its own phone there, and
the θ or s heard at that time is what counts. θ is in that model's vocabulary.
Words with ``z`` or ``c`` before e/i are the positions.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

OPERATION = "qa.accent"
MIN_POSITIONS = 3
_WORD = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


def _fold(word: str) -> str:
    text = unicodedata.normalize("NFKD", str(word or "").lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def theta_sites(text: str) -> list[str]:
    """Each ``z``, and each ``c`` before e or i, in reading order. The word is repeated per site."""
    sites: list[str] = []
    for match in _WORD.finditer(str(text or "")):
        folded = _fold(match.group(0))
        for index, char in enumerate(folded):
            nxt = folded[index + 1] if index + 1 < len(folded) else ""
            if char == "z" or (char == "c" and nxt in "ei"):
                sites.append(match.group(0))
    return sites


def _kind(phoneme: Any) -> str:
    text = unicodedata.normalize("NFKD", str(phoneme or "")).strip().lower()
    if "θ" in text or text == "th":
        return "theta"
    if text == "s":
        return "s"
    return ""


def _tagged(phonemes: list) -> list[tuple[str, str]]:
    heard: list[tuple[str, str]] = []
    for item in phonemes or []:
        if not isinstance(item, dict):
            continue
        kind = _kind(item.get("phoneme"))
        word = item.get("word")
        if kind:
            heard.append((kind, word if isinstance(word, str) else ""))
    return heard


def _counted(sites: list[str], heard: list[tuple[str, str]]) -> list[str]:
    """Heard θ or s lined up with the orthographic sites. Untagged audio is taken in order."""
    if any(word.strip() for _kind_name, word in heard):
        queues: dict[str, list[str]] = defaultdict(list)
        for kind, word in heard:
            if word.strip():
                queues[_fold(word)].append(kind)
        counted = []
        for site in sites:
            queue = queues.get(_fold(site))
            if queue:
                counted.append(queue.pop(0))
        return counted
    kinds = [kind for kind, _word in heard]
    return kinds[:len(sites)]


def _seconds(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _word_runs(aligned: list) -> list[tuple[str, list[dict]]]:
    """``(word, phones)`` for each run of forced-alignment phones of one word."""
    runs: list[tuple[str, list[dict]]] = []
    previous = None
    for phone in aligned or []:
        word = phone.get("word") if isinstance(phone, dict) else None
        if not isinstance(word, str) or not word.strip():
            previous = None
            continue
        if word != previous:
            runs.append((word, []))
        runs[-1][1].append(phone)
        previous = word
    return runs


def _sibilant_letters(word: str) -> list[bool]:
    """Each s, x, z and c before e/i of a word in reading order; True where it spells θ.

    Castilian eSpeak says each of them with one s or θ phone (x is k s), so these
    line up one to one with the word's sibilant phones in the forced alignment.
    """
    folded = _fold(word)
    letters: list[bool] = []
    for index, char in enumerate(folded):
        nxt = folded[index + 1] if index + 1 < len(folded) else ""
        theta = char == "z" or (char == "c" and nxt in "ei")
        if theta or char in "sx":
            letters.append(theta)
    return letters


def _heard_over(heard: list, start: float, end: float) -> str:
    """The θ or s heard longest between ``start`` and ``end``, or "" when none overlaps."""
    found, longest = "", 0.0
    for phone in heard or []:
        if not isinstance(phone, dict):
            continue
        kind = _kind(phone.get("phoneme"))
        begin = _seconds(phone.get("start"))
        overlap = min(_seconds(phone.get("end"), begin), end) - max(begin, start)
        if kind and overlap > longest:
            found, longest = kind, overlap
    return found


def _theta_phones(word: str, phones: list[dict]) -> list[dict]:
    """The forced phones of the word's θ letters, or [] when its sibilant phones do not line up with its letters."""
    letters = _sibilant_letters(word)
    sibilants = [phone for phone in phones if _kind(phone.get("phoneme"))]
    if [_kind(phone.get("phoneme")) == "theta" for phone in sibilants] != letters:
        return []
    return [phone for phone, theta in zip(sibilants, letters) if theta]


def tag_sites(text: str, heard: list | None, aligned: list | None) -> list[dict[str, str]]:
    """One heard θ or s per θ letter, timed by that letter's own phone in the forced alignment.

    The s of «es» in «estación» is not taken for the θ of «ción». A word whose
    sibilant phones do not line up with its letters is left out, so it is not counted.
    """
    wanted = {_fold(site) for site in theta_sites(text)}
    tagged: list[dict[str, str]] = []
    for word, phones in _word_runs(aligned or []):
        if _fold(word) not in wanted:
            continue
        for phone in _theta_phones(word, phones):
            start = _seconds(phone.get("start"))
            kind = _heard_over(heard or [], start, _seconds(phone.get("end"), start))
            if kind:
                tagged.append({"phoneme": "θ" if kind == "theta" else "s", "word": word})
    return tagged


def score_accent(text: str, phonemes: list | None) -> dict[str, Any]:
    """``{thetaRate, positions, verdict}``. ``unknown`` below three matched positions."""
    counted = _counted(theta_sites(text), _tagged(phonemes or []))
    positions = len(counted)
    rate = round(counted.count("theta") / positions, 3) if positions else None
    if positions < MIN_POSITIONS:
        verdict = "unknown"
    elif rate is not None and rate >= 0.5:
        verdict = "castilian"
    else:
        verdict = "seseo"
    return {"thetaRate": rate, "positions": positions, "verdict": verdict}


def measure_accent(path: str, text: str, *, decode: Callable[[bytes, str], list]) -> dict[str, Any]:
    """Score a workspace take. ``decode`` is injected in tests so the model stays unloaded.

    The phoneme model reads only mono 16 kHz PCM WAV and render takes are 44.1 kHz,
    so the take is converted first, as ``audio.mouth_cues`` does.
    """
    from services.speech_file_commands import _probe_duration, _window_wav
    return score_accent(text, decode(_window_wav(path, 0, _probe_duration(path)), text))


def _phones(payload: Any) -> list:
    phones = payload.get("phonemes") if isinstance(payload, dict) else None
    return phones if isinstance(phones, list) else []


def _recognize(data: bytes, text: str) -> list:
    """Heard θ and s at each site. The transcript supplies word times only."""
    from services.phoneme_analysis import analyze_voice
    heard = analyze_voice(data, dialogue="", language="es")
    aligned = analyze_voice(data, dialogue=text, language="es")
    return tag_sites(text, _phones(heard), _phones(aligned))


def command_catalog() -> list[dict[str, Any]]:
    return [{
        "name": OPERATION,
        "mutation": False,
        "description": ("Count Castilian θ against s on a spoken take. Words with z, or c before e/i, are the "
                        "positions. The wav2vec2 phoneme model recognizes what was said (it is not forced onto the "
                        "text). Returns thetaRate, positions and verdict castilian, seseo or unknown. unknown when "
                        "fewer than 3 positions matched. accent is castilian. CPU only; a warning, never a block."),
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "input"], "properties": {
            "version": {"type": "integer", "const": 1},
            "input": {"type": "object", "additionalProperties": False,
                      "required": ["workspace", "file", "text", "accent"], "properties": {
                "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
                "file": {"type": "string", "minLength": 1, "maxLength": 300},
                "text": {"type": "string", "minLength": 1, "maxLength": 4000},
                "accent": {"type": "string", "const": "castilian"},
            }},
        }},
    }]


def command_handlers(workspace_dir: Callable[[str], str], decode: Callable[[bytes, str], list] | None = None) -> dict[str, Callable]:
    """MCP ``qa.accent``. Pass ``decode`` in tests; the default loads the phoneme model on the CPU lane."""
    recognize = decode or _recognize

    async def handle(arguments: Any) -> dict[str, Any]:
        import subprocess
        import uuid
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool
        from services import resource_scheduler
        from services.scene3d_speech import SpeechAnalysisUnavailable
        from services.speech_qa import _workspace_file
        data = (arguments or {}).get("input") if isinstance(arguments, dict) else None
        if not isinstance(data, dict) or not all(isinstance(data.get(key), str) and data.get(key) for key in ("workspace", "file", "text")):
            raise HTTPException(422, {"code": "invalid_command", "message": "Use version 1 with input.workspace, file, text and accent", "retryable": False})
        if data.get("accent") != "castilian":
            raise HTTPException(422, {"code": "invalid_command", "message": "accent must be castilian", "retryable": False})
        path = _workspace_file(Path(workspace_dir(data["workspace"])).resolve(), data["file"])

        def run() -> dict[str, Any]:
            with resource_scheduler.coordinator.acquire(resource_scheduler.cpu_lane("audio-analysis"),
                                                        task_id=f"accent-qa-{uuid.uuid4().hex}", description="Accent check"):
                return measure_accent(str(path), data["text"], decode=recognize)
        # A take that cannot be decoded or analyzed is a tool error, which a render reads as no warning.
        try:
            result = await run_in_threadpool(run)
        except SpeechAnalysisUnavailable as exc:
            raise HTTPException(503, {"code": "speech_unavailable", "message": str(exc), "retryable": True}) from exc
        except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            raise HTTPException(422, {"code": "accent_analysis_failed", "message": f"The take could not be analyzed: {exc}"[:300],
                                      "retryable": False}) from exc
        return {"version": 1, "status": "completed", "operation": OPERATION, "result": result}

    return {OPERATION: handle}

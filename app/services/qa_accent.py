"""Measure Castilian θ on a spoken take. The result warns; it never blocks.

Phonemes come from the wav2vec2 model in ``phoneme_runtime`` (the same weights
the lip-sync uses). Recognition is free, not forced onto the script: a forced
alignment would label the expected phonemes and hide a seseo. The transcript
pass is used only for word times. θ and s heard inside each word are what count.
θ is in that model's vocabulary. Words with ``z`` or ``c`` before e/i are the
positions.
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


def _word_spans(aligned: list) -> list[tuple[str, float, float]]:
    """One ``(word, start, end)`` for each run of forced-alignment phones."""
    spans: list[tuple[str, float, float]] = []
    phones = [item for item in aligned or [] if isinstance(item, dict)]
    index = 0
    while index < len(phones):
        word = phones[index].get("word")
        if not isinstance(word, str) or not word.strip():
            index += 1
            continue
        start = _seconds(phones[index].get("start"))
        end = _seconds(phones[index].get("end"), start)
        index += 1
        while index < len(phones) and phones[index].get("word") == word:
            end = _seconds(phones[index].get("end"), end)
            index += 1
        spans.append((word, start, end))
    return spans


def _sibilants_between(heard: list, start: float, end: float) -> list[str]:
    found: list[str] = []
    for phone in heard or []:
        if not isinstance(phone, dict):
            continue
        kind = _kind(phone.get("phoneme"))
        if not kind:
            continue
        begin = _seconds(phone.get("start"))
        finish = _seconds(phone.get("end"), begin)
        if finish > start and begin < end:
            found.append(kind)
    return found


def tag_sites(text: str, heard: list | None, aligned: list | None) -> list[dict[str, str]]:
    """One heard θ or s per orthographic site, timed by the forced word span.

    An ``s`` in a word that has no ``z`` or ``c`` + e/i is ignored. A second ``z``
    in the same word takes the next sibilant inside that word.
    """
    sites = theta_sites(text)
    tagged: list[dict[str, str]] = []
    cursor = 0
    for word, start, end in _word_spans(aligned or []):
        folded = _fold(word)
        count = 0
        while cursor + count < len(sites) and _fold(sites[cursor + count]) == folded:
            count += 1
        if not count:
            continue
        kinds = _sibilants_between(heard or [], start, end)
        for offset, site in enumerate(sites[cursor:cursor + count]):
            if offset >= len(kinds):
                break
            tagged.append({"phoneme": "θ" if kinds[offset] == "theta" else "s", "word": site})
        cursor += count
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
    """Read a workspace take and score it. ``decode`` is injected in tests so the model stays unloaded."""
    return score_accent(text, decode(Path(path).read_bytes(), text))


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
        import uuid
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool
        from services import resource_scheduler
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
        return {"version": 1, "status": "completed", "operation": OPERATION, "result": await run_in_threadpool(run)}

    return {OPERATION: handle}

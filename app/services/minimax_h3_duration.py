"""Mandatory dialogue-to-duration contract for every MiniMax H3 clip."""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, MutableMapping


_DIALOGUE_BLOCK = re.compile(
    r"<d>\s*\[([^\]\r\n]+)\]\s*(.*?)\s*</d>",
    flags=re.IGNORECASE | re.DOTALL,
)
_PLAIN_SPEECH = re.compile(
    r"\b(?:says?|asks?|shouts?|whispers?|replies|dice|pregunta|grita|susurra|responde)"
    r"(?:\s+exactly)?\s*[:,]?\s*[\"“«](.*?)[\"”»]",
    flags=re.IGNORECASE | re.DOTALL,
)
_WORD = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*", flags=re.UNICODE)


def extract_h3_dialogue(prompt: Any) -> list[dict[str, str]]:
    """Return authored spoken segments without treating visible quoted text as speech."""

    text = str(prompt or "")
    tagged = [
        {"language": match.group(1).strip(), "text": match.group(2).strip()}
        for match in _DIALOGUE_BLOCK.finditer(text)
        if match.group(2).strip()
    ]
    if tagged:
        return tagged
    return [
        {"language": "", "text": match.group(1).strip()}
        for match in _PLAIN_SPEECH.finditer(text)
        if match.group(1).strip()
    ]


def estimate_h3_dialogue_seconds(
    segments: list[Mapping[str, str]],
    *,
    words_per_second: float = 2.1,
) -> dict[str, float | int]:
    """Estimate complete spoken time, including punctuation and safe edge room."""

    cleaned = [str(segment.get("text") or "").strip() for segment in segments]
    cleaned = [text for text in cleaned if text]
    word_count = sum(len(_WORD.findall(text)) for text in cleaned)
    comma_pauses = sum(len(re.findall(r"[,;:]", text)) for text in cleaned) * 0.12
    terminal_pauses = sum(len(re.findall(r"(?<!\.)[.!?](?!\.)", text)) for text in cleaned) * 0.22
    ellipsis_pauses = sum(len(re.findall(r"(?:\.{3}|…)", text)) for text in cleaned) * 0.38
    speaker_gaps = max(0, len(cleaned) - 1) * 0.20
    edge_room = 0.70 if cleaned else 0.0
    speech_seconds = word_count / max(0.1, float(words_per_second))
    total = speech_seconds + comma_pauses + terminal_pauses + ellipsis_pauses + speaker_gaps + edge_room
    return {
        "word_count": word_count,
        "segment_count": len(cleaned),
        "spoken_seconds": round(speech_seconds, 3),
        "estimated_seconds": round(max(0.0, total), 3),
    }


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _align_up(frames: int, modulus: int, remainder: int) -> int:
    if modulus <= 1:
        return frames
    if frames <= remainder:
        return remainder
    return remainder + math.ceil((frames - remainder) / modulus) * modulus


def apply_h3_dialogue_duration(
    params: MutableMapping[str, Any],
    model_def: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Replace an H3 job's clip length with its calculated dialogue length.

    The H3 frame lattice and minimum are physical model constraints. The
    contract therefore rounds upward and records when that minimum leaves
    unavoidable edge room, instead of pretending an unsupported duration was
    requested.
    """

    existing = params.get("_h3_dialogue_duration_contract")
    if (
        isinstance(existing, dict)
        and existing.get("effective_frames") == params.get("video_length")
    ):
        return existing

    segments = extract_h3_dialogue(params.get("prompt"))
    if not segments:
        params.pop("_h3_dialogue_duration_contract", None)
        return None

    definition = model_def if isinstance(model_def, Mapping) else {}
    fps = float(definition.get("fps") or 24.0)
    minimum = _positive_int(definition.get("frames_minimum"), 124)
    maximum = _positive_int(definition.get("frames_maximum"), 345)
    modulus = _positive_int(
        definition.get("frame_alignment_modulus") or definition.get("frames_steps"),
        17,
    )
    try:
        remainder = int(definition.get("frame_alignment_remainder", 5))
    except (TypeError, ValueError):
        remainder = 5

    estimate = estimate_h3_dialogue_seconds(segments)
    raw_frames = max(1, math.ceil(float(estimate["estimated_seconds"]) * fps))
    aligned_frames = _align_up(raw_frames, modulus, remainder)
    effective_frames = max(minimum, min(maximum, aligned_frames))
    effective_seconds = round(effective_frames / fps, 3)
    requested_before = params.get("video_length")
    overflow = aligned_frames > maximum
    minimum_limited = aligned_frames < minimum

    contract: dict[str, Any] = {
        **estimate,
        "fps": fps,
        "requested_frames_before": requested_before,
        "calculated_frames": aligned_frames,
        "effective_frames": effective_frames,
        "effective_seconds": effective_seconds,
        "minimum_limited": minimum_limited,
        "requires_split": overflow,
        "model_minimum_frames": minimum,
        "model_maximum_frames": maximum,
        "frame_lattice": f"{modulus}n+{remainder}",
    }
    params["video_length"] = effective_frames
    params["duration_seconds"] = effective_seconds
    params["_duration_seconds"] = effective_seconds
    params["_h3_dialogue_duration_contract"] = contract
    return contract


def h3_dialogue_split_error(contract: Mapping[str, Any]) -> str:
    return (
        f"MiniMax H3 dialogue needs about {contract.get('estimated_seconds')} seconds "
        f"for {contract.get('word_count')} words, beyond this model's "
        f"{contract.get('effective_seconds')}-second single-clip limit. "
        "Split the dialogue across multiple clips; it will not be truncated."
    )

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
_VOCAL_TIMELINE_BLOCK = re.compile(
    r"\s*VOCAL TIMELINE LOCK:\s*.*?"
    r"(?=\s+(?:overall_soundscape|non_diegetic_music)\s*:|$)",
    flags=re.IGNORECASE | re.DOTALL,
)
_SOUND_FIELD = re.compile(
    r"\b(?:overall_soundscape|non_diegetic_music)\s*:",
    flags=re.IGNORECASE,
)
_WORD = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*", flags=re.UNICODE)
_SPANISH_LANGUAGES = {"castilian", "es", "es-es", "español", "spanish"}
_SPANISH_VOWEL_RUN = re.compile(r"[aeiouáéíóúü]+", flags=re.IGNORECASE)
_GENERIC_VOWEL_RUN = re.compile(
    r"[aeiouyáéíóúüàèìòùâêîôûäëïöü]+",
    flags=re.IGNORECASE,
)
_SPANISH_STRONG_VOWELS = frozenset("aeoáéóíú")
_SPANISH_STRESSED_WEAK_VOWELS = frozenset("íú")
DEFAULT_SECONDS_PER_SYLLABLE = 0.22


def _h3_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds or 0.0) * 1000)))
    minutes, remainder = divmod(milliseconds, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{whole_seconds:02d}.{millis:03d}"


def _ordinal_line(index: int) -> str:
    words = (
        "first", "second", "third", "fourth", "fifth", "sixth",
        "seventh", "eighth", "ninth", "tenth",
    )
    return words[index] if index < len(words) else f"number {index + 1}"


def _spanish_word_syllables(word: str) -> int:
    normalized = word.casefold()
    # In que/qui and gue/gui, an unmarked "u" is orthographic rather than
    # spoken. The diaeresis in güe/güi deliberately remains vocalic.
    normalized = re.sub(r"(?<=[gq])u(?=[eiéí])", "", normalized)
    runs = _SPANISH_VOWEL_RUN.findall(normalized)
    if not runs:
        return 1

    count = 0
    for run in runs:
        count += 1
        for left, right in zip(run, run[1:]):
            hiatus = (
                left in _SPANISH_STRESSED_WEAK_VOWELS
                or right in _SPANISH_STRESSED_WEAK_VOWELS
                or (
                    left in _SPANISH_STRONG_VOWELS
                    and right in _SPANISH_STRONG_VOWELS
                )
            )
            if hiatus:
                count += 1
    return count


def count_spoken_syllables(text: Any, language: Any = "") -> int:
    """Count spoken syllables, with Castilian-aware diphthong handling."""

    words = _WORD.findall(str(text or ""))
    language_key = str(language or "").strip().casefold()
    is_spanish = (
        language_key in _SPANISH_LANGUAGES
        or language_key.startswith("es-")
        or "spanish" in language_key
        or "español" in language_key
        or "castilian" in language_key
    )
    if is_spanish:
        return sum(_spanish_word_syllables(word) for word in words)

    # Other H3 languages use a conservative vowel-nucleus fallback. Keeping
    # this centralized means a language-specific counter can replace it later
    # without allowing any generation path to bypass the duration contract.
    return sum(max(1, len(_GENERIC_VOWEL_RUN.findall(word))) for word in words)


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
    seconds_per_syllable: float = DEFAULT_SECONDS_PER_SYLLABLE,
) -> dict[str, float | int]:
    """Estimate speech from syllables, plus authored pauses and small edge room."""

    cleaned = [
        segment
        for segment in segments
        if str(segment.get("text") or "").strip()
    ]
    texts = [str(segment.get("text") or "").strip() for segment in cleaned]
    word_count = sum(len(_WORD.findall(text)) for text in texts)
    syllable_count = sum(
        count_spoken_syllables(
            segment.get("text"),
            segment.get("language"),
        )
        for segment in cleaned
    )
    comma_pauses = sum(len(re.findall(r"[,;:]", text)) for text in texts) * 0.12
    terminal_pauses = sum(len(re.findall(r"(?<!\.)[.!?](?!\.)", text)) for text in texts) * 0.18
    ellipsis_pauses = sum(len(re.findall(r"(?:\.{3}|…)", text)) for text in texts) * 0.32
    speaker_gaps = max(0, len(texts) - 1) * 0.15
    edge_room = 0.35 if texts else 0.0
    syllable_seconds = max(0.01, float(seconds_per_syllable))
    speech_seconds = syllable_count * syllable_seconds
    total = speech_seconds + comma_pauses + terminal_pauses + ellipsis_pauses + speaker_gaps + edge_room
    return {
        "word_count": word_count,
        "syllable_count": syllable_count,
        "seconds_per_syllable": round(syllable_seconds, 3),
        "segment_count": len(texts),
        "spoken_seconds": round(speech_seconds, 3),
        "estimated_seconds": round(max(0.0, total), 3),
    }


def plan_h3_vocal_timeline(
    segments: list[Mapping[str, str]],
    duration_seconds: float,
    *,
    mapped_driving_audio: bool = False,
) -> dict[str, Any]:
    """Allocate every H3 second to authored speech or explicit silence.

    H3's native minimum can leave several seconds around a short line.  A
    generic "do not improvise" instruction does not tell the audiovisual model
    what occupies that time, so it may extend the vocal texture with invented
    syllables.  This deterministic schedule gives each authored line a bounded
    local interval and assigns all remaining time to closed-mouth action,
    ambience, and physical effects.
    """

    duration = round(max(0.0, float(duration_seconds or 0.0)), 3)
    cleaned = [
        {
            "language": str(segment.get("language") or "").strip(),
            "text": str(segment.get("text") or "").strip(),
        }
        for segment in segments
        if str(segment.get("text") or "").strip()
    ]
    if duration <= 0:
        return {
            "duration_seconds": duration,
            "segment_count": len(cleaned),
            "estimated_dialogue_seconds": 0.0,
            "intervals": [],
            "text": "",
        }

    end_stamp = _h3_timestamp(duration)
    if not cleaned:
        if mapped_driving_audio:
            text = (
                f"From 00:00.000 to {end_stamp}, audible voice or vocals come "
                "only from the mapped driving audio and remain synchronized to "
                "it; H3 generates no additional dialogue, muttering, gibberish, "
                "or speech-like vocalization."
            )
            kind = "mapped_audio"
        else:
            text = (
                f"From 00:00.000 to {end_stamp}, all characters remain silent "
                "with mouths closed while only the described ambience, physical "
                "actions, and non-verbal sounds continue; no voice, muttering, "
                "gibberish, or speech-like vocalization occurs."
            )
            kind = "silence"
        return {
            "duration_seconds": duration,
            "segment_count": 0,
            "estimated_dialogue_seconds": 0.0,
            "intervals": [{
                "kind": kind,
                "start_seconds": 0.0,
                "end_seconds": duration,
            }],
            "text": text,
        }

    combined = estimate_h3_dialogue_seconds(cleaned)
    estimated = min(duration, float(combined["estimated_seconds"]))
    free_seconds = max(0.0, duration - estimated)
    if free_seconds >= 1.0:
        lead_silence = min(1.25, max(0.45, free_seconds * 0.35))
    else:
        lead_silence = free_seconds * 0.35
    tail_silence = max(0.0, free_seconds - lead_silence)

    gap_count = max(0, len(cleaned) - 1)
    interline_gap = min(0.15, estimated * 0.08 / max(1, gap_count)) if gap_count else 0.0
    dialogue_budget = max(0.0, estimated - interline_gap * gap_count)
    weights = [
        max(
            0.25,
            float(estimate_h3_dialogue_seconds([segment])["estimated_seconds"]),
        )
        for segment in cleaned
    ]
    weight_total = sum(weights) or float(len(weights))
    line_durations = [dialogue_budget * weight / weight_total for weight in weights]

    intervals: list[dict[str, Any]] = []
    sentences: list[str] = []
    cursor = 0.0

    def add_silence(start: float, end: float) -> None:
        if end - start < 0.025:
            return
        start = round(start, 3)
        end = round(end, 3)
        intervals.append({
            "kind": "silence",
            "start_seconds": start,
            "end_seconds": end,
        })
        sentences.append(
            f"From {_h3_timestamp(start)} to {_h3_timestamp(end)}, all "
            "characters remain silent with mouths closed while only the "
            "described ambience, physical actions, and non-verbal sounds continue."
        )

    add_silence(cursor, lead_silence)
    cursor = lead_silence
    for index, line_duration in enumerate(line_durations):
        start = round(cursor, 3)
        end = round(min(duration, cursor + line_duration), 3)
        intervals.append({
            "kind": "dialogue",
            "line": index + 1,
            "start_seconds": start,
            "end_seconds": end,
        })
        sentences.append(
            f"From {_h3_timestamp(start)} to {_h3_timestamp(end)}, the "
            f"{_ordinal_line(index)} tagged line is spoken exactly once by its "
            "assigned speaker; every other character remains silent with their "
            "mouth closed."
        )
        cursor = end
        if index < len(line_durations) - 1:
            next_start = min(duration, cursor + interline_gap)
            add_silence(cursor, next_start)
            cursor = next_start

    # Use the exact physical clip boundary for the final closed-mouth interval;
    # rounding the per-line schedule must never leave an undescribed tail.
    add_silence(cursor, duration)
    sentences.append(
        "Outside the assigned dialogue intervals, no tagged line starts, "
        "continues, repeats, or is replaced by other speech, muttering, "
        "gibberish, background voices, or speech-like vocalization."
    )
    return {
        "duration_seconds": duration,
        "segment_count": len(cleaned),
        "estimated_dialogue_seconds": round(estimated, 3),
        "leading_silence_seconds": round(lead_silence, 3),
        "trailing_silence_seconds": round(tail_silence, 3),
        "intervals": intervals,
        "text": " ".join(sentences),
    }


def inject_h3_vocal_timeline(prompt: Any, duration_seconds: float) -> tuple[str, dict[str, Any]]:
    """Insert one idempotent vocal schedule before H3's sound fields."""

    source = str(prompt or "").strip()
    if not source or float(duration_seconds or 0.0) <= 0:
        return source, {}
    clean = _VOCAL_TIMELINE_BLOCK.sub(" ", source).strip()
    segments = extract_h3_dialogue(clean)
    mapped_driving_audio = not segments and "mapped driving audio" in clean.casefold()
    explicit_silence = bool(re.search(
        r"\b(?:no (?:one|character) speaks|all (?:visible )?(?:people|characters) "
        r"remain silent|everyone remains silent)\b",
        clean,
        flags=re.IGNORECASE,
    ))
    # Do not reinterpret an unstructured Studio prompt such as "a woman
    # sings" as silence merely because it contains no canonical <d> block.
    # Director and the window planner already emit an explicit silence
    # contract whenever no vocal performance is authored.
    if not segments and not mapped_driving_audio and not explicit_silence:
        return clean, {}
    timeline = plan_h3_vocal_timeline(
        segments,
        duration_seconds,
        mapped_driving_audio=mapped_driving_audio,
    )
    # Keep the schedule as metadata only. Writing "remain silent" / "spoken
    # exactly once" into the picture description makes H3 say those notes.
    return re.sub(r"[ \t]+", " ", clean).strip(), timeline


def apply_h3_vocal_timeline(
    params: MutableMapping[str, Any],
    model_def: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Bind a generation job's final prompt to its effective H3 duration."""

    definition = model_def if isinstance(model_def, Mapping) else {}
    fps = float(definition.get("fps") or 24.0)
    try:
        duration = float(
            params.get("duration_seconds")
            or params.get("_duration_seconds")
            or float(params.get("video_length") or 0) / max(0.1, fps)
        )
    except (TypeError, ValueError):
        return None
    if duration <= 0 or not str(params.get("prompt") or "").strip():
        return None
    prompt, contract = inject_h3_vocal_timeline(params.get("prompt"), duration)
    params["prompt"] = prompt
    if contract:
        params["_h3_vocal_timeline_contract"] = contract
        return contract
    params.pop("_h3_vocal_timeline_contract", None)
    return None


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
        f"for {contract.get('syllable_count')} syllables, beyond this model's "
        f"{contract.get('effective_seconds')}-second single-clip limit. "
        "Split the dialogue across multiple clips; it will not be truncated."
    )

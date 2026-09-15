"""Literal lyric alignment and source-audio visual timing."""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


@dataclass
class LyricWord:
    start: float
    end: float
    text: str


@dataclass
class LyricSegment:
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    words: Optional[list[LyricWord]] = None
    source: str = "transcription"
    confidence: Optional[float] = None
    section: Optional[str] = None


def normalise_token(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return "".join(ch for ch in value if ch.isalnum())


def authoritative_lines(lyrics: str) -> list[dict]:
    """Parse editable lyrics without changing their literal line text."""
    lines: list[dict] = []
    section = ""
    for raw in str(lyrics or "").splitlines():
        text = raw.strip()
        if not text:
            continue
        tag = re.fullmatch(r"\[([^\]]+)\]", text)
        if tag:
            section = tag.group(1).strip()
            continue
        tokens = []
        for token in re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text, flags=re.UNICODE):
            normalized = normalise_token(token)
            if normalized:
                tokens.append({"text": token, "normalized": normalized})
        if tokens:
            lines.append({"text": text, "section": section, "tokens": tokens})
    return lines


def has_authoritative_lyrics(lyrics: str) -> bool:
    return bool(authoritative_lines(lyrics))


def _flatten_words(transcript: list[LyricSegment]) -> list[LyricWord]:
    words: list[LyricWord] = []
    for segment in transcript:
        if segment.words:
            words.extend(segment.words)
            continue
        raw = segment.text.split()
        if not raw:
            continue
        duration = max(0.001, segment.end - segment.start)
        for index, token in enumerate(raw):
            words.append(LyricWord(
                start=segment.start + duration * index / len(raw),
                end=segment.start + duration * (index + 1) / len(raw),
                text=token,
            ))
    return words


def _similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    if left[0] != right[0] or abs(len(left) - len(right)) > 2:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _global_word_matches(authored: list[str], heard: list[str]) -> dict[int, tuple[int, float]]:
    """Return monotonic authored-index to heard-index matches."""
    n, m = len(authored), len(heard)
    previous = [-0.65 * j for j in range(m + 1)]
    trace = [bytearray(m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        current = [-1.0 * i] + [0.0] * m
        trace[i][0] = 2
        for j in range(1, m + 1):
            similarity = _similarity(authored[i - 1], heard[j - 1])
            match_score = 3.0 if similarity == 1.0 else (1.4 if similarity >= 0.78 else -2.2)
            choices = (
                (previous[j - 1] + match_score, 1),
                (previous[j] - 1.0, 2),
                (current[j - 1] - 0.65, 3),
            )
            current[j], trace[i][j] = max(choices, key=lambda item: item[0])
        previous = current

    matches: dict[int, tuple[int, float]] = {}
    i, j = n, m
    while i > 0 or j > 0:
        direction = trace[i][j]
        if direction == 1:
            similarity = _similarity(authored[i - 1], heard[j - 1])
            if similarity >= 0.78:
                matches[i - 1] = (j - 1, similarity)
            i -= 1
            j -= 1
        elif direction == 2 or j == 0:
            i -= 1
        else:
            j -= 1
    return matches


def _build_cues(
    lines: list[dict],
    audio_words: list[LyricWord],
    matches: dict[int, tuple[int, float]],
) -> list[LyricSegment]:
    timeline: list[LyricSegment] = []
    token_cursor = 0
    for line in lines:
        similarities = []
        aligned_words: list[LyricWord] = []
        for local_index, token in enumerate(line["tokens"]):
            match = matches.get(token_cursor + local_index)
            if not match:
                continue
            word_index, similarity = match
            evidence = audio_words[word_index]
            similarities.append(similarity)
            aligned_words.append(LyricWord(evidence.start, evidence.end, token["text"]))
        token_cursor += len(line["tokens"])
        if aligned_words:
            timeline.append(LyricSegment(
                start=round(aligned_words[0].start, 3),
                end=round(aligned_words[-1].end, 3),
                text=line["text"], words=aligned_words,
                source="aligned_lyrics",
                confidence=round(sum(similarities) / len(line["tokens"]), 3),
                section=line["section"] or None,
            ))
        else:
            timeline.append(LyricSegment(
                0.0, 0.0, line["text"], source="interpolated",
                confidence=0.0, section=line["section"] or None,
            ))
    return timeline


def _interpolate_missing_cues(timeline: list[LyricSegment], duration: float) -> None:
    index = 0
    while index < len(timeline):
        if timeline[index].end > timeline[index].start:
            index += 1
            continue
        run_start = index
        while index < len(timeline) and timeline[index].end <= timeline[index].start:
            index += 1
        run_end = index
        previous_end = timeline[run_start - 1].end if run_start else 0.0
        next_start = timeline[run_end].start if run_end < len(timeline) else duration
        count = run_end - run_start
        available = max(0.2 * count, next_start - previous_end)
        for position, cue_index in enumerate(range(run_start, run_end)):
            timeline[cue_index].start = round(previous_end + available * position / count, 3)
            timeline[cue_index].end = round(
                min(duration, previous_end + available * (position + 1) / count), 3
            )


def align_authoritative_lyrics(
    lyrics: str,
    transcript: list[LyricSegment],
    duration: float,
) -> tuple[list[LyricSegment], dict]:
    """Align literal lyric lines to audio-derived word boundaries."""
    lines = authoritative_lines(lyrics)
    audio_words = _flatten_words(transcript)
    authored_tokens = [token for line in lines for token in line["tokens"]]
    if not lines:
        return [], {"method": "none", "coverage": 0.0, "matched_words": 0, "total_words": 0}
    matches = _global_word_matches(
        [token["normalized"] for token in authored_tokens],
        [normalise_token(word.text) for word in audio_words],
    )
    timeline = _build_cues(lines, audio_words, matches)
    _interpolate_missing_cues(timeline, duration)
    matched_count = len(matches)
    return timeline, {
        "method": "authoritative_lyrics_word_alignment",
        "coverage": round(matched_count / max(1, len(authored_tokens)), 3),
        "matched_words": matched_count,
        "total_words": len(authored_tokens),
        "approximate_lines": sum(cue.source == "interpolated" for cue in timeline),
    }


def lyrics_to_srt(timeline: list[LyricSegment]) -> str:
    def stamp(seconds: float) -> str:
        milliseconds = max(0, round(seconds * 1000))
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        secs, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

    return "\n\n".join(
        f"{index}\n{stamp(cue.start)} --> {stamp(max(cue.end, cue.start + 0.1))}\n{cue.text}"
        for index, cue in enumerate(timeline, 1)
    ) + ("\n" if timeline else "")


def build_visual_events(timeline: list[LyricSegment]) -> list[dict]:
    patterns = {
        "entrance": ("entra", "entrado", "aparece", "llega", "vuelve", "enter", "appears", "arrives", "returns", "joins"),
        "transformation": ("transforma", "transform", "clona", "clone", "convierte", "becomes"),
        "impact": ("explota", "explosion", "estalla", "rayo", "lightning", "breaks", "rompe"),
    }
    events: list[dict] = []
    for cue_index, cue in enumerate(timeline):
        for word in cue.words or []:
            normalized = normalise_token(word.text)
            kind = next((name for name, triggers in patterns.items() if any(normalized.startswith(trigger) for trigger in triggers)), None)
            if kind:
                events.append({
                    "time": round(word.start, 3), "end": round(word.end, 3),
                    "kind": kind, "cue_index": cue_index, "lyric": cue.text,
                    "trigger": word.text,
                    "rule": "The visual action starts here; do not reveal its result earlier.",
                })
    return events


def build_timing_bundle(
    lyrics: str,
    transcript: list[LyricSegment],
    duration: float,
) -> dict:
    """Create one canonical timeline payload for the audio analyser."""
    warnings: list[str] = []
    if has_authoritative_lyrics(lyrics):
        timeline, timing = align_authoritative_lyrics(lyrics, transcript, duration)
        if timing["coverage"] < 0.7:
            warnings.append(
                "Written lyrics had low audio alignment coverage; approximate cues are marked in the timeline."
            )
    else:
        timeline = transcript
        word_count = sum(len(segment.words or []) for segment in transcript)
        timing = {
            "method": "automatic_transcription", "coverage": 1.0 if transcript else 0.0,
            "matched_words": word_count, "total_words": word_count,
            "approximate_lines": 0,
        }
    return {
        "timeline": timeline,
        "timing": timing,
        "srt": lyrics_to_srt(timeline),
        "visual_events": build_visual_events(timeline),
        "warnings": warnings,
    }


def structure_from_aligned_lyrics(timeline: list[dict]) -> list[dict]:
    aliases = {
        "pre chorus": "pre-chorus", "prechorus": "pre-chorus",
        "inst": "instrumental", "solo": "instrumental",
        "intro hablado": "intro", "spoken intro": "intro",
        "verso": "verse", "estrofa": "verse",
        "pre estribillo": "pre-chorus", "preestribillo": "pre-chorus",
        "estribillo": "chorus", "coro": "chorus",
        "ultimo estribillo": "chorus", "final chorus": "chorus",
        "puente": "bridge", "puente hablado": "bridge", "spoken bridge": "bridge",
        "outro hablado": "outro", "spoken outro": "outro", "instrumental": "instrumental",
    }
    valid_labels = {"intro", "verse", "pre-chorus", "chorus", "bridge", "outro", "instrumental"}
    structure: list[dict] = []
    previous = None
    for cue in timeline or []:
        display = str(cue.get("section") or "").strip() if isinstance(cue, dict) else ""
        if not display or display.casefold() == previous:
            continue
        normalized = unicodedata.normalize("NFKD", display.casefold())
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = re.sub(r"\d+$", "", normalized).strip()
        normalized = re.sub(r"[-_]+", " ", normalized)
        label = aliases.get(normalized, normalized.replace(" ", "-"))
        structure.append({
            "label": label if label in valid_labels else "verse",
            "display_label": display,
            "start": round(float(cue.get("start", 0.0) or 0.0), 3),
        })
        previous = display.casefold()
    return structure


def attach_timing_to_clips(clips: list[dict], analysis: dict) -> None:
    """Attach absolute and clip-relative lyric timing in place."""
    timeline = analysis.get("lyric_timeline") or analysis.get("lyrics") or []
    events = analysis.get("visual_events") or []
    for clip in clips:
        start, end = clip["start"], clip["end"]
        clip["lyric_cues"] = [
            {
                **dict(cue),
                "offset": round(max(0.0, float(cue.get("start", 0.0)) - start), 3),
            }
            for cue in timeline
            if isinstance(cue, dict)
            and float(cue.get("start", 0.0)) < end
            and float(cue.get("end", 0.0)) > start
        ]
        clip["visual_events"] = [
            {
                **dict(event),
                "offset": round(max(0.0, float(event.get("time", 0.0)) - start), 3),
            }
            for event in events
            if isinstance(event, dict)
            and start <= float(event.get("time", -1.0)) < end
        ]

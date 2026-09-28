"""Shorten a song on the CPU by keeping editable ranges and crossfading the joins.

Cut points move to a nearby strong onset. Correlation against a beat-period comb
chooses that onset; correlating the onset window with itself is not used, because
that match always peaks at the original cut.
"""

from __future__ import annotations

import os
import wave
from typing import Any

import numpy as np

from services.montage_shots import timeline_slots

SEARCH_SECONDS = 1.6
CONTEXT_SECONDS = 4.0
FADE_SECONDS = 0.012
MIN_PIECE_SECONDS = 0.05


class SongShortenError(ValueError):
    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _load(path: str) -> tuple[np.ndarray, int]:
    import librosa
    audio, sample_rate = librosa.load(path, sr=None, mono=True)
    return np.asarray(audio, dtype=np.float32), int(sample_rate)


def _onset_track(audio: np.ndarray, sample_rate: int, center: float) -> tuple[np.ndarray, np.ndarray]:
    import librosa
    duration = len(audio) / sample_rate
    start = max(0.0, center - CONTEXT_SECONDS)
    end = min(duration, center + CONTEXT_SECONDS)
    i0 = int(start * sample_rate)
    i1 = max(i0 + 1, int(end * sample_rate))
    slice_audio = audio[i0:i1]
    onset = librosa.onset.onset_strength(y=slice_audio, sr=sample_rate)
    times = librosa.times_like(onset, sr=sample_rate) + start
    return np.asarray(onset, dtype=np.float32), np.asarray(times, dtype=np.float32)


def _beat_period(onset: np.ndarray, times: np.ndarray) -> float:
    if onset.size < 8 or times.size < 2:
        return 0.5
    hop = float(times[1] - times[0]) if times.size > 1 else 0.02
    centered = onset - float(onset.mean())
    norm = float(np.linalg.norm(centered))
    if hop <= 0 or norm < 1e-8:
        return 0.5
    correlation = np.correlate(centered, centered, mode="full")
    correlation = correlation[correlation.size // 2:] / (norm * norm)
    low = max(1, int(round(60 / 180 / hop)))
    high = min(correlation.size - 1, int(round(60 / 60 / hop)))
    if high <= low:
        return 0.5
    lag = low + int(np.argmax(correlation[low:high + 1]))
    return max(hop, lag * hop)


def _peaks(onset: np.ndarray, times: np.ndarray, center: float) -> list[float]:
    window = (times >= center - SEARCH_SECONDS) & (times <= center + SEARCH_SECONDS)
    local = onset[window]
    local_times = times[window]
    if local.size < 3:
        return []
    threshold = 0.5 * float(local.max())
    found = []
    for index in range(1, local.size - 1):
        strength = float(local[index])
        if strength >= threshold and strength >= float(local[index - 1]) and strength >= float(local[index + 1]):
            found.append(float(local_times[index]))
    return found


def _comb_score(onset: np.ndarray, times: np.ndarray, candidate: float, period: float) -> float:
    width = max(period * 0.08, 0.02)
    phase = np.zeros_like(onset)
    for step in range(-8, 9):
        center = candidate + step * period
        phase += np.exp(-0.5 * ((times - center) / width) ** 2)
    left = onset - float(onset.mean())
    right = phase - float(phase.mean())
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom < 1e-8:
        return 0.0
    return float(np.dot(left, right) / denom)


def snap_time(audio: np.ndarray, sample_rate: int, instant: float) -> float:
    """Move one cut onto the nearest strong onset inside ±1.6 s."""
    duration = len(audio) / float(sample_rate)
    instant = min(max(float(instant), 0.0), duration)
    onset, times = _onset_track(audio, sample_rate, instant)
    if onset.size == 0:
        return instant
    period = _beat_period(onset, times)
    candidates = _peaks(onset, times, instant)
    if not candidates:
        return instant
    # Distance wins. The comb score only breaks a tie so a self-match at the original cut cannot override a nearer onset.
    nearest = min(candidates, key=lambda candidate: (abs(candidate - instant), -_comb_score(onset, times, candidate, period)))
    return float(nearest)


def _parse_keep(keep: Any, duration: float) -> list[tuple[float, float]]:
    if not isinstance(keep, list) or not keep:
        raise SongShortenError("keep must be a list of [start, end] ranges")
    ranges = []
    for item in keep:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise SongShortenError("each keep range is [start, end]")
        try:
            start, end = float(item[0]), float(item[1])
        except (TypeError, ValueError) as exc:
            raise SongShortenError("keep times must be numbers") from exc
        start, end = max(0.0, start), min(duration, end)
        if end - start >= MIN_PIECE_SECONDS:
            ranges.append((start, end))
    if not ranges:
        raise SongShortenError("keep ranges do not cover any audio")
    ranges.sort()
    return ranges


def _crossfade(left: np.ndarray, right: np.ndarray, fade: int) -> np.ndarray:
    if fade < 1 or len(left) <= fade or len(right) <= fade:
        return np.concatenate([left, right])
    ramp = np.linspace(0.0, 1.0, fade, endpoint=False, dtype=np.float32)
    mixed = left[-fade:] * (1.0 - ramp) + right[:fade] * ramp
    return np.concatenate([left[:-fade], mixed, right[fade:]])


def shorten_audio(audio: np.ndarray, sample_rate: int, keep: Any, *, snap: bool = True) -> tuple[np.ndarray, list[list[float]]]:
    duration = len(audio) / float(sample_rate)
    ranges = _parse_keep(keep, duration)
    snapped = []
    for start, end in ranges:
        left = snap_time(audio, sample_rate, start) if snap else start
        right = snap_time(audio, sample_rate, end) if snap else end
        if right < left:
            left, right = right, left
        if right - left >= MIN_PIECE_SECONDS:
            snapped.append((left, right))
    if not snapped:
        raise SongShortenError("snapped ranges do not cover any audio")
    fade = int(round(FADE_SECONDS * sample_rate))
    pieces = [audio[int(round(start * sample_rate)):int(round(end * sample_rate))].copy() for start, end in snapped]
    mixed = pieces[0]
    for piece in pieces[1:]:
        mixed = _crossfade(mixed, piece, fade)
    time_map = []
    cursor = 0.0
    for index, (start, end) in enumerate(snapped):
        span = end - start
        time_map.append([round(cursor, 6), round(start, 6), round(span, 6)])
        cursor += span
        if index < len(snapped) - 1:
            cursor -= FADE_SECONDS
    return mixed, time_map


def write_wav(path: str, audio: np.ndarray, sample_rate: int) -> None:
    pcm = np.clip(audio, -1.0, 1.0)
    frames = (pcm * 32767.0).astype(np.int16)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames.tobytes())


def suggest_keep(analysis: dict[str, Any], duration_max: float = 180.0) -> list[list[float]]:
    """Editable ranges. A repeated chorus is dropped and bridges shrink first."""
    try:
        duration = float(analysis.get("duration") or 0)
    except (TypeError, ValueError) as exc:
        raise SongShortenError("analysis duration must be a number") from exc
    if duration <= 0:
        raise SongShortenError("analysis needs a duration")
    limit = max(1.0, float(duration_max))
    sections = analysis.get("sections") or []
    if duration <= limit or not isinstance(sections, list) or not sections:
        return [[0.0, round(min(duration, limit), 3)]]
    chorus = 0
    ranges: list[list[float]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = str(section.get("label") or "").lower()
        start = float(section.get("start") or 0)
        end = float(section.get("end") or start)
        if end <= start:
            continue
        if "chorus" in label:
            chorus += 1
            if chorus > 1:
                continue
        elif any(word in label for word in ("bridge", "instrumental", "break")):
            end = start + max(4.0, (end - start) * 0.5)
            end = min(end, float(section.get("end") or end))
        ranges.append([round(start, 3), round(end, 3)])
    if not ranges:
        ranges = [[0.0, round(min(duration, limit), 3)]]
    fitted: list[list[float]] = []
    used = 0.0
    for start, end in ranges:
        if used >= limit:
            break
        room = limit - used
        fitted.append([start, round(start + min(end - start, room), 3)])
        used += fitted[-1][1] - fitted[-1][0]
    return fitted


def _remap_interval(start: float, end: float, time_map: list[list[float]]) -> list[tuple[float, float, float, float]]:
    pieces = []
    for new_start, original, span in time_map:
        low = max(start, original)
        high = min(end, original + span)
        if high - low > 0.001:
            pieces.append((new_start + (low - original), new_start + (high - original), low, high))
    return pieces


def _piece_changed(pieces: list, start: float, end: float) -> bool:
    if len(pieces) != 1:
        return True
    return abs(pieces[0][2] - start) > 0.001 or abs(pieces[0][3] - end) > 0.001


def _clip_span(clip: dict[str, Any]) -> float:
    return max(0.0, float(clip.get("trimEnd") or 0) - float(clip.get("trimStart") or 0))


def _remap_clips(document: dict[str, Any], time_map: list[list[float]], report: dict[str, list]) -> list:
    # Overlays/cues already sit on soundtrack time. Clips must use the same
    # overlap-aware slots as export and the shot board, or a crossfade makes
    # the second clip look like it starts after the cut and gets dropped.
    source = list(document.get("clips") or [])
    slots = timeline_slots(source, _clip_span)
    clips = []
    for clip, (start, end) in zip(source, slots):
        pieces = _remap_interval(start, end, time_map)
        if not pieces:
            report["dropped"].append({"kind": "clip", "id": clip.get("id"), "start": round(start, 3), "end": round(end, 3)})
            continue
        if _piece_changed(pieces, start, end):
            report["trimmed"].append({"kind": "clip", "id": clip.get("id")})
        for index, (new_start, new_end, old_start, _old_end) in enumerate(pieces):
            copied = dict(clip)
            media_start = float(clip.get("trimStart") or 0) + (old_start - start)
            copied["trimStart"] = round(media_start, 6)
            copied["trimEnd"] = round(media_start + (new_end - new_start), 6)
            if index:
                copied["id"] = f"{clip.get('id')}-keep-{index + 1}"
            clips.append(copied)
    return clips


def remap_montage(document: dict[str, Any], time_map: list[list[float]]) -> tuple[dict[str, Any], dict[str, list]]:
    """Move clips, overlays and cues onto the shortened timeline. Drop what falls in a gap."""
    report: dict[str, list] = {"dropped": [], "trimmed": []}
    clips = _remap_clips(document, time_map, report)
    if not clips:
        raise SongShortenError("shortening removed every clip")

    def _timed(items: list, kind: str, start_key: str, end_key: str | None) -> list:
        kept = []
        for item in items:
            start = float(item.get(start_key) or 0)
            end = float(item.get(end_key) or start) if end_key else start + 0.001
            pieces = _remap_interval(start, end, time_map)
            if not pieces:
                report["dropped"].append({"kind": kind, "id": item.get("id"), "start": round(start, 3), "end": round(end, 3)})
                continue
            if _piece_changed(pieces, start, end):
                report["trimmed"].append({"kind": kind, "id": item.get("id")})
            for index, (new_start, new_end, _old_start, _old_end) in enumerate(pieces):
                copied = dict(item)
                copied[start_key] = round(new_start, 6)
                if end_key:
                    copied[end_key] = round(new_end, 6)
                if index:
                    copied["id"] = f"{item.get('id')}-keep-{index + 1}"
                kept.append(copied)
        return kept

    updated = dict(document)
    updated["clips"] = clips
    updated["overlays"] = _timed(list(document.get("overlays") or []), "overlay", "start", "end")
    updated["audioCues"] = _timed(list(document.get("audioCues") or []), "audioCue", "start", None)
    return updated, report


def load_and_shorten(path: str, keep: Any, *, snap: bool = True) -> tuple[np.ndarray, int, list[list[float]]]:
    audio, sample_rate = _load(path)
    mixed, time_map = shorten_audio(audio, sample_rate, keep, snap=snap)
    return mixed, sample_rate, time_map

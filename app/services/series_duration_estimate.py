"""How long an episode will run, before anyone renders it.

Each shot is the planner's timing (intro, the gap between lines, tail, pauses).
A line lasts its words divided by that character's pace: words per second of
speech on their approved takes, or 2.6 in Spanish and 2.8 in English when they
have none. A shot with no lines keeps the length it asked for, which is how a
title card is counted. ``method`` is ``approved_takes`` when every speaker had
a measured pace, ``default_rate`` when none did, and ``mixed`` when both.
"""
from __future__ import annotations

from typing import Any

from services.series_shot_extras import pauses, timing_args
from services.series_shot_plan import language_key, plan_timing

DEFAULT_WORDS_PER_SECOND = {"spanish": 2.6, "english": 2.8}
FALLBACK_RATE = 2.6
_MIN_WORDS = 3
_MIN_SPEECH = 1.0


def estimate_episode(series: dict[str, Any] | None, shots: list[Any] | None) -> dict[str, Any]:
    """``{seconds, method, perShot}`` for these shots, paced by the series' approved takes."""
    series = series if isinstance(series, dict) else {}
    language = language_key(series)
    rates = _measured_rates(series)
    per_shot = []
    methods: set[str] = set()
    for shot in shots or []:
        if not isinstance(shot, dict):
            continue
        seconds, method = _shot_seconds(shot, rates, language)
        if method:
            methods.add(method)
        per_shot.append({"id": shot.get("id"), "seconds": round(seconds, 3)})
    return {"seconds": round(sum(item["seconds"] for item in per_shot), 1), "method": _method(methods),
            "perShot": per_shot}


def _method(methods: set[str]) -> str:
    if not methods or methods <= {"default_rate"}:
        return "default_rate"
    return "mixed" if "default_rate" in methods else "approved_takes"


def _words(text: Any) -> int:
    return len(str(text or "").split())


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _speech_seconds(shot: dict[str, Any], beats: list[dict[str, Any]]) -> float:
    args = timing_args(shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {})
    gaps = args["gap"] * max(0, len(beats) - 1)
    return _number(shot.get("durationSeconds")) - args["intro"] - args["tail"] - gaps - sum(pauses(beats))


def _measured_rates(series: dict[str, Any]) -> dict[str, float]:
    words: dict[str, int] = {}
    seconds: dict[str, float] = {}
    for episode in (series.get("episodesById") or {}).values():
        if not isinstance(episode, dict):
            continue
        for shot in episode.get("shots") or []:
            _add_shot_rate(shot, words, seconds)
    return {who: words[who] / seconds[who] for who in words if words[who] >= _MIN_WORDS and seconds.get(who, 0) >= _MIN_SPEECH}


def _spoken_beats(shot: dict[str, Any]) -> list[dict[str, Any]]:
    return [beat for beat in shot.get("dialogueBeats") or [] if isinstance(beat, dict) and str(beat.get("text") or "").strip()]


def _add_shot_rate(shot: Any, words: dict[str, int], seconds: dict[str, float]) -> None:
    if not isinstance(shot, dict) or not shot.get("approvedAttemptId"):
        return
    beats = _spoken_beats(shot)
    speech = _speech_seconds(shot, beats) if beats else 0.0
    total = sum(_words(beat.get("text")) for beat in beats)
    if speech <= 0.3 or total <= 0:
        return
    for beat in beats:
        count = _words(beat.get("text"))
        who = str(beat.get("characterId") or "")
        if not who or count <= 0:
            continue
        words[who] = words.get(who, 0) + count
        seconds[who] = seconds.get(who, 0.0) + speech * count / total


def _shot_seconds(shot: dict[str, Any], rates: dict[str, float], language: str) -> tuple[float, str | None]:
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    beats = _spoken_beats(shot)
    if not beats:
        _, duration = plan_timing([], **timing_args(layout), at_least=_number(shot.get("durationSeconds")))
        return duration, None
    used_default = False
    durations = []
    for beat in beats:
        rate = rates.get(str(beat.get("characterId") or ""))
        if not rate:
            rate = DEFAULT_WORDS_PER_SECOND.get(language, FALLBACK_RATE)
            used_default = True
        durations.append(max(0.2, _words(beat.get("text")) / rate))
    _, duration = plan_timing(durations, **timing_args(layout), pauses=pauses(beats))
    return duration, "default_rate" if used_default else "approved_takes"

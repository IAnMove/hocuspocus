"""The shot's dialogue in a card's scene (``series.shot.card.apply``).

A Series 2D take carries its lines two ways: the speech in the scene's ``audioTracks`` (the exported video has the voices) and
the scene's ``dialogueBeats`` (the episode's subtitles read their timing from the take's scene document). A compiled card has
neither, so the shot's lines are laid into it here, from the recordings the shot's render would reuse
(``ln-<episode>-<beat>-<key>.wav``, named by text and voice), timed as the render times them (``plan_timing``). Nothing is
spoken here: a line nobody recorded yet is an error that says which, and the way out (``series.shot.voice``).

A card has no mouths, so the beats lip-sync nothing (``mouthLayerIds`` is empty); the person can still draw them in Video 2D.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from services import series_hearing
from services.series_native_render import NativeRenderError, SeriesNativeRender
from services.series_shot_extras import pauses, timing_args
from services.series_shot_plan import line_id, plan_timing
from services.series_voice_rooms import RoomError, roomed

# Dialogue ducks the music under it by this much (DIALOGUE_DUCK_DB in ui/scripts/seriesShot.ts).
DIALOGUE_DUCK_DB = 10


class LinesError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def spoken(shot: dict[str, Any]) -> list[dict[str, Any]]:
    return [beat for beat in shot.get("dialogueBeats") or [] if isinstance(beat, dict) and str(beat.get("text") or "").strip()]


def recorded(series: dict[str, Any], episode: dict[str, Any], shot: dict[str, Any], kits: dict[str, Any], language: str, root: str,
             probe: Callable[[str], float]) -> dict[str, dict[str, Any]]:
    """beat id -> {filename, duration} for every spoken line of the shot. A line with no voice, or none recorded yet, is an error."""
    found: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for number, beat in enumerate(spoken(shot), start=1):
        try:
            _text, _voice, key = SeriesNativeRender.line_voice(series, beat, kits, language)
        except NativeRenderError as error:
            raise LinesError("no_voice", f"Line {number} of the shot: {error}") from error
        filename = f"{SeriesNativeRender.recording_stem(episode['id'], beat['id'], key)}.wav"
        if not os.path.isfile(os.path.join(root, filename)):
            missing.append(str(number))
            continue
        found[beat["id"]] = {"filename": filename, "duration": round(float(probe(os.path.join(root, filename))), 3)}
    if missing:
        raise LinesError("lines_not_recorded", f"Line {', '.join(missing)} of the shot {'is' if len(missing) == 1 else 'are'} not recorded yet: "
                         "record the shot's lines first (series.shot.voice) or render the shot, then apply the card again")
    return found


def heard(series: dict[str, Any], shot: dict[str, Any], lines: dict[str, dict[str, Any]], root: str,
          room: Callable[[str, str, str], str]) -> dict[str, dict[str, Any]]:
    """The recordings as the shot plays them: the room's copy of each when its location (or the shot) has a room."""
    try:
        return dict(roomed(series, shot, lines, lambda filename, preset: room(root, filename, preset)))
    except RoomError as error:
        raise LinesError("room_failed", f"Voice room: {error}", 502) from error


def plan(series: dict[str, Any], episode: dict[str, Any], shot: dict[str, Any], clips: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    """The shot's lines placed in time as the render places them (intro, gaps, pauses), and the length they need (0 without lines)."""
    beats = spoken(shot)
    if not beats:
        return [], 0.0
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    timing, seconds = plan_timing([float(clips[beat["id"]]["duration"]) for beat in beats], **timing_args(layout), pauses=pauses(beats))
    lines = [{"id": line_id(episode["id"], beat["id"]), "text": str(beat["text"]).strip(), "start": start, "end": end,
              "filename": clips[beat["id"]]["filename"], "name": beat.get("characterId") or ""}
             for beat, (start, end) in zip(beats, timing)]
    lines, _tracks = series_hearing.shape(series, shot, lines, [])
    return lines, seconds


def lay_dialogue(document: dict[str, Any], lines: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    """The card's scene with the shot's speech and subtitles in it. The scene lasts as long as the lines need."""
    if not lines:
        return document
    tracks = [{"id": line["id"], "filename": line["filename"], "name": line["name"], "kind": "speech", "startTime": line["start"],
               "volume": 1, "prompt": line["text"]} for line in lines]
    beats = [{"id": line["id"], "text": line["text"], "start": line["start"], "end": line["end"], "audioTrackId": line["id"],
              "mouthLayerIds": [], "confidence": "known-text"} for line in lines]
    return {**document, "duration": max(float(document.get("duration") or 0), seconds),
            "audioTracks": [*(document.get("audioTracks") or []), *tracks], "dialogueBeats": beats, "audioMix": {"duckDb": DIALOGUE_DUCK_DB}}

"""The script check's warning for a presence effect that a script cuts short (``fx_presence_too_short``).

An aura, a light, weather or a screen grade is a presence effect: with no ``duration`` it lasts the shot (see
``series_fx_classes``). One that a script gives under two seconds, in a shot of more than four, is almost always a
shortened halo, so ``check`` says so. It does not stop the script, and the duration is played as written.
"""
from __future__ import annotations

from typing import Any

from services.series_duration_estimate import script_shot_seconds
from services.series_fx_classes import too_short
from services.series_script_warnings import group_warning


def check_shot(episode: Any, shot: dict[str, Any], shot_id: str) -> None:
    """Add ``fx_presence_too_short`` (one per effect kind, grouped by shot) to ``episode.warnings``."""
    cues = [cue for cue in shot.get("fx") or [] if isinstance(cue, dict) and isinstance(cue.get("kind"), str)]
    if not cues:
        return
    from services.series_script import _line_text
    shot_seconds = script_shot_seconds(shot, episode.original, _line_text)
    for cue in cues:
        if too_short(cue["kind"], cue.get("duration"), shot_seconds):
            group_warning(episode.warnings, "fx_presence_too_short", cue["kind"], shot_id,
                          f"lasts {cue['duration']:g} s in a shot of about {shot_seconds:g} s: it is a presence effect, so leave `duration` out "
                          f"(it lasts the shot) or write \"shot\"")

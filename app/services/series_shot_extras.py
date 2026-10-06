"""Shot details beyond framing and cast: rhythm, timed sound effects, screen effects, perched characters.

1x02 needed all of them and had to add them after the render by editing each
scene. Declared in ``layout2d`` they are planned with the lines:

* ``timing``: ``{intro, gap, tail}`` seconds (defaults 0.35 / 0.22 / 0.45);
  a dialogue beat's ``pauseBefore`` adds a beat of silence before it.
* ``sfx``: ``[{file, line, anchor, offset, at, volume}]`` sound effects at a
  line's start or end (or at an absolute second), next to the shot's music.
* ``fx``: ``[{kind, line, anchor, offset, at, duration, x, y, size, ...}]``
  screen effects from ``shared/scene_effects.json`` at the same kind of time.
  ``duration`` is seconds (0.1-30, a value outside is clamped to that range,
  1 when missing or not a number) or ``"shot"``: until the end of the shot.
* a character with ``layout2d.perch = {file, width, height, top, widthRatio}``
  (a laptop on a desk) is placed on that prop in every framing.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

EFFECT_KINDS = frozenset(item["id"] for item in json.loads(
    (Path(__file__).resolve().parents[1] / "shared" / "scene_effects.json").read_text(encoding="utf-8")))
TIMING_DEFAULTS = {"intro": 0.35, "gap": 0.22, "tail": 0.45}
# A workspace file, in a subfolder if the user keeps one (``music/theme.wav``); never absolute, never ``..``.
_FILE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[^\\\x00]{1,300}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
FX_DURATION_RANGE = (0.1, 30.0)
FX_DEFAULT_DURATION = 1.0
FX_TO_SHOT_END = "shot"


def _number(value: Any, low: float, high: float) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high else None


def fx_duration(value: Any) -> float | str:
    """How long a screen effect lasts: seconds clamped to 0.1-30 (an author who writes 99 means "long", not 1 s),
    ``"shot"`` for the rest of the shot, and 1 s only when it is missing or not a number."""
    if isinstance(value, str) and value.strip().lower() == FX_TO_SHOT_END:
        return FX_TO_SHOT_END
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value):
        return FX_DEFAULT_DURATION
    low, high = FX_DURATION_RANGE
    return float(min(max(value, low), high))


def _when(value: dict[str, Any]) -> dict[str, Any]:
    """When a cue happens: at a line (start or end, plus an offset) or at an absolute second."""
    found: dict[str, Any] = {}
    if isinstance(value.get("line"), int) and not isinstance(value.get("line"), bool) and 0 <= value["line"] < 50:
        found["line"] = value["line"]
        found["anchor"] = "end" if value.get("anchor") == "end" else "start"
    elif _number(value.get("at"), 0, 600) is not None:
        found["at"] = float(value["at"])
    offset = _number(value.get("offset"), -10, 30)
    if offset is not None:
        found["offset"] = offset
    return found


def normalize_timing(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    timing = {key: float(value[key]) for key in TIMING_DEFAULTS if _number(value.get(key), 0, 6) is not None}
    return {"timing": timing} if timing else {}


def sfx_entry(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("file"), str) or not _FILE.match(value["file"]) or ".." in value["file"]:
        return None
    volume = _number(value.get("volume"), 0, 1)
    return {"file": value["file"], **_when(value), "volume": 0.8 if volume is None else volume}


def fx_entry(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("kind") not in EFFECT_KINDS:
        return None
    entry = {"kind": value["kind"], **_when(value), "duration": fx_duration(value.get("duration"))}
    # rotation turns directional effects (a laser leaves the muzzle of a gun that points left: 180).
    for key, low, high in (("x", 0, 100), ("y", 0, 100), ("size", 1, 200), ("intensity", 0.1, 2), ("volume", 0, 1),
                           ("rotation", -180, 180)):
        if _number(value.get(key), low, high) is not None:
            entry[key] = float(value[key])
    if isinstance(value.get("color"), str) and _COLOR.match(value["color"]):
        entry["color"] = value["color"]
    if isinstance(value.get("sound"), bool):
        entry["sound"] = value["sound"]
    return entry


def pauses(beats: list[dict[str, Any]]) -> list[float]:
    return [_number(beat.get("pauseBefore"), 0, 6) or 0.0 for beat in beats]


def timing_args(layout: dict[str, Any]) -> dict[str, float]:
    return {**TIMING_DEFAULTS, **(layout.get("timing") or {})}


def cue_time(cue: dict[str, Any], timing: list[tuple[float, float]], duration: float) -> float:
    """Absolute second of a cue; a line index past the shot's lines falls back to the start."""
    if "line" in cue and cue["line"] < len(timing):
        start, end = timing[cue["line"]]
        base = end if cue.get("anchor") == "end" else start
    else:
        base = cue.get("at", 0.0)
    return round(min(max(0.0, base + cue.get("offset", 0.0)), max(0.0, duration - 0.05)), 3)


def sfx_tracks(layout: dict[str, Any], timing: list[tuple[float, float]], duration: float) -> list[dict[str, Any]]:
    return [{"id": f"sfx-{index}", "filename": cue["file"], "name": "Sound effect", "kind": "sfx",
             "startTime": cue_time(cue, timing, duration), "volume": cue.get("volume", 0.8)}
            for index, cue in enumerate(layout.get("sfx") or [])]


def fx_cues(layout: dict[str, Any], timing: list[tuple[float, float]], duration: float) -> list[dict[str, Any]]:
    cues = []
    for index, cue in enumerate(layout.get("fx") or []):
        start = cue_time(cue, timing, duration)
        length = fx_duration(cue.get("duration"))
        # "shot" lasts to the end of the shot, like any cue that would run past it.
        end = round(min(duration - 0.01, duration if length == FX_TO_SHOT_END else start + length), 3)
        if end <= start:
            continue
        extra = {key: cue[key] for key in ("x", "y", "size", "intensity", "color", "sound", "volume", "rotation") if key in cue}
        cues.append({"id": f"fx-{index}", "kind": cue["kind"], "start": start, "end": end, **extra})
    return cues


def perch(character: dict[str, Any], workspace: str) -> dict[str, Any] | None:
    """The prop a perched character sits on (Gary's desk), as the compiler needs it."""
    value = (character.get("layout2d") or {}).get("perch") if isinstance(character.get("layout2d"), dict) else None
    if not isinstance(value, dict) or not isinstance(value.get("file"), str) or not _FILE.match(value["file"]):
        return None
    width, height = _number(value.get("width"), 1, 20000), _number(value.get("height"), 1, 20000)
    if not width or not height:
        return None
    return {"source": f"/api/v1/file/{quote(value['file'])}?workspace={quote(workspace)}", "width": width, "height": height,
            "top": _number(value.get("top"), 0, 1) or 0.04, "widthRatio": _number(value.get("widthRatio"), 0.5, 4) or 1.45}

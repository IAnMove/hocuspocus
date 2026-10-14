"""What an H3 shot was made from, beyond the two digests ``forget_changed_shots`` has always kept.

``h3_sources[key]`` holds two hashes (``frame``: prompt, seed, cast; ``clip``: that plus action, camera, singing). Adding
an input to those hashes would change the stored value of every production already made, and the first resume after an
upgrade would draw every frame and shoot every clip again. So the hashes stay as they are and each further input is
recorded next to them as a named part (``h3_sources[key]["parts"]``):

* ``image`` (model and steps) and ``frame_size`` are what the start frame was drawn with. A change draws the frame again
  and so shoots the clip again.
* ``video_look`` (``style.video``) and ``clip_size`` (``resolution.clips``) are what the clip was shot with. A change
  shoots only the clip again.

A part the record never held is learned, not compared (the rule ``cast_sources`` and ``h3_sources`` already follow): a
production made before the part existed keeps what it has until a person changes the input. The sizes are read through
``frame_resolution`` and ``clip_resolution``, so naming the default size is not a change.

The audio window is different: a clip is shot against ONE window, and several small moves (each under the 0.3 s bar of
``production.song.use``) add up. It is therefore written on the clip record when the take lands, never refreshed by a
resume, and compared with the same 0.3 s bar. A clip without a window (made before it was recorded) learns the current
one the first time it is seen.
"""
from __future__ import annotations

from typing import Any

from services.production_image_defaults import image_choice
from services.production_resolution import clip_resolution, frame_resolution
from services.production_song_switch import window_moved

FRAME_PARTS = {"image": "the image model or steps", "frame_size": "the start-frame size"}
CLIP_PARTS = {"video_look": "the video look", "clip_size": "the clip size"}


def recipe_parts(spec: dict, window: dict) -> dict[str, Any]:
    """The inputs of this shot's picture, and for an H3 shot its clip, as plain values that survive a JSON round trip."""
    style = spec.get("style") or {}
    parts: dict[str, Any] = {"image": list(image_choice(window, style)), "frame_size": frame_resolution(spec, 0, "")}
    if window.get("kind") == "h3":
        parts.update(video_look=str(style.get("video") or ""), clip_size=clip_resolution(spec))
    return parts


def changed_parts(known: dict, parts: dict[str, Any]) -> list[str]:
    """The parts whose recorded value differs. A part the record never held is not a change."""
    stored = known.get("parts") if isinstance(known.get("parts"), dict) else {}
    return [name for name, value in parts.items() if name in stored and stored[name] != value]


def shot_window(window: dict) -> list[float] | None:
    """``[t0, t1]`` of a timed shot, else None (a caller that did not time the shot cannot say it moved)."""
    try:
        return [round(float(window["t0"]), 3), round(float(window["t1"]), 3)]
    except (KeyError, TypeError, ValueError):
        return None


def remember_window(record: dict, window: dict) -> dict:
    """Write the window a take was shot against onto its clip or take record."""
    shot = shot_window(window)
    if shot is not None:
        record["window"] = shot
    return record


def learn_window(clip: Any, window: dict) -> None:
    """A kept clip with no recorded window takes the current one as the window it was shot against."""
    if isinstance(clip, dict) and "window" not in clip and window.get("kind") == "h3":
        remember_window(clip, window)


def moved_since_shot(clip: Any, window: dict) -> bool:
    """True when the audio window of an H3 shot is more than the song switch's 0.3 s bar away from the one its kept clip
    was shot against. Several smaller moves add up because the recorded window is never refreshed."""
    current, stored = shot_window(window), clip.get("window") if isinstance(clip, dict) else None
    if window.get("kind") != "h3" or current is None or not isinstance(stored, (list, tuple)) or len(stored) != 2:
        return False
    try:
        return window_moved((float(stored[0]), float(stored[1])), (current[0], current[1]))
    except (TypeError, ValueError):
        return False


def stale_reasons(known: dict, now: dict[str, Any], window: dict, clip: Any) -> tuple[str | None, str | None]:
    """(why the start frame must be drawn again, why the clip must be shot again); None for what is still good.

    ``known`` is the record kept on the last pass, ``now`` the same shape for this pass. A frame to draw again also
    sends the clip back, as a changed ``frame`` digest always has."""
    changed = changed_parts(known, now["parts"])
    frame = "the shot's picture changed" if known["frame"] != now["frame"] else next(
        (f"{FRAME_PARTS[name]} changed" for name in changed if name in FRAME_PARTS), None)
    if frame:
        return frame, frame
    if known["clip"] != now["clip"]:
        return None, "the shot changed"
    if window.get("kind") == "h3":
        later = next((f"{CLIP_PARTS[name]} changed" for name in changed if name in CLIP_PARTS), None)
        if later or moved_since_shot(clip, window):
            return None, later or "its audio window moved"
    return None, None

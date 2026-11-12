"""``actor_out_of_frame``: is the object a beat is about inside the picture of a fixed camera when it matters?

A beat sheet cannot see the frame. For a fixed camera this projects the middle of the object (``camera.eye``, ``look``, ``fov``
and the size of the picture, the maths of ``camera.ts projectPoint``) at the moments the audience should see it: when it appears,
speaks or acts (``do``), turns (``face``) or has an effect (``fx``), and across a ``go``, which may enter or leave the frame
(a walk-in starts outside it) but should be seen at some point. Other camera families move the eye and are not checked.
"""
from __future__ import annotations

import math

from services.world3d_beat_verbs import Beat, Stage
from services.world3d_scene_motion import pose_at

MARGIN = 1.1            # the middle of an object this far past the edge (in half-frames) still shows part of it
SAMPLES = 9
LOOKED_AT = ("appear", "do", "face", "fx")


def check(stage: Stage, beats: list[Beat]) -> None:
    view = _fixed_view(stage)
    if view is None:
        return
    for beat in beats:
        slot = stage.slot(beat.who)
        if slot is None or (slot.get("media") or "model3d") != "model3d" or not slot.get("sourceUrl"):
            continue
        text = _unseen(view, slot, beat, stage.duration)
        if text:
            stage.warn(text)


def _fixed_view(stage: Stage) -> "_View | None":
    camera = stage.document.get("camera")
    if not isinstance(camera, dict) or camera.get("family") != "fixed" or not _triple(camera.get("eye")) or not _triple(camera.get("look")):
        return None
    return _View(camera, float(stage.document.get("width") or 1280) / max(1.0, float(stage.document.get("height") or 720)))


def _unseen(view: "_View", slot: dict, beat: Beat, duration: float) -> str | None:
    """The warning for a beat whose object is out of the picture when it should be seen, else None."""
    if beat.verb in LOOKED_AT and not _shows(view, slot, [beat.t], duration):
        return (f"actor_out_of_frame: {beat.who} is outside the fixed camera's frame at {beat.t:g} s (beats[{beat.index}] {beat.verb}); "
                "move the camera, the object or the beat")
    if beat.verb == "go" and slot.get("motion") and not _shows(view, slot, _along(slot, beat, duration), duration):
        return f"actor_out_of_frame: {beat.who} is never inside the fixed camera's frame during beats[{beat.index}] go; move the camera or the path"
    return None


def _triple(value) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(type(item) in (int, float) and math.isfinite(item) for item in value)


def _along(slot: dict, beat: Beat, duration: float) -> list[float]:
    motion = slot["motion"]
    start, end = float(motion.get("start", beat.t)), float(motion.get("end", duration))
    return [start + (end - start) * index / (SAMPLES - 1) for index in range(SAMPLES)]


def _shows(view: "_View", slot: dict, times: list[float], duration: float) -> bool:
    height = 1.7 * float(slot.get("scale") or 1)
    for seconds in times:
        position, _rotation = pose_at(slot, seconds, duration)
        if view.contains([position[0], position[1] + height / 2, position[2]]):
            return True
    return False


class _View:
    """The fixed camera as the renderer builds it: looking from ``eye`` at ``look``, ``fov`` degrees tall, y up."""

    def __init__(self, camera: dict, aspect: float) -> None:
        self.eye, self.aspect = [float(item) for item in camera["eye"]], aspect
        self.forward = _unit([camera["look"][axis] - self.eye[axis] for axis in range(3)])
        right = _cross(self.forward, [0.0, 1.0, 0.0])
        self.right = _unit(right) if math.hypot(*right) > 1e-6 else [1.0, 0.0, 0.0]
        self.up = _unit(_cross(self.right, self.forward))
        fov = camera.get("fov")
        self.focal = 1 / math.tan((float(fov) if isinstance(fov, (int, float)) and fov > 1 else 50.0) * math.pi / 360)

    def contains(self, point: list[float]) -> bool:
        rel = [point[axis] - self.eye[axis] for axis in range(3)]
        depth = _dot(rel, self.forward)
        if depth <= 1e-4:
            return False
        return abs(_dot(rel, self.right) * self.focal / (self.aspect * depth)) <= MARGIN and abs(_dot(rel, self.up) * self.focal / depth) <= MARGIN


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(vector) -> list[float]:
    length = math.sqrt(_dot(vector, vector)) or 1.0
    return [item / length for item in vector]

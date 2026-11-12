"""The verbs of a beat sheet, each resolved into the normal fields of one Video 3D object.

``world3d.scene.beats`` says who does what when. Nothing is stored apart from the document, so the editor opens and edits
the result like any other scene:

- ``appear {at?, duration?, color?}``: the object's ``appearance`` (hidden until ``t``, then it materializes) and, with ``at``, its place.
- ``go {to, via?, duration? | speed_mps?, face?}``: its ``motion`` over ``t`` to ``t + duration`` (``motion.start`` / ``motion.end``) and, when the
  model has a walk (or, fast, a run) clip, a ``clips`` entry over the same seconds with its idle clip before and after.
- ``face {toward}``: its ``rotationY`` before it moves, or a turn in place (a ``motion`` to where it stands with a ``turnTo``).
- ``do {action, duration?}``: a ``clips`` entry for the clip of the model's own GLB that the word names (``world3d_beat_clips``).
- ``fx {kind, at?}``: a ``worldSfx`` cue (``world3d_beat_fx``).

An object has one ``motion``: the first ``go`` of an object in a call is its move, a second one is ignored with a warning.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from services import world3d_beat_clips as clips
from services import world3d_slot_fields as slot_fields
from services.world3d_scene_motion import check_motion, pose_at

WALK_MPS = 1.4                    # a walk with no duration or speed given
RUN_MPS = 3.0                     # at or above this pace a model with a run clip runs
MAX_MPS = 15.0                    # above this pace a go warns implied_speed
NEAR_M = 1.5                      # go {near} stops this far short of its target
TURN_SECONDS = 0.5                # a turn in place takes this long
LIMIT_M = 1000.0
MAX_SECONDS = 600


@dataclass
class Beat:
    index: int
    t: float
    who: str
    verb: str
    raw: dict


@dataclass
class Stage:
    """The scene the beats act on, and what they report."""
    document: dict
    workspace: str | None
    workspace_dir: object
    warnings: list[str] = field(default_factory=list)
    resolved: dict[int, dict] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return float(self.document.get("duration") or 0)

    def slot(self, identifier: str) -> dict | None:
        return next((slot for slot in self.document.get("slots") or [] if isinstance(slot, dict) and slot.get("id") == identifier), None)

    def note(self, beat: Beat, fields: dict, *notes: str) -> None:
        self.resolved[beat.index] = {"beat": beat.index, "who": beat.who, "verb": beat.verb, "set": fields, **({"notes": list(notes)} if notes else {})}

    def warn(self, text: str) -> None:
        self.warnings.append(text)


def refuse(beat: Beat | int, message: str):
    from services.world3d_scenes import World3DSceneError
    index = beat.index if isinstance(beat, Beat) else beat
    return World3DSceneError("invalid_beats", f"beats[{index}] {message}")


def number(beat: Beat, name: str, low: float, high: float, *, strict_low: bool = False) -> float | None:
    value = beat.raw.get(name)
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value > high or value < low or (strict_low and value <= low):
        raise refuse(beat, f".{name} must be a number {'above' if strict_low else 'from'} {low:g} to {high:g}")
    return float(value)


def point(beat: Beat, name: str, value: Any, y: float) -> list[float]:
    """``[x, z]`` or ``[x, y, z]`` metres as ``[x, y, z]`` (``y`` fills a missing height)."""
    ok = isinstance(value, (list, tuple)) and len(value) in (2, 3) and all(type(item) in (int, float) and math.isfinite(item) and abs(item) <= LIMIT_M for item in value)
    if not ok:
        raise refuse(beat, f".{name} must be [x, z] or [x, y, z] in metres (within {LIMIT_M:g} m)")
    return [float(value[0]), float(y), float(value[1])] if len(value) == 2 else [float(item) for item in value]


class Sheet:
    """What the beats of one object add up to."""

    def __init__(self, stage: Stage, slot: dict, beats: list[Beat]) -> None:
        self.stage, self.slot, self.beats = stage, slot, beats
        self.info = clips.clip_info(slot, stage.workspace, stage.workspace_dir)
        self.cues: list[dict] = []
        self.first_go = next((beat for beat in beats if beat.verb == "go"), None)
        self.appeared = False

    @property
    def position(self) -> list[float]:
        return [float(item) for item in self.slot.get("position") or [0, 0, 0]]

    def next_t(self, beat: Beat) -> float:
        """When the next beat of this object starts, else the end of the scene."""
        later = [other.t for other in self.beats if other.t > beat.t]
        return min(later) if later else self.stage.duration


# ------------------------------------------------------------------------------------------------------------------ appear

def appear(sheet: Sheet, beat: Beat) -> None:
    if sheet.appeared:
        sheet.stage.warn(f"second_appear_ignored: {beat.who} appears once; beats[{beat.index}] is ignored")
        sheet.stage.note(beat, {}, "ignored: an object appears once")
        return
    sheet.appeared = True
    fields: dict = {}
    if beat.raw.get("at") is not None:
        sheet.slot["position"] = point(beat, "at", beat.raw["at"], sheet.position[1])
        fields["position"] = sheet.slot["position"]
    try:
        look = {"start": beat.t, **{key: beat.raw[key] for key in ("duration", "color") if beat.raw.get(key) is not None}}
        sheet.slot["appearance"] = slot_fields.appearance(look)
    except ValueError as error:
        raise refuse(beat, f": {error}") from error
    fields["appearance"] = sheet.slot["appearance"]
    sheet.stage.note(beat, fields)


# ---------------------------------------------------------------------------------------------------------------------- go

def go(sheet: Sheet, beat: Beat) -> None:
    if beat is not sheet.first_go:
        sheet.stage.warn(f"second_go_ignored: {beat.who} has one move per call; beats[{beat.index}] is ignored (give it waypoints with via, or another object)")
        sheet.stage.note(beat, {}, "ignored: an object has one move per call")
        return
    start = sheet.position
    destination = _destination(sheet, beat, start)
    via = _via(sheet, beat, start, destination)
    length = _length(start, destination, via)
    if length < 1e-6:
        sheet.stage.warn(f"go_nowhere: {beat.who} is already at the destination of beats[{beat.index}]; it does not move")
        sheet.stage.note(beat, {}, "ignored: the destination is where it stands")
        return
    seconds = _seconds(sheet, beat, length)
    end = beat.t + seconds
    notes = []
    if end > sheet.stage.duration:
        notes.append(f"the move was cut at the end of the scene ({sheet.stage.duration:g} s)")
        sheet.stage.warn(f"go_cut_short: beats[{beat.index}] {beat.who} would arrive at {end:.2f} s, after the scene ends at {sheet.stage.duration:g} s; it covers the distance in the time left")
        end = sheet.stage.duration
    pace = length / max(end - beat.t, 1e-6)
    if pace > MAX_MPS:
        sheet.stage.warn(f"implied_speed: beats[{beat.index}] {beat.who} would move at {pace:.1f} m/s ({length:.1f} m in {end - beat.t:.2f} s); give it more time")
    motion = _motion(beat, destination, via, end)
    try:
        sheet.slot["motion"] = check_motion(motion, sheet.stage.duration)
    except ValueError as error:
        raise refuse(beat, f": {error}") from error
    fields: dict = {"motion": sheet.slot["motion"]}
    clip = clips.locomotion(sheet.info, pace >= RUN_MPS)
    if clip:
        cue = {"clip": clips.ref(clip), "start": round(beat.t, 3), "duration": round(end - beat.t, 3), "loop": True}
        sheet.cues.append(cue)
        fields["clips"] = [cue]
    elif sheet.info["names"]:
        notes.append(f"{beat.who} has no walk or run clip; it slides (clips: {', '.join(sheet.info['names'][:8])})")
    sheet.stage.note(beat, fields, f"impliedSpeedMps {pace:.2f}", *notes)


def _motion(beat: Beat, destination: list[float], via: list[float] | None, end: float) -> dict:
    easing = beat.raw.get("easing", "linear")
    if easing not in ("linear", "smooth"):
        raise refuse(beat, ".easing must be linear or smooth")
    motion: dict = {"to": [round(item, 4) for item in destination], "start": round(beat.t, 3), "end": round(end, 3), "easing": easing}
    if beat.raw.get("face") is True:
        motion["faceTravel"] = True
    if via is not None:
        motion["via"] = [round(item, 4) for item in via]
    offset = number(beat, "headingOffset", -2 * math.pi, 2 * math.pi)
    if offset:
        motion["headingOffset"] = offset
    return motion


def _destination(sheet: Sheet, beat: Beat, start: list[float]) -> list[float]:
    target = beat.raw.get("to")
    if isinstance(target, dict):
        if set(target) - {"near", "distance_m"} or not isinstance(target.get("near"), str):
            raise refuse(beat, ".to must be [x, z], [x, y, z] or {near: object_id, distance_m?}")
        return _near(sheet, beat, start, target)
    return point(beat, "to", target, start[1])


def _via(sheet: Sheet, beat: Beat, start: list[float], destination: list[float]) -> list[float] | None:
    if beat.raw.get("via") is None:
        return None
    return point(beat, "via", beat.raw["via"], (start[1] + destination[1]) / 2)


def _near(sheet: Sheet, beat: Beat, start: list[float], target: dict) -> list[float]:
    """A point ``distance_m`` short of another object, on the line from where this one stands, where that one is when this one arrives."""
    other = sheet.stage.slot(target["near"])
    if other is None or other is sheet.slot:
        raise refuse(beat, f".to.near {target['near']!r} must be another object of the scene")
    distance = _distance(beat, target)
    where, destination = pose_at(other, beat.t, sheet.stage.duration)[0], start
    for _ in range(3):
        destination = _short_of(start, where, distance)
        arrival = min(beat.t + _seconds(sheet, beat, _length(start, destination, None)), sheet.stage.duration)
        where = pose_at(other, arrival, sheet.stage.duration)[0]
    if destination == start:
        sheet.stage.warn(f"go_nowhere: {beat.who} is already within {distance:g} m of {target['near']}")
    return destination


def _distance(beat: Beat, target: dict) -> float:
    value = target.get("distance_m", NEAR_M)
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= LIMIT_M:
        raise refuse(beat, f".to.distance_m must be a number of metres above 0 and at most {LIMIT_M:g}")
    return float(value)


def _short_of(start: list[float], where: list[float], distance: float) -> list[float]:
    dx, dz = where[0] - start[0], where[2] - start[2]
    gap = math.hypot(dx, dz)
    if gap <= distance:
        return list(start)
    return [where[0] - dx / gap * distance, start[1], where[2] - dz / gap * distance]


def _length(start: list[float], destination: list[float], via: list[float] | None) -> float:
    """The path's length in metres (the curve through ``via`` measured on nine points, as the walk bake does)."""
    if via is None:
        return math.dist(start, destination)
    points = [[(1 - t) ** 2 * start[axis] + 2 * (1 - t) * t * via[axis] + t * t * destination[axis] for axis in range(3)] for t in (i / 8 for i in range(9))]
    return sum(math.dist(points[i], points[i + 1]) for i in range(8))


def _seconds(sheet: Sheet, beat: Beat, length: float) -> float:
    """How long the move takes: ``duration``, else ``length / speed_mps``, else a walk, else until the next beat of the object."""
    given, speed = number(beat, "duration", 0, MAX_SECONDS, strict_low=True), number(beat, "speed_mps", 0, 1000, strict_low=True)
    if given is not None and speed is not None:
        raise refuse(beat, "gives duration and speed_mps; give one")
    if given is not None:
        return given
    if speed is not None:
        return max(0.05, length / speed)
    if clips.locomotion(sheet.info, False):
        return max(0.05, length / WALK_MPS)
    return max(0.05, sheet.next_t(beat) - beat.t)


# --------------------------------------------------------------------------------------------------------------------- face

def face(sheet: Sheet, beat: Beat) -> None:
    angle = _bearing(sheet, beat)
    stage = sheet.stage
    if sheet.first_go is not None and beat.t <= sheet.first_go.t:
        sheet.slot["rotationY"] = round(angle, 5)
        stage.note(beat, {"rotationY": sheet.slot["rotationY"]}, "before it moves: it stands turned this way from the start of the scene")
    elif sheet.first_go is not None:
        stage.warn(f"face_after_go_ignored: beats[{beat.index}] {beat.who} turns while it moves (go with face: true) or before it moves; "
                   "a turn after the move cannot be timed, so it is ignored")
        stage.note(beat, {}, "ignored: a turn after the move cannot be timed")
    elif beat.t <= 0.05:
        sheet.slot["rotationY"] = round(angle, 5)
        stage.note(beat, {"rotationY": sheet.slot["rotationY"]})
    else:
        _turn_in_place(sheet, beat, angle)


def _turn_in_place(sheet: Sheet, beat: Beat, angle: float) -> None:
    """A move to where it stands with a ``turnTo``: it turns over ``TURN_SECONDS`` from ``t``, the short way round."""
    here = float(sheet.slot.get("rotationY") or 0)
    short = here + (angle - here + math.pi) % (2 * math.pi) - math.pi
    end = min(beat.t + TURN_SECONDS, sheet.stage.duration)
    if end <= beat.t:
        raise refuse(beat, f".t is too close to the end of the scene ({sheet.stage.duration:g} s) to turn")
    motion = {"to": sheet.position, "start": round(beat.t, 3), "end": round(end, 3), "easing": "smooth", "turnTo": round(short, 5)}
    sheet.slot["motion"] = check_motion(motion, sheet.stage.duration)
    sheet.stage.note(beat, {"motion": sheet.slot["motion"]})


def _bearing(sheet: Sheet, beat: Beat) -> float:
    """The ``rotationY`` that turns the object's front (+z) toward a place: ``atan2(dx, dz)``."""
    target = beat.raw.get("toward")
    here = sheet.position
    if isinstance(target, str):
        other = sheet.stage.slot(target)
        if other is None or other is sheet.slot:
            raise refuse(beat, f".toward {target!r} must be another object of the scene")
        where = pose_at(other, beat.t, sheet.stage.duration)[0]
    else:
        where = point(beat, "toward", target, here[1])
    dx, dz = where[0] - here[0], where[2] - here[2]
    if math.hypot(dx, dz) < 1e-6:
        raise refuse(beat, ".toward is where the object stands; it has no direction to turn to")
    return math.atan2(dx, dz)


# ----------------------------------------------------------------------------------------------------------------------- do

def do(sheet: Sheet, beat: Beat) -> None:
    action = beat.raw.get("action")
    if not isinstance(action, str) or not action.strip() or len(action) > 120:
        raise refuse(beat, ".action must be a clip id or name such as wave, talk, nod, point, bow, hit, crouch, jump, hover, bounce or wobble")
    found = clips.find(sheet.info, action)
    if found is None:
        have = ", ".join(sheet.info["names"][:12]) or "none"
        sheet.stage.warn(f"no_clip_for_verb: beats[{beat.index}] {beat.who} has no clip for {action!r} (clips: {have}); the beat does nothing")
        sheet.stage.note(beat, {}, f"no clip for {action!r}: the model has {have}")
        return
    length = found["length"]
    seconds = number(beat, "duration", 0, MAX_SECONDS, strict_low=True) or length or 2.0
    cue = {"clip": clips.ref(found), "start": round(beat.t, 3), "duration": round(seconds, 3),
           "loop": not clips.is_hold(found) and (length is None or seconds > length * 1.05)}
    sheet.cues.append(cue)
    sheet.stage.note(beat, {"clips": [cue]})


# --------------------------------------------------------------------------------------------------------------- the sheet

def finish(sheet: Sheet) -> None:
    """The object's clip sequence: its cues by start, its idle clip before the first and wherever one ends and nothing follows."""
    if not sheet.cues:
        return
    try:
        sheet.slot["clips"] = slot_fields.clip_cues(_with_idle(sheet, sorted(sheet.cues, key=lambda cue: cue["start"])))
    except ValueError as error:
        raise refuse(sheet.beats[0], f": {error}") from error


def _with_idle(sheet: Sheet, cues: list[dict]) -> list[dict]:
    idle = clips.idle(sheet.info)
    if idle is None:
        return cues
    filled = [_idle_cue(idle, 0.0)] if cues[0]["start"] > 0.05 else []
    for index, cue in enumerate(cues):
        filled.append(cue)
        after = cues[index + 1]["start"] if index + 1 < len(cues) else sheet.stage.duration
        end = cue["start"] + cue.get("duration", after)
        if end < after - 0.05:
            filled.append(_idle_cue(idle, end))
    return filled


def _idle_cue(idle: dict, start: float) -> dict:
    return {"clip": clips.ref(idle), "start": round(start, 3), "loop": True}


HANDLERS = {"appear": appear, "go": go, "face": face, "do": do}

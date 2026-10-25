"""``world3d.scene.beats``: tell a story in a Video 3D scene as who does what when.

``world3d.scene.patch`` places things; a beat sheet says what happens. Each beat is ``{t, who, verb, ...}``: ``t`` seconds into
the scene, ``who`` an object id, and a verb:

- ``appear {at?: [x, z], duration?, color?}``: the object materializes at ``t`` (and stands at ``at``).
- ``go {to, via?, duration? | speed_mps?, face?}``: it moves from where it stands over ``t`` to ``t + duration``. ``to`` is ``[x, z]``,
  ``[x, y, z]`` or ``{near: object_id, distance_m?}``; ``via`` bends the path; ``face: true`` turns it along its way. With no
  duration or speed a model with a walk clip walks at 1.4 m/s and any other object takes until its next beat. A model with a
  walk (or, at 3 m/s and over, a run) clip plays it over the move, and its idle clip before and after.
- ``face {toward: object_id | [x, z]}``: it turns toward that, before it moves or, with no move, in place over half a second.
- ``do {action, duration?}``: it plays the clip its GLB has for the word (wave, talk, nod, point, bow, hit, crouch, jump, hover,
  bounce, wobble, or the exact clip name). A model with no such clip gets a ``no_clip_for_verb`` warning, never an error.
- ``fx {kind, at?: object_id | [x, y, z] | "collision", duration?, scale?, color?, intensity?, sound?, volume?}``: a 3D effect at ``t``.

Everything becomes ordinary document fields (``motion`` with ``start`` and ``end``, ``clips``, ``appearance``, ``rotationY``,
``worldSfx``), so the editor opens and edits the result and the reply is the inspect view plus ``resolved``: what each beat
turned into. The collisions the moves cause are in ``layout.collisions`` of that view.

One call is one sheet for the objects it names: ``go``, ``face`` and ``do`` beats of an object replace its earlier ``motion`` and ``clips``,
``appear`` replaces its ``appearance`` and ``fx`` beats its earlier beat effects. An object has one move per call (a second ``go`` is
ignored with a warning); a ``face`` after the move cannot be timed (ignored with a warning).
"""
from __future__ import annotations

import math

from services.world3d_beat_frame import check as check_frame
from services.world3d_beat_fx import apply as apply_fx, clear as clear_fx
from services.world3d_beat_verbs import HANDLERS, Beat, Sheet, Stage, finish, refuse
from services.world3d_scenes import World3DSceneError, update_scene

VERBS = ("appear", "go", "face", "do", "fx")
PHASES = (("appear",), ("go",), ("face", "do"))     # a turn or a clip may depend on where another object ends up
MAX_BEATS = 64
BEATS_DOC = (
    "Tell a story in a Video 3D scene as who does what when: beats [{t (scene seconds), who (object id), verb, ...}] resolve into the object's own fields "
    "(motion with start and end, clips, appearance, rotationY, worldSfx), so the editor opens and edits the result. Verbs: "
    "appear {at? [x, z], duration?, color?}: it materializes at t. "
    "go {to ([x, z], [x, y, z] or {near: object_id, distance_m? 1.5}), via? (bends the path), duration? or speed_mps?, face? (turn along the way), easing?}: it moves from where it "
    "stands over t to t+duration (a model with a walk clip walks at 1.4 m/s when you give neither; any other object takes until its next beat); a walk "
    "(or run, from 3 m/s) clip plays over the move with the idle clip before and after; implied_speed warns above 15 m/s. One go per object per call. "
    "face {toward: object_id or [x, z]}: it turns before it moves, or in place over 0.5 s when it does not move (a turn after its go cannot be timed and is ignored). "
    "do {action, duration?}: it plays the clip its GLB has for the word (wave, talk, nod, point, bow, hit, crouch, jump, hover, bounce, wobble, or the exact clip name); "
    "a model with no such clip gets the warning no_clip_for_verb and the beat does nothing. "
    "fx {kind (a world effect: explosion, shockwave, sparks, smoke, fire...), at? (object id: it follows it; [x, y, z]; or \"collision\": where who passes through something; "
    "default who), duration?, scale?, color?, intensity?, sound?, volume?}. "
    "A call replaces the earlier go/face/do beats of the objects it names (their motion and clips), appear beats their appearance and fx beats their beat effects; objects it "
    "does not name are untouched. t must be inside the scene and who an object of it. Requires base_revision. The reply is the inspect view of the new revision plus "
    "resolved: [{beat, who, verb, set: {fields}, notes?}], with layout.collisions and the warnings of what the moves cause "
    "(collision, implied_speed, no_clip_for_verb, actor_out_of_frame for a fixed camera...).")


def beat_scene(workspace: str, scene_id: str, workspace_dir, changes: dict, base_revision: int) -> dict:
    """Apply a beat sheet to a working scene: a new revision with the objects' fields set, and ``resolved`` in the reply."""
    raw = changes.get("beats")
    return update_scene(workspace, scene_id, workspace_dir, base_revision,
                        lambda document: apply_beats(document, parse_beats(raw, document), workspace, workspace_dir))


def parse_beats(raw, document: dict) -> list[Beat]:
    """The beats as ``Beat`` rows in the order given, each checked: a known object and verb, a time inside the scene."""
    if not isinstance(raw, list) or not 0 < len(raw) <= MAX_BEATS:
        raise World3DSceneError("invalid_beats", f"beats must be a list of 1-{MAX_BEATS} beats {{t, who, verb, ...}}")
    ids = {slot.get("id") for slot in document.get("slots") or [] if isinstance(slot, dict)}
    duration = float(document.get("duration") or 0)
    return [_beat(index, item, ids, duration) for index, item in enumerate(raw)]


def _beat(index: int, item, ids: set, duration: float) -> Beat:
    if not isinstance(item, dict):
        raise refuse(index, "must be an object {t, who, verb, ...}")
    t, who, verb = item.get("t"), item.get("who"), item.get("verb")
    if type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t < duration:
        raise refuse(index, f".t ({t!r}) is outside the scene: it runs from 0 to {duration:g} seconds")
    if who not in ids:
        raise refuse(index, f".who {who!r} is not an object of the scene (objects: {', '.join(str(name) for name in sorted(ids, key=str)) or 'none'})")
    if verb not in VERBS:
        raise refuse(index, f".verb {verb!r} is not one of {', '.join(VERBS)}")
    if verb == "fx" and not isinstance(item.get("kind"), str):
        raise refuse(index, ".kind is the world effect of an fx beat (explosion, shockwave, sparks, smoke, fire...)")
    return Beat(index, float(t), who, verb, item)


def apply_beats(document: dict, beats: list[Beat], workspace: str | None, workspace_dir) -> tuple[list[str], dict]:
    """Set the document's fields from the beats. Returns ``(warnings, {"resolved": [...]})``."""
    stage = Stage(document, workspace, workspace_dir)
    sheets = _sheets(stage, [beat for beat in beats if beat.verb != "fx"])
    fx = [beat for beat in beats if beat.verb == "fx"]
    _clear(stage, sheets, fx)
    for phase in PHASES:
        for sheet, beat in _in_phase(sheets, phase):
            HANDLERS[beat.verb](sheet, beat)
    for sheet in sheets.values():
        finish(sheet)
    if fx:
        apply_fx(stage, fx)
    check_frame(stage, beats)
    return stage.warnings, {"resolved": [stage.resolved[index] for index in sorted(stage.resolved)]}


def _sheets(stage: Stage, beats: list[Beat]) -> dict[str, Sheet]:
    grouped: dict[str, list[Beat]] = {}
    for beat in beats:
        grouped.setdefault(beat.who, []).append(beat)
    return {who: Sheet(stage, stage.slot(who), sorted(group, key=lambda item: (item.t, item.index))) for who, group in grouped.items()}


def _in_phase(sheets: dict[str, Sheet], verbs: tuple) -> list[tuple[Sheet, Beat]]:
    """The beats of a phase over all the objects: a ``go`` toward another object waits until the plain ones have set their moves."""
    found = [(sheet, beat) for sheet in sheets.values() for beat in sheet.beats if beat.verb in verbs]
    if verbs == ("go",):
        found.sort(key=lambda pair: isinstance(pair[1].raw.get("to"), dict))
    return found


def _clear(stage: Stage, sheets: dict[str, Sheet], fx: list[Beat]) -> None:
    """What the earlier beats of these objects set goes before the new ones are applied."""
    for sheet in sheets.values():
        verbs = {beat.verb for beat in sheet.beats}
        if verbs & {"go", "face", "do"}:
            sheet.slot.pop("motion", None)
            sheet.slot.pop("clips", None)
        if "appear" in verbs:
            sheet.slot.pop("appearance", None)
    clear_fx(stage.document, {beat.who for beat in fx})

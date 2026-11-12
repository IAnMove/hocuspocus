"""``fx`` beats: a 3D effect at a moment of the beat sheet, as the ``worldSfx`` cue ``worldFx`` writes (``world3d_world_fx``).

``{t, who, verb: "fx", kind, at?}``: ``at`` is another object's id (the cue follows it), ``[x, y, z]`` metres, or ``"collision"``
for the passage of ``who`` through something (the one of ``layout.collisions`` nearest ``t``). Without ``at`` the effect is on
``who``. The cue carries the label ``beat:<who>``: a call that has ``fx`` beats for an object replaces the cues its earlier
beats made and leaves every other cue (the template's, ``worldFx``'s) alone.
"""
from __future__ import annotations

from services.world3d_beat_verbs import Beat, Stage, refuse
from services.world3d_scene_collisions import scene_collisions
from services.world3d_world_fx import MAX_CUES, build_cue

LABEL = "beat:"
PREFIX = "fx-beat-"
_PASSED_ON = ("scale", "color", "intensity", "sound", "volume", "to")


def label(who: str) -> str:
    return (LABEL + who)[:80]


def clear(document: dict, who: set[str]) -> None:
    """Take the cues earlier beats of these objects made out of the document."""
    owned = {label(name) for name in who}
    if "worldSfx" in document:
        document["worldSfx"] = [cue for cue in document["worldSfx"] if not (isinstance(cue, dict) and cue.get("label") in owned and str(cue.get("id", "")).startswith(PREFIX))]


def apply(stage: Stage, beats: list[Beat]) -> None:
    from services.world3d_scenes import World3DSceneError
    document = stage.document
    collisions = scene_collisions(document, stage.workspace, stage.workspace_dir)["collisions"]
    cues = [cue for cue in document.get("worldSfx") or [] if isinstance(cue, dict)]
    taken = {str(cue.get("id")) for cue in cues}
    added = []
    for number, beat in enumerate(beats, start=1):
        spec = _spec(stage, beat, number, collisions)
        if spec is None:
            continue
        context = {"document": document, "collisions": collisions, "workspace": stage.workspace, "workspace_dir": stage.workspace_dir, "warnings": []}
        try:
            entry = build_cue(beat.index, spec, context, taken)
        except World3DSceneError as error:
            raise refuse(beat, str(error).split("] ", 1)[-1] if "worldFx[" in str(error) else f": {error}") from error
        entry["label"] = label(beat.who)
        stage.warnings.extend(text.replace(f"worldFx[{beat.index}]", f"beats[{beat.index}]") for text in context["warnings"])
        taken.add(entry["id"])
        added.append(entry)
        stage.note(beat, {"worldSfx": [entry]})
    if len(cues) + len(added) > MAX_CUES:
        raise refuse(beats[0], f": the scene would hold {len(cues) + len(added)} world effects; at most {MAX_CUES}")
    document["worldSfx"] = cues + added


def _spec(stage: Stage, beat: Beat, number: int, collisions: list[dict]) -> dict | None:
    raw = beat.raw
    where = raw.get("at", beat.who)
    if where == "collision":
        found = _collision_for(beat, collisions)
        if found is None:
            stage.warn(f"no_collision_for_fx: beats[{beat.index}] {beat.who} passes through nothing in layout.collisions, so its {raw.get('kind')} has no place; the beat is ignored")
            stage.note(beat, {}, "ignored: no collision involves this object")
            return None
        where = {"collision": found}
    elif isinstance(where, str):
        where = {"object_id": where}
    spec = {"id": f"{PREFIX}{beat.who[:40]}-{raw.get('kind')}-{number}", "kind": raw.get("kind"), "start": beat.t, "at": where}
    spec.update({key: raw[key] for key in _PASSED_ON if raw.get(key) is not None})
    if raw.get("duration") is not None:
        spec["end"] = beat.t + raw["duration"] if isinstance(raw["duration"], (int, float)) and not isinstance(raw["duration"], bool) else raw["duration"]
    return spec


def _collision_for(beat: Beat, collisions: list[dict]) -> int | None:
    """The passage involving ``who`` that is on at ``t``, else the one that starts nearest it."""
    mine = [(index, row) for index, row in enumerate(collisions) if beat.who in (row["a"], row["b"])]
    if not mine:
        return None
    return min(mine, key=lambda item: 0 if item[1]["from_s"] <= beat.t <= item[1]["to_s"] else min(abs(beat.t - item[1]["from_s"]), abs(beat.t - item[1]["to_s"])))[0]

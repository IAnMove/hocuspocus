"""``worldFx`` in a ``world3d.scene.patch``: 3D effects in the scene (an explosion, a shockwave, sparks, smoke, fire...).

``screenFx`` lays an effect over the frame; ``worldFx`` places one *in* the world, where the renderer draws it with
depth, light and bloom (``worldSfx`` of the document, ``ui/src/features/sceneFx/world.ts``). Each cue is::

    {id?, kind, start, end?, at, scale?, color?, intensity?, sound?, volume?, to?}

``at`` is where, and it is one of:

- ``[x, y, z]`` metres in the scene (within 50 m of the origin: the editor cannot place a cue farther);
- ``{object_id, offset?}`` a point in the object's own frame, ``offset`` ``[x, y, z]`` metres from its ``position`` (a grounded
  object's feet), turning with it: the cue is stored as the editor's own ``anchor: {slotId, offset}`` so it follows an object
  that moves, and the editor shows and moves it like any anchored cue;
- ``{collision: n}`` the middle of ``layout.collisions[n]`` of this scene (as the patch leaves it).

``kind`` is a world effect of ``scene_commands.WORLD_KINDS``; ``id`` starts with ``fx-`` (one is made when absent). A patch
that carries ``worldFx`` replaces the earlier ``fx-*`` cues and leaves the template's own, like ``screenFx``; ``[]`` removes
them. ``end`` defaults to a length that suits the kind and never goes past the end of the scene. A beam (lightning,
energy_beam, laser, arcane_missiles) may say where it ends with ``to``, in the same shapes as ``at`` but not a collision.
"""
from __future__ import annotations

import math
import re
import zlib
from typing import Any

from services.scene_commands import WORLD_KINDS
from services.world3d_scene_bounds import normalisation, slot_native_bounds
from services.world3d_scene_motion import pose_at

FX_PREFIX = "fx-"
MAX_CUES = 160                      # parseWorldSfx keeps at most this many
MAX_AT = 50.0                       # WorldVec: the editor clamps a cue's place to this many metres either way
MAX_ANCHOR = 20.0                   # parseAnchor clamps an offset to this many units of the model either way
BEAMS = frozenset({"lightning", "energy_beam", "laser", "arcane_missiles"})
LENGTH = {"explosion": 2.4, "shockwave": 1.6, "sparks": 1.2, "splash": 1.6, "ice_burst": 1.8, "dust": 2.0, "smoke": 3.0, "fire": 3.0,
          "lightning": 0.8}
DEFAULT_LENGTH = 2.5
NUMBERS = {"scale": (0.05, 20), "intensity": (0.1, 2), "volume": (0, 1)}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_KEYS = {"id", "kind", "start", "end", "at", "to", "sound", *NUMBERS, "color"}
WORLD_FX_DOC = ("worldFx: 3D effects placed in the scene (not over the frame), [{id? (fx-*), kind (one of %s), start (scene s), end? (a length that suits the kind, "
                "never past the scene), at, scale? 0.05-20, intensity? 0.1-2, color? #rrggbb, sound? (true plays the effect's sound), volume? 0-1, to? (a beam's end, "
                "in the shapes of at but not a collision)}]. at is [x, y, z] metres within 50 m of the origin, or {object_id, offset? [x, y, z] metres in the object's "
                "own frame from its position (feet, for a grounded object)}: the cue follows that object when it moves, or {collision: n}: the middle of "
                "layout.collisions[n] as this patch leaves the scene. Replaces earlier fx-* effects and keeps the template's own; [] removes them. "
                "An explosion at a collision: {kind: \"explosion\", start: <the collision's from_s>, at: {collision: 0}}.") % ", ".join(sorted(WORLD_KINDS))


def refusal(index: int | None, message: str):
    from services.world3d_scenes import World3DSceneError
    return World3DSceneError("invalid_world_fx", f"worldFx[{index}] {message}" if index is not None else f"worldFx {message}")


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def set_world_fx(document: dict, cues: Any, collisions: list[dict], workspace: str | None, workspace_dir) -> list[str]:
    """Replace the caller's world effects (``fx-*``) with ``cues`` and keep the template's. Returns warnings; raises ``invalid_world_fx``."""
    if not isinstance(cues, list) or len(cues) > 64:
        raise refusal(None, "must be a list of at most 64 effects")
    context = {"document": document, "collisions": collisions, "workspace": workspace, "workspace_dir": workspace_dir, "warnings": []}
    added, taken = [], set()
    for index, cue in enumerate(cues):
        entry = build_cue(index, cue, context, taken)
        added.append(entry)
        taken.add(entry["id"])
    kept = [cue for cue in document.get("worldSfx") or [] if isinstance(cue, dict) and not str(cue.get("id", "")).startswith(FX_PREFIX)]
    if len(kept) + len(added) > MAX_CUES:
        raise refusal(None, f"would leave {len(kept) + len(added)} world effects in the scene; at most {MAX_CUES}")
    document["worldSfx"] = kept + added
    return context["warnings"]


def build_cue(index: int, cue: Any, context: dict, taken: set[str]) -> dict:
    """One ``worldSfx`` entry from a ``worldFx`` cue (the shape the editor parses), or ``invalid_world_fx``."""
    if not isinstance(cue, dict) or set(cue) - _KEYS:
        raise refusal(index, f"must be {{id?, kind, start, end?, at, scale?, color?, intensity?, sound?, volume?, to?}}; unknown: {sorted(set(cue) - _KEYS) if isinstance(cue, dict) else cue!r}")
    kind = cue.get("kind")
    if kind not in WORLD_KINDS:
        raise refusal(index, f".kind {kind!r} is not a world effect (one of {', '.join(sorted(WORLD_KINDS))})")
    start, end = _span(index, cue, kind, context["document"].get("duration") or 0)
    identifier = _identifier(index, cue, kind, taken)
    entry: dict = {"id": identifier, "kind": kind, "start": start, "end": end, "rotation": {"x": 0, "y": 0, "z": 0}, "seed": _seed(identifier)}
    entry.update(_where(index, cue.get("at"), start, context, allow_collision=True, key="at"))
    for key, (low, high) in NUMBERS.items():
        if cue.get(key) is not None:
            if not _finite(cue[key]) or not low <= cue[key] <= high:
                raise refusal(index, f".{key} must be a number {low}-{high}")
            entry[key] = float(cue[key])
    _flags(index, cue, entry)
    if cue.get("to") is not None:
        _beam_end(index, cue, entry, start, context)
    elif kind in BEAMS:
        context["warnings"].append(f"fx_beam_without_target: worldFx[{index}] {kind} has no \"to\"; it ends where the editor's default puts it")
    return entry


def _span(index: int, cue: dict, kind: str, duration: float) -> tuple[float, float]:
    start = cue.get("start")
    if not _finite(start) or not 0 <= start < 600:
        raise refusal(index, ".start must be a time in the scene, 0-600 seconds")
    if duration and start >= duration:
        raise refusal(index, f".start ({start:g} s) is at or after the end of the scene ({duration:g} s): it would never show")
    end = cue.get("end")
    if end is None:                       # a length that suits the kind, never past the end of the scene
        end = start + LENGTH.get(kind, DEFAULT_LENGTH)
        end = min(end, float(duration)) if duration else end
    elif not _finite(end) or not 0 < end <= 600:
        raise refusal(index, ".end must be a time in the scene, 0-600 seconds")
    end = float(end)
    if end <= start:
        raise refusal(index, f".end ({end:g} s) must come after .start ({start:g} s)")
    return round(float(start), 3), round(end, 3)


def _identifier(index: int, cue: dict, kind: str, taken: set[str]) -> str:
    identifier = cue.get("id")
    if identifier is None:
        identifier = next(f"{FX_PREFIX}{kind}-{number}" for number in range(index + 1, index + 200) if f"{FX_PREFIX}{kind}-{number}" not in taken)
    if not isinstance(identifier, str) or not identifier.startswith(FX_PREFIX) or len(identifier) > 160 or identifier in taken:
        raise refusal(index, f".id must be unique and start with {FX_PREFIX} (the caller's effects; the template's own are left alone)")
    return identifier


def _seed(identifier: str) -> int:
    """The same cue always draws the same way: a seed from its id."""
    return zlib.crc32(identifier.encode()) % 1_000_000 + 1


def _flags(index: int, cue: dict, entry: dict) -> None:
    if cue.get("sound") is not None:
        if not isinstance(cue["sound"], bool):
            raise refusal(index, ".sound must be true or false")
        entry["sound"] = cue["sound"]
    if cue.get("color") is not None:
        if not isinstance(cue["color"], str) or not _COLOR.match(cue["color"]):
            raise refusal(index, ".color must be #rrggbb")
        entry["color"] = cue["color"]


def _beam_end(index: int, cue: dict, entry: dict, start: float, context: dict) -> None:
    if entry["kind"] not in BEAMS:
        raise refusal(index, ".to is where a beam ends: use it on lightning, energy_beam, laser or arcane_missiles")
    found = _where(index, cue["to"], start, context, allow_collision=False, key="to")
    if "anchor" in found:
        entry["target"] = found["anchor"]
        entry["targetPosition"] = found["position"]
    else:
        entry["targetPosition"] = found["position"]


# ----------------------------------------------------------------------------------------------------------------- where

def _where(index: int, spec: Any, start: float, context: dict, *, allow_collision: bool, key: str) -> dict:
    """``{position}`` for a point and ``{position, anchor}`` for an object (``position`` is where the object's point is at ``start``)."""
    if isinstance(spec, (list, tuple)):
        return {"position": _point(index, spec, key)}
    if isinstance(spec, dict) and "collision" in spec and allow_collision and set(spec) == {"collision"}:
        return {"position": _point(index, _collision_at(index, spec["collision"], context["collisions"]), key)}
    if isinstance(spec, dict) and "object_id" in spec and set(spec) <= {"object_id", "offset"}:
        return _object_point(index, spec, start, context, key)
    shapes = "[x, y, z], {object_id, offset?}" + (" or {collision: n}" if allow_collision else "")
    raise refusal(index, f".{key} must be {shapes}")


def _point(index: int, value: Any, key: str) -> dict:
    if len(value) != 3 or not all(_finite(item) for item in value):
        raise refusal(index, f".{key} must be [x, y, z], three numbers in metres")
    if any(abs(item) > MAX_AT for item in value):
        raise refusal(index, f".{key} {list(value)} is farther than {MAX_AT:g} m from the origin: the editor cannot place a world effect there; "
                      "anchor it to an object instead")
    return {"x": round(float(value[0]), 4), "y": round(float(value[1]), 4), "z": round(float(value[2]), 4)}


def _collision_at(index: int, number: Any, collisions: list[dict]) -> list[float]:
    if type(number) is not int or not 0 <= number < len(collisions):
        raise refusal(index, f".at.collision must be a position in layout.collisions, which has {len(collisions)} entries now")
    return collisions[number]["at"]


def _object_point(index: int, spec: dict, start: float, context: dict, key: str) -> dict:
    document = context["document"]
    slot = next((item for item in document.get("slots") or [] if isinstance(item, dict) and item.get("id") == spec["object_id"]), None)
    if slot is None:
        raise refusal(index, f".{key}.object_id {spec['object_id']!r} is not an object of the scene")
    offset = spec.get("offset", [0, 0, 0])
    if not isinstance(offset, (list, tuple)) or len(offset) != 3 or not all(_finite(item) for item in offset):
        raise refusal(index, f".{key}.offset must be [x, y, z] metres in the object's own frame")
    position, rotation = pose_at(slot, start, float(document.get("duration") or 0))
    cos, sin = math.cos(rotation), math.sin(rotation)
    world = [position[0] + offset[0] * cos + offset[2] * sin, position[1] + offset[1], position[2] - offset[0] * sin + offset[2] * cos]
    where = {"position": {axis: round(max(-MAX_AT, min(MAX_AT, value)), 4) for axis, value in zip("xyz", world)}}
    local = _local_offset(slot, offset, context)
    if local is None:
        context["warnings"].append(f"fx_anchor_fixed: worldFx[{index}] {slot['id']} cannot be measured (no readable workspace .glb), "
                                   f"so the effect stays at {[round(value, 2) for value in world]} and does not follow it")
        return where
    if any(abs(value) > MAX_ANCHOR for value in local.values()):
        raise refusal(index, f".{key}.offset is farther than the editor keeps an anchored cue ({MAX_ANCHOR:g} units of the model); use a smaller offset")
    return {**where, "anchor": {"slotId": slot["id"], "offset": local}}


def _local_offset(slot: dict, offset, context: dict) -> dict | None:
    """Metres in the object's frame as the editor's anchor offset, which is in the model's own units: the renderer draws a
    model at ``1.7 / its height x scale`` (``normalisation``), and a grounded one stands with its lowest point at ``position[1]``."""
    workspace = context["workspace"]
    if (slot.get("media") or "model3d") != "model3d" or not workspace or context["workspace_dir"] is None:
        return None
    box = slot_native_bounds(slot, workspace, context["workspace_dir"])
    if not box["ok"]:
        return None
    factor = normalisation(box) * float(slot.get("scale") or 1)
    floor = box["min"][1] if slot.get("grounded") else 0.0
    return {"x": round(offset[0] / factor, 5), "y": round(offset[1] / factor + floor, 5), "z": round(offset[2] / factor, 5)}


# ---------------------------------------------------------------------------------------------------------------- reading

def world_fx_view(document: dict) -> list[dict]:
    """The world effects of a scene as an agent reads them: ``fx-*`` are the caller's, the others the template's."""
    rows = []
    for cue in document.get("worldSfx") or []:
        if not isinstance(cue, dict):
            continue
        position = cue.get("position") if isinstance(cue.get("position"), dict) else {}
        row = {"id": cue.get("id"), "kind": cue.get("kind"), "start": cue.get("start"), "end": cue.get("end"),
               "at": [position.get(axis) for axis in "xyz"], "own": str(cue.get("id", "")).startswith(FX_PREFIX)}
        if isinstance(cue.get("anchor"), dict):
            row["anchoredTo"] = cue["anchor"].get("slotId")
        rows.append(row)
    return rows


def world_fx_problems(document: dict) -> list[str]:
    """What ``parseWorldSfx`` would drop from the scene's world effects: a duplicate id, an end that is not after the start,
    and (for the caller's ``fx-*`` cues) a kind the editor does not know. The editor opens the scene either way."""
    cues = document.get("worldSfx")
    if not isinstance(cues, list):
        return []
    problems, seen = [], set()
    if len(cues) > MAX_CUES:
        problems.append(f"worldSfx has {len(cues)} cues; the editor keeps the first {MAX_CUES}")
    for index, cue in enumerate(cues[:MAX_CUES]):
        if not isinstance(cue, dict):
            problems.append(f"worldSfx[{index}] is not an object; the editor drops it")
            continue
        identifier = cue.get("id") if isinstance(cue.get("id"), str) and cue.get("id") else f"world-fx-{index}"
        if _finite(cue.get("start")) and _finite(cue.get("end")) and cue["end"] <= cue["start"]:
            problems.append(f"worldSfx[{index}] ends before it starts; the editor drops it")
        elif identifier in seen:
            problems.append(f"worldSfx[{index}] repeats the id {identifier!r}; the editor drops it")
        else:
            seen.add(identifier)
        if identifier.startswith(FX_PREFIX) and cue.get("kind") not in WORLD_KINDS:
            problems.append(f"worldSfx[{index}] has the unknown kind {cue.get('kind')!r}; the editor drops it")
    return problems

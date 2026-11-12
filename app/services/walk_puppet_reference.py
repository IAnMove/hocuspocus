"""The reference drawing of a puppet walk: checked before anything is cut, drawn again when it will not cut.

A puppet is cut from ONE drawing (``services/walk_puppet.py``), so a bad drawing is twelve bad frames. The drawing used to be made once and
used as it came: with no check that it shows the pose it was asked for, and with a hard failure of the whole job when the pose model missed a
joint. Now every candidate is looked at first, before the See-through layers are made (which cost the GPU):

* the pose model must find the fourteen joints the cut needs (``find_joints``);
* a reference that has a guide (a pose of a catalog walk: it was drawn over the walk of ``services/walk_guides.py`` at its phase) must have
  the legs as wide as that guide's, within ``guide.tolerance`` (the measure of ``services/character_animation_guides.py``). The front walk is cut
  from the rest pose of ``idle``, which has no guide: for it the joints are the whole check.

A pose of the kit that is already there is the first candidate. When it does not pass, or the kit has none, the job draws one (``draw``)
with a new seed, at most ``guide.puppet.tries`` times, and takes the first that passes. When none does, the one with all its joints and the
legs nearest its guide stays, with a warning; when none has its joints the cut cannot be made and ``WalkPuppetError`` goes up, which the job
answers by drawing the walk pose by pose instead.
"""
from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

import numpy as np
from PIL import Image

from services.character_animation_directions import contract_of
from services.character_animations import animation_def, catalog
from services.walk_guides import TURN, expected_spread, leg_spread, phase_of
from services.walk_puppet import WalkPuppetError


def tries() -> int:
    """How many drawings a reference may take (``guide.puppet.tries`` of the catalog, at least one)."""
    return max(1, int((catalog().get("guide") or {}).get("puppet", {}).get("tries", 3)))


def reference_gait(rgba: np.ndarray, animation: str, pose: str) -> dict[str, Any] | None:
    """The legs of a keyed reference against the guide of its pose: ``{"expected", "measured", "ok"}``; None for a pose that has no guide."""
    try:
        definition = animation_def(animation)
    except Exception:  # noqa: BLE001 - an animation the catalog does not know has no guide to compare with
        return None
    ids = [item["id"] for item in definition["poses"]]
    direction = contract_of(definition["id"], definition).get("dir")
    if definition.get("guide") != "walk" or pose not in ids or direction not in TURN:
        return None
    expected = expected_spread(direction, phase_of(ids.index(pose), len(ids)))
    measured = leg_spread(Image.fromarray(rgba), int(catalog()["sheet"]["alphaFloor"]))
    return {"expected": round(expected, 3), "measured": round(measured, 3), "ok": abs(measured - expected) <= float((catalog().get("guide") or {}).get("tolerance", 0.18))}


def look(rgba: np.ndarray, animation: str, pose: str, find: Callable[[np.ndarray], dict[str, Any]]) -> dict[str, Any]:
    """What one candidate shows: ``joints`` (None when the pose model missed some), ``missing`` (why), ``gait`` and ``ok`` (joints and gait)."""
    try:
        joints, missing = find(rgba), ""
    except WalkPuppetError as error:
        joints, missing = None, str(error)
    gait = reference_gait(rgba, animation, pose)
    return {"joints": joints, "missing": missing, "gait": gait, "ok": joints is not None and (gait is None or bool(gait["ok"]))}


def _miss(found: dict[str, Any]) -> float:
    gait = found["gait"]
    return abs(gait["measured"] - gait["expected"]) if gait else 0.0


def pick(*, animation: str, pose: str, source: str, draw: Callable[[str, str, int, int], str], load: Callable[[str], np.ndarray],
         find: Callable[[np.ndarray], dict[str, Any]], seed: int) -> dict[str, Any]:
    """The reference to cut: ``{"source", "rgba", "joints", "gait", "attempts", "ok"}``. ``source`` is the kit's own picture of the pose ('' when
    it has none); ``draw(animation, pose, seed, attempt)`` makes another; ``seed`` is the first seed (the others are random).
    ``attempts`` lists every candidate looked at (source, whether its joints were found, its gait and whether it passed)."""
    candidates: list[dict[str, Any]] = []
    held = source
    for attempt in range(tries() + (1 if source else 0)):
        if not held:
            held = draw(animation, pose, seed if not candidates else random.randrange(2_000_000_000), len(candidates))
        rgba = load(held)
        shown = look(rgba, animation, pose, find)
        candidates.append({"source": held, "rgba": rgba, **shown})
        if shown["ok"]:
            break
        held = ""
    usable = [item for item in candidates if item["joints"] is not None]
    if not usable:
        raise WalkPuppetError(candidates[0]["missing"] or "the pose model found no joints on the reference drawing")
    chosen = next((item for item in candidates if item["ok"]), None) or min(usable, key=_miss)
    return {**chosen, "ok": bool(chosen["ok"]), "attempts": [{"source": item["source"], "joints": item["joints"] is not None, "gait": item["gait"], "ok": item["ok"]}
                                                           for item in candidates]}

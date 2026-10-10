"""Looping clips for the standard humanoid, baked on a rig's real proportions.

``clip_library`` returns, per clip, its keyframe times, a local rotation track
for every moving bone and a Hips translation track. Rotations are the stored
rig's local rotations, so they can be written straight into its GLB. The loop
closes exactly: the last key equals the first. A hold (``loop: false``, such
as Kneel Pray) instead ends in the pose it keeps, for a slot that plays it once.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from services.humanoid_rig.clip_recipes import HOLDS, RECIPES
from services.humanoid_rig.contacts import foot_contacts
from services.humanoid_rig.errors import InvalidInput
from services.humanoid_rig.motion import Pose, Rig, bake_with_frames
from services.humanoid_rig.names import BONE_NAMES, CLIP_IDS, CLIP_INFO, CLIP_LABELS

FPS = 30

__all__ = ["FPS", "clip_catalog", "clip_library", "default_rig", "rig_for_skeleton"]

if set(RECIPES) != set(CLIP_IDS) or set(CLIP_INFO) != set(CLIP_IDS) or not HOLDS <= set(CLIP_IDS):
    raise RuntimeError("clip table does not match CLIP_IDS")


def clip_catalog() -> list[dict]:
    return [
        {"id": clip_id, "label": CLIP_LABELS[clip_id], "description": CLIP_INFO[clip_id][1], "category": CLIP_INFO[clip_id][0],
         "beats": RECIPES[clip_id][0], "loop": clip_id not in HOLDS}
        for clip_id in CLIP_IDS
    ]


def clip_library(bpm: float, ids: list[str] | None = None, rig: Rig | None = None) -> list[dict]:
    """Return in-place clips at ``bpm`` for ``ids`` (default: all) on ``rig``. Only the ``HOLDS`` do not loop."""
    tempo = _require_bpm(bpm)
    target = rig or default_rig()
    return [_build_clip(clip_id, tempo, target) for clip_id in _select_ids(ids)]


def rig_for_skeleton(skeleton: dict, limits: dict | None = None) -> Rig:
    """The motion rig of a freshly built skeleton."""
    return Rig(skeleton["bones"], skeleton["frames"], facing=skeleton["facing"], floor=skeleton["y_min"],
               scale=skeleton["scale"], limits=limits)


@lru_cache(maxsize=1)
def default_rig() -> Rig:
    """A 1.7 m T-pose adult, for catalogs and tests without a mesh."""
    from services.humanoid_rig.skeleton import build_skeleton

    points = {
        "crotch": (0.0, 0.82, 0.0), "neck": (0.0, 1.47, 0.0), "head": (0.0, 1.53, 0.02), "crown": (0.0, 1.70, 0.02),
    }
    for side, sign in (("left", 1.0), ("right", -1.0)):
        points.update({
            f"{side}_hip": (sign * 0.10, 0.90, 0.0), f"{side}_knee": (sign * 0.095, 0.49, 0.01),
            f"{side}_ankle": (sign * 0.09, 0.076, 0.0), f"{side}_ball": (sign * 0.09, 0.03, 0.12),
            f"{side}_toe": (sign * 0.09, 0.017, 0.19), f"{side}_shoulder": (sign * 0.19, 1.38, 0.0),
            f"{side}_elbow": (sign * 0.47, 1.38, 0.0), f"{side}_wrist": (sign * 0.72, 1.38, 0.0),
            f"{side}_hand_tip": (sign * 0.89, 1.38, 0.0),
        })
    skeleton = build_skeleton({name: np.asarray(value) for name, value in points.items()}, 1.70, 0.0)
    return rig_for_skeleton(skeleton)


def _build_clip(clip_id: str, bpm: float, rig: Rig) -> dict:
    beats, author = RECIPES[clip_id]
    duration = beats * 60.0 / bpm
    count = max(2, int(math.ceil(duration * FPS))) + 1
    times = np.linspace(0.0, duration, count)
    u = times / duration
    pose = Pose(rig, u)
    author(pose, u)
    local, root, positions, worlds = bake_with_frames(pose)
    loop = clip_id not in HOLDS
    if loop:
        _close_loop(local, root)
    rotations = {name: local[:, index] for index, name in enumerate(BONE_NAMES) if not name.endswith("_End")}
    return {
        "id": clip_id,
        "name": CLIP_LABELS[clip_id],
        "bpm": bpm,
        "beats": beats,
        "duration": duration,
        "times": times,
        "rotations": rotations,
        "hips_translation": root,
        "loop": loop,
        "contacts": foot_contacts(rig, times, positions, worlds, loop=loop),
    }


def _close_loop(local: np.ndarray, root: np.ndarray) -> None:
    """Pin the last key to the first, so float noise never shows a seam."""
    for index in range(local.shape[1]):
        first = local[0, index]
        local[-1, index] = first if float(first @ local[-2, index]) >= 0.0 else -first
    root[-1] = root[0]


def _require_bpm(bpm: float) -> float:
    value = float(bpm)
    if not math.isfinite(value) or value < 60.0 or value > 180.0:
        raise InvalidInput("bpm must be finite and in [60, 180]")
    return value


def _select_ids(ids: list[str] | None) -> tuple[str, ...]:
    chosen = CLIP_IDS if ids is None else tuple(ids)
    unknown = [item for item in chosen if item not in CLIP_LABELS]
    if unknown:
        raise InvalidInput(f"unknown clip id: {unknown[0]}")
    return chosen

"""Rig a humanoid GLB on CPU: landmarks, Mixamo skeleton, weights, skin and clips."""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.names import BONE_NAMES

RIG_VERSION = 2


def rig_humanoid(source: bytes, clip_ids: list[str] | None = None, bpm: float = 120.0) -> tuple[bytes, dict]:
    """Return ``(glb, sidecar)``. Raises ``NotHumanoid`` when the mesh is not a person."""
    from services.humanoid_rig.clips import clip_library, rig_for_skeleton
    from services.humanoid_rig.comfort import comfort_limits
    from services.humanoid_rig.gltf_export import read_primitives, write_rigged_glb
    from services.humanoid_rig.landmarks import detect_landmarks
    from services.humanoid_rig.skeleton import build_skeleton
    from services.humanoid_rig.weights import compute_weights

    primitives = read_primitives(bytes(source))
    positions, indices, counts = _combined(primitives)
    found = detect_landmarks(positions, indices)
    skeleton = build_skeleton(found["points"], found["height"], found["y_min"], found["facing"], found["head_region"], found["base"],
                              found["robe"])
    joints, weights = compute_weights(positions, indices, skeleton, found["cloth"])
    limits = comfort_limits(positions, indices, joints, weights, skeleton)
    clips = clip_library(bpm, list(clip_ids or ["idle"]), rig_for_skeleton(skeleton, limits))
    marker = rig_marker(skeleton, limits)
    rigged = write_rigged_glb(bytes(source), skeleton, _split(joints, weights, counts), clips, marker)
    return rigged, _sidecar(found, skeleton, limits, clips)


def rig_marker(skeleton: dict, limits: dict) -> dict:
    """Facts stored on the Hips node, so later clips fit this exact body."""
    return {
        "version": RIG_VERSION,
        "height": round(float(skeleton["height"]), 6),
        "floor": round(float(skeleton["y_min"]), 6),
        "facing": int(skeleton["facing"]),
        "arm_down": float(limits["arm_down"]),
        "arm_up": float(limits["arm_up"]),
        "swing_up": float(limits["swing_up"]),
        "chest_front": float(limits["chest_front"]),
    }


def _combined(primitives: list[dict]) -> tuple[np.ndarray, np.ndarray, list[int]]:
    if not primitives:
        raise NotHumanoid("degenerate")
    positions, faces, counts = [], [], []
    offset = 0
    for item in primitives:
        world = np.asarray(item["world"], dtype=np.float64)
        indices = item["indices"]
        if indices is None:
            indices = np.arange(len(world) - len(world) % 3, dtype=np.int64).reshape(-1, 3)
        positions.append(world)
        faces.append(np.asarray(indices, dtype=np.int64) + offset)
        counts.append(len(world))
        offset += len(world)
    return np.vstack(positions), np.vstack(faces), counts


def _split(joints: np.ndarray, weights: np.ndarray, counts: list[int]) -> list[tuple[np.ndarray, np.ndarray]]:
    groups = []
    start = 0
    for count in counts:
        groups.append((joints[start:start + count], weights[start:start + count]))
        start += count
    return groups


def _sidecar(found: dict, skeleton: dict, limits: dict, clips: list[dict]) -> dict:
    return {
        "version": RIG_VERSION,
        "landmarks": found["points"],
        "confidence": found["confidence"],
        "warnings": list(found["warnings"]),
        "pose": found["pose"],
        "arm_drop": found["arm_drop"],
        "facing": found["facing"],
        "height": found["height"],
        "scale": skeleton["scale"],
        "limits": limits,
        "bones": list(BONE_NAMES),
        "clips": [{"index": index, "id": clip["id"], "name": clip["name"], "duration": clip["duration"],
                   "loop": clip.get("loop", True), "contacts": clip.get("contacts", [])} for index, clip in enumerate(clips)],
    }

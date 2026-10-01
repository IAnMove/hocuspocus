"""Rig a humanoid GLB on CPU: landmarks, Mixamo skeleton, weights, skin."""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.names import BONE_NAMES
from services.humanoid_rig.skeleton import build_skeleton
from services.humanoid_rig.weights import compute_weights


def rig_humanoid(source: bytes, clips: list[dict] | None = None) -> tuple[bytes, dict]:
    """Return ``(glb, sidecar)``. Raises ``NotHumanoid`` when the mesh is not a person."""
    from services.humanoid_rig.gltf_export import read_primitives, write_rigged_glb

    primitives = read_primitives(bytes(source))
    positions, indices = _combined(primitives)
    found = detect_landmarks(positions, indices)
    skeleton = build_skeleton(found["points"], found["height"], found["y_min"])
    influences = [compute_weights(item["world"], item["indices"], skeleton) for item in primitives]
    rigged = write_rigged_glb(bytes(source), skeleton, influences, clips)
    return rigged, _sidecar(found, skeleton)


def _combined(primitives: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    if not primitives:
        raise NotHumanoid("degenerate")
    positions = []
    faces = []
    offset = 0
    for item in primitives:
        world = np.asarray(item["world"], dtype=np.float64)
        positions.append(world)
        indices = item["indices"]
        if indices is None:
            indices = np.arange(len(world), dtype=np.int64).reshape(-1, 3)
        faces.append(np.asarray(indices, dtype=np.int64) + offset)
        offset += len(world)
    return np.vstack(positions), np.vstack(faces)


def _sidecar(found: dict, skeleton: dict) -> dict:
    return {
        "landmarks": found["points"],
        "confidence": found["confidence"],
        "warnings": list(found["warnings"]),
        "height": found["height"],
        "scale": skeleton["scale"],
        "bones": list(BONE_NAMES),
    }

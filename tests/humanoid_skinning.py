"""Reference skinning for tests: what a glTF viewer does with the exported skeleton."""

from __future__ import annotations

import numpy as np

from services.humanoid_rig import rotation as rot


def batch_worlds(bones: list[dict], local: np.ndarray, root_translation: np.ndarray | None = None) -> np.ndarray:
    """World matrices ``(F, B, 4, 4)`` for local rotations ``(F, B, 4)``."""
    frames = local.shape[0]
    index = {bone["name"]: position for position, bone in enumerate(bones)}
    out = np.zeros((frames, len(bones), 4, 4))
    for position, bone in enumerate(bones):
        matrix = np.zeros((frames, 4, 4))
        matrix[:, :3, :3] = rot.to_matrix(local[:, position]) * np.asarray(bone["scale"], dtype=np.float64)[None, None, :]
        translation = bone["translation"] if root_translation is None or bone["parent"] is not None else root_translation
        matrix[:, :3, 3] = translation
        matrix[:, 3, 3] = 1.0
        parent = bone["parent"]
        out[:, position] = matrix if parent is None else out[:, index[parent]] @ matrix
    return out


def skin_vertices(
    vertices: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    bind_worlds: list[np.ndarray],
    anim_worlds: list[np.ndarray],
) -> np.ndarray:
    """Linear blend skinning with ``inverseBind = inverse(bind world)``. At rest the mesh is unchanged."""
    points = np.asarray(vertices, dtype=np.float64)
    skinned = np.zeros_like(points)
    for influence in range(joints.shape[1]):
        weight = weights[:, influence].astype(np.float64)
        active = weight > 0
        if not np.any(active):
            continue
        chosen = joints[active, influence]
        rows = np.flatnonzero(active)
        for joint in np.unique(chosen):
            mask = rows[chosen == joint]
            matrix = anim_worlds[int(joint)] @ np.linalg.inv(bind_worlds[int(joint)])
            skinned[mask] += weight[mask, None] * (points[mask] @ matrix[:3, :3].T + matrix[:3, 3])
    return skinned

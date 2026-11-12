"""Where the points of a model object's GLB land in the scene, and back: the renderer's ``fitGltf`` and grounding as a matrix.

A model object is scaled about its GLB origin by ``1.7 / box height x scale`` (``normalisation``), turned by Euler XYZ
(``rotationX/Y/Z``), moved to ``position``; a ``grounded`` one is lifted so the lowest corner of its turned box sits at
``position[1]`` (``placed_bounds``, ``groundLoadedSlot``). ``SlotFrame`` does the same sums on numpy points, so a seat
found in a chair's own units, or a joint of a character's clip, can be put in the scene, and a scene point taken into
a model's own units (a seat point for ``sit_clip``).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from services.world3d_scene_bounds import _euler_xyz, _tilt, normalisation


@dataclass
class SlotFrame:
    factor: float              # native units -> metres
    rotation: np.ndarray       # 3 x 3
    offset: np.ndarray         # where the GLB origin lands

    def to_world(self, points) -> np.ndarray:
        return np.asarray(points, dtype=np.float64) * self.factor @ self.rotation.T + self.offset

    def to_native(self, points) -> np.ndarray:
        return (np.asarray(points, dtype=np.float64) - self.offset) @ self.rotation / self.factor

    def direction(self, local_xz) -> np.ndarray:
        """A direction on the GLB's floor (x, z) as a unit direction on the scene floor (x, z)."""
        turned = self.rotation @ np.array([local_xz[0], 0.0, local_xz[1]], dtype=np.float64)
        flat = np.array([turned[0], turned[2]])
        return flat / max(np.linalg.norm(flat), 1e-12)


def slot_frame(slot: dict, box: dict, *, grounded_low: float | None = None) -> SlotFrame:
    """The frame of a model slot whose native box is ``box`` (``glb_bounds``). ``grounded_low``: the native y of the
    lowest point for a grounded slot when it is not the box's own (a posed character)."""
    factor = normalisation(box) * float(slot.get("scale") or 1)
    rotation = np.asarray(_euler_xyz(_tilt(slot, "rotationX"), _tilt(slot, "rotationY"), _tilt(slot, "rotationZ")), dtype=np.float64)
    position = np.asarray([float(value) for value in slot.get("position") or [0, 0, 0]], dtype=np.float64)
    offset = position.copy()
    if slot.get("grounded"):
        if grounded_low is None:
            corners = np.array([[x, y, z] for x in (box["min"][0], box["max"][0]) for y in (box["min"][1], box["max"][1])
                                for z in (box["min"][2], box["max"][2])], dtype=np.float64)
            lowest = float((corners * factor @ rotation.T)[:, 1].min())
        else:
            lowest = float((np.array([0.0, grounded_low, 0.0]) * factor @ rotation.T)[1])
        offset[1] = position[1] - lowest
    return SlotFrame(factor, rotation, offset)


def yaw_of(direction_xz) -> float:
    """The ``rotationY`` (radians) that turns a model's +z onto a scene floor direction (x, z)."""
    return float(np.arctan2(direction_xz[0], direction_xz[1]))

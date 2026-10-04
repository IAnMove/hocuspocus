"""Turn silhouette pixels into 3D landmarks: X and Y from the mask, Z from the mesh.

Each joint takes the middle of the mesh cross-section through it, so a belly,
a backpack or a forward-leaning neck moves the joint with the body.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.silhouette import Silhouette

_UP = np.array([0.0, 1.0])


class Depth:
    def __init__(self, vertices: np.ndarray, silhouette: Silhouette, height: float, y_min: float, floor: float | None = None) -> None:
        self.vertices = vertices
        self.silhouette = silhouette
        self.height = height
        self.y_max = y_min + height
        # Feet stand on ``floor``: the mesh bottom, or the top of a pedestal.
        self.y_min = y_min if floor is None else floor

    def xy(self, pixel) -> np.ndarray:
        x, y = self.silhouette.to_metres(float(pixel[0]), float(pixel[1]))
        return np.array([x, y])

    def section_z(self, point: np.ndarray, direction: np.ndarray, band: float, radius: float) -> float:
        """Middle depth of the mesh slab through ``point`` across ``direction``."""
        delta = self.vertices[:, :2] - point
        along = np.abs(delta @ direction)
        across = np.abs(delta @ np.array([-direction[1], direction[0]]))
        for widen in (1.0, 2.0, 4.0):
            chosen = self.vertices[(along <= band * widen) & (across <= radius * widen), 2]
            if len(chosen) >= 6:
                return float(np.percentile(chosen, 3) + np.percentile(chosen, 97)) * 0.5
        return float(np.median(self.vertices[:, 2]))

    def spine(self, legs: dict, neck: dict, half: float) -> dict:
        pixel = self.silhouette.pixel
        crotch_xy = self.xy((legs["crotch_row"], legs["crotch_col"]))
        crotch_z = self.section_z(crotch_xy + _UP * self.height * 0.02, _UP, self.height * 0.02, half * pixel * 0.8)
        neck_xy = self.xy((neck["row"], neck["col"]))
        neck_half = max(neck["width"] * 0.5 * pixel, self.height * 0.02)
        neck_z = self.section_z(neck_xy, _UP, self.height * 0.015, neck_half)
        head_y = neck_xy[1] + min((self.y_max - neck_xy[1]) * 0.25, self.height * 0.04)
        head_z = self.section_z(np.array([neck_xy[0], head_y]), _UP, self.height * 0.015, neck_half * 1.3)
        return {
            "crotch": np.array([crotch_xy[0], crotch_xy[1], crotch_z]),
            "neck": np.array([neck_xy[0], neck_xy[1], neck_z]),
            "head": np.array([neck_xy[0], head_y, head_z]),
            "crown": self._crown(),
        }

    def _crown(self) -> np.ndarray:
        top = self.vertices[self.vertices[:, 1] >= self.y_max - self.height * 0.012]
        return np.array([float(top[:, 0].mean()), self.y_max, float(top[:, 2].mean())])

    def leg(self, side: str, region: np.ndarray, legs: dict, crotch: np.ndarray, center_of) -> dict:
        tall = legs["top"] - legs["floor"] + 1
        hip_row = legs["crotch_row"] - max(2, int(tall * 0.03))
        hip_x = self._leg_x(region, hip_row, center_of)
        hip = np.array([hip_x, float(crotch[1]) + self._half_width(region, hip_row) * 0.9, float(crotch[2])])
        ankle_y = self.y_min + min(self.height * 0.045, (float(crotch[1]) - self.y_min) * 0.25)
        ankle = self._leg_point(region, ankle_y, center_of, lift=self.height * 0.015)
        knee = self._leg_point(region, (float(hip[1]) + ankle_y) * 0.5, center_of)
        ball, toe = self._foot(ankle, region)
        return {f"{side}_hip": hip, f"{side}_knee": knee, f"{side}_ankle": ankle, f"{side}_ball": ball, f"{side}_toe": toe}

    def _leg_x(self, region: np.ndarray, row: int, center_of) -> float:
        col = center_of(region, int(np.clip(row, 0, region.shape[0] - 1)))
        if col is None:
            raise NotHumanoid("single_leg")
        return float(self.xy((row, col))[0])

    def _half_width(self, region: np.ndarray, row: int) -> float:
        cols = np.flatnonzero(region[int(np.clip(row, 0, region.shape[0] - 1))])
        if len(cols) == 0:
            return self.height * 0.015
        return max((cols.max() - cols.min() + 1) * 0.5 * self.silhouette.pixel, self.height * 0.015)

    def _leg_point(self, region: np.ndarray, y: float, center_of, lift: float = 0.0) -> np.ndarray:
        row = int(np.clip(self.silhouette.row_of(y), 0, region.shape[0] - 1))
        x = self._leg_x(region, row, center_of)
        z = self.section_z(np.array([x, y + lift]), _UP, self.height * 0.012, self._half_width(region, row))
        return np.array([x, y, z])

    def _foot(self, ankle: np.ndarray, region: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        reach = self.height * 0.05
        near = self.vertices[(self.vertices[:, 1] < float(ankle[1]) + self.height * 0.01) & (np.abs(self.vertices[:, 0] - float(ankle[0])) < reach)]
        toe_z = float(np.percentile(near[:, 2], 98)) if len(near) >= 6 else float(ankle[2])
        toe_z = max(toe_z, float(ankle[2]) + self.height * 0.025)
        toe = np.array([float(ankle[0]), self.y_min + self.height * 0.01, toe_z])
        ball_z = float(ankle[2]) + (toe_z - float(ankle[2])) * 0.65
        ball = np.array([float(ankle[0]), self.y_min + self.height * 0.018, ball_z])
        return ball, toe

    def arm(self, side: str, line: dict) -> dict:
        pixel = self.silhouette.pixel
        radius = max(line["radius"] * pixel * 1.4, self.height * 0.015)
        band = self.height * 0.012
        shoulder, elbow, wrist, tip = (self.xy(line[name]) for name in ("shoulder", "elbow", "wrist", "tip"))
        upper, lower, hand = _unit(elbow - shoulder), _unit(wrist - elbow), _unit(tip - wrist)
        tip_probe = tip - hand * self.height * 0.01
        return {
            f"{side}_shoulder": np.array([*shoulder, self.section_z(shoulder + upper * radius * 0.5, upper, band, radius)]),
            f"{side}_elbow": np.array([*elbow, self.section_z(elbow, upper, band, radius)]),
            f"{side}_wrist": np.array([*wrist, self.section_z(wrist, lower, band, radius)]),
            f"{side}_hand_tip": np.array([*tip, self.section_z(tip_probe, hand, band, radius)]),
        }


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    return vector / length if length > 1e-9 else np.array([1.0, 0.0])

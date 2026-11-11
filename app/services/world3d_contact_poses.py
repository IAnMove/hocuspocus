"""The people and the furniture of a Video 3D scene, measured for the contact check (``world3d_scene_contacts``).

A *person* is a model object whose GLB has the standard humanoid skeleton: its joints at the pose it shows at a scene
second (``world3d_body_pose``), in scene metres, with its floor and lengths. A *piece* is any other model object no
bigger than ``PIECE_M`` on every side whose triangles can be read (``world3d_mesh_solid``): a chair, a table, a bed.
A whole room or a village is not a piece; the collision check covers those for things that move.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from services.world3d_body_pose import Body, body_of, held_time, measures
from services.world3d_mesh_solid import Mesh, crossings, inside, mesh_of
from services.world3d_scene_bounds import resolve_workspace_glb, slot_native_bounds, slot_native_parts
from services.world3d_slot_frame import SlotFrame, slot_frame

PIECE_M = 6.0
SEGMENTS = (("left thigh", "LeftUpLeg", "LeftLeg"), ("right thigh", "RightUpLeg", "RightLeg"), ("left shin", "LeftLeg", "LeftFoot"),
            ("right shin", "RightLeg", "RightFoot"), ("left upper arm", "LeftArm", "LeftForeArm"), ("right upper arm", "RightArm", "RightForeArm"),
            ("left forearm", "LeftForeArm", "LeftHand"), ("right forearm", "RightForeArm", "RightHand"), ("back", "Hips", "Spine2"),
            ("neck", "Spine2", "Head"))
CORE = ("Hips", "Spine2", "Head")
_SAMPLES = 5


@dataclass
class Piece:
    slot: dict
    box: dict
    parts: list
    mesh: Mesh
    frame: SlotFrame

    @property
    def id(self) -> str:
        return str(self.slot.get("id"))

    def drawn_height(self) -> float:
        return self.box["size"][1] * self.frame.factor

    def floor_y(self) -> float:
        low, high = self.box["min"], self.box["max"]
        corners = np.array([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])])
        return float(self.frame.to_world(corners)[:, 1].min())

    def depth(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """How deep each scene point is inside the piece (metres) and the part it is in."""
        depth, part = inside(self.mesh, self.frame.to_native(points))
        return depth * self.frame.factor, part

    def crossed(self, start: np.ndarray, end: np.ndarray) -> np.ndarray:
        """The parts whose faces a scene segment crosses."""
        native = self.frame.to_native([start, end])
        return crossings(self.mesh, native[0], native[1])

    def part_name(self, index: int) -> str:
        name = self.mesh.names[index] if 0 <= index < len(self.mesh.names) else None
        return f'part {index} "{name}"' if name else f"part {index}"


@dataclass
class Person:
    slot: dict
    body: Body
    frame: SlotFrame
    joints: dict              # scene metres
    rest: dict                # native rest joints
    size: dict                # metres: thigh, shank, leg, arm, forearm
    floor: float              # scene y of the soles at rest
    held: bool

    @property
    def id(self) -> str:
        return str(self.slot.get("id"))

    @property
    def hips_height(self) -> float:
        return float(self.joints["Hips"][1] - self.floor)

    @property
    def rest_hips_height(self) -> float:
        return float((self.rest["Hips"][1] - self.body.box_low) * self.frame.factor)

    @property
    def forward(self) -> np.ndarray:
        return self.frame.direction([0.0, float(self.body.facing)])

    def seated(self) -> bool:
        """Both thighs within 40 degrees of level and both knees bent 65-150 degrees: sitting (on a seat or on nothing),
        whatever the leg length; a deep crouch bends the knees more."""
        for side in ("Left", "Right"):
            thigh = self.joints[f"{side}Leg"] - self.joints[f"{side}UpLeg"]
            shin = self.joints[f"{side}Foot"] - self.joints[f"{side}Leg"]
            lengths = np.linalg.norm(thigh) * np.linalg.norm(shin)
            if lengths < 1e-9 or abs(thigh[1]) > 0.64 * np.linalg.norm(thigh):
                return False
            knee = np.degrees(np.arccos(np.clip(float(-thigh @ shin) / lengths, -1.0, 1.0)))
            if not 65.0 <= knee <= 150.0:
                return False
        return True

    def segments(self) -> list[tuple[str, np.ndarray, np.ndarray]]:
        return [(label, self.joints[start], self.joints[end]) for label, start, end in SEGMENTS if start in self.joints and end in self.joints]

    def samples(self) -> list[tuple[str, np.ndarray]]:
        """Points along the limbs and the back, each with the limb it belongs to."""
        found = []
        for label, start, end in SEGMENTS:
            if start in self.joints and end in self.joints:
                for share in np.linspace(0.0, 1.0, _SAMPLES):
                    found.append((label, self.joints[start] + (self.joints[end] - self.joints[start]) * share))
        return found


def measure_scene(document: dict, workspace: str, workspace_dir, seconds: float) -> tuple[list[Person], list[Piece], dict]:
    """People, pieces of furniture, and the drawn height (metres) and scale of every measurable model object."""
    people, pieces, drawn = [], [], {}
    for slot in document.get("slots") or []:
        if not isinstance(slot, dict) or (slot.get("media") or "model3d") != "model3d" or slot.get("hold") or not slot.get("sourceUrl"):
            continue
        path, _reason = resolve_workspace_glb(slot.get("sourceUrl"), workspace, workspace_dir)
        if path is None:
            continue
        box = slot_native_bounds(slot, workspace, workspace_dir)
        if box.get("ok"):
            drawn[slot.get("id")] = (box["size"][1] * slot_frame(slot, box).factor, float(slot.get("scale") or 1))
        body = body_of(path)
        if body is not None:
            person = _person(slot, body, workspace, workspace_dir, seconds)
            if person is not None:
                people.append(person)
            continue
        piece = _piece(slot, path, workspace, workspace_dir)
        if piece is not None:
            pieces.append(piece)
    return people, pieces, drawn


def _piece(slot: dict, path, workspace: str, workspace_dir) -> Piece | None:
    box = slot_native_bounds(slot, workspace, workspace_dir)
    if not box.get("ok"):
        return None
    frame = slot_frame(slot, box)
    if max(box["size"]) * frame.factor > PIECE_M:
        return None
    mesh = mesh_of(path)
    if mesh is None:
        return None
    return Piece(slot, box, slot_native_parts(slot, workspace, workspace_dir)["parts"], mesh, frame)


def _person(slot: dict, body: Body, workspace: str, workspace_dir, seconds: float) -> Person | None:
    box = slot_native_bounds(slot, workspace, workspace_dir)
    if not box.get("ok"):
        return None
    clip, local, held = held_time(slot, body, seconds)
    native = body.pose(clip, local)
    rest = body.pose()
    lowest = None
    if slot.get("grounded"):
        # The renderer re-grounds a grounded model on its posed mesh; the soles sit this far under the lowest foot joint.
        feet = ("LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase")
        sole = min(rest[name][1] for name in feet if name in rest) - body.box_low
        lowest = min(native[name][1] for name in feet if name in native) - sole
    frame = slot_frame(slot, box, grounded_low=lowest)
    joints = {name: frame.to_world([point])[0] for name, point in native.items()}
    soles = frame.to_world([[0.0, body.box_low if lowest is None else lowest, 0.0]])[0][1]
    size = {key: value * frame.factor for key, value in measures(rest).items()}
    return Person(slot, body, frame, joints, rest, size, float(soles), held)


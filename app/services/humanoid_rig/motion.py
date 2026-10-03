"""Turn canonical poses into keyframes for one rig.

A ``Pose`` holds, per frame, Euler angles in each bone's canonical frame
(identity is the T pose; see ``skeleton``), optional foot and wrist targets
solved with two-bone IK, a root offset and an airborne lift. ``bake`` runs
forward kinematics on the rig's real proportions, keeps the lowest foot point
on the floor, and returns local rotations for the rig as it is stored.

Conventions, in degrees, for the helpers below. Spine, neck, head and hips:
pitch > 0 bends forward, yaw > 0 turns to the character's left, roll > 0
leans to its left. Arms: lift > 0 raises the arm sideways (0 is the T pose),
swing > 0 carries it forward around the shoulder's side axis, sweep > 0
carries it forward around the vertical. Elbow flex > 0 bends; legs are solved
by IK from ankle targets, and their foot pitch > 0 lifts the toes. Foot and root offsets are
in leg lengths (hip to ankle), so a clip fits a mascot and an adult alike; hand
targets are in metres, built by the recipes from the arm length and chest depth.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES, BONE_PARENTS

_PARENT = dict(BONE_PARENTS)
_SIDES = ("Left", "Right")
_X = np.array([1.0, 0.0, 0.0])
_Y = np.array([0.0, 1.0, 0.0])
_Z = np.array([0.0, 0.0, 1.0])


def side_sign(side: str) -> float:
    return 1.0 if side == "Left" else -1.0


class Rig:
    """Canonical geometry of one stored skeleton: offsets, contacts and comfort limits."""

    def __init__(self, bones: list[dict], frames: dict, *, facing: int, floor: float, scale: float, limits: dict | None = None) -> None:
        self.bones = bones
        self.facing = rot.IDENTITY.copy() if facing >= 0 else rot.axis_angle(_Y, 180.0)
        actual = _actual_frames(bones)
        self.correction = np.stack([rot.multiply(rot.inverse(frames[name]), actual[name]) for name in BONE_NAMES])
        self.offsets = np.stack([_canonical_offset(bone, frames, actual, scale) for bone in bones])
        self.rest_local = np.stack([_canonical_local(name, frames, self.facing) for name in BONE_NAMES])
        self.root = np.asarray(bones[0]["translation"], dtype=np.float64)
        self.floor = float(floor)
        self.limits = {"arm_down": 72.0, "arm_up": 130.0, "swing_up": 140.0, **(limits or {})}
        positions, worlds = self.forward(self.rest_local[None], self.root[None])
        self.rest_positions, self.rest_worlds = positions[0], worlds[0]
        self.leg = self.length("LeftUpLeg", "LeftLeg") + self.length("LeftLeg", "LeftFoot")
        self.arm = self.length("LeftArm", "LeftForeArm") + self.length("LeftForeArm", "LeftHand")
        self.limits.setdefault("chest_front", self.leg * 0.15)
        self.contacts = _contacts(self)

    def index(self, name: str) -> int:
        return BONE_BY_NAME[name]

    def length(self, start: str, end: str) -> float:
        return float(np.linalg.norm(self.offsets[self.index(end)])) if _PARENT[end] == start else float(
            np.linalg.norm(self.rest_positions[self.index(end)] - self.rest_positions[self.index(start)]))

    def forward(self, local: np.ndarray, root: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Canonical FK: positions ``(F, B, 3)`` and world rotations ``(F, B, 4)``."""
        count = local.shape[0]
        positions = np.zeros((count, len(BONE_NAMES), 3))
        worlds = np.zeros((count, len(BONE_NAMES), 4))
        for index, name in enumerate(BONE_NAMES):
            parent = _PARENT[name]
            if parent is None:
                positions[:, index] = root
                worlds[:, index] = rot.multiply(np.broadcast_to(self.facing, local[:, index].shape), local[:, index])
                continue
            at = BONE_BY_NAME[parent]
            positions[:, index] = positions[:, at] + rot.rotate(worlds[:, at], np.broadcast_to(self.offsets[index], (count, 3)))
            worlds[:, index] = rot.multiply(worlds[:, at], local[:, index])
        return positions, worlds

    def to_actual(self, worlds: np.ndarray) -> np.ndarray:
        """Local rotations of the stored rig for canonical world rotations."""
        actual = rot.multiply(worlds, self.correction[None])
        local = np.zeros_like(actual)
        for index, name in enumerate(BONE_NAMES):
            parent = _PARENT[name]
            local[:, index] = actual[:, index] if parent is None else rot.multiply(rot.inverse(actual[:, BONE_BY_NAME[parent]]), actual[:, index])
        return np.stack([rot.continuous(rot.normalize(local[:, index])) for index in range(local.shape[1])], axis=1)


class Pose:
    """Per-frame canonical angles, IK targets and lift, starting from a relaxed stance."""

    def __init__(self, rig: Rig, u: np.ndarray) -> None:
        self.rig = rig
        self.u = np.asarray(u, dtype=np.float64)
        count = len(self.u)
        self.angles = np.zeros((count, len(BONE_NAMES), 3))
        self.feet: dict[str, dict] = {}
        self.hands: dict[str, dict] = {}
        self.root = np.zeros((count, 3))
        self.grounded = True
        self.twists = {side: np.zeros(count) for side in _SIDES}
        for side in _SIDES:
            self.arm(side, lift=-rig.limits["arm_down"], swing=6.0)
            self.elbow(side, 14.0)

    def _vector(self, value) -> np.ndarray:
        return np.broadcast_to(np.asarray(value, dtype=np.float64), self.u.shape)

    def _add(self, name: str, axis: int, value) -> None:
        self.angles[:, BONE_BY_NAME[name], axis] += self._vector(value)

    def _set(self, name: str, axis: int, value) -> None:
        self.angles[:, BONE_BY_NAME[name], axis] = self._vector(value)

    def hips(self, pitch=0.0, yaw=0.0, roll=0.0) -> None:
        self._add("Hips", 0, pitch)
        self._add("Hips", 1, yaw)
        self._add("Hips", 2, -self._vector(roll))

    def spine(self, pitch=0.0, yaw=0.0, roll=0.0) -> None:
        for name, share in (("Spine", 0.3), ("Spine1", 0.35), ("Spine2", 0.35)):
            self._add(name, 0, self._vector(pitch) * share)
            self._add(name, 1, self._vector(yaw) * share)
            self._add(name, 2, -self._vector(roll) * share)

    def head(self, pitch=0.0, yaw=0.0, roll=0.0) -> None:
        for name, share in (("Neck", 0.35), ("Head", 0.65)):
            self._add(name, 0, self._vector(pitch) * share)
            self._add(name, 1, self._vector(yaw) * share)
            self._add(name, 2, -self._vector(roll) * share)

    def arm(self, side: str, lift=None, swing=None, sweep=None) -> None:
        sign = side_sign(side)
        if lift is not None:
            self._set(f"{side}Arm", 2, sign * self._vector(lift))
        if sweep is not None:
            self._set(f"{side}Arm", 1, -sign * self._vector(sweep))
        if swing is not None:
            self._set(f"{side}Arm", 0, -self._vector(swing))

    def twist(self, side: str, degrees) -> None:
        """Roll the upper arm about itself; > 0 turns the elbow's bend upward."""
        self.twists[side] = self._vector(degrees).copy()

    def elbow(self, side: str, flex) -> None:
        self._set(f"{side}ForeArm", 1, -side_sign(side) * self._vector(flex))

    def palm(self, side: str, roll) -> None:
        """Roll the hand about the forearm; > 0 turns the palm up. X is normal to the mirror plane, so no side sign."""
        self._set(f"{side}Hand", 0, -self._vector(roll))

    def wrist(self, side: str, flex=0.0, wave=0.0) -> None:
        sign = side_sign(side)
        self._set(f"{side}Hand", 2, -sign * self._vector(flex))
        self._set(f"{side}Hand", 1, -sign * self._vector(wave))

    def clavicle(self, side: str, shrug=0.0, forward=0.0) -> None:
        sign = side_sign(side)
        self._set(f"{side}Shoulder", 2, sign * self._vector(shrug))
        self._set(f"{side}Shoulder", 1, -sign * self._vector(forward))

    def plant(self, side: str, forward=0.0, up=0.0, out=0.0, pitch=0.0, yaw=0.0) -> None:
        """Ankle target as an offset from the rest ankle, in leg lengths. IK solves the leg.

        ``yaw`` turns the planted foot about the vertical, in degrees (> 0 toward the character's left).
        """
        offset = np.stack((side_sign(side) * self._vector(out), self._vector(up), self._vector(forward)), axis=1)
        self.feet[side] = {"offset": offset, "pitch": self._vector(pitch).copy(), "yaw": self._vector(yaw).copy()}

    def reach(self, side: str, target, pole=(0.3, -1.0, -0.5)) -> None:
        """Wrist target in metres from the chest joint, in the chest frame (x mirrored for the right)."""
        sign = side_sign(side)
        goal = np.broadcast_to(np.asarray(target, dtype=np.float64), (len(self.u), 3)) * np.array([sign, 1.0, 1.0])
        self.hands[side] = {"target": goal, "pole": np.asarray(pole, dtype=np.float64) * np.array([sign, 1.0, 1.0])}

    def move_root(self, forward=0.0, up=0.0, side=0.0) -> None:
        """Root offset in leg lengths, before the floor contact is solved."""
        self.root += np.stack((self._vector(side), self._vector(up), self._vector(forward)), axis=1)


def bake(pose: Pose) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(local rotations (F, B, 4), root translations (F, 3))`` for the stored rig."""
    local, root, _positions, _worlds = bake_with_frames(pose)
    return local, root


def bake_with_frames(pose: Pose) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``bake`` plus the canonical joint positions and world rotations of every frame."""
    rig = pose.rig
    root = rig.root[None] + rot.rotate(rig.facing, pose.root * rig.leg)
    local = _euler_locals(pose)
    _solve_feet(pose, local, root)
    _solve_hands(pose, local, root)
    if pose.grounded:
        positions, worlds = rig.forward(local, root)
        root = root.copy()
        root[:, 1] += rig.floor - lowest_contact(rig, positions, worlds)
    positions, worlds = rig.forward(local, root)
    return rig.to_actual(worlds), root, positions, worlds


def lowest_contact(rig: Rig, positions: np.ndarray, worlds: np.ndarray) -> np.ndarray:
    lowest = np.full(positions.shape[0], np.inf)
    for bone, offset in rig.contacts:
        points = positions[:, bone] + rot.rotate(worlds[:, bone], np.broadcast_to(offset, positions[:, bone].shape))
        lowest = np.minimum(lowest, points[:, 1])
    return lowest


def _euler_locals(pose: Pose) -> np.ndarray:
    angles = pose.angles
    local = rot.euler(angles[..., 0], angles[..., 1], angles[..., 2])
    for index, name in enumerate(BONE_NAMES):
        if name.endswith("_End"):
            local[:, index] = pose.rig.rest_local[index]
    for side in _SIDES:
        arm, fore = BONE_BY_NAME[f"{side}Arm"], BONE_BY_NAME[f"{side}ForeArm"]
        local[:, arm] = rot.multiply(local[:, arm], rot.axis_angle(_X, -pose.twists[side]))
        local[:, fore] = rot.multiply(rot.axis_angle(_Y, angles[:, fore, 1]), rot.axis_angle(_X, angles[:, fore, 0]))
    return local


def _solve_feet(pose: Pose, local: np.ndarray, root: np.ndarray) -> None:
    """3D two-bone IK per leg: the ankle lands exactly on its goal, the knee points forward."""
    rig = pose.rig
    for side, target in pose.feet.items():
        hip, knee, ankle = (rig.index(f"{side}{part}") for part in ("UpLeg", "Leg", "Foot"))
        positions, worlds = rig.forward(local, root)
        lift = _sole_lift(rig, side, target["pitch"])
        goal = rig.rest_positions[ankle] + rot.rotate(rig.facing, target["offset"] * rig.leg + np.outer(lift, _Y))
        pelvis = worlds[:, rig.index("Hips")]
        pole = rot.rotate(pelvis, np.broadcast_to(np.array([0.08 * side_sign(side), 0.0, 1.0]), goal.shape))
        thigh, bend, hinge = _leg_chain(rig, side, positions[:, hip], goal, pole)
        local[:, hip] = rot.multiply(rot.inverse(pelvis), thigh)
        local[:, knee] = rot.axis_angle(np.broadcast_to(hinge, goal.shape), bend)
        _positions, worlds = rig.forward(local, root)
        local[:, ankle] = rot.multiply(rot.inverse(worlds[:, knee]), _planted(rig, ankle, target["pitch"], target.get("yaw")))


def _leg_chain(rig: Rig, side: str, hip: np.ndarray, goal: np.ndarray, pole: np.ndarray):
    """Thigh world rotation, knee bend in degrees and the knee hinge in the thigh's frame."""
    upper, lower = rig.length(f"{side}UpLeg", f"{side}Leg"), rig.length(f"{side}Leg", f"{side}Foot")
    delta = goal - hip
    distance = np.linalg.norm(delta, axis=1)
    reach = np.clip(distance, abs(upper - lower) + 1e-6, (upper + lower) * 0.9999)
    aim = delta / np.maximum(distance, 1e-9)[:, None]
    toward = _unit_rows(pole - aim * np.sum(pole * aim, axis=1, keepdims=True))
    inner = np.arccos(np.clip((upper * upper + reach * reach - lower * lower) / (2 * upper * reach), -1.0, 1.0))
    thigh_dir = aim * np.cos(inner)[:, None] + toward * np.sin(inner)[:, None]
    shin_dir = _unit_rows(hip + aim * reach[:, None] - (hip + thigh_dir * upper))
    bend_dir = shin_dir - thigh_dir * np.sum(shin_dir * thigh_dir, axis=1, keepdims=True)
    bend_dir = _unit_rows(np.where(np.linalg.norm(bend_dir, axis=1, keepdims=True) < 1e-6, -toward, bend_dir))
    along = rig.offsets[rig.index(f"{side}Leg")] / max(upper, 1e-9)
    backward = np.array([0.0, 0.0, -1.0]) - along * float(-along[2])
    backward = backward / max(float(np.linalg.norm(backward)), 1e-9)
    hinge = np.cross(along, backward)
    local_basis = np.stack((along, backward, hinge), axis=1)
    world_basis = np.stack((thigh_dir, bend_dir, np.cross(thigh_dir, bend_dir)), axis=-1)
    thigh = rot.from_matrix(world_basis @ local_basis.T)
    bend = np.degrees(np.arccos(np.clip(np.sum(thigh_dir * shin_dir, axis=1), -1.0, 1.0)))
    return thigh, bend, hinge


def _planted(rig: Rig, ankle: int, pitch: np.ndarray, yaw: np.ndarray | None = None) -> np.ndarray:
    """The foot's rest orientation in the world, toes lifted by ``pitch`` degrees, then turned by ``yaw``."""
    axis = rot.rotate(rig.facing, _X)
    turn = rot.axis_angle(np.broadcast_to(axis, (len(pitch), 3)), -np.asarray(pitch, dtype=np.float64))
    if yaw is not None and np.any(yaw):
        turn = rot.multiply(rot.axis_angle(np.broadcast_to(_Y, (len(pitch), 3)), np.asarray(yaw, dtype=np.float64)), turn)
    return rot.multiply(turn, np.broadcast_to(rig.rest_worlds[ankle], turn.shape))


def _sole_lift(rig: Rig, side: str, pitch: np.ndarray) -> np.ndarray:
    """How far the ankle must rise so a pitched foot rests on its heel or toes, not below them."""
    ankle = rig.index(f"{side}Foot")
    offsets = [rot.rotate(rot.inverse(rig.facing), rig.rest_positions[bone] + rot.rotate(rig.rest_worlds[bone], offset) - rig.rest_positions[ankle])
               for bone, offset in rig.contacts if bone in (ankle, rig.index(f"{side}ToeBase"))]
    angle = np.radians(np.asarray(pitch, dtype=np.float64))[:, None]
    heights = np.stack([point[1] * np.cos(angle[:, 0]) + point[2] * np.sin(angle[:, 0]) for point in offsets], axis=1)
    rest = min(float(point[1]) for point in offsets)
    return rest - heights.min(axis=1)


def _solve_hands(pose: Pose, local: np.ndarray, root: np.ndarray) -> None:
    rig = pose.rig
    for side, target in pose.hands.items():
        arm, fore = rig.index(f"{side}Arm"), rig.index(f"{side}ForeArm")
        upper, lower = rig.length(f"{side}Arm", f"{side}ForeArm"), rig.length(f"{side}ForeArm", f"{side}Hand")
        positions, worlds = rig.forward(local, root)
        chest = worlds[:, rig.index("Spine2")]
        goal = positions[:, rig.index("Spine2")] + rot.rotate(chest, target["target"])
        pole = rot.rotate(chest, np.broadcast_to(target["pole"], goal.shape))
        upper_world, bend = arm_chain(positions[:, arm], goal, pole, upper, lower, side_sign(side))
        local[:, arm] = rot.multiply(rot.inverse(worlds[:, rig.index(f"{side}Shoulder")]), upper_world)
        local[:, fore] = rot.axis_angle(_Y, -side_sign(side) * bend)


def arm_chain(shoulder, goal, pole, upper, lower, sign) -> tuple[np.ndarray, np.ndarray]:
    """Upper arm world rotation and elbow bend so the wrist lands on ``goal``.

    The elbow points toward ``pole``. In the canonical arm frame the bone runs
    along ``sign * X`` and the forearm bends toward local +Z about local Y.
    """
    delta = goal - shoulder
    distance = np.linalg.norm(delta, axis=1)
    reach = np.clip(distance, abs(upper - lower) + 1e-6, (upper + lower) * 0.9999)
    aim = delta / np.maximum(distance, 1e-9)[:, None]
    side = _unit_rows(pole - aim * np.sum(pole * aim, axis=1, keepdims=True))
    inner = np.arccos(np.clip((upper * upper + reach * reach - lower * lower) / (2 * upper * reach), -1.0, 1.0))
    upper_dir = aim * np.cos(inner)[:, None] + side * np.sin(inner)[:, None]
    wrist = shoulder + aim * reach[:, None]
    lower_dir = _unit_rows(wrist - (shoulder + upper_dir * upper))
    bend_dir = lower_dir - upper_dir * np.sum(lower_dir * upper_dir, axis=1, keepdims=True)
    bend_dir = np.where(np.linalg.norm(bend_dir, axis=1, keepdims=True) < 1e-6, side, bend_dir)
    axis_x = upper_dir * sign
    axis_z = _unit_rows(bend_dir)
    axis_y = np.cross(axis_z, axis_x)
    frame = np.stack((axis_x, axis_y, axis_z), axis=-1)
    bend = np.degrees(np.arccos(np.clip(np.sum(upper_dir * lower_dir, axis=1), -1.0, 1.0)))
    return rot.from_matrix(frame), bend


def _unit_rows(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)


def _contacts(rig: Rig) -> list[tuple[int, np.ndarray]]:
    """Heel under each ankle and the toe tip, as offsets in their bones' frames."""
    found = []
    forward = rot.rotate(rig.facing, _Z)
    for side in _SIDES:
        foot, toe_base, toe_end = (rig.index(f"{side}{part}") for part in ("Foot", "ToeBase", "Toe_End"))
        ankle, toe = rig.rest_positions[foot], rig.rest_positions[toe_end]
        heel = ankle - forward * float(np.dot(toe - ankle, forward)) * 0.25
        heel[1] = rig.floor
        tip = toe.copy()
        tip[1] = min(float(tip[1]), rig.floor + rig.leg * 0.02)
        for bone, point in ((foot, heel), (toe_base, tip)):
            found.append((bone, rot.rotate(rot.inverse(rig.rest_worlds[bone]), point - rig.rest_positions[bone])))
    return found


def _actual_frames(bones: list[dict]) -> dict:
    frames = {}
    for bone in bones:
        parent = bone["parent"]
        local = rot.normalize(np.asarray(bone["rotation"], dtype=np.float64))
        frames[bone["name"]] = local if parent is None else rot.multiply(frames[parent], local)
    return frames


def _canonical_offset(bone: dict, frames: dict, actual: dict, scale: float) -> np.ndarray:
    """The bone's offset from its parent, in metres, in the parent's canonical frame."""
    parent = bone["parent"]
    if parent is None:
        return np.zeros(3)
    world_offset = rot.rotate(actual[parent], np.asarray(bone["translation"], dtype=np.float64) * scale)
    return rot.rotate(rot.inverse(frames[parent]), world_offset)


def _canonical_local(name: str, frames: dict, facing: np.ndarray) -> np.ndarray:
    parent = _PARENT[name]
    if parent is None:
        return rot.normalize(rot.multiply(rot.inverse(facing), frames[name]))
    return rot.normalize(rot.multiply(rot.inverse(frames[parent]), frames[name]))

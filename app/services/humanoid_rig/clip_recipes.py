"""Authored clips for the standard humanoid. Each recipe fills a ``Pose``.

``u`` runs from 0 to 1 over one loop. Every curve returns to its start value,
so the first and last keys match and the loop has no seam. The clips in
``HOLDS`` are the exception: they go down into a pose and stay there, so their
last key is that pose and a slot plays them once. Distances are in leg lengths;
angles follow the conventions in ``motion``.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.motion import Pose, bake_with_frames, sole_lift
from services.humanoid_rig.names import BONE_NAMES

TAU = 2.0 * np.pi


def keys(u: np.ndarray, points: list[tuple[float, float]]) -> np.ndarray:
    """Eased interpolation through ``(u, value)`` keys from u=0 to u=1."""
    times = np.array([item[0] for item in points])
    values = np.array([item[1] for item in points])
    index = np.clip(np.searchsorted(times, u, side="right") - 1, 0, len(times) - 2)
    span = np.maximum(times[index + 1] - times[index], 1e-9)
    local = np.clip((u - times[index]) / span, 0.0, 1.0)
    eased = local * local * (3.0 - 2.0 * local)
    return values[index] + (values[index + 1] - values[index]) * eased


def wave(u: np.ndarray, cycles: float = 1.0, phase: float = 0.0) -> np.ndarray:
    return np.sin(TAU * (u * cycles + phase))


def pulse(u: np.ndarray, cycles: float = 1.0, phase: float = 0.0) -> np.ndarray:
    """0 at the start of each cycle, 1 in its middle."""
    return 0.5 - 0.5 * np.cos(TAU * (u * cycles + phase))


def _overhead(pose: Pose, wanted: float) -> float:
    """The arm lift for an overhead pose, held below what the head allows."""
    return min(wanted, pose.rig.limits["arm_up"] - 5.0)


def _plant_both(pose: Pose) -> None:
    for side in ("Left", "Right"):
        pose.plant(side)


def idle(pose: Pose, u: np.ndarray) -> None:
    pose.move_root(side=0.012 * wave(u), up=-0.012 - 0.004 * pulse(u, 2))
    pose.hips(roll=-1.5 * wave(u))
    pose.spine(pitch=1.0 + 1.2 * pulse(u, 2), roll=1.2 * wave(u))
    pose.head(pitch=-1.0 + 1.5 * wave(u, 2, 0.1), yaw=4.0 * wave(u, 1, 0.15))
    down = -pose.rig.limits["arm_down"]
    for side, shift in (("Left", 0.0), ("Right", 0.5)):
        pose.arm(side, lift=down + 2.0 * wave(u, 1, shift), swing=6.0 + 2.0 * wave(u, 1, shift + 0.2))
        pose.elbow(side, 14.0 + 4.0 * pulse(u, 1, shift))
        pose.clavicle(side, shrug=1.2 * pulse(u, 2))
    _plant_both(pose)


def breathe(pose: Pose, u: np.ndarray) -> None:
    breath = pulse(u)
    pose.move_root(up=-0.01)
    pose.spine(pitch=-3.0 * breath)
    pose.head(pitch=-2.5 * breath)
    for side in ("Left", "Right"):
        pose.clavicle(side, shrug=6.0 * breath)
        pose.arm(side, lift=-pose.rig.limits["arm_down"] + 3.0 * breath, swing=5.0)
        pose.elbow(side, 14.0 - 4.0 * breath)
    _plant_both(pose)


def _stride(phase: np.ndarray, stance: float, length: float, height: float):
    """In-place foot path: back along the floor in stance, up and forward in swing."""
    phase = np.mod(phase, 1.0)
    in_stance = phase < stance
    s = np.where(in_stance, phase / stance, (phase - stance) / (1.0 - stance))
    eased = s * s * (3.0 - 2.0 * s)
    forward = np.where(in_stance, length * (0.5 - s), length * (eased - 0.5))
    up = np.where(in_stance, 0.0, height * np.sin(np.pi * s) ** 1.4)
    pitch = np.where(in_stance, keys(s, [(0.0, 12.0), (0.18, 0.0), (0.72, 0.0), (1.0, -22.0)]), keys(s, [(0.0, -22.0), (0.35, -8.0), (0.8, 6.0), (1.0, 12.0)]))
    return forward, up, pitch


def walk(pose: Pose, u: np.ndarray) -> None:
    pose.grounded = False
    for side, phase in (("Left", 0.0), ("Right", 0.5)):
        forward, up, pitch = _stride(u + phase, 0.6, 0.42, 0.075)
        pose.plant(side, forward=forward, up=up, pitch=pitch)
    pose.move_root(up=-0.035 - 0.016 * np.cos(2 * TAU * u), side=0.018 * wave(u))
    pose.hips(yaw=-5.0 * np.cos(TAU * u), roll=-2.5 * wave(u))
    pose.spine(pitch=3.0, yaw=4.5 * np.cos(TAU * u), roll=1.5 * wave(u))
    pose.head(pitch=-2.0, yaw=-0.5 * np.cos(TAU * u))
    lift = -pose.rig.limits["arm_down"] + 3.0
    for side, sign in (("Left", -1.0), ("Right", 1.0)):
        swing = sign * 18.0 * np.cos(TAU * u)
        pose.arm(side, lift=lift, swing=6.0 + swing)
        pose.elbow(side, 20.0 + 0.45 * np.maximum(swing, 0.0))


def run(pose: Pose, u: np.ndarray) -> None:
    pose.grounded = False
    for side, phase in (("Left", 0.0), ("Right", 0.5)):
        forward, up, pitch = _stride(u + phase, 0.36, 0.78, 0.30)
        pose.plant(side, forward=forward, up=up, pitch=pitch)
    flight = np.maximum(0.0, np.sin(2 * TAU * (u - 0.18 + 0.25)))
    pose.move_root(up=-0.07 + 0.05 * flight, side=0.012 * wave(u))
    pose.hips(yaw=-8.0 * np.cos(TAU * u), roll=-2.0 * wave(u))
    pose.spine(pitch=10.0, yaw=8.0 * np.cos(TAU * u))
    pose.head(pitch=-8.0, yaw=-1.0 * np.cos(TAU * u))
    for side, sign in (("Left", -1.0), ("Right", 1.0)):
        swing = sign * 34.0 * np.cos(TAU * u)
        pose.arm(side, lift=-pose.rig.limits["arm_down"] + 8.0, swing=12.0 + swing, sweep=0.0)
        pose.elbow(side, 85.0 + 0.3 * swing)


def jump(pose: Pose, u: np.ndarray) -> None:
    pose.grounded = False
    root = keys(u, [(0.0, -0.02), (0.18, -0.24), (0.3, -0.02), (0.38, 0.16), (0.5, 0.30), (0.62, 0.16), (0.7, -0.04), (0.78, -0.20), (0.92, -0.04), (1.0, -0.02)])
    feet = keys(u, [(0.0, 0.0), (0.33, 0.0), (0.42, 0.10), (0.5, 0.20), (0.58, 0.10), (0.68, 0.0), (1.0, 0.0)])
    toes = keys(u, [(0.0, 0.0), (0.22, 0.0), (0.32, -35.0), (0.45, -20.0), (0.62, -18.0), (0.7, 0.0), (1.0, 0.0)])
    pose.move_root(up=root)
    for side in ("Left", "Right"):
        pose.plant(side, up=feet, pitch=toes)
    crouch = keys(u, [(0.0, 0.0), (0.18, 1.0), (0.3, 0.0), (0.7, 0.0), (0.78, 1.0), (1.0, 0.0)])
    pose.spine(pitch=4.0 + 18.0 * crouch - 4.0 * keys(u, [(0.0, 0.0), (0.5, 1.0), (1.0, 0.0)]))
    pose.head(pitch=-6.0 * crouch)
    top = min(140.0, pose.rig.limits["swing_up"])
    swing = keys(u, [(0.0, 6.0), (0.18, -45.0), (0.32, 60.0), (0.5, top), (0.66, 40.0), (0.78, 10.0), (1.0, 6.0)])
    for side in ("Left", "Right"):
        pose.arm(side, lift=-pose.rig.limits["arm_down"] + 15.0, swing=swing)
        pose.elbow(side, 20.0 + 10.0 * crouch)


def wave_hand(pose: Pose, u: np.ndarray) -> None:
    lift = min(28.0, pose.rig.limits["arm_up"] - 15.0)
    pose.arm("Right", lift=lift, sweep=18.0, swing=0.0)
    pose.twist("Right", 90.0)
    pose.elbow("Right", 95.0 + 25.0 * wave(u, 2))
    pose.wrist("Right", wave=14.0 * wave(u, 2, 0.08))
    pose.palm("Right", -10.0)
    pose.head(roll=-4.0, yaw=-8.0, pitch=-2.0)
    pose.spine(roll=3.0 + 1.0 * wave(u, 2), yaw=-5.0)
    pose.move_root(side=0.01, up=-0.012)
    _plant_both(pose)


def cheer(pose: Pose, u: np.ndarray) -> None:
    pump = pulse(u, 2)
    up = _overhead(pose, 70.0)
    pose.move_root(up=-0.02 - 0.05 * pump)
    pose.spine(pitch=-6.0 + 3.0 * pump)
    pose.head(pitch=-10.0 + 5.0 * pump)
    for side in ("Left", "Right"):
        pose.arm(side, lift=up - 22.0 * pump, sweep=10.0)
        pose.elbow(side, 12.0 + 35.0 * pump)
        pose.clavicle(side, shrug=8.0 - 4.0 * pump)
    _plant_both(pose)


def dance_bounce(pose: Pose, u: np.ndarray) -> None:
    beat = pulse(u, 2)
    pose.move_root(up=-0.03 - 0.07 * beat, side=0.02 * wave(u))
    pose.hips(roll=-4.0 * wave(u), yaw=5.0 * wave(u))
    pose.spine(pitch=4.0 * beat, roll=3.0 * wave(u), yaw=-6.0 * wave(u))
    pose.head(pitch=7.0 * beat, roll=-3.0 * wave(u))
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        pose.arm(side, lift=-50.0, swing=25.0 + sign * 15.0 * wave(u))
        pose.elbow(side, 85.0 + 10.0 * beat)
    _plant_both(pose)


def dance_side(pose: Pose, u: np.ndarray) -> None:
    sway = np.cos(TAU * u)
    beat = pulse(u, 2)
    pose.move_root(side=0.09 * sway, up=-0.04 - 0.04 * beat)
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        lift = np.maximum(0.0, sign * -sway) ** 2 * 0.06
        pose.plant(side, out=0.07, up=lift, pitch=-12.0 * (lift / 0.06))
    pose.hips(roll=7.0 * sway)
    pose.spine(roll=-9.0 * sway, yaw=4.0 * wave(u))
    pose.head(roll=5.0 * sway, pitch=3.0 * beat)
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        pose.arm(side, lift=-35.0 + sign * 18.0 * sway, swing=20.0)
        pose.elbow(side, 70.0 - sign * 15.0 * sway)


def dance_arms(pose: Pose, u: np.ndarray) -> None:
    beat = pulse(u, 2)
    point = keys(u, [(0.0, 1.0), (0.4, 1.0), (0.5, -1.0), (0.9, -1.0), (1.0, 1.0)])
    pose.move_root(up=-0.03 - 0.05 * beat, side=0.03 * point)
    pose.hips(roll=6.0 * point, yaw=-6.0 * point)
    pose.spine(roll=-6.0 * point, yaw=8.0 * point)
    pose.head(roll=4.0 * point, pitch=4.0 * beat)
    up, down = _overhead(pose, 60.0), -min(45.0, pose.rig.limits["arm_down"])
    middle, reach = (up + down) * 0.5, (up - down) * 0.5
    pose.arm("Left", lift=middle + reach * point, sweep=15.0)
    pose.arm("Right", lift=middle - reach * point, sweep=15.0)
    for side in ("Left", "Right"):
        pose.elbow(side, 10.0 + 15.0 * beat)
    _plant_both(pose)


def clap(pose: Pose, u: np.ndarray) -> None:
    apart = 0.5 - 0.5 * np.cos(2 * TAU * u)
    arm, front = pose.rig.arm, pose.rig.limits["chest_front"]
    pose.move_root(up=-0.02 - 0.025 * (1.0 - apart))
    pose.spine(pitch=3.0 + 3.0 * (1.0 - apart))
    pose.head(pitch=4.0 * (1.0 - apart))
    for side in ("Left", "Right"):
        target = np.stack((arm * (0.07 + 0.2 * apart), arm * (-0.12 + 0.03 * apart), front + arm * (0.26 + 0.03 * apart)), axis=1)
        pose.reach(side, target)
        pose.palm(side, -20.0)  # palms face each other when the hands meet
        pose.wrist(side, flex=-20.0)
    _plant_both(pose)


def punch(pose: Pose, u: np.ndarray) -> None:
    hit = keys(u, [(0.0, 0.0), (0.2, 0.0), (0.3, 1.0), (0.42, 1.0), (0.6, 0.0), (1.0, 0.0)])
    arm, front = pose.rig.arm, pose.rig.limits["chest_front"]
    pose.move_root(up=-0.05, side=-0.02 * hit)
    pose.hips(yaw=8.0 * hit)
    pose.spine(yaw=14.0 * hit, pitch=4.0)
    pose.head(yaw=-14.0 * hit, pitch=-2.0)
    guard = np.array([arm * 0.16, arm * 0.22, front + arm * 0.18])
    strike = np.array([arm * 0.02, arm * 0.16, front + arm * 0.95])
    pose.reach("Left", guard, pole=(0.6, -1.0, -0.2))
    pose.reach("Right", guard[None] + (strike - guard)[None] * hit[:, None], pole=(0.6, -1.0, -0.2))
    for side in ("Left", "Right"):
        pose.palm(side, 20.0)
        pose.plant(side, forward=0.06 if side == "Left" else -0.06, out=0.04)


def sit_down(pose: Pose, u: np.ndarray) -> None:
    pose.grounded = False
    seat = keys(u, [(0.0, 0.0), (0.08, 0.0), (0.38, 1.0), (0.62, 1.0), (0.92, 0.0), (1.0, 0.0)])
    move = keys(u, [(0.0, 0.0), (0.08, 0.0), (0.23, 1.0), (0.38, 0.0), (0.62, 0.0), (0.77, 1.0), (0.92, 0.0), (1.0, 0.0)])
    pose.move_root(up=-0.02 - 0.48 * seat, forward=-0.42 * seat)
    pose.spine(pitch=12.0 * seat + 22.0 * move)
    pose.head(pitch=-6.0 * seat - 10.0 * move)
    for side in ("Left", "Right"):
        pose.plant(side, out=0.02 * seat)
        pose.arm(side, lift=-pose.rig.limits["arm_down"] + 10.0 * move, swing=6.0 + 30.0 * seat + 25.0 * move)
        pose.elbow(side, 14.0 + 40.0 * seat)


def victory(pose: Pose, u: np.ndarray) -> None:
    hop = pulse(u, 2)
    up = _overhead(pose, 58.0)
    pose.move_root(up=-0.02 - 0.06 * hop)
    pose.spine(pitch=-5.0, roll=3.0 * wave(u))
    pose.head(pitch=-10.0, roll=-4.0 * wave(u))
    for side in ("Left", "Right"):
        pose.arm(side, lift=up - 8.0 * hop, sweep=5.0)
        pose.elbow(side, 6.0 + 18.0 * hop)
        pose.clavicle(side, shrug=6.0)
    _plant_both(pose)


def talk(pose: Pose, u: np.ndarray) -> None:
    pose.move_root(up=-0.015, side=0.01 * wave(u))
    pose.hips(roll=-1.2 * wave(u))
    pose.spine(pitch=2.0 + 1.5 * wave(u, 2), yaw=4.0 * wave(u, 1, 0.2))
    pose.head(pitch=-2.0 + 3.0 * wave(u, 4, 0.1), yaw=-6.0 * wave(u, 1, 0.3), roll=2.0 * wave(u, 2))
    for side, shift in (("Left", 0.0), ("Right", 0.35)):
        gesture = keys(np.mod(u + shift, 1.0), [(0.0, 0.0), (0.2, 1.0), (0.45, 0.7), (0.6, 0.0), (1.0, 0.0)])
        pose.arm(side, lift=-pose.rig.limits["arm_down"] + 6.0 + 10.0 * gesture, swing=10.0 + 18.0 * gesture)
        pose.elbow(side, 30.0 + 50.0 * gesture)
        pose.palm(side, 70.0 * gesture)  # open hand, palm up and in
        pose.wrist(side, flex=-15.0 * gesture)
    _plant_both(pose)


def nod(pose: Pose, u: np.ndarray) -> None:
    pose.move_root(up=-0.012)
    pose.head(pitch=keys(u, [(0.0, 0.0), (0.15, 14.0), (0.3, -2.0), (0.45, 12.0), (0.6, 0.0), (1.0, 0.0)]))
    pose.spine(pitch=1.5 * pulse(u, 2))
    _plant_both(pose)


def look_around(pose: Pose, u: np.ndarray) -> None:
    turn = keys(u, [(0.0, 0.0), (0.12, 0.0), (0.3, 1.0), (0.45, 1.0), (0.62, -1.0), (0.8, -1.0), (0.95, 0.0), (1.0, 0.0)])
    pose.move_root(up=-0.012)
    pose.head(yaw=45.0 * turn, pitch=-3.0 * np.abs(turn))
    pose.spine(yaw=15.0 * turn)
    pose.hips(yaw=4.0 * turn)
    _plant_both(pose)


def bow(pose: Pose, u: np.ndarray) -> None:
    down = keys(u, [(0.0, 0.0), (0.15, 0.0), (0.4, 1.0), (0.6, 1.0), (0.85, 0.0), (1.0, 0.0)])
    pose.move_root(up=-0.012, forward=-0.04 * down)
    pose.hips(pitch=18.0 * down)
    pose.spine(pitch=22.0 * down)
    pose.head(pitch=10.0 * down)
    for side in ("Left", "Right"):
        pose.arm(side, lift=-pose.rig.limits["arm_down"], swing=6.0 + 22.0 * down)
        pose.elbow(side, 14.0 + 6.0 * down)
    _plant_both(pose)


def point(pose: Pose, u: np.ndarray) -> None:
    aim = keys(u, [(0.0, 0.0), (0.2, 1.0), (0.75, 1.0), (1.0, 0.0)])
    pose.move_root(up=-0.015)
    pose.spine(yaw=-8.0 * aim)
    pose.head(yaw=-6.0 * aim, pitch=-3.0 * aim)
    pose.arm("Right", lift=-pose.rig.limits["arm_down"] * (1.0 - aim) + 5.0 * aim, swing=6.0 * (1.0 - aim), sweep=75.0 * aim)
    pose.elbow("Right", 14.0 * (1.0 - aim) + 4.0 * aim)
    _plant_both(pose)


def shrug(pose: Pose, u: np.ndarray) -> None:
    up = keys(u, [(0.0, 0.0), (0.25, 1.0), (0.6, 1.0), (0.85, 0.0), (1.0, 0.0)])
    pose.move_root(up=-0.015)
    pose.head(roll=6.0 * up, pitch=-3.0 * up)
    for side in ("Left", "Right"):
        pose.clavicle(side, shrug=12.0 * up)
        pose.arm(side, lift=-pose.rig.limits["arm_down"] + 12.0 * up, swing=6.0 + 6.0 * up)
        pose.elbow(side, 14.0 + 70.0 * up)
        pose.palm(side, 130.0 * up)  # palms turn up
    _plant_both(pose)


def _rest_in_chest(pose: Pose, bone: str) -> np.ndarray:
    """A joint's T-pose position in metres from the chest joint, in the chest frame (x left, y up, z forward)."""
    rig = pose.rig
    positions, _worlds = rig.forward(np.tile(rot.IDENTITY, (1, len(BONE_NAMES), 1)), rig.root[None])
    return rot.rotate(rot.inverse(rig.facing), positions[0, rig.index(bone)] - positions[0, rig.index("Spine2")])


def _mirror(side: str) -> np.ndarray:
    return np.array([1.0 if side == "Left" else -1.0, 1.0, 1.0])


def _hanging(pose: Pose, side: str) -> np.ndarray:
    """Where the wrist hangs in the relaxed stance, in the chest frame (x mirrored), so a reach can start there."""
    rig = pose.rig
    _local, _root, positions, worlds = bake_with_frames(Pose(rig, np.zeros(1)))
    chest = rig.index("Spine2")
    return rot.rotate(rot.inverse(worlds[0, chest]), positions[0, rig.index(f"{side}Hand")] - positions[0, chest]) * _mirror(side)


def _step(amount: np.ndarray) -> np.ndarray:
    """A foot's lift while ``amount`` carries it from one spot to the next: 0 at both ends."""
    return np.sin(np.pi * amount) ** 1.3


def _reach_world(pose: Pose, side: str, goal: np.ndarray, chest_at: np.ndarray, chest: np.ndarray, pole) -> None:
    """Wrist goals in model space, held in the chest frame of an earlier bake so the floor contact cannot move them."""
    local = rot.rotate(rot.inverse(chest), goal - chest_at)
    pose.reach(side, local * _mirror(side), pole=pole)


def _within_reach(goal: np.ndarray, shoulder: np.ndarray, reach: float) -> np.ndarray:
    """Pull each goal toward the shoulder until it is no farther than ``reach``.

    A straight arm turns a small move of its goal into a big jump of the elbow, so a short-armed body
    stops a little short of a goal it cannot reach instead of locking the elbow.
    """
    offset = goal - shoulder
    distance = np.linalg.norm(offset, axis=1, keepdims=True)
    return shoulder + offset * np.minimum(1.0, reach / np.maximum(distance, 1e-9))


def _recoil(u: np.ndarray, beats: int) -> np.ndarray:
    """A kick on every beat: up within a frame, then eased back over half a beat."""
    beat = np.mod(u * beats, 1.0)
    rise, fall = 0.04, 0.45
    back = np.clip((beat - rise) / fall, 0.0, 1.0)
    return np.where(beat < rise, np.sin(0.5 * np.pi * beat / rise), (1.0 - back) ** 2)


def _rifle(pose: Pose, u: np.ndarray, kick: np.ndarray) -> None:
    """Right-handed two-handed rifle aim, left foot forward; ``kick`` (0..1) is the recoil."""
    breath = pulse(u)
    sway = wave(u, 1, 0.3)
    pose.move_root(up=-0.05 - 0.006 * breath - 0.012 * kick, forward=-0.015 * kick, side=0.006 * sway)
    pose.plant("Left", forward=0.14, out=0.03, yaw=-12.0)
    pose.plant("Right", forward=-0.14, out=0.06, yaw=-35.0)
    pose.hips(yaw=-14.0, roll=-1.0 * sway)
    pose.spine(pitch=5.0 - 1.5 * breath - 4.0 * kick, yaw=-12.0 - 3.0 * kick, roll=-1.5)
    # Cheek down on the stock, eyes back on the target over the turned shoulders.
    pose.head(pitch=8.0 - 1.0 * breath - 4.0 * kick, yaw=22.0 + 2.0 * kick, roll=-9.0)
    pose.clavicle("Right", shrug=1.5 * breath, forward=4.0 - 9.0 * kick)
    pose.clavicle("Left", shrug=1.0 * breath, forward=6.0)
    rig = pose.rig
    _local, _root, positions, worlds = bake_with_frames(pose)
    chest_at, chest = positions[:, rig.index("Spine2")], worlds[:, rig.index("Spine2")]
    # The barrel points at the target whatever the stance; breathing and each kick lift the muzzle a little.
    climb = np.radians(0.8 * breath - 0.4 + 5.0 * kick)
    drift = np.radians(0.6 * wave(u, 1, 0.1))
    ahead = rot.rotate(rig.facing, np.stack((np.sin(drift) * np.cos(climb), np.sin(climb), np.cos(drift) * np.cos(climb)), axis=1))
    up = rot.rotate(rig.facing, np.stack((np.zeros_like(climb), np.cos(climb), -np.sin(climb)), axis=1))
    left = np.cross(up, ahead)
    arm = rig.arm
    stock = positions[:, rig.index("RightArm")] + arm * (0.10 * left + 0.04 * ahead + 0.03 * up)
    _reach_world(pose, "Right", stock + arm * (0.42 * ahead - 0.14 * up), chest_at, chest, (0.4, -1.0, -0.3))  # trigger elbow down
    support = _within_reach(stock + arm * (0.92 * ahead - 0.07 * up + 0.02 * left), positions[:, rig.index("LeftArm")], 0.92 * arm)
    _reach_world(pose, "Left", support, chest_at, chest, (0.1, -1.0, 0.2))
    pose.palm("Right", -10.0)  # the grip: palm in, fingers forward round it
    pose.wrist("Right", wave=-45.0)
    pose.palm("Left", 60.0)  # the support hand cups the barrel from below
    pose.wrist("Left", flex=-30.0)


def aim(pose: Pose, u: np.ndarray) -> None:
    _rifle(pose, u, np.zeros_like(u))


def shoot(pose: Pose, u: np.ndarray) -> None:
    _rifle(pose, u, _recoil(u, RECIPES["shoot"][0]))


_SLASH = (0.02, 0.20, 0.29, 0.36, 0.62)  # wind-up starts, swipe starts, swipe ends, recovery starts, back on guard


def _slash_target(pose: Pose, side: str, phase: np.ndarray) -> np.ndarray:
    """The wrist path of one claw swipe, in the chest frame (x mirrored): guard, wind-up high and out, across, back."""
    start, swing, end, back, guard_at = _SLASH
    rig = pose.rig
    arm, front = rig.arm, rig.limits["chest_front"]
    shoulder = _rest_in_chest(pose, f"{side}Arm") * _mirror(side)
    raise_to = np.radians(min(50.0, rig.limits["arm_up"] - 15.0))
    height = min(0.45, np.tan(raise_to) * 0.39)
    guard = shoulder + np.array([-0.05 * arm, -0.22 * arm, front + 0.30 * arm - shoulder[2]])
    windup = shoulder + arm * np.array([0.38, height, -0.10])
    across = shoulder + np.array([-0.55 * arm, -0.42 * arm, front + 0.35 * arm - shoulder[2]])
    bend = shoulder + arm * np.array([0.10, 0.10, 1.10])  # pulls the swipe out in front of the body
    gather = keys(phase, [(0.0, 0.0), (start, 0.0), (swing, 1.0), (1.0, 1.0)])[:, None]
    s = keys(phase, [(0.0, 0.0), (swing, 0.0), (end, 1.0), (1.0, 1.0)])[:, None]
    settle = keys(phase, [(0.0, 0.0), (back, 0.0), (guard_at, 1.0), (1.0, 1.0)])[:, None]
    arc = (1.0 - s) ** 2 * windup + 2.0 * s * (1.0 - s) * bend + s * s * across
    return np.where(phase[:, None] < swing, guard + (windup - guard) * gather,
                    np.where(phase[:, None] < back, arc, across + (guard - across) * settle))


def claw(pose: Pose, u: np.ndarray) -> None:
    start, swing, end, back, guard_at = _SLASH
    turn, lunge = np.zeros_like(u), np.zeros_like(u)
    for side, shift, sign in (("Right", 0.0, 1.0), ("Left", 0.5, -1.0)):
        phase = np.mod(u + 1.0 - shift, 1.0)
        twist = keys(phase, [(0.0, 0.0), (start, 0.0), (swing, -1.0), (end, 1.0), (back, 1.0), (guard_at, 0.0), (1.0, 0.0)])
        strike = keys(phase, [(0.0, 0.0), (swing - 0.05, 0.0), (end, 1.0), (back + 0.04, 1.0), (guard_at, 0.0), (1.0, 0.0)])
        gather = keys(phase, [(0.0, 0.0), (start, 0.0), (swing, 1.0), (end, 0.0), (1.0, 0.0)])
        turn += sign * twist
        lunge += strike
        pose.reach(side, _slash_target(pose, side, phase), pole=(1.0, -0.5, -0.5))
        pose.clavicle(side, shrug=9.0 * gather, forward=-6.0 * gather + 10.0 * strike)
        pose.wrist(side, flex=-30.0 + 15.0 * strike)  # claws bent back, then leading the swipe
        pose.palm(side, -30.0 * strike)
    pose.move_root(up=-0.09 - 0.03 * lunge, forward=0.03 * lunge)
    pose.plant("Left", forward=0.08, out=0.06, yaw=8.0)
    pose.plant("Right", forward=-0.08, out=0.06, yaw=-8.0)
    pose.hips(yaw=9.0 * turn, pitch=4.0 + 4.0 * lunge)
    pose.spine(pitch=14.0 + 8.0 * lunge, yaw=22.0 * turn)
    pose.head(pitch=-16.0 - 6.0 * lunge, yaw=-20.0 * turn)  # eyes stay on the prey


def hit(pose: Pose, u: np.ndarray) -> None:
    blow = keys(u, [(0.0, 0.0), (0.035, 1.0), (0.12, 0.75), (0.3, 0.25), (0.55, 0.0), (1.0, 0.0)])
    step = keys(u, [(0.0, 0.0), (0.05, 0.0), (0.2, 1.0), (0.52, 1.0), (0.68, 0.0), (1.0, 0.0)])
    give = keys(u, [(0.0, 0.0), (0.16, 0.0), (0.3, 1.0), (0.48, 0.4), (0.7, 0.0), (1.0, 0.0)])
    lift = 0.07 * _step(np.clip((u - 0.05) / 0.15, 0.0, 1.0)) + 0.05 * _step(np.clip((u - 0.52) / 0.16, 0.0, 1.0))
    pose.plant("Right", forward=-0.3 * step, out=0.02 * step, up=lift, pitch=10.0 * lift / 0.07)
    pose.plant("Left")
    pose.move_root(forward=-0.15 * step - 0.05 * blow, up=-0.02 - 0.07 * give)
    pose.hips(pitch=-6.0 * blow, yaw=5.0 * blow)
    pose.spine(pitch=-20.0 * blow + 10.0 * give, yaw=8.0 * blow, roll=-3.0 * blow)
    # The head lags the snap of the chest, then whips back past it.
    whip = keys(u, [(0.0, 0.0), (0.02, 6.0), (0.07, -22.0), (0.15, -8.0), (0.32, 6.0), (0.6, 0.0), (1.0, 0.0)])
    pose.head(pitch=whip + 4.0 * give, yaw=-6.0 * blow)
    down = pose.rig.limits["arm_down"]
    for side, shift in (("Left", 0.0), ("Right", 0.02)):
        fling = keys(u, [(0.0, 0.0), (0.03 + shift, 1.0), (0.2, 0.7), (0.45, 0.2), (0.75, 0.0), (1.0, 0.0)])
        pose.arm(side, lift=-down + 22.0 * fling, swing=6.0 + 50.0 * fling, sweep=10.0 * fling)
        pose.elbow(side, 14.0 + 35.0 * fling)
        pose.clavicle(side, shrug=6.0 * fling)


def hover(pose: Pose, u: np.ndarray) -> None:
    pose.grounded = False
    beat = TAU * 2.0 * u  # a wing beat per beat lifts the body on the downstroke
    pose.move_root(up=0.32 + 0.05 * np.sin(beat), forward=0.01 * np.sin(beat - 0.6), side=0.012 * wave(u))
    pose.hips(pitch=10.0 + 2.0 * np.sin(beat - 0.5), roll=-2.0 * wave(u))
    pose.spine(pitch=12.0 + 3.0 * np.sin(beat + 0.4), roll=1.5 * wave(u))
    pose.head(pitch=-16.0 - 3.0 * np.sin(beat + 0.8), yaw=6.0 * wave(u, 1, 0.2))
    for side, lag in (("Left", 1.2), ("Right", 1.45)):
        # Legs hang loose and trail behind, swinging a little after each beat.
        pose.leg(side, swing=-12.0 + 5.0 * np.sin(beat - lag), spread=4.0, knee=26.0 + 9.0 * np.sin(beat - lag - 0.5),
                 toes=-35.0 + 8.0 * np.sin(beat - lag - 0.9))
        pose.arm(side, lift=-52.0 + 6.0 * np.sin(beat - lag + 0.3), swing=30.0 + 4.0 * np.sin(beat - lag), sweep=0.0)
        pose.elbow(side, 30.0 + 8.0 * np.sin(beat - lag - 0.2))


def _kneeling(pose: Pose, side: str, tilt: float) -> tuple[float, float, float, float]:
    """``(hips drop, ankle forward, ankle out, toe pitch)`` that put this knee on the floor; lengths in leg lengths.

    The thigh leans ``tilt`` degrees forward from the vertical under a hip kept where it stands, and the shin
    reaches back from the knee to an ankle under the hip, so legs modeled apart still kneel with the knees
    together. The foot rests on its tucked toes, tucked less when a big foot would lift the ankle above the knee.
    """
    rig = pose.rig
    hip, ankle = (rot.rotate(rot.inverse(rig.facing), rig.rest_positions[rig.index(f"{side}{part}")]) for part in ("UpLeg", "Foot"))
    thigh, shin = rig.length(f"{side}UpLeg", f"{side}Leg") / rig.leg, rig.length(f"{side}Leg", f"{side}Foot") / rig.leg
    rest_ankle = (ankle[1] - rig.floor) / rig.leg
    knee_up = float(np.clip(0.8 * rest_ankle, 0.03, 0.18))  # the knee joint sits about half the knee's depth above the floor
    pitches = np.arange(-60.0, -4.0, 5.0)
    rises = rest_ankle + sole_lift(rig, side, pitches) / rig.leg - knee_up
    pick = int(np.argmax(rises <= 0.6 * shin)) if np.any(rises <= 0.6 * shin) else len(pitches) - 1
    lean = np.radians(tilt)
    drop = (hip[1] - rig.floor) / rig.leg - (knee_up + thigh * np.cos(lean))
    knee_ahead = (hip[2] - ankle[2]) / rig.leg + thigh * np.sin(lean)
    behind = np.sqrt(max(shin * shin - float(rises[pick]) ** 2, 1e-6))
    apart = (1.0 if side == "Left" else -1.0) * (ankle[0] - hip[0]) / rig.leg
    return float(drop), float(knee_ahead - behind), float(-apart), float(pitches[pick])


def kneel_pray(pose: Pose, u: np.ndarray) -> None:
    drop, right_back, right_in, right_toes = _kneeling(pose, "Right", 8.0)
    _drop, left_back, left_in, left_toes = _kneeling(pose, "Left", 8.0)
    first = keys(u, [(0.0, 0.0), (0.02, 0.0), (0.11, 1.0), (1.0, 1.0)])   # right foot back, right knee down
    second = keys(u, [(0.0, 0.0), (0.11, 0.0), (0.19, 1.0), (1.0, 1.0)])  # then the left
    ball = keys(u, [(0.0, 0.0), (0.04, 0.0), (0.11, 1.0), (0.13, 1.0), (0.19, 0.0), (1.0, 0.0)])
    hands = keys(u, [(0.0, 0.0), (0.12, 0.0), (0.23, 1.0), (1.0, 1.0)])
    bowed = keys(u, [(0.0, 0.0), (0.16, 0.0), (0.26, 1.0), (1.0, 1.0)])
    breath = pulse(u, 4) * keys(u, [(0.0, 0.0), (0.22, 0.0), (0.3, 1.0), (1.0, 1.0)])
    pose.move_root(up=-0.015 * (1.0 - first) - drop * first - 0.02 * _step(first), forward=-0.08 * _step(first) - 0.04 * _step(second))
    pose.plant("Right", forward=right_back * first, out=right_in * first, up=0.06 * _step(first), pitch=right_toes * first)
    # The front foot rolls onto its ball while its knee folds, then steps back beside the other.
    pose.plant("Left", forward=left_back * second, out=left_in * second, up=0.05 * _step(second), pitch=-30.0 * ball + left_toes * second)
    pose.spine(pitch=10.0 * _step(first) + 6.0 * bowed - 2.0 * breath)
    pose.head(pitch=26.0 * bowed - 2.0 * breath)
    arm, front = pose.rig.arm, pose.rig.limits["chest_front"]
    joined = np.array([0.04 * arm, -0.1 * arm, front + 0.2 * arm])
    lift = np.outer(np.sin(np.pi * hands), [0.0, 0.0, 0.15 * arm])  # the hands come up clear of the belly
    for side in ("Left", "Right"):
        rest = _hanging(pose, side)
        pose.reach(side, rest[None] + (joined - rest)[None] * hands[:, None] + lift, pole=(0.4, -1.0, -0.6))
        pose.clavicle(side, shrug=3.0 * breath, forward=4.0 * hands)
        pose.palm(side, -60.0 * hands)
        pose.wrist(side, flex=-40.0 * hands, wave=40.0 * hands)  # fingers up, palm to palm


def crouch(pose: Pose, u: np.ndarray) -> None:
    down = keys(u, [(0.0, 0.0), (0.02, 0.0), (0.1, 1.0), (1.0, 1.0)])
    peek = keys(u, [(0.0, 0.0), (0.3, 0.0), (0.38, 1.0), (0.5, 1.0), (0.57, 0.0), (1.0, 0.0)])
    breath = pulse(u, 4) * keys(u, [(0.0, 0.0), (0.1, 0.0), (0.16, 1.0), (1.0, 1.0)])
    low = down * (1.0 - 0.55 * peek)
    pose.move_root(up=-0.015 - 0.43 * low - 0.004 * breath, forward=-0.12 * low)
    for side in ("Left", "Right"):
        pose.plant(side, pitch=-10.0 * low)
    pose.hips(pitch=8.0 * low)
    pose.spine(pitch=22.0 * low - 1.5 * breath)
    pose.head(pitch=-18.0 * low, yaw=10.0 * peek * wave(u, 2, 0.1))  # face up over the cover, a glance each way when peeking
    arm, front = pose.rig.arm, pose.rig.limits["chest_front"]
    ready = np.array([0.12 * arm, -0.05 * arm, front + 0.5 * arm])
    for side in ("Left", "Right"):
        rest = _hanging(pose, side)
        pose.reach(side, rest[None] + (ready - rest)[None] * down[:, None], pole=(0.4, -1.0, -0.6))
        pose.clavicle(side, shrug=2.0 * breath + 4.0 * down)


# Clips that go down into a pose and keep it: their last key is that pose, so a slot plays them once.
HOLDS = frozenset({"kneel_pray", "crouch"})

RECIPES = {
    "idle": (4, idle),
    "breathe": (4, breathe),
    "walk": (2, walk),
    "run": (2, run),
    "jump": (2, jump),
    "wave": (2, wave_hand),
    "cheer": (2, cheer),
    "dance_bounce": (2, dance_bounce),
    "dance_side": (2, dance_side),
    "dance_arms": (2, dance_arms),
    "clap": (2, clap),
    "punch": (2, punch),
    "sit_down": (4, sit_down),
    "victory": (2, victory),
    "talk": (4, talk),
    "nod": (2, nod),
    "look_around": (4, look_around),
    "bow": (4, bow),
    "point": (2, point),
    "shrug": (2, shrug),
    "aim": (4, aim),
    "shoot": (2, shoot),
    "claw": (4, claw),
    "hit": (4, hit),
    "hover": (2, hover),
    "kneel_pray": (16, kneel_pray),
    "crouch": (8, crouch),
}

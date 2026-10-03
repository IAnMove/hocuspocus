"""Authored clips for the standard humanoid. Each recipe fills a ``Pose``.

``u`` runs from 0 to 1 over one loop. Every curve returns to its start value,
so the first and last keys match and the loop has no seam. Distances are in
leg lengths; angles follow the conventions in ``motion``.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.motion import Pose

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
}

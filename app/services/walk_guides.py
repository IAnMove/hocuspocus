"""Pose guides for the walk cycles of a Character Kit: one walking figure computed in 3D and seen from the camera of each direction.

Qwen draws a walk badly from words alone: twelve poses asked one by one come back as three leg positions in no order, and a
three-quarter view slides to a profile from one pose to the next. A guide is the pose drawn for it. ``walk_pose`` computes the body
at one moment of a walk cycle from the joint angles of a human gait (hip, knee and ankle through the cycle, the arms swinging against
the legs, the pelvis turning and swaying over the leg that carries it, the body as high as the lowest sole lets it be);
``guide_image`` projects it from the camera of one of the five directions of ``character_animation_directions`` and draws it as an
OpenPose skeleton (``skeleton``: the colours say which limb is which, and a back view has no nose or eyes) or as a shaded mannequin
(``mannequin``: the limbs nearer the camera are lighter and cover the far ones).

Phase 0 is the contact of the leg nearest the viewer in the side view: the character faces right there, so its right side is toward
the viewer, and phase 0 is the right heel touching down. Phase 0.5 is the same pose on the left leg, so the second half of a
twelve-pose sheet is the first half with the legs swapped and the cycle loops. A sheet of ``count`` poses shows phases
``index / count`` (``phase_of``): the four-pose ``walk`` is contact, passing, contact, passing.

Units are the character's height (1 is the top of the head, 0 the ground). Body axes: ``f`` forward, ``u`` up, ``r`` the character's
right. Picture axes: ``X`` to the right of the picture, ``Y`` up, ``Z`` toward the viewer.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

STYLES = ("skeleton", "mannequin")
# How far the way the character faces is turned from the viewer, toward the picture's right (degrees).
TURN = {"front": 0.0, "front34": 45.0, "side": 90.0, "back34": 135.0, "back": 180.0}
# The catalog's first pose steps with the leg on the viewer's left in the back view, the character's left leg (phase 0.5).
SHIFT = {"back": 0.5}

HIP_HALF, THIGH, SHIN, SOLE = 0.06, 0.245, 0.25, 0.04
HEEL, BALL, TOE = 0.045, 0.095, 0.13
SPINE, LEAN, SHOULDER_HALF, UPPER_ARM, FOREARM = 0.29, math.radians(4), 0.12, 0.18, 0.15
HEAD_UP, HEAD_TOP = 0.105, 0.07

# Joint angles of one leg through its cycle (degrees; heel strike at phase 0), after the averages of normal walking, a little wider
# for a drawn walk and a little early in the swing, so the free foot passes under the body a quarter of the way through the cycle
# as the animators' passing pose does. Hip: the thigh forward of the vertical. Knee: how much the shin bends back from the thigh. Ankle: the toes up.
HIP_KEYS = ((0.0, 26), (0.12, 22), (0.3, 6), (0.48, -12), (0.56, -8), (0.7, 14), (0.85, 28))
KNEE_KEYS = ((0.0, 3), (0.12, 16), (0.33, 4), (0.42, 12), (0.48, 30), (0.56, 46), (0.67, 64), (0.82, 26), (0.93, 4))
ANKLE_KEYS = ((0.0, 0), (0.08, -6), (0.28, 8), (0.42, 12), (0.48, 8), (0.56, -16), (0.66, -6), (0.82, 4))
PELVIS_TURN, SHOULDER_TURN, SWAY = math.radians(6), math.radians(-8), 0.012
ARM_GAIN, ELBOW_REST, ELBOW_GAIN = 0.8, 10.0, 0.7

# The camera every guide is seen from: a little above the hips, a few heights away, looking down a few degrees, so the foot that
# steps toward the viewer is lower in the picture.
CAMERA_HEIGHT, CAMERA_DISTANCE, CAMERA_LOOK = 1.35, 4.5, 0.5
TOP_SHARE, FEET_SHARE = 0.04, 0.95

# OpenPose (COCO 18 points): the order of the points, the limbs as pairs of points and the colour of each limb and point.
POINTS = ("nose", "neck", "r_shoulder", "r_elbow", "r_wrist", "l_shoulder", "l_elbow", "l_wrist", "r_hip", "r_knee", "r_ankle",
          "l_hip", "l_knee", "l_ankle", "r_eye", "l_eye", "r_ear", "l_ear")
LIMBS = ((1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13), (1, 0), (0, 14), (14, 16),
         (0, 15), (15, 17))
COLOURS = ((255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170),
           (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85))
FEET = (("r_ankle", "r_toe", 8), ("r_ankle", "r_heel", 8), ("l_ankle", "l_toe", 11), ("l_ankle", "l_heel", 11))


class WalkGuideError(ValueError):
    pass


def _slopes(keys: tuple[tuple[float, float], ...]) -> list[float]:
    """The slope of the curve at each key: the mean of the two secants around it, flat where they disagree (no overshoot)."""
    count = len(keys)
    slopes = []
    for index, (phase, value) in enumerate(keys):
        before, after = keys[index - 1], keys[(index + 1) % count]
        left = (value - before[1]) / ((phase - before[0]) % 1.0 or 1.0)
        right = (after[1] - value) / ((after[0] - phase) % 1.0 or 1.0)
        slopes.append(0.0 if left * right <= 0 else (left + right) / 2)
    return slopes


def curve(keys: tuple[tuple[float, float], ...], phase: float) -> float:
    """The value of a gait curve at ``phase`` (degrees): a smooth loop through every key."""
    phase %= 1.0
    slopes = _slopes(keys)
    index = max(position for position, key in enumerate(keys) if key[0] <= phase) if phase >= keys[0][0] else len(keys) - 1
    (start, low), (end, high) = keys[index], keys[(index + 1) % len(keys)]
    span = (end - start) % 1.0 or 1.0
    t = ((phase - start) % 1.0) / span
    blend = (2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t, -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2)
    return float(blend[0] * low + blend[1] * span * slopes[index] + blend[2] * high + blend[3] * span * slopes[(index + 1) % len(keys)])


def phase_of(index: int, count: int) -> float:
    """The phase a pose of a sheet shows: the poses split one cycle evenly, the first is the contact of the near leg."""
    if count < 1 or not 0 <= index < count:
        raise WalkGuideError("a pose index is within the sheet")
    return index / count


def _turn(vector: np.ndarray, angle: float) -> np.ndarray:
    """Turn a body vector about the vertical: a positive angle brings the right side forward."""
    f, u, r = vector
    return np.array([f * math.cos(angle) + r * math.sin(angle), u, -f * math.sin(angle) + r * math.cos(angle)])


def _bend(start: np.ndarray, length: float, angle: float, side: float = 0.0) -> np.ndarray:
    """The end of a bone that hangs from ``start`` swung ``angle`` forward of the vertical."""
    return start + np.array([length * math.sin(angle), -length * math.cos(angle), side])


def _sole(ankle: np.ndarray, angle: float, along: float) -> np.ndarray:
    """A point of the sole ``along`` the foot from below the ankle, the foot tilted ``angle`` (toes up is positive)."""
    return ankle + np.array([along * math.cos(angle) + SOLE * math.sin(angle), along * math.sin(angle) - SOLE * math.cos(angle), 0.0])


def _leg(phase: float, sign: float, pelvis: np.ndarray, turn: float) -> dict[str, np.ndarray]:
    hip_angle, knee, ankle = (math.radians(curve(keys, phase)) for keys in (HIP_KEYS, KNEE_KEYS, ANKLE_KEYS))
    side = "r" if sign > 0 else "l"
    hip = pelvis + _turn(np.array([0.0, 0.0, sign * HIP_HALF]), turn)
    knee_at = _bend(hip, THIGH, hip_angle)
    ankle_at = _bend(knee_at, SHIN, hip_angle - knee)
    foot = hip_angle - knee + ankle
    return {f"{side}_hip": hip, f"{side}_knee": knee_at, f"{side}_ankle": ankle_at, f"{side}_heel": _sole(ankle_at, foot, -HEEL),
            f"{side}_ball": _sole(ankle_at, foot, BALL), f"{side}_toe": _sole(ankle_at, foot, TOE)}


def _arm(phase: float, sign: float, shoulder: np.ndarray) -> dict[str, np.ndarray]:
    """An arm swings with the leg of the other side: forward while that leg is forward."""
    mean = curve(HIP_KEYS, 0.0) / 2 + curve(HIP_KEYS, 0.5) / 2
    swing = ARM_GAIN * (curve(HIP_KEYS, (phase + 0.5) % 1.0) - mean)
    elbow_bend = ELBOW_REST + ELBOW_GAIN * max(0.0, swing)
    side = "r" if sign > 0 else "l"
    elbow = _bend(shoulder, UPPER_ARM, math.radians(swing), sign * 0.015)
    return {f"{side}_shoulder": shoulder, f"{side}_elbow": elbow, f"{side}_wrist": _bend(elbow, FOREARM, math.radians(swing + elbow_bend), sign * 0.01)}


def _head(neck: np.ndarray) -> dict[str, np.ndarray]:
    centre = neck + np.array([0.015, HEAD_UP, 0.0])
    return {"head": centre, "head_top": centre + np.array([0.0, HEAD_TOP, 0.0]), "nose": centre + np.array([0.06, -0.01, 0.0]),
            "r_eye": centre + np.array([0.045, 0.015, 0.032]), "l_eye": centre + np.array([0.045, 0.015, -0.032]),
            "r_ear": centre + np.array([-0.005, 0.0, 0.062]), "l_ear": centre + np.array([-0.005, 0.0, -0.062])}


def walk_pose(phase: float) -> dict[str, np.ndarray]:
    """Every point of the body at ``phase`` of the cycle, in body axes, the lowest sole on the ground."""
    phase %= 1.0
    wave = math.cos(2 * math.pi * phase)
    pelvis = np.array([0.0, 0.0, SWAY * math.sin(2 * math.pi * phase)])
    neck = pelvis * 0.5 + np.array([SPINE * math.sin(LEAN), SPINE * math.cos(LEAN), 0.0])
    points = {"pelvis": pelvis, "neck": neck, **_head(neck)}
    for sign, own in ((1.0, phase), (-1.0, (phase + 0.5) % 1.0)):
        points.update(_leg(own, sign, pelvis, PELVIS_TURN * wave))
        points.update(_arm(phase if sign > 0 else (phase + 0.5) % 1.0, sign,
                           neck + _turn(np.array([0.0, -0.02, sign * SHOULDER_HALF]), SHOULDER_TURN * wave)))
    lift = -min(points[f"{side}_{part}"][1] for side in "rl" for part in ("heel", "ball"))
    grounded = {name: point + np.array([0.0, lift, 0.0]) for name, point in points.items()}
    for side in "rl":  # a foot that pushes off on the ball of the foot bends its toes flat on the ground
        ball, toe = grounded[f"{side}_ball"], grounded[f"{side}_toe"]
        if toe[1] < 0:
            grounded[f"{side}_toe"] = np.array([ball[0] + math.sqrt(max(0.0, (TOE - BALL) ** 2 - ball[1] ** 2)), 0.0, ball[2]])
    return grounded


def _axes(direction: str) -> tuple[np.ndarray, np.ndarray]:
    if direction not in TURN:
        raise WalkGuideError(f"direction is one of {', '.join(TURN)}")
    angle = math.radians(TURN[direction])
    forward = np.array([math.sin(angle), 0.0, math.cos(angle)])
    return forward, np.array([-forward[2], 0.0, forward[0]])


def to_picture(points: dict[str, np.ndarray], direction: str) -> dict[str, np.ndarray]:
    """Body points placed in the picture's axes for a character facing ``direction``."""
    forward, right = _axes(direction)
    up = np.array([0.0, 1.0, 0.0])
    return {name: point[0] * forward + point[1] * up + point[2] * right for name, point in points.items()}


def _camera() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    eye = np.array([0.0, CAMERA_HEIGHT, CAMERA_DISTANCE])
    look = np.array([0.0, CAMERA_LOOK, 0.0]) - eye
    look /= np.linalg.norm(look)
    across = np.cross(look, np.array([0.0, 1.0, 0.0]))
    across /= np.linalg.norm(across)
    return eye, look, across, np.cross(across, look)


def _seen(point: np.ndarray) -> tuple[float, float, float]:
    """A picture point as the camera sees it: right, up (both over the depth) and the depth."""
    eye, look, across, upward = _camera()
    offset = point - eye
    depth = float(offset @ look)
    return float(offset @ across) / depth, float(offset @ upward) / depth, depth


def project(points: dict[str, np.ndarray], size: tuple[int, int]) -> dict[str, tuple[float, float, float]]:
    """Pixel x, y and depth of each picture point. A standing figure one height tall fills the picture from ``TOP_SHARE`` to
    ``FEET_SHARE`` (the same scale in every pose, so the body's rise and fall stays in the guide)."""
    width, height = size
    _, foot_y, _ = _seen(np.zeros(3))
    _, top_y, _ = _seen(np.array([0.0, 1.0, 0.0]))
    scale = height * (FEET_SHARE - TOP_SHARE) / (top_y - foot_y)
    return {name: (width / 2 + seen[0] * scale, height * FEET_SHARE - (seen[1] - foot_y) * scale, seen[2])
            for name, seen in ((name, _seen(point)) for name, point in points.items())}


def _toward_viewer(direction: str) -> dict[str, float]:
    """How much each face point looks at the camera (above 0 it is seen)."""
    forward, right = _axes(direction)
    viewer = np.array([0.0, 0.0, 1.0])
    eye_turn = math.radians(30)
    facing = {"nose": forward, "r_ear": right, "l_ear": -right,
              "r_eye": forward * math.cos(eye_turn) + right * math.sin(eye_turn), "l_eye": forward * math.cos(eye_turn) - right * math.sin(eye_turn)}
    return {name: float(normal @ viewer) for name, normal in facing.items()}


def visible_face(direction: str) -> set[str]:
    """The points of the face the camera sees: none of the face from behind, one eye and one ear in profile."""
    limits = {"nose": -0.05, "r_eye": 0.05, "l_eye": 0.05, "r_ear": -0.25, "l_ear": -0.25}
    return {name for name, toward in _toward_viewer(direction).items() if toward > limits[name]}


def _ellipse(draw: ImageDraw.ImageDraw, a: tuple[float, float], b: tuple[float, float], width: float, colour: tuple[int, ...]) -> None:
    """A limb drawn as OpenPose draws it: an ellipse from one point to the other."""
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    steps = 24
    centre = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    outline = [(centre[0] + length / 2 * math.cos(t) * math.cos(angle) - width / 2 * math.sin(t) * math.sin(angle),
                centre[1] + length / 2 * math.cos(t) * math.sin(angle) + width / 2 * math.sin(t) * math.cos(angle))
               for t in (2 * math.pi * k / steps for k in range(steps))]
    draw.polygon(outline, fill=colour)


def _skeleton(placed: dict[str, tuple[float, float, float]], direction: str, size: tuple[int, int]) -> Image.Image:
    face = visible_face(direction)
    shown = {index for index, name in enumerate(POINTS) if name not in ("nose", "r_eye", "l_eye", "r_ear", "l_ear") or name in face}
    stick = max(3.0, size[1] / 128)
    canvas = Image.new("RGB", size, (0, 0, 0))
    for (a, b), colour in zip(LIMBS, COLOURS):
        if a in shown and b in shown:
            layer = canvas.copy()
            _ellipse(ImageDraw.Draw(layer), placed[POINTS[a]][:2], placed[POINTS[b]][:2], stick * 2, colour)
            canvas = Image.blend(canvas, layer, 0.6)
    draw = ImageDraw.Draw(canvas)
    for start, end, colour_index in FEET:
        colour = tuple(int(channel * 0.6) for channel in COLOURS[colour_index])
        _ellipse(draw, placed[start][:2], placed[end][:2], stick * 1.6, colour)
    for index in sorted(shown):
        x, y, _ = placed[POINTS[index]]
        draw.ellipse((x - stick, y - stick, x + stick, y + stick), fill=COLOURS[index])
    return canvas


# The mannequin's parts: two points, the thickness (share of the height) and the side (for its shade).
PARTS = (("r_hip", "r_knee", 0.075, "r"), ("r_knee", "r_ankle", 0.06, "r"), ("r_heel", "r_toe", 0.045, "r"),
         ("l_hip", "l_knee", 0.075, "l"), ("l_knee", "l_ankle", 0.06, "l"), ("l_heel", "l_toe", 0.045, "l"),
         ("r_shoulder", "r_elbow", 0.052, "r"), ("r_elbow", "r_wrist", 0.044, "r"), ("l_shoulder", "l_elbow", 0.052, "l"),
         ("l_elbow", "l_wrist", 0.044, "l"))


def _capsule(draw: ImageDraw.ImageDraw, a: tuple[float, float], b: tuple[float, float], width: float, fill: tuple[int, int, int]) -> None:
    edge = (30, 30, 30)
    for colour, grow in ((edge, 3.0), (fill, 0.0)):
        half = width / 2 + grow
        draw.line([a, b], fill=colour, width=int(round(half * 2)))
        for x, y in (a, b):
            draw.ellipse((x - half, y - half, x + half, y + half), fill=colour)


def _shade(depth: float, near: float, far: float, side: str) -> tuple[int, int, int]:
    light = 215 - 95 * ((depth - near) / max(1e-6, far - near))
    tint = (8, 0, -8) if side == "r" else (-8, 0, 8)
    return tuple(int(max(0, min(255, light + offset))) for offset in tint)  # type: ignore[return-value]


def _torso(placed: dict[str, tuple[float, float, float]]) -> list[tuple[float, float]]:
    corners = ("r_shoulder", "l_shoulder", "l_hip", "r_hip")
    return [placed[name][:2] for name in corners]


def _face(draw: ImageDraw.ImageDraw, placed: dict[str, tuple[float, float, float]], face: set[str], unit: float) -> None:
    for eye in ("r_eye", "l_eye"):
        if eye in face:
            x, y, _ = placed[eye]
            draw.ellipse((x - unit * 0.008, y - unit * 0.008, x + unit * 0.008, y + unit * 0.008), fill=(30, 30, 30))
    if "nose" in face:
        x, y, _ = placed["nose"]
        draw.ellipse((x - unit * 0.01, y - unit * 0.01, x + unit * 0.01, y + unit * 0.01), fill=(120, 90, 80))


def _mannequin(placed: dict[str, tuple[float, float, float]], direction: str, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    unit = size[1] * (FEET_SHARE - TOP_SHARE)
    depths = [value[2] for value in placed.values()]
    near, far = min(depths), max(depths)
    torso_depth = sum(placed[name][2] for name in ("r_shoulder", "l_shoulder", "r_hip", "l_hip")) / 4
    items: list[tuple[float, Any]] = [(torso_depth, ("torso", None))]
    items += [((placed[a][2] + placed[b][2]) / 2, ("part", (a, b, width, side))) for a, b, width, side in PARTS]
    for _depth, (kind, part) in sorted(items, key=lambda item: -item[0]):
        if kind == "torso":
            _capsule(draw, placed["pelvis"][:2], placed["neck"][:2], unit * 0.12, _shade(torso_depth, near, far, "c"))
            draw.polygon(_torso(placed), fill=_shade(torso_depth, near, far, "c"), outline=(30, 30, 30), width=3)
            _capsule(draw, placed["neck"][:2], placed["head"][:2], unit * 0.05, _shade(torso_depth, near, far, "c"))
            continue
        a, b, width, side = part
        lift = unit * width / 2 + 3 if a.endswith("heel") else 0.0  # the sole, not the middle of the foot, touches the ground
        ends = [(placed[name][0], placed[name][1] - lift) for name in (a, b)]
        _capsule(draw, ends[0], ends[1], unit * width, _shade((placed[a][2] + placed[b][2]) / 2, near, far, side))
    x, y, _ = placed["head"]
    radius = (placed["head"][1] - placed["head_top"][1]) * 1.05
    draw.ellipse((x - radius * 0.8, y - radius, x + radius * 0.8, y + radius), fill=(205, 205, 205), outline=(30, 30, 30), width=3)
    _face(draw, placed, visible_face(direction), unit)
    return canvas


def guide_image(direction: str, phase: float, size: tuple[int, int] = (896, 1152), style: str = "skeleton") -> Image.Image:
    """The guide of one pose: the walk at ``phase`` seen from the camera of ``direction``, as ``style`` draws it."""
    if style not in STYLES:
        raise WalkGuideError(f"style is one of {', '.join(STYLES)}")
    placed = project(to_picture(walk_pose(phase + SHIFT.get(direction, 0.0)), direction), size)
    return _skeleton(placed, direction, size) if style == "skeleton" else _mannequin(placed, direction, size)


# The legs are the lowest part of a figure: below this share of its height from the top.
LEGS = 0.72


def leg_spread(figure: Image.Image, floor: int = 8) -> float:
    """How wide the legs of a keyed figure are, as a share of its height: the width of the lowest part of its outline. A stride is
    wide in profile and narrow at the passing pose; a figure seen from the front or the back is narrow all through its walk."""
    mask = np.asarray(figure.getchannel("A")) > floor
    rows = np.nonzero(mask.any(axis=1))[0]
    if not len(rows):
        return 0.0
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    columns = np.nonzero(mask[top + int((bottom - top) * LEGS):bottom].any(axis=0))[0]
    return float(columns[-1] - columns[0] + 1) / (bottom - top) if len(columns) else 0.0


@lru_cache(maxsize=512)
def _expected(direction: str, phase: float) -> float:
    guide = guide_image(direction, phase, (224, 288), "mannequin")
    figure = Image.new("RGBA", guide.size, (0, 0, 0, 0))
    figure.putalpha(Image.fromarray(((np.asarray(guide.convert("L")) < 250) * 255).astype(np.uint8)))
    return leg_spread(figure)


def expected_spread(direction: str, phase: float) -> float:
    """How wide the legs of a walk pose should be (``leg_spread`` of the guide's mannequin)."""
    return _expected(direction, round(phase % 1.0, 4))


def parse_size(resolution: str) -> tuple[int, int]:
    """``"896x1152"`` as (width, height)."""
    try:
        width, height = (int(part) for part in str(resolution).lower().split("x"))
    except ValueError as error:
        raise WalkGuideError("resolution is WIDTHxHEIGHT") from error
    if not (64 <= width <= 4096 and 64 <= height <= 4096):
        raise WalkGuideError("resolution is between 64 and 4096 pixels a side")
    return width, height


__all__ = ["STYLES", "TURN", "WalkGuideError", "curve", "expected_spread", "guide_image", "leg_spread", "parse_size", "phase_of", "project", "to_picture", "visible_face", "walk_pose"]

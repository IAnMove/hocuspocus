"""Walk cycles made of ONE drawing: the character is cut into rigid pieces and the pieces are moved with the walk mould.

Asking an image model for twelve walk poses gives twelve slightly different people (the bag, the hem, the boots change) and legs that
barely follow the guide. A puppet cannot do that: every frame is made of the same pixels. Three parts do the work:

* the pose model (DWPose, ``face_landmarks``) finds the joints of the drawing, on one reference picture of the character;
* the mould (``walk_guides``) knows where every joint of a walking body is, seen from each of the five directions;
* the drawing is cut into a head, a torso and two arms, two thighs, two shins and two feet; each piece follows its bone.

A bone of the drawing keeps its own length and thickness; what it takes from the mould is the *change* since the reference pose: the
angle it turns and, seen from the front, how much it shortens (a leg that swings toward the viewer is shorter in the picture). So the same
routine makes the side walk (legs and arms swing across the picture) and the front or back walk (they swing in depth: the picture shows
shorter legs, a bobbing body and a swaying pelvis). The depth of each joint, from the mould, says which limb is in front.

A skirt hides the thigh: it is kept with the torso (``skirt`` mask) and the thigh is a plain strip under it. A reference pose where the
limbs are apart (legs spread and arms away from the body, as in the contact poses of a walk sheet, or an A-pose from the front) cuts best.
"""
from __future__ import annotations

import math
import os
from typing import Any

import cv2
import numpy as np
from PIL import Image

from services import face_landmarks
from services.walk_guides import SHIFT, project, to_picture, walk_pose

SIDES = "rl"
# OpenPose indexes of the body points the puppet needs (face_landmarks returns the 18 points of the body first).
POINTS = {"nose": 0, "neck": 1, "r_shoulder": 2, "r_elbow": 3, "r_wrist": 4, "l_shoulder": 5, "l_elbow": 6, "l_wrist": 7,
          "r_hip": 8, "r_knee": 9, "r_ankle": 10, "l_hip": 11, "l_knee": 12, "l_ankle": 13}
MIN_SCORE = 0.3
MOULD = 1000            # the mould is projected at this size; only its ratios and displacements are used
UP = 2                  # frames are drawn this many times larger and shrunk again: clean edges
OVERLAP = 3             # pixels each piece reaches into its neighbours, so a turned piece leaves no crack
SHARE = {"arm": 0.06, "leg": 0.085}     # reach of a limb, as a share of the figure's height
BLEND = 0.04             # half the length of a soft joint, as a share of the figure's height
MESH = 8                 # pixels between the vertices of a limb's mesh
ROOT = {"arm": 0.3, "leg": 0.15}  # how far down a limb its root joint still pulls, as a share of its first bone
PELVIS = (0.75, 0.25)     # trousers: the hips stay with the torso down to this share of the thigh, fading out over this much more
LAYER_NAMES = ("bottomwear", "legwear", "topwear", "neck", "neckwear", "handwear", "footwear")   # back to front
HAND, FOOT = 0.45, 0.6   # a hand reaches this far past the wrist, a foot past the ankle (shares of the bone)
MIN_BONE = 0.03          # a bone that is shorter than this share of the figure in the mould's picture does not scale or turn
SCALE_RANGE = (0.3, 1.7)
FRONT = ("front", "back")


class WalkPuppetError(ValueError):
    """The drawing cannot be cut or moved (no joints found, a limb missing)."""


def _unit(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-6)


def _turn(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s], [s, c]])


def find_joints(rgba: np.ndarray) -> dict[str, np.ndarray]:
    """The joints of the drawing, in its pixels."""
    height, width = rgba.shape[:2]
    page = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    page.alpha_composite(Image.fromarray(rgba, "RGBA"))
    found = face_landmarks.detect(page.convert("RGB"))
    body = (found or {}).get("body") or []
    joints = {name: np.array(body[i][:2], float) for name, i in POINTS.items() if i < len(body) and body[i][2] >= MIN_SCORE}
    missing = [name for name in POINTS if name not in joints]
    if missing:
        raise WalkPuppetError(f"the pose model did not find {', '.join(missing)} on the drawing")
    return joints


def mould(direction: str, phase: float) -> dict[str, np.ndarray]:
    """Every joint of the walking body in the picture of ``direction``: x, y (mould pixels) and depth (smaller is nearer)."""
    points = project(to_picture(walk_pose(phase + SHIFT.get(direction, 0.0)), direction), (MOULD, MOULD))
    return {name: np.array(value, float) for name, value in points.items()}


def _hipmid(joints: dict[str, np.ndarray]) -> np.ndarray:
    return (joints["r_hip"] + joints["l_hip"]) / 2


def _faces_left(joints: dict[str, np.ndarray], direction: str) -> bool:
    return direction not in FRONT and joints["nose"][0] < joints["neck"][0]


def _normal(points: dict[str, np.ndarray], names: tuple[str, ...], origin: np.ndarray, size: float) -> np.ndarray:
    return np.array([(points[name][:2] - origin) / size for name in names]).ravel()


def pair_sides(drawn: dict[str, np.ndarray], ref: dict[str, np.ndarray]) -> dict[str, dict[str, str]]:
    """Which drawn limb is the mould's right one, for the legs and for the arms. The pose model calls a limb right or left by its
    look, which in profile is a guess: the pairing is the one that puts the ankles (and wrists) nearest where the mould has them."""
    d_size = float(np.linalg.norm(drawn["neck"] - _hipmid(drawn)))
    m_size = float(np.linalg.norm(ref["neck"][:2] - ref["pelvis"][:2]))
    pairs: dict[str, dict[str, str]] = {}
    for group, part in (("legs", "ankle"), ("arms", "wrist")):
        names = tuple(f"{side}_{part}" for side in SIDES)
        want = _normal(ref, names, ref["neck"][:2], m_size)
        costs = {}
        for swap in (False, True):
            order = names[::-1] if swap else names
            costs[swap] = float(np.linalg.norm(_normal(drawn, order, drawn["neck"], d_size) - want))
        swap = costs[True] < costs[False]
        pairs[group] = {"r": "l" if swap else "r", "l": "r" if swap else "l"}
    return pairs


def _chain(points: np.ndarray, chain: list[np.ndarray], push: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Distance of each point to the bones of a limb (joint to joint) and how far along the limb the nearest bone puts it, in pixels
    from the first joint. The first bone goes on above its joint (a trouser waist is the thigh's too) and the last one ``push`` of its length past the end."""
    best = np.full(len(points), np.inf)
    along = np.zeros(len(points))
    start = 0.0
    for index in range(len(chain) - 1):
        a, b = chain[index], chain[index + 1]
        axis = b - a
        length = max(float(np.linalg.norm(axis)), 1e-6)
        t = np.clip(((points - a) @ axis) / length ** 2, -1.0 if index == 0 else 0.0, 1.0 + (push if index == len(chain) - 2 else 0.0))
        distance = np.linalg.norm(points - (a + t[:, None] * axis), axis=1)
        nearer = distance < best
        best[nearer] = distance[nearer]
        along[nearer] = start + t[nearer] * length
        start += length
    return best, along


def load_layers(folder: str) -> dict[str, np.ndarray]:
    """The garment layers See-through cut out of the drawing (``services/see_through``), the ones the puppet uses."""
    layers = {}
    for name in LAYER_NAMES:
        path = os.path.join(folder, f"{name}.png")
        if os.path.exists(path):
            layers[name] = np.array(Image.open(path).convert("RGBA"))
    return layers


def _is_skirt(layer: np.ndarray, joints: dict[str, np.ndarray]) -> bool:
    """A bottom garment that ends above the knees' half way to the ankles is a skirt (or shorts): the legs come out under it."""
    rows = np.nonzero(layer[..., 3] > 40)[0]
    knee = (joints["r_knee"][1] + joints["l_knee"][1]) / 2
    ankle = (joints["r_ankle"][1] + joints["l_ankle"][1]) / 2
    return bool(len(rows)) and float(rows.max()) < knee + 0.5 * (ankle - knee)


def _paint(target: np.ndarray, layer: np.ndarray, mask: np.ndarray) -> None:
    """Lay the pixels of ``layer`` under ``mask`` over ``target`` (both RGBA uint8)."""
    front = layer.astype(np.float32)
    alpha = front[..., 3:4] / 255.0 * mask[..., None]
    back = target.astype(np.float32)
    back_alpha = back[..., 3:4] / 255.0
    out = alpha + back_alpha * (1 - alpha)
    rgb = (front[..., :3] * alpha + back[..., :3] * back_alpha * (1 - alpha)) / np.maximum(out, 1e-6)
    target[...] = np.dstack([rgb, out * 255.0]).astype(np.uint8)


def _components(mask: np.ndarray, want: int) -> list[np.ndarray]:
    """The ``want`` biggest separate parts of a mask; one part that holds two limbs (both arms in one layer) is split by eroding it until it comes apart."""
    count, parts = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    found = sorted((parts == i for i in range(1, count)), key=lambda part: -int(part.sum()))
    found = [part for part in found if int(part.sum()) >= 300]
    if len(found) >= want or not found:
        return found[:want]
    whole = found[0].astype(np.uint8)
    for radius in range(1, 60):
        core = cv2.erode(whole, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1)))
        count, seeds = cv2.connectedComponents(core, connectivity=8)
        if count - 1 >= want:
            sizes = sorted(range(1, count), key=lambda i: -int((seeds == i).sum()))[:want]
            markers = np.zeros(mask.shape, np.int32)
            for number, i in enumerate(sizes, 1):
                markers[seeds == i] = number
            grown = cv2.watershed(cv2.cvtColor(whole * 255, cv2.COLOR_GRAY2BGR), markers)
            return [(grown == number) & found[0] for number in range(1, want + 1)]
    return found


def _adopt_strays(label: np.ndarray, rows: np.ndarray, cols: np.ndarray, size: tuple[int, int]) -> None:
    """A bit of a piece that is cut off from the rest of it (the toe of a boot past a limb's reach) joins the piece it touches most."""
    everything = np.full(size, "", dtype=object)
    everything[rows, cols] = label
    for name in sorted(set(label.tolist())):
        mask = np.zeros(size, np.uint8)
        mask[rows[label == name], cols[label == name]] = 1
        count, parts = cv2.connectedComponents(mask, connectivity=8)
        if count <= 2:
            continue
        main = 1 + int(np.argmax([int((parts == i).sum()) for i in range(1, count)]))
        for i in range(1, count):
            if i == main:
                continue
            part = parts == i
            ring = cv2.dilate(part.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
            around = [v for v in everything[ring & ~part].tolist() if v and v != name]
            if around:
                label[part[rows, cols]] = max(set(around), key=around.count)


def _smooth(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def cut_groups(rgba: np.ndarray, joints: dict[str, np.ndarray], layers: dict[str, np.ndarray] | None = None) -> dict[str, Any]:
    """The parts of the drawing: ``{name: picture (RGBA)}`` for the torso, the head and, for each drawn side, the arm, the leg and the foot,
    and under ``"skirt"`` the mask of a skirt (kept with the torso).

    With the garment layers (See-through) each layer goes where it belongs: the jacket and skirt to the torso, the sleeves to the arms,
    the trousers to the legs, the boots to the feet, each already painted whole behind what covered it. Whatever no layer holds (the hat,
    a bag) and every drawing without layers is cut by the bones: a pixel goes to the limb whose bone is nearest, inside its reach."""
    height, width = rgba.shape[:2]
    layers = layers or {}
    solid = rgba[..., 3] > 40
    rows, cols = np.nonzero(solid)
    figure = float(rows.max() - rows.min())
    neck, hips = joints["neck"], _hipmid(joints)
    down = _unit(hips - neck)
    grid = np.stack(np.meshgrid(np.arange(width), np.arange(height)), -1).reshape(-1, 2).astype(float)
    head_zone = (((grid - neck) @ down) < -0.015 * figure).reshape(height, width)
    chains = {side: {"arm": [joints[f"{side}_{part}"] for part in ("shoulder", "elbow", "wrist")],
                     "leg": [joints[f"{side}_{part}"] for part in ("hip", "knee", "ankle")]} for side in SIDES}
    groups = {name: np.zeros((height, width, 4), np.uint8) for name in ("torso", "head") + tuple(f"{kind}_{side}" for kind in ("arm", "leg", "foot") for side in SIDES)}
    _paint(groups["head"], rgba, solid & head_zone)
    skirt = "bottomwear" in layers and _is_skirt(layers["bottomwear"], joints)
    covered = np.zeros((height, width), bool)

    def by_limb(mask: np.ndarray, kind: str) -> dict[str, np.ndarray]:
        """The pixels of a mask shared out between the two limbs of a kind, to the nearest."""
        ys, xs = np.nonzero(mask)
        pts = np.column_stack([xs, ys]).astype(float)
        mine = _chain(pts, chains["r"][kind], push=FOOT)[0] <= _chain(pts, chains["l"][kind], push=FOOT)[0]
        return {side: _mask_of(ys, xs, (mine if side == "r" else ~mine), (height, width)) for side in SIDES}

    for name in LAYER_NAMES:
        if name not in layers:
            continue
        layer = layers[name]
        mask = (layer[..., 3] > 40) & ~head_zone
        covered |= layer[..., 3] > 40
        if name in ("topwear", "neck", "neckwear") or (name == "bottomwear" and skirt):
            _paint(groups["torso"], layer, mask)
        elif name in ("bottomwear", "legwear"):
            for side, part in by_limb(mask, "leg").items():
                _paint(groups[f"leg_{side}"], layer, part)
        else:   # sleeves and boots come as two separate parts, one for each limb
            kind, group = ("arm", "arm") if name == "handwear" else ("leg", "foot")
            parts = _components(mask, 2)
            if len(parts) == 2:
                ys0, xs0 = np.nonzero(parts[0])
                pts0 = np.column_stack([xs0, ys0]).astype(float)[::25]
                keep = float(np.mean(_chain(pts0, chains["r"][kind], push=FOOT)[0])) <= float(np.mean(_chain(pts0, chains["l"][kind], push=FOOT)[0]))
                sides = {"r": parts[0] if keep else parts[1], "l": parts[1] if keep else parts[0]}
            else:
                sides = by_limb(mask, kind)
            for side, part in sides.items():
                _paint(groups[f"{group}_{side}"], layer, part)
    # what no layer holds, and every pixel when there are no layers: by the bones
    rest = solid & ~head_zone & ~covered
    ys, xs = np.nonzero(rest)
    if len(ys):
        pts = np.column_stack([xs, ys]).astype(float)
        label = np.full(len(pts), "torso", dtype=object)
        best = np.full(len(pts), np.inf)
        below_hip = ((pts - neck) @ down) > float(down @ (hips - neck)) - 0.03 * figure
        for side in SIDES:
            for kind, share, limit in (("arm", SHARE["arm"], None), ("leg", SHARE["leg"], below_hip)):
                distance, along = _chain(pts, chains[side][kind], push=HAND if kind == "arm" else FOOT)
                taken = (distance < share * figure) & (distance < best)
                if limit is not None:
                    taken &= limit
                best[taken] = distance[taken]
                label[taken] = f"{kind}_{side}"
                if kind == "leg":
                    reach = float(np.linalg.norm(chains[side]["leg"][1] - chains[side]["leg"][0]) + np.linalg.norm(chains[side]["leg"][2] - chains[side]["leg"][1]))
                    label[taken & (along > reach)] = f"foot_{side}"
        _adopt_strays(label, ys, xs, (height, width))
        for name in sorted(set(label.tolist())):
            _paint(groups[name], rgba, _mask_of(ys, xs, label == name, (height, width)))
        if "topwear" not in layers:   # an arm lay over the torso: the torso goes on under it
            hole = cv2.morphologyEx((groups["torso"][..., 3] > 0).astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))) > 0
            hole &= (groups["torso"][..., 3] == 0) & solid & ~head_zone
            if int(hole.sum()):
                filled = cv2.inpaint(np.ascontiguousarray(rgba[..., :3]), (hole * 255).astype(np.uint8), 5, cv2.INPAINT_TELEA)
                groups["torso"][hole, :3] = filled[hole]
                groups["torso"][hole, 3] = 255
    out: dict[str, Any] = {name: picture for name, picture in groups.items() if name in ("torso", "head") or int((picture[..., 3] > 0).sum()) >= 40}
    out["skirt"] = (cv2.dilate((layers["bottomwear"][..., 3] > 40).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) if skirt else None
    out["figure"] = figure
    return out


def _mask_of(ys: np.ndarray, xs: np.ndarray, pick: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(size, bool)
    mask[ys[pick], xs[pick]] = True
    return mask


def limb_mesh(picture: np.ndarray, chain: list[np.ndarray], root_reach: float, blend: float) -> dict[str, np.ndarray]:
    """A mesh over one limb's picture, with the weight each vertex gives to its three bones: the one the limb hangs from (``root``, the
    pelvis or the torso), the upper bone and the lower bone. Near the root joint a vertex follows the root, then the upper bone; round
    the middle joint it passes from the upper to the lower bone, so a garment bends instead of breaking."""
    height, width = picture.shape[:2]
    occupied = cv2.dilate((picture[..., 3] > 0).astype(np.uint8), np.ones((2 * MESH + 1, 2 * MESH + 1), np.uint8)) > 0
    xs, ys = np.meshgrid(np.arange(0, width, MESH), np.arange(0, height, MESH))
    keep = occupied[ys, xs]
    number = -np.ones(xs.shape, int)
    number[keep] = np.arange(int(keep.sum()))
    src = np.column_stack([xs[keep], ys[keep]]).astype(float)
    cells = keep[:-1, :-1] & keep[1:, :-1] & keep[:-1, 1:] & keep[1:, 1:]
    i, j = np.nonzero(cells)
    a, b, c, d = number[i, j], number[i, j + 1], number[i + 1, j], number[i + 1, j + 1]
    tris = np.vstack([np.column_stack([a, b, c]), np.column_stack([b, d, c])])
    along = _chain(src, chain, push=1.0)[1]
    joint = float(np.linalg.norm(chain[1] - chain[0]))
    root = 1.0 - _smooth(along / max(root_reach, 1.0))
    knee = _smooth((along - (joint - blend)) / (2 * blend))
    weights = np.column_stack([root, (1 - root) * (1 - knee), (1 - root) * knee])
    return {"src": src, "tris": tris, "weights": weights, "along": along, "joint": np.array(joint)}


def _skin(picture: np.ndarray, mesh: dict[str, np.ndarray], bones: list[tuple[np.ndarray, np.ndarray, np.ndarray]], size: tuple[int, int]) -> np.ndarray:
    """The picture of a limb with its mesh moved by the three bones (each ``(matrix, anchor in the drawing, anchor now)``): premultiplied float, ``UP`` times larger."""
    width, height = size
    out = np.zeros((height * UP, width * UP, 4), np.float32)
    src, tris = mesh["src"], mesh["tris"]
    if not len(tris):
        return out
    dst = sum(w[:, None] * (anchor1 + (src - anchor0) @ matrix.T) for w, (matrix, anchor0, anchor1) in zip(mesh["weights"].T, bones))
    low = np.maximum(np.floor(dst.min(0) * UP).astype(int) - 2, 0)
    high = np.minimum(np.ceil(dst.max(0) * UP).astype(int) + 2, [width * UP, height * UP])
    if (high <= low).any():
        return out
    ox, oy = low
    index = np.zeros((high[1] - oy, high[0] - ox), np.int32)
    corners = np.round((dst[tris] * UP - low) * 16).astype(np.int32)
    for number in range(len(tris)):
        cv2.fillConvexPoly(index, corners[number], number + 1, cv2.LINE_8, 4)
    # the map from a pixel of the moved picture back to the drawing: one affine map per triangle
    d, s = dst[tris] * UP, src[tris]
    system = np.concatenate([d, np.ones((len(tris), 3, 1))], axis=2)
    ok = np.abs(np.linalg.det(system)) > 1e-9
    coefficients = np.zeros((len(tris) + 1, 2, 3))
    coefficients[1:][ok] = np.linalg.solve(system[ok], s[ok]).transpose(0, 2, 1)
    yy, xx = np.nonzero(index)
    which = index[yy, xx]
    gx = xx + ox
    gy = yy + oy
    sx = coefficients[which, 0, 0] * gx + coefficients[which, 0, 1] * gy + coefficients[which, 0, 2]
    sy = coefficients[which, 1, 0] * gx + coefficients[which, 1, 1] * gy + coefficients[which, 1, 2]
    premultiplied = picture.astype(np.float32) / 255.0
    premultiplied[..., :3] *= premultiplied[..., 3:4]
    map_x = np.full(index.shape, -10.0, np.float32)
    map_y = np.full(index.shape, -10.0, np.float32)
    map_x[yy, xx] = sx
    map_y[yy, xx] = sy
    out[oy:oy + index.shape[0], ox:ox + index.shape[1]] = cv2.remap(premultiplied, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return out


def _bone_matrix(v0: np.ndarray, m0: np.ndarray, m1: np.ndarray) -> np.ndarray:
    """The 2×2 map that takes a bone of the drawing (``v0``) to the bone it becomes when the mould's bone goes from ``m0`` to ``m1``:
    turned by the angle the mould's bone turned, shorter or longer along itself by its change of length, as thick as before."""
    if float(np.linalg.norm(m0)) < MIN_BONE * MOULD:
        return np.eye(2)
    turned = math.atan2(m1[1], m1[0]) - math.atan2(m0[1], m0[0])
    scale = float(np.clip(np.linalg.norm(m1) / np.linalg.norm(m0), *SCALE_RANGE))
    axis = _unit(v0)
    return _turn(turned) @ (np.eye(2) + (scale - 1.0) * np.outer(axis, axis))


def pose_at(joints: dict[str, np.ndarray], feet: dict[str, np.ndarray], pairs: dict[str, dict[str, str]], ref: dict[str, np.ndarray],
            now: dict[str, np.ndarray], mirror: bool, k: float) -> dict[str, Any]:
    """Where every joint of the drawing goes at one phase, and the map of each piece (``(matrix, anchor in the drawing, anchor now)``)."""
    def m(points: dict[str, np.ndarray], name: str) -> np.ndarray:
        x, y = points[name][:2]
        return np.array([-x if mirror else x, y])
    def bone(points: dict[str, np.ndarray], a: str, b: str) -> np.ndarray:
        return m(points, b) - m(points, a)
    out: dict[str, Any] = {"maps": {}, "joints": {}, "depth": {}}
    spine0 = joints["neck"] - _hipmid(joints)
    spine_map = _bone_matrix(spine0, bone(ref, "pelvis", "neck"), bone(now, "pelvis", "neck"))
    neck_now = joints["neck"] + k * (m(now, "neck") - m(ref, "neck"))
    head_map = _turn(math.atan2(*(spine_map @ _unit(spine0))[::-1]) - math.atan2(*_unit(spine0)[::-1]))
    out["maps"]["torso"] = (spine_map, joints["neck"], neck_now)
    out["maps"]["head"] = (head_map, joints["neck"], neck_now)
    out["joints"]["neck"] = neck_now
    out["depth"]["torso"] = float(now["pelvis"][2])
    chains = {"arm": ("shoulder", "elbow", "wrist"), "leg": ("hip", "knee", "ankle")}
    for group, chain in chains.items():
        for side in SIDES:
            drawn_side = pairs["arms" if group == "arm" else "legs"][side]
            names = [f"{drawn_side}_{part}" for part in chain]
            moulds = [f"{side}_{part}" for part in chain]
            if group == "arm":   # the shoulders ride the torso
                start = neck_now + spine_map @ (joints[names[0]] - joints["neck"])
            else:
                start = joints[names[0]] + k * (m(now, moulds[0]) - m(ref, moulds[0]))
            out["joints"][names[0]] = start
            anchor = start
            for index in range(2):
                a, b = names[index], names[index + 1]
                matrix = _bone_matrix(joints[b] - joints[a], bone(ref, moulds[index], moulds[index + 1]), bone(now, moulds[index], moulds[index + 1]))
                piece = {"arm": ("arm_up", "arm_low"), "leg": ("thigh", "shin")}[group][index]
                out["maps"][f"{drawn_side}_{piece}"] = (matrix, joints[a], anchor)
                anchor = anchor + matrix @ (joints[b] - joints[a])
                out["joints"][b] = anchor
                out["depth"][f"{drawn_side}_{piece}"] = float((now[moulds[index]][2] + now[moulds[index + 1]][2]) / 2)
            if group == "leg":
                toe = f"{side}_toe"
                foot0 = feet[drawn_side] - joints[names[2]]
                matrix = _bone_matrix(foot0, bone(ref, moulds[2], toe), bone(now, moulds[2], toe))
                out["maps"][f"{drawn_side}_foot"] = (matrix, joints[names[2]], anchor)
                out["depth"][f"{drawn_side}_foot"] = out["depth"][f"{drawn_side}_shin"]
    return out


def _warp(piece: np.ndarray, matrix: np.ndarray, anchor0: np.ndarray, anchor1: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """A piece (RGBA uint8) moved by ``matrix`` about its anchor to the new anchor, premultiplied float, ``UP`` times larger."""
    a = piece.astype(np.float32) / 255.0
    a[..., :3] *= a[..., 3:4]
    offset = anchor1 - matrix @ anchor0
    full = np.hstack([matrix, offset[:, None]]) * UP
    return np.clip(cv2.warpAffine(a, full.astype(np.float32), (size[0] * UP, size[1] * UP), flags=cv2.INTER_CUBIC,
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0)), 0, 1)


def _over(back: np.ndarray, front: np.ndarray) -> np.ndarray:
    return front + back * (1 - front[..., 3:4])


def _strip(size: tuple[int, int], a: np.ndarray, b: np.ndarray, width: float, colour: np.ndarray) -> np.ndarray:
    """A flat limb strip from a to b: the thigh a skirt hides."""
    canvas = np.zeros((size[1] * UP, size[0] * UP, 4), np.float32)
    axis = _unit(b - a)
    normal = np.array([-axis[1], axis[0]]) * width / 2
    corners = (np.array([a + normal, a - normal, b - normal, b + normal]) * UP).astype(np.int32)
    cv2.fillConvexPoly(canvas, corners, tuple(float(c) / 255.0 for c in colour) + (1.0,))
    canvas[..., :3] *= canvas[..., 3:4]
    return canvas


def build(rgba: np.ndarray, direction: str = "side", frames: int = 12, layers: dict[str, np.ndarray] | None = None,
          joints: dict[str, np.ndarray] | None = None) -> tuple[list[np.ndarray], dict[str, Any]]:
    """The frames (RGBA, ``UP`` times the drawing's size) of one walk cycle of a drawing of the character as seen from ``direction``."""
    height, width = rgba.shape[:2]
    size = (width, height)
    joints = joints or find_joints(rgba)
    ref = mould(direction, 0.0)
    mirror = _faces_left(joints, direction)
    pairs = pair_sides(joints, {name: np.array([-p[0] if mirror else p[0], p[1], p[2]]) for name, p in ref.items()})
    parts = cut_groups(rgba, joints, layers)
    blend = BLEND * parts["figure"]
    k = float(np.linalg.norm(joints["neck"] - _hipmid(joints)) / np.linalg.norm(ref["neck"][:2] - ref["pelvis"][:2]))
    meshes, feet, covered, shin_width, whole = {}, {}, {}, {}, {}
    for side in SIDES:
        for kind in ("arm", "leg"):
            name = f"{kind}_{side}"
            if name not in parts:
                raise WalkPuppetError(f"no {kind} on the {side} side could be cut: the limbs are not apart in this drawing")
            chain = [joints[f"{side}_{part}"] for part in (("shoulder", "elbow", "wrist") if kind == "arm" else ("hip", "knee", "ankle"))]
            picture = parts[name]
            if kind == "leg":
                whole[side] = picture
            if kind == "leg" and parts["skirt"] is None:   # a thigh starts at its hip: what lies above it is the pelvis block's, and only pokes out when the thigh turns
                ys, xs = np.nonzero(picture[..., 3] > 0)
                picture = picture.copy()
                picture[ys, xs, 3] *= (_chain(np.column_stack([xs, ys]).astype(float), chain, push=1.0)[1] >= 0.0)
                parts[name] = picture
            meshes[name] = limb_mesh(picture, chain, ROOT[kind] * float(np.linalg.norm(chain[1] - chain[0])), blend)
        foot = parts.get(f"foot_{side}")
        ys, xs = np.nonzero(foot[..., 3] > 0) if foot is not None else ([], [])
        feet[side] = np.array([xs.mean(), ys.mean()]) if len(xs) else joints[f"{side}_ankle"] + np.array([0.0, 20.0])
        mesh = meshes[f"leg_{side}"]
        joint = float(mesh["joint"])
        shin = float(np.linalg.norm(joints[f"{side}_ankle"] - joints[f"{side}_knee"]))
        covered[side] = int((mesh["along"] < joint - blend).sum()) < 15
        shin_width[side] = max(8.0, float(((mesh["along"] > joint) & (mesh["along"] < joint + shin)).sum()) * MESH * MESH / max(shin, 1.0))
    pelvis = np.zeros_like(parts["torso"])   # the trousers' hips: the top of both legs is one block that stays with the torso, hiding where the thighs start
    for side in SIDES:
        if covered[side]:
            continue
        leg = whole[side]
        ys, xs = np.nonzero(leg[..., 3] > 0)
        chain = [joints[f"{side}_{part}"] for part in ("hip", "knee", "ankle")]
        reach = PELVIS[0] * float(np.linalg.norm(chain[1] - chain[0]))
        fade = PELVIS[1] * float(np.linalg.norm(chain[1] - chain[0]))
        along = _chain(np.column_stack([xs, ys]).astype(float), chain, push=1.0)[1]
        piece = leg.copy()
        piece[ys, xs, 3] = (leg[ys, xs, 3] * (1 - _smooth((along - (reach - fade)) / fade))).astype(np.uint8)
        _paint(pelvis, piece, np.ones(pelvis.shape[:2], bool))
    ground = float(np.nonzero(rgba[..., 3] > 40)[0].max())
    frames_out, info = [], {"feet": [], "ground": ground, "k": k, "mirror": mirror, "pairs": pairs, "covered": covered}
    for index in range(frames):
        pose = pose_at(joints, feet, pairs, ref, mould(direction, index / frames), mirror, k)
        maps = pose["maps"]
        drawn: dict[str, np.ndarray] = {"torso": _warp(parts["torso"], *maps["torso"], size), "head": _warp(parts["head"], *maps["head"], size)}
        for side in SIDES:
            for kind, bones in (("arm", ("arm_up", "arm_low")), ("leg", ("thigh", "shin"))):
                drawn[f"{kind}_{side}"] = _skin(parts[f"{kind}_{side}"], meshes[f"{kind}_{side}"], [maps["torso"]] + [maps[f"{side}_{bone}"] for bone in bones], size)
            if f"foot_{side}" in parts:
                drawn[f"foot_{side}"] = _warp(parts[f"foot_{side}"], *maps[f"{side}_foot"], size)
        low = [float(np.nonzero(drawn[name][..., 3].max(1) > 0.4)[0].max()) / UP for name in drawn if name.startswith(("leg_", "foot_")) and (drawn[name][..., 3] > 0.4).any()]
        lift = ground - max(low)
        shift = np.float32([[1, 0, 0], [0, 1, lift * UP]])
        drawn = {name: cv2.warpAffine(picture, shift, (width * UP, height * UP)) for name, picture in drawn.items()}
        torso_depth = pose["depth"]["torso"]
        legs = sorted(((pose["depth"][f"{side}_thigh"], side) for side in SIDES), reverse=True)
        arms = sorted(((pose["depth"][f"{side}_arm_up"], side) for side in SIDES), reverse=True)
        canvas = np.zeros((height * UP, width * UP, 4), np.float32)
        for depth, side in arms:
            if depth > torso_depth:
                canvas = _over(canvas, drawn[f"arm_{side}"])
        skirt_span = None
        if parts["skirt"] is not None:   # a thigh the skirt hides is a strip from hip to knee, seen only inside the skirt
            skirt = _warp(np.dstack([np.zeros((height, width, 3), np.uint8), parts["skirt"].astype(np.uint8) * 255]), *maps["torso"], size)[..., 3]
            solid = cv2.warpAffine(skirt, shift, (width * UP, height * UP)) > 0.3
            line = np.arange(solid.shape[0])[:, None]
            top = np.where(solid.any(0), solid.argmax(0), 10 ** 9)[None, :]
            bottom = np.where(solid.any(0), solid.shape[0] - 1 - solid[::-1].argmax(0), -1)[None, :]
            skirt_span = ((line >= top) & (line <= bottom)).astype(np.float32)[..., None]
        for _, side in legs:
            canvas = _over(canvas, drawn[f"leg_{side}"])
            if covered[side] and skirt_span is not None:
                hip, knee = pose["joints"][f"{side}_hip"], pose["joints"][f"{side}_knee"]
                alpha = parts[f"leg_{side}"][..., 3] > 0
                colour = np.median(parts[f"leg_{side}"][alpha][:, :3], axis=0)
                strip = _strip(size, hip, knee + _unit(knee - hip) * 30, shin_width[side], colour)
                canvas = _over(canvas, cv2.warpAffine(strip, shift, (width * UP, height * UP)) * skirt_span)
            if f"foot_{side}" in drawn:
                canvas = _over(canvas, drawn[f"foot_{side}"])
        if pelvis[..., 3].any():
            canvas = _over(canvas, cv2.warpAffine(_warp(pelvis, *maps["torso"], size), shift, (width * UP, height * UP)))
        canvas = _over(_over(canvas, drawn["torso"]), drawn["head"])
        for depth, side in arms:
            if depth <= torso_depth:
                canvas = _over(canvas, drawn[f"arm_{side}"])
        rgb = canvas[..., :3] / np.maximum(canvas[..., 3:4], 1e-6)
        frames_out.append((np.dstack([np.clip(rgb, 0, 1), canvas[..., 3:4]]) * 255).astype(np.uint8))
        info["feet"].append({side: (float(pose["joints"][f"{side}_ankle"][0]), float(pose["joints"][f"{side}_ankle"][1] + lift)) for side in SIDES})
    return frames_out, info

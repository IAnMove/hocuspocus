"""One picture for the whole head: the front, side and back portraits joined round the skull before a viewer sees them.

A head picture is three portraits painted side by side. Each one is right only where it looks straight at the head: the front
picture is the face, the side picture is the flank and the ear. Draped by a flat projection, the side picture also lays its own eye,
brow and temple on the cheek of the mould (a profile shows them at a depth that is the flank of a round skull), and the front picture
runs out of head before the mould does: the painted face ends about where the face patch does, and all the flank of the head, from the
corner of the eye to the ear, is a few pixels of it seen edge on. Blending the two by angle then shows both: a second face beside the
face.

Here the join is made once, in the picture. The front picture is its flat projection inside the face (the face patch shows the same
pixels) and fades out a little past the corner of the eye. The flank is the side picture laid **by its length along the head**, not by
a flat projection: what the profile shows between the corner of the eye and the ear goes, at its own scale, on the mould between the
face and the ear, so the profile's eye never lands on the cheek. Behind the ear the side picture is its flat projection, and the back
picture takes over round the nape. The pictures are joined in bands of detail (tones over a wide angle, fine texture over a narrow
one), as a panorama is. The result is a map of yaw by height that a viewer samples with no blending at all.
Pure numpy and OpenCV, about two seconds."""
from __future__ import annotations

import math

import numpy as np

MAP_SIZE = (1364, 1024)      # 360 degrees by the head tile's height: the two thirds of the head half that the side and back tiles used
FACE_BLEND = 10.0            # degrees inside the face patch's border where the front picture starts to give way (the patch fades over the last of them)
FRONT_OUT = 20.0             # degrees over which the front picture fades into the side picture, from where the patch starts to fade
EDGE_YAW = 90.0              # where the painted head's outline lands
EYE_DEPTH = 0.6              # of the profile's depth before the axis: just behind the corner of the eye, where the flank starts
BACK_HOLD = 32.0             # degrees from the nape where the back picture is still its flat projection
BACK_FROM, BACK_FULL = 112.0, 136.0   # the back picture comes in over this band of yaw
LEVELS = 5
NEAR_MOULD = (0.76, 1.12)    # a measure of the painted head is kept within these shares of the mould's
TONE_RANGE = (0.85, 1.2)     # how far a picture's tones may be moved to meet its neighbour's
EAR_ROWS = 0.2               # of the tile's height: bumps of the outline shorter than this are ears, not head


def _mask(tile: np.ndarray) -> np.ndarray:
    """The painted pixels of a tile: what is not the picture's ground colour (its top corners). Dark hair on a dark ground is close
    to it, so the cut is low, and the specks it lets in are dropped: holes are filled and only the largest piece is kept."""
    from scipy import ndimage

    corners = np.concatenate([tile[:12, :12].reshape(-1, 3), tile[:12, -12:].reshape(-1, 3)]).astype(np.float32)
    ground = np.median(corners, axis=0)
    mask = np.abs(tile.astype(np.float32) - ground).max(axis=2) > 13
    mask = ndimage.binary_fill_holes(ndimage.binary_closing(ndimage.binary_opening(mask, iterations=2), iterations=4))
    labels, count = ndimage.label(mask)
    if count > 1:
        mask = labels == 1 + int(np.argmax(ndimage.sum(mask, labels, range(1, count + 1))))
    return mask


def _fill(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Rows without a measure take the nearest measured row's."""
    rows = np.arange(len(values))
    if not valid.any():
        return np.zeros_like(values)
    return np.interp(rows, rows[valid], values[valid])


def _smooth(values: np.ndarray, sigma: float) -> np.ndarray:
    from scipy import ndimage

    return ndimage.gaussian_filter1d(values, sigma, mode="nearest")


def silhouettes(tiles: list[np.ndarray], tile_w: float) -> dict[str, np.ndarray]:
    """Per row of the head tiles, in metres from the head's axis: the painted head's half width seen from the front (``left`` is the
    picture's left, the character's right) and from behind, and its depth before and behind the axis seen from the side. A nose stands
    out of the ring of the head, so the front depth is the lower envelope over the rows near it."""
    from scipy import ndimage

    out = {}
    height, width = tiles[0].shape[:2]
    per_px = tile_w / width
    for name, tile in (("front", tiles[0]), ("side", tiles[1]), ("back", tiles[2])):
        mask = _mask(tile)
        any_row = mask.any(axis=1)
        first = np.where(any_row, mask.argmax(axis=1), 0).astype(np.float64)
        last = np.where(any_row, width - 1 - mask[:, ::-1].argmax(axis=1), 0).astype(np.float64)
        low = _fill((width / 2 - first) * per_px, any_row)
        high = _fill((last - width / 2) * per_px, any_row)
        if name == "side":
            low = ndimage.minimum_filter1d(low, max(3, height // 8), mode="nearest")   # the face without its nose
        else:
            # the head without its ears: an ear is a bump of the outline a fifth of the head tall, an opening that tall takes it off
            low, high = (ndimage.grey_opening(side, size=max(3, int(height * EAR_ROWS)), mode="nearest") for side in (low, high))
        sigma = height / 120
        out[name + "_low"], out[name + "_high"] = _smooth(np.maximum(low, 1e-4), sigma), _smooth(np.maximum(high, 1e-4), sigma)
    return out


def radius_map(triangles: np.ndarray, frame: dict, size: tuple[int, int] = (360, 256), samples: int = 600000) -> np.ndarray:
    """The mould's radius about the head's axis for every yaw (-180 to 180, the face at the middle) and row of the head tile: the
    farthest surface point of each cell, from points spread over the head's triangles (``triangles``: n x 3 x 3)."""
    from scipy import ndimage

    cy, span, _cut = frame["head"]
    width, height = size
    rng = np.random.RandomState(7)
    area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1)
    pick = rng.choice(len(triangles), samples, p=area / area.sum())
    a = rng.rand(samples, 2)
    flip = a.sum(axis=1) > 1
    a[flip] = 1 - a[flip]
    weights = np.concatenate([a, 1 - a.sum(axis=1, keepdims=True)], axis=1)
    points = np.einsum("sk,skc->sc", weights, triangles[pick])
    column = ((np.degrees(np.arctan2(points[:, 0], points[:, 2])) + 180) / 360 * width).astype(int) % width
    row = np.clip(((0.5 - (points[:, 1] - cy) / span) * height).astype(int), 0, height - 1)
    radius = np.zeros((height, width))
    np.maximum.at(radius, (row, column), np.hypot(points[:, 0], points[:, 2]))
    seen = radius > 0
    radius = ndimage.grey_closing(radius, size=(5, 5), mode="wrap")
    # rows the mould does not reach (above the crown, a gap) take the nearest radius, so the map has no hole
    filled = np.where(radius > 0, radius, 0)
    if not seen.all():
        index = ndimage.distance_transform_edt(radius <= 0, return_distances=False, return_indices=True)
        filled = radius[tuple(index)]
    return ndimage.gaussian_filter(filled, (1.0, 1.5), mode=("nearest", "wrap"))


def head_triangles(mesh, frame: dict) -> np.ndarray:
    """The triangles of ``mesh`` that take the head tiles (as ``blob_texture._is_head``), n x 3 x 3."""
    _cy, span, cut = frame["head"]
    triangles = np.asarray(mesh.vertices, np.float64).reshape(-1, 3, 3)
    keep = (triangles[:, :, 1].mean(axis=1) >= cut) & (np.abs(triangles[:, :, [0, 2]]).max(axis=(1, 2)) <= span / 1.5 * 0.49)
    return triangles[keep]


def _ease(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _reach(flat: np.ndarray, at_hold: np.ndarray, edge: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Where to read a portrait across its width: its flat projection (``flat``) up to the hold angle, then on to the painted head's
    edge (``edge``) at 90 degrees, never backwards. ``t`` is 0 at the hold angle and 1 at 90 degrees."""
    edge = np.maximum(edge, at_hold * 1.02)
    stretched = at_hold + (edge - at_hold) * (1 - (1 - np.clip(t, 0, 1)) ** 3)
    return np.where(t <= 0, flat, stretched)


def _pyramid_blend(pictures: list[np.ndarray], weights: list[np.ndarray], levels: int = LEVELS) -> np.ndarray:
    """A join in bands of detail (Burt and Adelson): each level of detail of the pictures is mixed with the weights blurred to that
    level, so tones change over a wide angle and fine texture over a narrow one. The map wraps round the head."""
    import cv2

    down = cv2.pyrDown
    total = np.maximum(sum(weights), 1e-6)
    gauss = [[w / total for w in weights]]
    stack = [[p.astype(np.float32) for p in pictures]]
    for _ in range(levels):
        gauss.append([down(w) for w in gauss[-1]])
        stack.append([down(p) for p in stack[-1]])
    out = sum(p * w[..., None] for p, w in zip(stack[-1], gauss[-1]))
    for level in range(levels - 1, -1, -1):
        size = (stack[level][0].shape[1], stack[level][0].shape[0])
        out = cv2.pyrUp(out, dstsize=size)
        for index, picture in enumerate(stack[level]):
            detail = picture - cv2.pyrUp(stack[level + 1][index], dstsize=size)
            out = out + detail * gauss[level][index][..., None]
    return out


def head_map(head: np.ndarray, radius: np.ndarray, frame: dict, face_yaw: float = 40.0, blend: float = FACE_BLEND, size: tuple[int, int] = MAP_SIZE, raw: np.ndarray | None = None) -> np.ndarray:
    """The head's picture as yaw by height (uint8, ``size``; the face at the middle column, the nape at both ends) from the head
    half of the atlas ``head`` (three tiles side by side, already bled over their ground) and the mould's ``radius_map``. ``raw`` is
    the same picture before the bleed, where the silhouettes are measured (the bleed hides them)."""
    import cv2

    width, height = size
    _cy, span, _cut = frame["head"]
    tile_w = span / 1.5
    third = head.shape[1] // 3
    tiles = [np.ascontiguousarray(head[:, i * third:(i + 1) * third]).astype(np.float32) for i in range(3)]
    measured = raw if raw is not None else head
    shape = silhouettes([measured[:, i * third:(i + 1) * third] for i in range(3)], tile_w)
    rows = np.repeat(((np.arange(height) + 0.5) / height * head.shape[0] - 0.5)[:, None], width, axis=1)
    yaw = np.repeat(((np.arange(width) + 0.5) / width * 360 - 180)[None, :], height, axis=0)
    around = np.abs(yaw)
    right = yaw >= 0   # the character's left, the picture's right
    mould = cv2.resize(radius.astype(np.float32), (width, height), interpolation=cv2.INTER_LINEAR)

    hold = face_yaw - blend
    column = lambda degrees: np.clip(((np.where(right, degrees, -degrees) + 180) / 360 * width).astype(int), 0, width - 1)
    at = lambda degrees: np.take_along_axis(mould, column(np.full_like(yaw, degrees)), axis=1)

    def per_row(name: str, degrees: float) -> np.ndarray:
        """A measure of the painted head, kept near the mould's own at that yaw: a painted head follows its guide, and a measure far
        from it is a silhouette that was not found (dark hair on the dark ground), not a head that shape."""
        measure = np.repeat(cv2.resize(shape[name].astype(np.float32)[:, None], (1, height), interpolation=cv2.INTER_LINEAR), width, axis=1)
        return np.clip(measure, at(degrees) * NEAR_MOULD[0], at(degrees) * NEAR_MOULD[1])
    sign = np.where(right, 1.0, -1.0)
    # the front picture: flat inside the face, then on to the painted head's edge while it fades out
    edge_front = np.where(right, per_row("front_high", 90.0), per_row("front_low", 90.0))
    across_front = _reach(mould * np.sin(np.radians(np.minimum(around, 90))), at(hold) * math.sin(math.radians(hold)), edge_front, (around - hold) / (2 * FRONT_OUT))
    front = cv2.remap(tiles[0], ((0.5 + sign * across_front / tile_w) * third - 0.5).astype(np.float32), rows.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # the side picture: before the ear by its length along the head (from behind the eye's corner at the face to the axis at 90
    # degrees), behind the ear by its flat projection, at the painted head's depth
    start = np.minimum(per_row("side_low", 0.0) * EYE_DEPTH, at(hold) * math.cos(math.radians(hold)))
    depth_front = start * np.clip((EDGE_YAW - around) / (EDGE_YAW - hold), 0, 1.3)
    deep = per_row("side_high", 179.0) / np.maximum(at(179.0), 1e-4)
    depth = np.where(around <= 90, depth_front, mould * np.cos(np.radians(around)) * deep)
    side = cv2.remap(tiles[1], ((0.5 - depth / tile_w) * third - 0.5).astype(np.float32), rows.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # the back picture: flat round the nape, then on to the painted head's edge
    behind = 180 - around
    edge_back = np.where(right, per_row("back_low", 90.0), per_row("back_high", 90.0))
    across_back = _reach(mould * np.sin(np.radians(np.minimum(behind, 90))), at(180 - BACK_HOLD) * math.sin(math.radians(BACK_HOLD)), edge_back, (behind - BACK_HOLD) / (EDGE_YAW - BACK_HOLD))
    back = cv2.remap(tiles[2], ((0.5 - sign * across_back / tile_w) * third - 0.5).astype(np.float32), rows.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    to_side = _ease((around - hold - 1.0) / FRONT_OUT)
    # the portraits are lit each in its own way: the side picture takes the front picture's tones where they meet and goes back to
    # its own by the ear, and the back picture takes the side picture's the same way, so no step of tone marks the join
    side = _meet(side, front, around, (hold + 2.0, hold + FRONT_OUT), (hold - 10.0, hold), 84.0)
    band = (180 - BACK_FULL, 180 - BACK_FROM)
    back = _meet(back, side, 180 - around, band, band, 14.0)
    to_back = _ease((around - BACK_FROM) / (BACK_FULL - BACK_FROM))
    weights = [(1 - to_side).astype(np.float32), (to_side * (1 - to_back)).astype(np.float32), to_back.astype(np.float32)]
    # the join in bands needs room round the nape: the map is wrapped by a quarter turn on each side, joined, and cut back
    pad = width // 4
    wrap = lambda image: np.concatenate([image[:, -pad:], image, image[:, :pad]], axis=1)
    joined = _pyramid_blend([wrap(front), wrap(side), wrap(back)], [wrap(w) for w in weights])[:, pad:pad + width]
    return joined.clip(0, 255).astype(np.uint8)


def _meet(picture: np.ndarray, neighbour: np.ndarray, angle: np.ndarray, ours: tuple[float, float], theirs: tuple[float, float], free: float) -> np.ndarray:
    """``picture`` with its tones moved to ``neighbour``'s where they are joined, per row and per side of the head: the gain is the
    neighbour's tone over the band of ``angle`` ``theirs`` (where the neighbour is still good) by the picture's over ``ours``, and it
    fades to nothing at ``free`` degrees."""
    from scipy import ndimage

    width = picture.shape[1]
    out = picture.copy()
    sigma = picture.shape[0] / 10

    def tone(image: np.ndarray, band: tuple[float, float], half: slice) -> np.ndarray:
        inside = ((angle[:, half] >= band[0]) & (angle[:, half] <= band[1])).astype(np.float32)
        mean = (image[:, half] * inside[..., None]).sum(axis=1) / np.maximum(inside.sum(axis=1, keepdims=True), 1.0)
        return ndimage.gaussian_filter1d(mean + 2.0, sigma, axis=0, mode="nearest")

    for half in (slice(0, width // 2), slice(width // 2, width)):
        gain = np.clip(tone(neighbour, theirs, half) / tone(picture, ours, half), *TONE_RANGE)
        if free > ours[1]:
            fade = 1 - _ease((angle[:, half] - ours[1]) / (free - ours[1]))
        else:
            fade = 1 - _ease((ours[0] - angle[:, half]) / max(ours[0] - free, 1e-3))
        out[:, half] = picture[:, half] * (1 + (gain[:, None, :] - 1) * fade[..., None])
    return out

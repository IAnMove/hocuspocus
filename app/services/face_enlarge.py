"""Enlarge a small face, work on it, and put it back (the flat rig's small faces).

On a full figure the head is 70–150 pixels and the mouth 20–45: DWPose's lips land a few pixels off, the mouth line
snaps onto a stroke one or two pixels thick and a warp state's opening has stair-stepped edges. Cut out and enlarged
``k`` times (Lanczos, premultiplied), the face is worked on at a bust's size, and each result is brought back to the
pose's own pixels (``put_back``): k×k averages where something moved, the drawing's pixels where nothing did (a mouth
at rest is the drawing unchanged) and whole-pixel copies where the jaw moved by a whole number of pose pixels (a beard
is moved, not resampled).

Pixel centres are whole numbers in both images and pose pixel ``x`` is enlarged pixels ``k (x - x0)`` to
``k (x - x0) + k - 1``, so a point maps as ``X = k (x - x0) + (k - 1) / 2`` (``to_view``) and back (``to_image``).
"""
from __future__ import annotations

import math

import cv2
import numpy as np

# A head smaller than this (the larger of its jaw's width and its brows-to-chin height, in pose pixels) is small: the
# full figures on hand measure 72–148 px on 896×1152 poses, busts and three-quarter shots 174 px and up.
SMALL_HEAD = 160
# A small face is enlarged to about this head size (a bust's), at most MOST times.
TARGET_HEAD, MOST = 400, 6
# Without landmarks the head is guessed from the mouth: 2.9–3.5 mouth widths across on every pose measured.
HEAD_MOUTHS = 3.0
# An enlarged view is at most this many pixels across (a mouth hint dragged very wide on a small face).
MAX_VIEW = 4096


def size_class(head: float) -> str:
    return "small" if head < SMALL_HEAD else "normal"


def factor(head: float | None, view: float = 0) -> int:
    """How many times a face with this head size is enlarged: 1 (not at all) for a normal one, and never so much that
    a ``view`` pixels across grows past ``MAX_VIEW``."""
    if not head or head >= SMALL_HEAD:
        return 1
    return int(max(1, min(np.clip(round(TARGET_HEAD / head), 2, MOST), MAX_VIEW // max(1, math.ceil(view)))))


def face_caption(face: dict) -> str:
    """One short line for the rig review sheet: the head's size class and pixels, whether the landmarks were read on
    the head alone (``head pass``) and how many times the face was enlarged to warp it."""
    parts = [f"{face.get('size', 'normal')} face {round(face.get('head') or 0)} px"]
    if face.get("pass") == "head":
        parts.append("head pass")
    if (face.get("upscale") or 1) > 1:
        parts.append(f"warped {face['upscale']}x")
    return ", ".join(parts)


def to_view(points, origin, k: float) -> np.ndarray:
    """Points of the image in the view cut at ``origin`` (its top-left pixel) and enlarged ``k`` times."""
    return k * (np.asarray(points, dtype=float) - np.asarray(origin, dtype=float)) + (k - 1) / 2


def to_image(points, origin, k: float) -> np.ndarray:
    """Points of the view back in the image (``to_view`` undone)."""
    return (np.asarray(points, dtype=float) - (k - 1) / 2) / k + np.asarray(origin, dtype=float)


def view_affine(origin, k: float) -> tuple[float, float, float]:
    """``to_view`` as ``(scale, dx, dy)``: ``X = scale x + dx``, ``Y = scale y + dy``."""
    return float(k), (k - 1) / 2 - k * origin[0], (k - 1) / 2 - k * origin[1]


def image_affine(origin, k: float) -> tuple[float, float, float]:
    """``to_image`` as ``(scale, dx, dy)``."""
    return 1 / k, origin[0] - (k - 1) / (2 * k), origin[1] - (k - 1) / (2 * k)


def enlarge(pixels: np.ndarray, x0: int, y0: int, width: int, height: int, k: int, fill: int = 0) -> np.ndarray:
    """``pixels`` cut to the box (``fill`` where it runs past them) and enlarged ``k`` times with Lanczos. RGBA is
    enlarged premultiplied, so the colour behind a see-through outline never bleeds into it."""
    out = np.full((height, width, pixels.shape[2]), fill, pixels.dtype)
    h, w = pixels.shape[:2]
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(w, x0 + width), min(h, y0 + height)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = pixels[sy0:sy1, sx0:sx1]
    if k == 1:
        return out
    values = out.astype(np.float32)
    rgba = values.shape[2] == 4
    if rgba:
        values[..., :3] *= values[..., 3:] / 255
    big = np.clip(cv2.resize(values, None, fx=k, fy=k, interpolation=cv2.INTER_LANCZOS4), 0, 255)
    if rgba:
        alpha = big[..., 3:]
        big[..., :3] = np.where(alpha > 0, big[..., :3] * 255 / np.maximum(alpha, 1e-3), 0)
    return np.clip(np.round(big), 0, 255).astype(pixels.dtype)


def _blocks(values: np.ndarray, k: int) -> np.ndarray:
    """``values`` (side·k square) as ``(side, side, k·k, ...)``: each pose pixel's k×k enlarged pixels."""
    side = values.shape[0] // k
    blocks = values.reshape(side, k, side, k, *values.shape[2:]).swapaxes(1, 2)
    return blocks.reshape(side, side, k * k, *values.shape[2:])


def _source(rgba: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """``rgba`` at integer ``xs``, ``ys``; transparent off the image."""
    h, w = rgba.shape[:2]
    inside = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    out = rgba[np.clip(ys, 0, h - 1), np.clip(xs, 0, w - 1)].copy()
    out[~inside] = 0
    return out


def put_back(rgba: np.ndarray, box: tuple[int, int, int], k: int, rgb: np.ndarray, alpha: np.ndarray, changed: np.ndarray,
             dy: np.ndarray, pure: np.ndarray, fade: np.ndarray) -> np.ndarray:
    """One state worked on the enlarged face, as a patch of the pose's ``box`` square (``x0, y0, side``, pose pixels).

    ``rgb`` and ``alpha`` are the enlarged state (side·k square, not premultiplied, not faded), ``changed`` where it
    differs from the drawing, ``dy`` the downward move at each enlarged pixel and ``pure`` where that move is all there
    is (no sideways move, no opening painted). A pose pixel none of whose k×k pixels changed is the drawing's own (or
    empty where the drawing is see-through, so laid on the pose it changes nothing); one moved whole by a whole number
    of pose pixels is the drawing's pixel that far up; any other is the average of its k×k pixels. ``fade`` (side
    square, 0–1) fades the patch out at its edge."""
    x0, y0, side = box
    ys, xs = np.mgrid[0:side, 0:side]
    original = _source(rgba, xs + x0, ys + y0)
    weight = alpha.astype(np.float32) / 255
    premultiplied = _blocks(np.dstack([rgb * weight[..., None], weight]), k).mean(axis=2)
    cover = premultiplied[..., 3]
    average = np.where(cover[..., None] > 0, premultiplied[..., :3] / np.maximum(cover[..., None], 1e-6), 0)
    moved = _blocks(changed, k).any(axis=2)
    shifts = _blocks(dy, k)
    steps = shifts.max(axis=2) / k
    whole = (moved & _blocks(pure, k).all(axis=2) & (np.ptp(shifts, axis=2) < 1e-3)
             & (np.abs(steps - np.round(steps)) < 1e-3))
    copied = _source(rgba, xs + x0, ys + y0 - np.round(steps).astype(int))
    out_rgb = np.where(whole[..., None], copied[..., :3], np.where(moved[..., None], average, original[..., :3]))
    out_alpha = np.where(whole, copied[..., 3], np.where(moved, cover * 255, (original[..., 3] == 255) * 255.0)) * fade
    return np.dstack([np.clip(np.round(out_rgb), 0, 255), np.clip(np.round(out_alpha), 0, 255)]).astype(np.uint8)

"""Fit a skull to the head picture it will wear: the painted head is never exactly the mould's.

The head picture is painted by a model over a grey guide of the mould and follows it only roughly: with hair on, the upper head is narrower
(and the face and ears wider) than the mould's table. A front picture projected on a skull wider than the painted head runs out of head
(its background lands on the temples, at the yaw where the painted silhouette ends), and the junction with the side picture shows exactly
there. So the skull is fitted to the picture: for each height, how much narrower the painted front silhouette is than the mould's (never
wider, ears and the jaw above the neck stay the mould's), and how much deeper or shallower the side silhouette is at the back and at the
front. The factors ride on the layout (``skull_fit``) and ``blob_loft.skull_point`` applies them, so the head, the hair, the patch and
the ears all follow it. Pure numpy; the mould's own table is the default (no fit)."""
from __future__ import annotations

import numpy as np

LATS = tuple(range(-30, 81, 10))     # the heights fitted, degrees up from the chin's pole
WIDTH_RANGE = (0.78, 1.0)
BACK_RANGE = (0.85, 1.08)
FRONT_RANGE = (0.85, 1.0)


def _mask(tile: np.ndarray) -> np.ndarray:
    corners = np.concatenate([tile[:12, :12].reshape(-1, 3), tile[:12, -12:].reshape(-1, 3)]).astype(np.float32)
    ground = np.median(corners, axis=0)
    return np.abs(tile.astype(np.float32) - ground).max(axis=2) > 28


def _half_width(mask: np.ndarray, row: int) -> float:
    xs = np.nonzero(mask[max(0, min(mask.shape[0] - 1, row))])[0]
    return float(xs.max() - xs.min()) / 2 if len(xs) else 0.0


def _extent(mask: np.ndarray, row: int):
    xs = np.nonzero(mask[max(0, min(mask.shape[0] - 1, row))])[0]
    return (float(xs.min()), float(xs.max())) if len(xs) else None


def fit_skull(head, layout: dict, frame: dict) -> dict:
    """``{"width": [[lat, factor]...], "front": [...], "back": [...]}`` from a head picture (three tiles side by side), or {} when the
    picture does not show a head. Factors are smoothed along the height."""
    from services.blob_loft import skull_point

    width, height = head.size
    third = width // 3
    rgb = np.asarray(head.convert("RGB"))
    front, side = rgb[:, :third], rgb[:, third:2 * third]
    cy, span_y, _cut = frame["head"]
    span_x = span_y / 1.5
    tile_w, tile_h = front.shape[1], front.shape[0]
    front_mask, side_mask = _mask(front), _mask(side)
    if front_mask.sum() < 2000 or side_mask.sum() < 2000:
        return {}
    out = {"width": [], "front": [], "back": []}
    plain = {**layout}
    plain.pop("skull_fit", None)
    for lat in LATS:
        ring = [skull_point(plain, yaw, lat) for yaw in range(0, 360, 3)]
        y = ring[0][1]
        row = int((0.5 - (y - cy) / span_y) * tile_h)
        mould_half = max(abs(p[0]) for p in ring) / span_x * tile_w
        photo_half = _half_width(front_mask, row)
        w_factor = photo_half / mould_half if mould_half > 1 and photo_half > 1 else 1.0
        out["width"].append([float(lat), float(np.clip(w_factor, *WIDTH_RANGE))])
        extent = _extent(side_mask, row)
        # the side tile: the face looks to the left, a point at depth z is at column (0.5 - z / span_x) of the tile
        z_front = max(p[2] for p in ring)
        z_back = -min(p[2] for p in ring)
        if extent is not None and z_front > 0 and z_back > 0:
            centre = tile_w * 0.5
            photo_front = (centre - extent[0]) / tile_w * span_x
            photo_back = (extent[1] - centre) / tile_w * span_x
            out["front"].append([float(lat), float(np.clip(photo_front / z_front, *FRONT_RANGE))])
            out["back"].append([float(lat), float(np.clip(photo_back / z_back, *BACK_RANGE))])
        else:
            out["front"].append([float(lat), 1.0])
            out["back"].append([float(lat), 1.0])
    for key in out:
        values = np.array([f for _lat, f in out[key]], dtype=np.float64)
        kernel = np.array([0.25, 0.5, 0.25])
        padded = np.pad(values, 1, mode="edge")
        values = np.convolve(padded, kernel, mode="valid")
        out[key] = [[lat, round(float(v), 4)] for (lat, _), v in zip(out[key], values)]
    return out


def factor_at(table, lat: float) -> float:
    """The factor at ``lat`` degrees, 1 outside the fitted heights and a smooth ramp to 1 at both ends."""
    if not table:
        return 1.0
    lats = [row[0] for row in table]
    values = [row[1] for row in table]
    if lat <= lats[0]:
        t = max(0.0, 1.0 - (lats[0] - lat) / 20.0)
        return 1.0 + (values[0] - 1.0) * t
    if lat >= lats[-1]:
        t = max(0.0, 1.0 - (lat - lats[-1]) / 10.0)
        return 1.0 + (values[-1] - 1.0) * t
    return float(np.interp(lat, lats, values))

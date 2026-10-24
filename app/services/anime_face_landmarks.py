"""Optional 28-point anime face landmarks for the flat rig.

The detector (``anime-face-detector``, MIT; weights MIT; vendored mmpose,
mmdet and mmcv code Apache-2.0) runs in its own CPU environment, never in
the studio interpreter. This module only places geometry. With the
component missing, ``detect`` returns None and the rig keeps today's search.

Point order (image-left is the smaller x; the same order as hysts'
``anime-face-detector``): 0–4 contour, 5–7 left brow, 8–10 right brow,
11–16 left eye, 17–22 right eye, 23–27 mouth (23 leftmost, 26 rightmost).

The worker keeps the highest-scoring box whose 28 points average at least
``MIN_SCORE``. A brighter box with unsure points, such as a buckle drawn
like a face, is skipped, and the next sure face is used.

A white-eye box disagrees when its centre is farther than
``EYE_CENTER_FRACTION`` (0.30) of the landmark eye-pair width (the distance
between the two eye centres), or when it is wider or taller than
``1 + EYE_SIZE_FRACTION`` (1.5×) the landmark pair box. A smaller white that
shares the centre, such as a highlight, does not disagree. A painted mouth
disagrees when its centre is farther than ``MOUTH_FRACTION`` (0.50) of the
landmark mouth width. Points whose mean score is under ``MIN_SCORE`` (0.35)
are ignored; missing scores count as sure.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

EYE_CENTER_FRACTION = 0.30
EYE_SIZE_FRACTION = 0.50
MOUTH_FRACTION = 0.50
MIN_SCORE = 0.35
_LEFT_BROW, _RIGHT_BROW = slice(5, 8), slice(8, 11)
_LEFT_EYE, _RIGHT_EYE, _MOUTH = slice(11, 17), slice(17, 23), slice(23, 28)


def _python() -> Path | None:
    """The component's interpreter, or None when that environment is not installed."""
    try:
        from services.runtime_environment import engine_python
        path = engine_python("anime_face")
    except (KeyError, OSError):
        return None
    return path if path.is_file() else None


def _cache_dir() -> Path:
    from services.runtime_profiles import APP_DIR
    path = APP_DIR / "services" / "anime_face" / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _on_white(image: Image.Image) -> Image.Image:
    """RGB on white, so a keyed cutout has a background the detector can see."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32)
    rgb = rgba[..., :3] * (rgba[..., 3:] / 255.0) + 255.0 * (1.0 - rgba[..., 3:] / 255.0)
    return Image.fromarray(rgb.clip(0, 255).astype(np.uint8), "RGB")


def detect(image: Image.Image) -> dict[str, Any] | None:
    """28 points ``[x, y, score]`` of the highest-scoring face, in pixels of ``image``.

    None when the component is not installed, ``HOCUS_ANIME_FACE=0``, or no face
    is found. ``{"error": ...}`` when the installed detector fails (the rig warns
    and keeps today's search). No time limit: the first call downloads the weights.
    """
    if os.environ.get("HOCUS_ANIME_FACE") == "0":
        return None
    python = _python()
    if python is None:
        return None
    from services.runtime_environment import isolated_environment
    worker = Path(__file__).resolve().parent / "anime_face" / "worker.py"
    env = isolated_environment(python)
    env["CUDA_VISIBLE_DEVICES"] = ""
    cache = _cache_dir()
    env["HF_HOME"] = str(cache)
    env["HUGGINGFACE_HUB_CACHE"] = str(cache / "hub")
    with tempfile.TemporaryDirectory(prefix="hocus-anime-") as folder:
        path = Path(folder) / "pose.png"
        _on_white(image).save(path)
        try:
            result = subprocess.run([str(python), "-I", str(worker), str(path)], env=env, capture_output=True, text=True)
        except OSError as error:
            return {"error": str(error)}
    if result.returncode != 0:
        message = (result.stdout or result.stderr or "anime face detector failed").strip()
        return {"error": message[-400:]}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "anime face detector returned no JSON"}
    if payload.get("error"):
        return {"error": str(payload["error"])}
    return payload if payload.get("keypoints") else None


def _box(points: np.ndarray, pad: float = 1.0) -> tuple[float, float, float, float]:
    low, high = points.min(axis=0) - pad, points.max(axis=0) + pad
    return float(low[0]), float(low[1]), float(high[0]), float(high[1])


def _pair(groups: tuple[np.ndarray, np.ndarray]) -> tuple[list[np.ndarray], list[tuple[float, float, float, float]]]:
    ordered = sorted(groups, key=lambda group: float(group[:, 0].mean()))
    return ordered, [_box(group) for group in ordered]


def geometry_from_points(points: Any) -> dict[str, Any] | None:
    """Eyes, brows and mouth from 28 points. None when their mean score is under ``MIN_SCORE``."""
    array = np.asarray(points, dtype=float)
    if array.shape != (28, 2) and array.shape != (28, 3):
        raise ValueError("anime landmarks are 28 points")
    scores = array[:, 2] if array.shape[1] == 3 else np.ones(28)
    score = float(np.mean(scores))
    if not np.isfinite(score) or score < MIN_SCORE:
        return None
    xy = array[:, :2]
    eyes, eye_boxes = _pair((xy[_LEFT_EYE], xy[_RIGHT_EYE]))
    brows, brow_boxes = _pair((xy[_LEFT_BROW], xy[_RIGHT_BROW]))
    mouth = xy[_MOUTH]
    centres = [group.mean(axis=0) for group in eyes]
    pair = np.concatenate([np.asarray(box, float) for box in eye_boxes])
    return {
        "score": round(score, 3),
        "points": xy,
        "eye_outlines": eyes,
        "eyes": eye_boxes,
        "pair_center": tuple(float(v) for v in (centres[0] + centres[1]) / 2),
        "pair_width": float(np.linalg.norm(centres[1] - centres[0])),
        "pair_box": (float(min(pair[0], pair[4])), float(min(pair[1], pair[5])),
                     float(max(pair[2], pair[6])), float(max(pair[3], pair[7]))),
        "brows": brow_boxes,
        "mouth": {"points": mouth, "center": tuple(float(v) for v in mouth.mean(axis=0)),
                  "width": float(np.ptp(mouth[:, 0]))},
    }


def into_crop(geom: dict[str, Any], crop, size) -> dict[str, Any]:
    """The same geometry in pixels of the cropped figure (origin subtracted, then clamped)."""
    moved = np.asarray(geom["points"], float) - np.asarray(crop[:2], float)
    moved[:, 0] = np.clip(moved[:, 0], 0, max(0, size[0] - 1))
    moved[:, 1] = np.clip(moved[:, 1], 0, max(0, size[1] - 1))
    scored = np.column_stack([moved, np.full(28, max(float(geom["score"]), MIN_SCORE))])
    return geometry_from_points(scored) or geom


def brow_boxes(geom: dict[str, Any] | None) -> list[list[int]] | None:
    if not geom or not geom.get("brows"):
        return None
    return [[int(round(value)) for value in box] for box in geom["brows"]]


def eyes_disagree(white_box, geom: dict[str, Any]) -> bool:
    """True when the white pair is too far from the landmark eyes, or much larger (a collar)."""
    x0, y0, x1, y1 = (float(v) for v in white_box)
    centre = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    limit = EYE_CENTER_FRACTION * max(float(geom["pair_width"]), 1.0)
    if float(np.linalg.norm(centre - np.array(geom["pair_center"]))) > limit:
        return True
    lx0, ly0, lx1, ly1 = geom["pair_box"]
    return (x1 - x0) > (lx1 - lx0) * (1 + EYE_SIZE_FRACTION) or (y1 - y0) > (ly1 - ly0) * (1 + EYE_SIZE_FRACTION)


def mouth_disagree(found_box, geom: dict[str, Any]) -> bool:
    """True when the painted mouth's centre is farther than half the landmark mouth width."""
    x0, y0, x1, y1 = (float(v) for v in found_box)
    centre = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    width = max(float(geom["mouth"]["width"]), 1.0)
    return float(np.linalg.norm(centre - np.array(geom["mouth"]["center"]))) > MOUTH_FRACTION * width


def lip_contour(geom: dict[str, Any]) -> np.ndarray:
    """Twelve outer-lip points (corners 0 and 6) whose midline is the line through the five mouth points."""
    mouth = np.asarray(geom["mouth"]["points"], float)
    order = np.argsort(mouth[:, 0])
    left, right = mouth[order[0]], mouth[order[-1]]
    span = max(float(right[0] - left[0]), 1.0)
    degree = 2 if len(mouth) >= 3 and span >= 4 else 1
    poly = np.polyfit(mouth[:, 0], mouth[:, 1], degree)
    gap = max(2.0, span * 0.04)
    xs = np.linspace(left[0], right[0], 7)
    upper = np.stack([xs, np.polyval(poly, xs) - gap / 2], axis=1)
    lower_x = np.linspace(right[0], left[0], 7)[1:-1]
    lower = np.stack([lower_x, np.polyval(poly, lower_x) + gap / 2], axis=1)
    return np.vstack([upper, lower])


def prepare(image: Image.Image, anime: Any) -> dict[str, Any] | None:
    """Geometry for ``rig_pose``.

    ``False`` skips the detector. ``None`` runs it when installed (and
    ``HOCUS_ANIME_FACE`` is not ``0``). A ``keypoints`` array, or 28 points,
    is used as given (tests). An ``error`` dict is returned unchanged.
    """
    if anime is False:
        return None
    if anime is None:
        if os.environ.get("HOCUS_ANIME_FACE") == "0":
            return None
        anime = detect(image)
    if not anime:
        return None
    if isinstance(anime, dict) and anime.get("error"):
        return {"error": str(anime["error"])}
    points = anime.get("keypoints") if isinstance(anime, dict) else anime
    if points is None:
        return None
    try:
        return geometry_from_points(points)
    except (TypeError, ValueError) as error:
        return {"error": str(error)}

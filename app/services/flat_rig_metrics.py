"""How wide a flat-rig mouth opens, and whether a keyed pose can be rigged.

``attach_openings`` records ``openPx`` and ``openRatio`` on each pose's mouth
after the mouths exist (paper, ink or warp). ``openRatio`` is the ``wide``
opening's height divided by the eye-pair width. A warp mouth's height is the
jaw drop (``flat_rig_warp.drop_pixels``), not the patch: the patch is the jaw
and the beard. A paper or ink mouth's height is the opaque rows of the wide
sprite, scaled the way the kit places it.

The warning threshold 0.08 was checked on ten graphic-novel poses, full figures
and busts. Their wide openings sat between about 0.12 and 0.19, so 0.08 warns
when a mouth barely opens and stays quiet on a full-figure mouth that still
reads. Showing the number is what the review is for.

``check_image`` looks at one keyed pose and saves nothing. It reuses the rig's
eye and mouth search. Face landmarks, when the models are installed, add the
face box and a low-confidence warning; a missing model does not fail a pose
the pixel search already accepts.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from PIL import Image

from services import face_landmarks
from services.flat_rig_eyes import _components, find_eyes, light_sclera
from services.flat_rig_warp import drop_pixels

# Wide opening height over the eye-pair width. See the module note.
MOUTH_SMALL_OPENING = 0.08
# Light pixels below this are noise, not sclera the eye search missed.
_SPECK = 6
# Opaque pixels below this are not a figure with a face.
_SUBSTANTIAL = 800
# A sprite row counts as the opening once it is more than a faint edge.
_OPAQUE = 16


def opening_caption(mouth: dict[str, Any]) -> str:
    """The review-sheet line under a face: ``mouth 9px 0.16``."""
    return f"mouth {mouth['openPx']:g}px {mouth['openRatio']:.2f}"


def attach_openings(rigs: dict[str, dict[str, Any]], mouths: dict[str, Image.Image]) -> None:
    """Add ``openPx`` and ``openRatio`` to each pose mouth, and warn when the opening is tiny."""
    for rig in rigs.values():
        opening = _opening(rig, mouths)
        if opening is None:
            continue
        mouth = rig.get("mouth")
        if not isinstance(mouth, dict):
            continue
        mouth["openPx"] = opening["openPx"]
        mouth["openRatio"] = opening["openRatio"]
        if opening["openRatio"] < MOUTH_SMALL_OPENING:
            _warn(rig, "mouth_small_opening")


def check_pose(workspace_dir: str, workspace: str, source: str) -> dict[str, Any]:
    """``characters.rig.check`` for one workspace file. A bad path still raises ``FlatRigError``."""
    from services.flat_rig import _workspace_file

    with Image.open(_workspace_file(source, workspace, workspace_dir)) as image:
        return check_image(image)


def check_image(image: Image.Image) -> dict[str, Any]:
    """Whether the flat rig can find eyes and a mouth on one keyed pose. Nothing is painted or saved."""
    from services.flat_rig import FlatRigError, _figure_box, find_mouth

    rgba = image.convert("RGBA")
    try:
        cleaned, crop = _figure_box(rgba)
    except FlatRigError as error:
        if error.code == "not_keyed":
            return _report(False, ["eyes_not_found"], None, 0.0)
        raise
    figure = cleaned.crop(crop)
    pixels = np.asarray(figure)
    rgb, alpha = pixels[..., :3], pixels[..., 3]
    landmarks = face_landmarks.detect(rgba)
    reason, eyes_box = _eye_reason(rgb, alpha)
    reasons = [reason] if reason else []
    if eyes_box is None:
        eyes_box = _landmark_eyes_box(landmarks, crop, figure.size)
    if eyes_box is not None and _mouth_missing(find_mouth, rgb, alpha, eyes_box):
        reasons.append("mouth_not_found")
    confidence = _confidence(landmarks)
    if landmarks and reasons and confidence < face_landmarks.MIN_SCORE:
        reasons.append("face_low_confidence")
    return _report(not reasons, reasons, _face_box(landmarks, crop), confidence)


def _opening(rig: dict[str, Any], mouths: dict[str, Image.Image]) -> dict[str, float] | None:
    span = _eye_span(rig)
    if span <= 0:
        return None
    open_px = _warp_open_px(rig)
    if open_px is None:
        open_px = _sprite_open_px(rig, mouths)
    if open_px is None:
        return None
    return {"openPx": open_px, "openRatio": round(open_px / span, 3)}


def _warp_open_px(rig: dict[str, Any]) -> int | None:
    """The wide jaw drop in pose pixels. ``mouthWidth`` is a percent of the original image width."""
    line, frame = rig.get("line"), rig.get("frame")
    if not isinstance(line, dict) or not frame or len(frame) < 3:
        return None
    width = line.get("mouthWidth")
    if isinstance(width, bool) or not isinstance(width, (int, float)):
        return None
    return int(drop_pixels("wide", float(width) / 100.0 * float(frame[2])))


def _sprite_open_px(rig: dict[str, Any], mouths: dict[str, Image.Image]) -> int | None:
    """Opaque rows of the wide sprite, scaled to the pose the way ``place`` scales the mouth."""
    mouth = rig.get("mouth")
    sprite = (rig.get("sprites") or mouths or {}).get("wide")
    if not isinstance(mouth, dict) or sprite is None:
        return None
    scale = mouth.get("scale")
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        return None
    array = np.asarray(sprite.convert("RGBA"))
    height = array.shape[0]
    if height <= 0:
        return None
    rows = int((array[..., 3] > _OPAQUE).any(axis=1).sum())
    edge = max(int(rig.get("width") or 0), int(rig.get("height") or 0))
    return int(round(rows / height * float(scale) * edge))


def _eye_span(rig: dict[str, Any]) -> float:
    box = rig.get("eyes_box") or ()
    if len(box) < 4:
        return 0.0
    return float(box[2]) - float(box[0])


def _warn(rig: dict[str, Any], code: str) -> None:
    warnings = rig.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
        rig["warnings"] = warnings
    if code not in warnings:
        warnings.append(code)


def _eye_reason(rgb: np.ndarray, alpha: np.ndarray) -> tuple[str | None, tuple[int, int, int, int] | None]:
    from services.flat_rig import FlatRigError

    try:
        box, _mask = find_eyes(rgb, alpha)
    except FlatRigError as error:
        if error.code != "eyes_not_found":
            raise
        if _light_specks(rgb, alpha):
            return "eyes_small", None
        if int((alpha > 200).sum()) >= _SUBSTANTIAL:
            return "sclera_dark", None
        return "eyes_not_found", None
    return None, box


def _light_specks(rgb: np.ndarray, alpha: np.ndarray) -> bool:
    """Light sclera anywhere on the figure. The eye search only looks at the top, and only for a pair."""
    _labels, parts = _components(light_sclera(rgb, alpha))
    return any(part["size"] >= _SPECK for part in parts)


def _landmark_eyes_box(landmarks: dict[str, Any] | None, crop, size) -> tuple[int, int, int, int] | None:
    if not landmarks:
        return None
    scores = landmarks.get("scores") or {}
    if float(scores.get("eyes") or 0) < face_landmarks.MIN_SCORE:
        return None
    points = [point for eye in landmarks.get("eyes") or [] for point in eye]
    if len(points) < 2:
        return None
    xs = [float(point[0]) - crop[0] for point in points]
    ys = [float(point[1]) - crop[1] for point in points]
    x0, y0 = max(0, math.floor(min(xs))), max(0, math.floor(min(ys)))
    x1, y1 = min(size[0], math.ceil(max(xs))), min(size[1], math.ceil(max(ys)))
    if x1 <= x0 or y1 <= y0:
        return None
    return int(x0), int(y0), int(x1), int(y1)


def _mouth_missing(find_mouth, rgb, alpha, eyes_box) -> bool:
    from services.flat_rig import FlatRigError

    try:
        find_mouth(rgb, alpha, eyes_box)
    except FlatRigError as error:
        if error.code == "mouth_not_found":
            return True
        raise
    return False


def _confidence(landmarks: dict[str, Any] | None) -> float:
    if not landmarks:
        return 0.0
    scores = landmarks.get("scores") or {}
    return round(min(float(scores.get("eyes") or 0), float(scores.get("mouth") or 0)), 3)


def _face_box(landmarks: dict[str, Any] | None, crop) -> list[int] | None:
    if not landmarks:
        return [int(crop[0]), int(crop[1]), int(crop[2]), int(crop[3])]
    points = list(landmarks.get("contour") or [])
    if not points:
        for eye in landmarks.get("eyes") or []:
            points.extend(eye)
        points.extend(landmarks.get("mouth") or [])
    box = _bounds(points)
    return box or [int(crop[0]), int(crop[1]), int(crop[2]), int(crop[3])]


def _bounds(points) -> list[int] | None:
    if not points:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [math.floor(min(xs)), math.floor(min(ys)), math.ceil(max(xs)), math.ceil(max(ys))]


def _report(ready: bool, reasons: list[str], box, confidence: float) -> dict[str, Any]:
    return {"ready": ready, "reasons": reasons, "face": {"box": box, "confidence": confidence}}

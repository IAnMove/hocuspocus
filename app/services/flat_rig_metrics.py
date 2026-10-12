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

``check_image`` looks at one keyed pose and saves nothing. It runs the rig's
own search (``rig_pose`` with the face landmarks and the kit look of a new kit),
so a pose the rig takes is ready, and a rig error becomes a reason. Landmarks,
when the models are installed, guide that search as they guide the rig, and add
the face box and a low-confidence warning; a missing model does not fail a pose
the pixel search already accepts. An image with no transparent background, or
with nothing left after the key, is ``not_keyed``.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from PIL import Image

from services import face_landmarks
from services.flat_rig_eyes import _components, light_sclera
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
    from services.flat_rig import FlatRigError, _figure_box, rig_pose
    from services.flat_rig_look import kit_look

    rgba = image.convert("RGBA")
    # A frame opaque all over still has its background, which the rig would take for the figure.
    if not (np.asarray(rgba.getchannel("A")) <= 128).any():
        return _report(False, ["not_keyed"], None, 0.0)
    try:
        cleaned, crop = _figure_box(rgba)
    except FlatRigError as error:
        if error.code == "not_keyed":
            return _report(False, ["not_keyed"], None, 0.0)
        raise
    landmarks = face_landmarks.detect(rgba)
    try:
        # The rig's own search: the landmarks place the eyes and the mouth when the pixels alone do not.
        rig = rig_pose(rgba, kit_look({}, None), None, landmarks)
        reasons = [] if rig["found"] else ["mouth_not_found"]
    except FlatRigError as error:
        reasons = [_rig_reason(error, cleaned.crop(crop))]
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


def _rig_reason(error: Exception, figure: Image.Image) -> str:
    """A rig error as a reason. Missing eyes say why: light sclera that is no usable pair, or no light sclera at all."""
    code = str(getattr(error, "code", "") or "rig_failed")
    if code != "eyes_not_found":
        return code
    pixels = np.asarray(figure)
    rgb, alpha = pixels[..., :3], pixels[..., 3]
    if _light_specks(rgb, alpha):
        return "eyes_small"
    if int((alpha > 200).sum()) >= _SUBSTANTIAL:
        return "sclera_dark"
    return "eyes_not_found"


def _light_specks(rgb: np.ndarray, alpha: np.ndarray) -> bool:
    """Light sclera anywhere on the figure. The eye search only looks at the top, and only for a pair."""
    _labels, parts = _components(light_sclera(rgb, alpha))
    return any(part["size"] >= _SPECK for part in parts)


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

"""Face landmarks of a drawn character, to guide the flat rig.

The flat rig finds eyes and mouth by their marks (white blobs, dark strokes). On graphic-novel faces that guess is often
wrong: a nose stroke under the eyes, the black shadow of an eye socket or the line between moustache and beard look
like a mouth, and a bust's eyes can be too small for the white-blob search. DWPose's whole-body model (already shipped
for the pose preprocessors, ``ckpts/pose``) puts the 68 face points of the 300-W layout on painted faces too, cartoon
ones included, so its eyes and mouth are used where the rig would otherwise guess.

It runs on the CPU (two ONNX sessions, loaded once). Without the model files nothing is found and the rig keeps its
own search.

The model sees each figure squeezed into 288×384 pixels: a full figure's head is a few dozen pixels there, and its lips
were placed on the philtrum or half on the nose. A small head (``SMALL_HEAD``), or a face the whole-figure pass was
unsure of, is looked at again on its own (``_head_pass``): the head and shoulders cut out with white round them,
enlarged (Lanczos) when they are smaller than the model's input, and the points mapped back to the pose image.
"""
from __future__ import annotations

import math
import os
import threading
from typing import Any

import numpy as np
from PIL import Image

from services.face_enlarge import SMALL_HEAD, enlarge, to_image, to_view

MODELS = ("pose/yolox_l.onnx", "pose/dw-ll_ucoco_384.onnx")
# In the whole-body output (body points with the neck inserted, then the feet) the 68 face points start here; the first
# 18 are the body's in OpenPose order (nose, neck, right shoulder, ..., left ear).
FACE, BODY = 24, 18
RIGHT_EYE, LEFT_EYE, MOUTH = range(36, 42), range(42, 48), range(48, 60)
# The jaw line round the face and the nose (bridge and nostrils): where the head turns (``pose_facing``).
CONTOUR, NOSE = range(0, 17), range(27, 36)
# Below this mean score a part was guessed, not seen (a face turned away, hair over the eyes). A bearded mouth seen
# from below scores 0.39.
MIN_SCORE = 0.35
# Under this, the whole-figure pass may have half guessed a face (the bearded mouth above put on the beard) and the head
# pass is tried; it is kept when it is surer.
UNSURE = 0.5
# What the head pass shows the model: a square this many head sizes across (head, hair and shoulders: the model reads
# a face only on a person), its middle this far under the face's. Tighter squares scored under 0.15 on profiles.
HEAD_VIEW, HEAD_DROP = 4.4, 0.3
# The model's input width; a view narrower than it (once padded as the model pads it) is enlarged first.
MODEL_WIDTH, PADDING = 288, 1.25

_lock = threading.Lock()
_model: Any = None


def _paths() -> tuple[str, str] | None:
    from shared.utils import files_locator
    paths = tuple(files_locator.locate_file(name, error_if_none=False) for name in MODELS)
    return paths if all(paths) else None


def _wholebody():
    """The DWPose sessions, or None when the model files are not installed (or disabled for tests)."""
    global _model
    if os.environ.get("HOCUS_FACE_LANDMARKS") == "0":
        return None
    with _lock:
        if _model is None:
            paths = _paths()
            if paths is None:
                _model = False
            else:
                from preprocessing.dwpose.wholebody import Wholebody
                _model = Wholebody(*paths, device="cpu")
        return _model or None


def _on_white(image: Image.Image) -> np.ndarray:
    """The image as the model reads it: BGR, with an RGBA keyed cutout laid on white."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32)
    rgb = rgba[..., :3] * (rgba[..., 3:] / 255.0) + 255.0 * (1 - rgba[..., 3:] / 255.0)
    return np.ascontiguousarray(rgb.clip(0, 255).astype(np.uint8)[..., ::-1])


def _whole_pass(model, bgr: np.ndarray):
    """The 68 face points and scores of the most confident figure in the image and its 18 body points (x, y, score),
    or None."""
    with _lock:
        keypoints, scores, _boxes = model(bgr)
    if keypoints is None or not len(keypoints):
        return None
    face = scores[:, FACE:FACE + 68]
    best = int(np.argmax(face.mean(axis=1)))
    return keypoints[best, FACE:FACE + 68], face[best], np.column_stack([keypoints[best, :BODY], scores[best, :BODY]])


def _pose(model, box, bgr: np.ndarray):
    """The model's 133 whole-body points and scores for the person in ``box`` (x0, y0, x1, y1), no detector."""
    from preprocessing.dwpose.onnxpose import inference_pose
    with _lock:
        keypoints, scores = inference_pose(model.session_pose, np.array([box], dtype=float), bgr)
    return keypoints[0], scores[0]


def head_size(points: np.ndarray) -> tuple[float, tuple[float, float]]:
    """The head's size (the larger of the jaw's width and the brows-to-chin height) and its middle, from the 68 points."""
    jaw, brows = points[0:17], points[17:27]
    width, height = float(np.ptp(jaw[:, 0])), float(jaw[:, 1].max() - brows[:, 1].min())
    middle = (float(jaw[:, 0].min() + jaw[:, 0].max()) / 2, float(brows[:, 1].min() + jaw[:, 1].max()) / 2)
    return max(width, height), middle


def head_view(head: float, middle) -> tuple[list[float], tuple[int, int, int, int], int]:
    """The head pass's box (``HEAD_VIEW`` heads square, ``HEAD_DROP`` under the face's middle), the part of the image the
    model will see of it (padded and made 3:4 as the model does: ``x0, y0, width, height``) and how many times that part
    is enlarged so the model never enlarges it itself."""
    cx, cy = middle[0], middle[1] + HEAD_DROP * head
    half = HEAD_VIEW * head / 2
    box = [cx - half, cy - half, cx + half, cy + half]
    seen_w = 2 * half * PADDING
    seen_h = seen_w * 4 / 3
    crop = (int(math.floor(cx - seen_w / 2)) - 2, int(math.floor(cy - seen_h / 2)) - 2,
            int(math.ceil(seen_w)) + 4, int(math.ceil(seen_h)) + 4)
    return box, crop, max(1, math.ceil(MODEL_WIDTH / seen_w))


def _head_pass(model, bgr: np.ndarray, head: float, middle):
    """The face points read on the head alone (``head_view``), in pixels of the whole image."""
    box, (x0, y0, width, height), k = head_view(head, middle)
    view = enlarge(bgr, x0, y0, width, height, k, fill=255)
    corners = to_view(np.array([box[:2], box[2:]], dtype=float), (x0, y0), k)
    keypoints, scores = _pose(model, corners.ravel().tolist(), view)
    # The raw whole-body points: 17 body and 6 feet points come before the face's (no neck is inserted here).
    return to_image(keypoints[FACE - 1:FACE + 67], (x0, y0), k), scores[FACE - 1:FACE + 67]


def _sure(scores: np.ndarray) -> float:
    return float(min(scores[list(RIGHT_EYE) + list(LEFT_EYE)].mean(), scores[list(MOUTH)].mean()))


def detect(image: Image.Image) -> dict[str, Any] | None:
    """The face of the most confident figure in ``image`` (RGBA keyed cutouts are laid on white): ``eyes`` (two lists
    of six points, the image's left eye first), ``mouth`` (its twelve outer-lip points) and their mean ``scores``, in
    pixels of ``image``; ``face``: the head's ``size`` class (``small`` under ``SMALL_HEAD``, else ``normal``), its
    ``head`` size in pixels and the ``pass`` the points come from (``head`` when the head pass was used, else
    ``whole``); ``nose`` and ``contour`` (the jaw line) with their scores and the whole pass's 18 ``body`` points
    ``[x, y, score]``, for ``pose_facing``. None when the model is missing or no figure is found."""
    model = _wholebody()
    if model is None:
        return None
    bgr = _on_white(image)
    try:
        found = _whole_pass(model, bgr)
    except Exception:
        return None
    if found is None:
        return None
    found, body = found[:2], found[2]
    head, middle = head_size(found[0])
    small, used = head < SMALL_HEAD, "whole"
    if small or _sure(found[1]) < UNSURE:
        try:
            closer = _head_pass(model, bgr, head, middle)
        except Exception:
            closer = None
        # A small head is read better alone even when the whole pass scores itself higher (it put a small mouth's lips
        # on the philtrum at 0.98); a large one only when the head pass is surer.
        if closer is not None and _sure(closer[1]) >= (MIN_SCORE if small else _sure(found[1])):
            found, used = closer, "head"
    points, score = found

    def part(indices):
        return [[round(float(x), 2), round(float(y), 2)] for x, y in points[list(indices)]], round(float(score[list(indices)].mean()), 3)
    first, second = part(RIGHT_EYE), part(LEFT_EYE)
    eyes = sorted((first, second), key=lambda eye: np.mean([p[0] for p in eye[0]]))
    mouth, nose, contour = part(MOUTH), part(NOSE), part(CONTOUR)
    return {"eyes": [eyes[0][0], eyes[1][0]], "mouth": mouth[0], "nose": nose[0], "contour": contour[0],
            "scores": {"eyes": round(min(eyes[0][1], eyes[1][1]), 3), "mouth": mouth[1], "nose": nose[1], "contour": contour[1]},
            "face": {"size": "small" if small else "normal", "head": round(head, 1), "pass": used},
            "body": [[round(float(x), 2), round(float(y), 2), round(float(score), 3)] for x, y, score in body]}


def guides(landmarks: dict[str, Any] | None) -> dict[str, Any]:
    """What the rig takes from the landmarks it can trust: the eyes' and mouth's centres, the mouth's corner-to-corner
    width, its twelve outer-lip points and each eye's outline, in the landmarks' pixels."""
    if not landmarks:
        return {}
    found: dict[str, Any] = {}
    scores = landmarks.get("scores") or {}
    if scores.get("eyes", 0) >= MIN_SCORE:
        eyes = [np.asarray(eye, dtype=float) for eye in landmarks["eyes"]]
        found["eyes"] = tuple(np.concatenate(eyes).mean(axis=0))
        found["eye_outlines"] = eyes
    if scores.get("mouth", 0) >= MIN_SCORE:
        mouth = np.asarray(landmarks["mouth"], dtype=float)
        found["mouth"] = tuple(mouth.mean(axis=0))
        found["mouth_width"] = float(np.ptp(mouth[:, 0]))
        found["mouth_points"], found["mouth_score"] = mouth, float(scores["mouth"])
    return found

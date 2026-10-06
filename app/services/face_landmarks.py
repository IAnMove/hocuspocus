"""Face landmarks of a drawn character, to guide the flat rig.

The flat rig finds eyes and mouth by their marks (white blobs, dark strokes). On graphic-novel faces that guess is often
wrong: a nose stroke under the eyes, the black shadow of an eye socket or the line between moustache and beard look
like a mouth, and a bust's eyes can be too small for the white-blob search. DWPose's whole-body model (already shipped
for the pose preprocessors, ``ckpts/pose``) puts the 68 face points of the 300-W layout on painted faces too, cartoon
ones included, so its eyes and mouth are used where the rig would otherwise guess.

It runs on the CPU (two ONNX sessions, loaded once). Without the model files nothing is found and the rig keeps its
own search.
"""
from __future__ import annotations

import os
import threading
from typing import Any

import numpy as np
from PIL import Image

MODELS = ("pose/yolox_l.onnx", "pose/dw-ll_ucoco_384.onnx")
# In the whole-body output (body points with the neck inserted, then the feet) the 68 face points start here.
FACE = 24
RIGHT_EYE, LEFT_EYE, MOUTH = range(36, 42), range(42, 48), range(48, 60)
# Below this mean score a part was guessed, not seen (a face turned away, hair over the eyes). A bearded mouth seen
# from below scores 0.39.
MIN_SCORE = 0.35

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


def detect(image: Image.Image) -> dict[str, Any] | None:
    """The face of the most confident figure in ``image`` (RGBA keyed cutouts are laid on white): ``eyes`` (two lists
    of six points, the image's left eye first), ``mouth`` (its twelve outer-lip points) and their mean ``scores``, in
    pixels of ``image``. None when the model is missing or no figure is found."""
    model = _wholebody()
    if model is None:
        return None
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32)
    rgb = rgba[..., :3] * (rgba[..., 3:] / 255.0) + 255.0 * (1 - rgba[..., 3:] / 255.0)
    bgr = np.ascontiguousarray(rgb.clip(0, 255).astype(np.uint8)[..., ::-1])
    try:
        with _lock:
            keypoints, scores, _boxes = model(bgr)
    except Exception:
        return None
    if keypoints is None or not len(keypoints):
        return None
    face = scores[:, FACE:FACE + 68]
    best = int(np.argmax(face.mean(axis=1)))
    points, score = keypoints[best, FACE:FACE + 68], face[best]

    def part(indices):
        return [[round(float(x), 2), round(float(y), 2)] for x, y in points[list(indices)]], round(float(score[list(indices)].mean()), 3)
    first, second = part(RIGHT_EYE), part(LEFT_EYE)
    eyes = sorted((first, second), key=lambda eye: np.mean([p[0] for p in eye[0]]))
    mouth = part(MOUTH)
    return {"eyes": [eyes[0][0], eyes[1][0]], "mouth": mouth[0],
            "scores": {"eyes": round(min(eyes[0][1], eyes[1][1]), 3), "mouth": mouth[1]}}


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

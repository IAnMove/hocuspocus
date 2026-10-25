"""One anime-face pass. The parent sets the cache and an empty CUDA_VISIBLE_DEVICES.

Prints JSON: ``{"keypoints": [[x, y, score], ...]}`` for the surest usable face,
``{"keypoints": null}`` when there is none. Torch stays in this process.

A face is usable when its 28 points average at least ``MIN_KEYPOINT_SCORE``
(the same 0.35 floor as ``anime_face_landmarks.MIN_SCORE``). Among those, the
highest box score wins. A brighter box with unsure points — a belt buckle
drawn like a face — is skipped so the real face can be used.
"""
from __future__ import annotations

import json
import os
import sys

os.environ["CUDA_VISIBLE_DEVICES"] = ""

MIN_KEYPOINT_SCORE = 0.35


def _box_score(face) -> float:
    import numpy as np
    box = np.asarray(face.get("bbox"), dtype=float).reshape(-1)
    return float(box[-1]) if box.size >= 5 else 0.0


def _keypoint_mean(face) -> float:
    import numpy as np
    points = np.asarray(face.get("keypoints"), dtype=float)
    if points.ndim != 2 or points.shape[0] != 28 or points.shape[1] < 2:
        return 0.0
    if points.shape[1] < 3:
        return 1.0
    return float(points[:, 2].mean())


def choose_face(faces):
    """The highest-scoring box whose points clear the floor, or None."""
    sure = [face for face in faces or [] if _keypoint_mean(face) >= MIN_KEYPOINT_SCORE]
    return max(sure, key=_box_score) if sure else None


def main() -> None:
    import cv2
    import numpy as np
    from anime_face_detector import create_detector

    image = cv2.imread(sys.argv[1], cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("unreadable image")
    chosen = choose_face(create_detector("yolov3", device="cpu")(image))
    if chosen is None:
        json.dump({"keypoints": None}, sys.stdout)
        return
    points = np.asarray(chosen["keypoints"], dtype=float)
    rows = [[round(float(value), 2) for value in row] for row in points.reshape(points.shape[0], -1)]
    json.dump({"keypoints": rows}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        json.dump({"error": str(error)}, sys.stdout)
        raise SystemExit(1) from error

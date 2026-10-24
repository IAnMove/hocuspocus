"""One anime-face pass. The parent sets the cache and an empty CUDA_VISIBLE_DEVICES.

Prints JSON: ``{"keypoints": [[x, y, score], ...]}`` for the highest-scoring face,
``{"keypoints": null}`` when there is none. Torch stays in this process.
"""
from __future__ import annotations

import json
import os
import sys

os.environ["CUDA_VISIBLE_DEVICES"] = ""


def main() -> None:
    import cv2
    import numpy as np
    from anime_face_detector import create_detector

    image = cv2.imread(sys.argv[1], cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("unreadable image")
    faces = create_detector("yolov3", device="cpu")(image)

    def score(face) -> float:
        box = np.asarray(face["bbox"], dtype=float).reshape(-1)
        return float(box[-1]) if box.size >= 5 else 0.0

    if not faces:
        json.dump({"keypoints": None}, sys.stdout)
        return
    points = np.asarray(max(faces, key=score)["keypoints"], dtype=float)
    rows = [[round(float(value), 2) for value in row] for row in points.reshape(points.shape[0], -1)]
    json.dump({"keypoints": rows}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        json.dump({"error": str(error)}, sys.stdout)
        raise SystemExit(1) from error

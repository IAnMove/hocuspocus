"""Small HTTP client and editable native backplate recipe; no private renderer."""
from __future__ import annotations

import json
from urllib.request import Request, urlopen


def request(base_url: str, path: str, data: dict | None = None, *, timeout: int = 30) -> dict:
    payload = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    with urlopen(Request(base_url.rstrip("/") + path, payload, headers), timeout=timeout) as response:
        return json.load(response)


def backplate_document(image_url: str, actor_url: str, *, duration: float = 8,
                       start=(-1.4, 0, .2), end=(1.0, 0, -.5), walking: bool = True) -> dict:
    """A fixed plate plus an animated actor. Authors can edit all native fields."""
    return {
        "version": 1, "units": "meters", "up": "y", "templateId": "two-shot",
        "width": 1280, "height": 720, "fps": 24, "duration": duration,
        "dressing": "none",
        "camera": {"family": "fixed", "eye": [0, 3.2, 7.8], "look": [0, .8, 0], "fov": 45},
        "light": {"kind": "directional", "direction": [-.6, -1, .5], "intensity": 1.5, "color": "#ffdbad"},
        "environment": {"reflectiveFloor": False, "platform": False, "bloom": 0, "floorStyle": "none"},
        "slots": [
            {"id": "background", "slot": "background", "media": "image", "sourceUrl": image_url,
             "surface": "environment", "position": [0, 0, -8], "rotationY": 0, "scale": 1, "clip": None},
            {"id": "subject_1", "slot": "subject_1", "media": "model3d", "sourceUrl": actor_url,
             "position": list(start), "rotationY": 0, "scale": 1, "grounded": True,
             "clip": {"index": 0 if walking else 1, "name": "Walking" if walking else "Idle"},
             "clipPlayback": {"speed": .8, "loop": True},
             "motion": {"to": list(end), "faceTravel": walking, "easing": "linear"}},
        ],
    }

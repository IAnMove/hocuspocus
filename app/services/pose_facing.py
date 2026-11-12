"""Which way a drawn figure looks: screen ``left``, ``right`` or ``front`` (for look room in 2D shots).

The head's turn is read from DWPose's face points (``face_landmarks.detect``, CPU): the nose (bridge and nostrils)
against the middle of the jaw line, over the jaw line's width. A face seen from the front has its nose in the middle
(under ``FRONT`` of the width either way on every frontal cartoon measured); a three-quarter view puts it a third of
the width toward where the figure looks. When the face points are only guessed (a face turned away, a tiny head), the
body says it instead: the nose against the middle of the shoulders, over their width.

A pose of a Character Kit can say it itself, ``"facing": "left" | "right" | "front"``: that wins over the detection
(``kit_pose_facing``). The flat rig stores what it detects on each pose (``settle``), so it is visible and editable;
a facing the user set since the last rig is kept. Detection is remembered per file (path, size and modification
time). Without the model (or with ``HOCUS_FACE_LANDMARKS=0``) nothing is detected and the facing is unknown (None).
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Any, Callable
from urllib.parse import unquote, urlparse

FACINGS = ("left", "right", "front")
# Under this turn (nose off the jaw line's middle, in jaw widths) a face looks to the front; three-quarter views
# measured 0.15-0.4, frontal cartoon faces at most 0.08.
FRONT = 0.1
# A turn this large is a sure left or right.
SURE = 0.25
# Below this mean score the face (nose and jaw line) or the body (nose and shoulders) was guessed, not seen.
FACE_MIN, BODY_MIN = 0.3, 0.3
# Shoulders narrower than this many head sizes were not found (a bust's collar read as both shoulders).
SHOULDERS_MIN = 0.5
# The body says less about where the head looks than the face does.
BODY_TRUST = 0.7

_CACHE: OrderedDict[tuple, Any] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_SIZE = 512


def normalize_facing(value: Any, label: str = "facing") -> str | None:
    """A kit pose's ``facing``: left, right or front; None (or missing) clears it."""
    if value is None:
        return None
    if value not in FACINGS:
        raise ValueError(f"{label} must be left, right or front")
    return value


def _call(yaw: float, score: float, source: str) -> dict[str, Any]:
    side = "front" if abs(yaw) < FRONT else "left" if yaw < 0 else "right"
    strength = 1 - abs(yaw) / (2 * FRONT) if side == "front" else min(1.0, abs(yaw) / SURE)
    return {"facing": side, "confidence": round(score * strength, 2), "yaw": round(yaw, 3), "source": source}


def _from_face(landmarks: dict[str, Any]) -> dict[str, Any] | None:
    scores = landmarks.get("scores") or {}
    score = (float(scores.get("nose") or 0) + float(scores.get("contour") or 0)) / 2
    nose, contour = landmarks.get("nose") or [], landmarks.get("contour") or []
    if score < FACE_MIN or not nose or len(contour) < 2:
        return None
    xs = [point[0] for point in contour]
    width = max(xs) - min(xs)
    if width <= 0:
        return None
    middle = sum(point[0] for point in nose) / len(nose)
    return _call((middle - (max(xs) + min(xs)) / 2) / width, score, "face")


def _from_body(landmarks: dict[str, Any]) -> dict[str, Any] | None:
    body = landmarks.get("body") or []
    if len(body) < 6:
        return None
    nose, right, left = body[0], body[2], body[5]
    width, head = abs(right[0] - left[0]), float((landmarks.get("face") or {}).get("head") or 0)
    score = min(nose[2], right[2], left[2])
    if score < BODY_MIN or width <= 0 or width < SHOULDERS_MIN * head:
        return None
    return _call((nose[0] - (right[0] + left[0]) / 2) / width, score * BODY_TRUST, "body")


def from_landmarks(landmarks: dict[str, Any] | None) -> dict[str, Any] | None:
    """``{"facing", "confidence" (0-1), "yaw", "source": "face" | "body"}`` from ``face_landmarks.detect``'s points,
    or None when neither the face nor the body was seen well enough."""
    if not landmarks:
        return None
    return _from_face(landmarks) or _from_body(landmarks)


def detect(image: Any) -> dict[str, Any] | None:
    """Which way the figure in a keyed cutout (PIL image) looks; None when unknown. Never raises."""
    try:
        from services import face_landmarks
        return from_landmarks(face_landmarks.detect(image))
    except Exception:  # noqa: BLE001 - a facing is advice: a broken model or image must never stop a render
        return None


def detect_file(path: str, *, cached_only: bool = False) -> dict[str, Any] | None:
    """``detect`` for an image file, remembered while the file is unchanged; ``cached_only`` never runs the model."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (os.path.realpath(path), stat.st_mtime_ns, stat.st_size, os.environ.get("HOCUS_FACE_LANDMARKS"))
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    if cached_only:
        return None
    try:
        from PIL import Image
        with Image.open(path) as image:
            image.load()
            found = detect(image)
    except Exception:  # noqa: BLE001 - an unreadable file has no facing
        found = None
    with _CACHE_LOCK:
        _CACHE[key] = found
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return found


def workspace_path(source: Any, root: str | None) -> str | None:
    """The workspace file behind a ``/api/v1/file/...`` source, or None (another kind of source, or outside ``root``)."""
    parsed = urlparse(str(source or ""))
    if not root or not parsed.path.startswith("/api/v1/file/"):
        return None
    base = os.path.realpath(root)
    path = os.path.realpath(os.path.join(base, unquote(parsed.path[len("/api/v1/file/"):])))
    return path if path.startswith(base + os.sep) and os.path.isfile(path) else None


def pose_asset(kit: dict[str, Any] | None, pose_id: str) -> dict[str, Any] | None:
    found = (kit or {}).get("base") if pose_id == "base" else ((kit or {}).get("poses") or {}).get(pose_id)
    return found if isinstance(found, dict) else None


def kit_pose_facing(kit: dict[str, Any] | None, pose_id: str, root: str | None = None, *,
                    cached_only: bool = False) -> dict[str, Any] | None:
    """A kit pose's facing: its own ``facing`` (set by hand or by the flat rig, ``source: "kit"``), else detected on its
    image in the workspace ``root``; None when unknown."""
    asset = pose_asset(kit, pose_id)
    if asset is None:
        return None
    if asset.get("facing") in FACINGS:
        return {"facing": asset["facing"], "confidence": 1.0, "source": "kit"}
    path = workspace_path(asset.get("source"), root)
    return detect_file(path, cached_only=cached_only) if path else None


def kit_facings(kit: dict[str, Any] | None, root: str | None = None,
                cached_only: Callable[[], bool] = lambda: False) -> dict[str, str]:
    """``{pose id: facing}`` for every pose of a kit whose facing is known (``kit_pose_facing``)."""
    poses = (["base"] if (kit or {}).get("base") else []) + sorted((kit or {}).get("poses") or {})
    found = {pose: kit_pose_facing(kit, pose, root, cached_only=cached_only()) for pose in poses}
    return {pose: value["facing"] for pose, value in found.items() if value}


def rigged_facings(kit: dict[str, Any]) -> dict[str, str]:
    """What the last flat rig detected per pose (its provenance), to tell a facing the user set since then."""
    for entry in reversed(kit.get("provenance") or []):
        if isinstance(entry, dict) and entry.get("method") == "flat-rig":
            found = entry.get("facings")
            return {pose: value for pose, value in found.items() if value in FACINGS} if isinstance(found, dict) else {}
    return {}


def settle(asset: dict[str, Any], found: dict[str, Any] | None, before: str | None) -> str | None:
    """Store on a pose the facing a rig ``found`` (``from_landmarks``), unless the pose has one the user set since the
    last rig (``before``, what that rig found). Returns the detected facing, for the rig's provenance."""
    detected = (found or {}).get("facing")
    own = asset.get("facing")
    if own in FACINGS and own != before:
        return detected
    if detected:
        asset["facing"] = detected
    else:
        asset.pop("facing", None)
    return detected

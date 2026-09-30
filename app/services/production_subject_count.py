"""Compare the cast's declared subject count with the people in a frame or clip.

A sheet that shows one person four times, or a group of four, asks the image
model for that many distinct subjects. This records whether the picture
actually has that many. The detector is injectable. Without the local YOLOX
weights ``pose/yolox_l.onnx`` (the same file ``qa.people`` uses, on CPU) no
count is invented.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_UNSET = object()
_MODEL = "pose/yolox_l.onnx"


def expected_subjects(spec: dict, window: dict, ready: dict | None = None) -> int | None:
    """How many distinct subjects this shot asked for. None when it names no cast."""
    counts = _counts(spec)
    named = [item for item in window.get("cast") or [] if isinstance(item, str) and item]
    if ready is not None:
        named = [item for item in named if item in ready]
    if not named:
        return None
    return sum(counts.get(item, 1) for item in named)


def judge_count(key: str, stage: str, expected: int, detected: int | None) -> dict:
    """ok when the picture matches the cast. A missing reading is unreliable, not a guess."""
    if detected is None:
        return {"key": key, "stage": stage, "verdict": "unreliable", "expected": expected, "detected": None}
    verdict = "ok" if detected == expected else "mismatch"
    row = {"key": key, "stage": stage, "verdict": verdict, "expected": expected, "detected": detected}
    if verdict == "mismatch":
        row["reason"] = "subject_count"
    return row


def note_media(production: Any, spec: dict, windows: list, stage: str) -> list[dict]:
    """Record one row per h3 shot that names a cast. Returns the rows added."""
    pending = _pending(production, spec, windows)
    if not pending:
        return []
    detector = _resolve(production)
    if detector is None:
        _missing(production)
        return []
    rows = []
    for window, expected in pending:
        detected = _detected(production, stage, window, detector)
        row = judge_count(window.get("key"), stage, expected, detected)
        rows.append(row)
        if row["verdict"] == "mismatch":
            production.log(f"subject count {row['key']} {stage}: expected {row['expected']} detected {row['detected']}")
    production.state.setdefault("subject_counts", []).extend(rows)
    return rows


def mismatches(state: dict) -> list[dict]:
    """Short rows for production.status. Empty when every counted shot matched."""
    rows = []
    for row in state.get("subject_counts") or []:
        if not isinstance(row, dict) or row.get("verdict") != "mismatch":
            continue
        rows.append({"key": row.get("key"), "stage": row.get("stage"), "expected": row.get("expected"), "detected": row.get("detected")})
    return rows[:8]


def _pending(production: Any, spec: dict, windows: list) -> list[tuple[dict, int]]:
    ready = production.state.get("cast") if isinstance(production.state.get("cast"), dict) else None
    found = []
    for window in windows:
        if not isinstance(window, dict) or window.get("kind") != "h3":
            continue
        expected = expected_subjects(spec, window, ready)
        if expected is None:
            continue
        found.append((window, expected))
    return found


def _missing(production: Any) -> None:
    production.state["subject_count_detector"] = f"missing: {_MODEL}"
    if getattr(production, "_subject_count_logged", False):
        return
    production._subject_count_logged = True
    production.log(f"subject count needs {_MODEL}; no count invented")


def _resolve(production: Any):
    if getattr(production, "_subject_bound", False):
        return getattr(production, "subject_detector", None) or None
    production._subject_bound = True
    preset = getattr(production, "subject_detector", _UNSET)
    if preset is not _UNSET:
        production.subject_detector = preset or None
        return production.subject_detector
    production.subject_detector = _load()
    return production.subject_detector


def _load():
    try:
        from services.qa_people import find_weights
        if not find_weights():
            return None
        from services.production_review_checks import load_people_detector
        return load_people_detector()
    except Exception:
        return None


def _detected(production: Any, stage: str, window: dict, detector) -> int | None:
    path = _media_path(production, stage, window)
    image = _open(path, stage) if path is not None else None
    if image is None:
        return None
    try:
        found = detector(image)
    except Exception:
        return None
    if isinstance(found, bool) or found is None:
        return None
    if isinstance(found, int):
        return found
    if isinstance(found, list):
        return len(found)
    return None


def _media_path(production: Any, stage: str, window: dict) -> Path | None:
    key = window.get("key")
    if stage == "frame":
        name = (production.state.get("frames") or {}).get(key)
    else:
        name = ((production.state.get("clips") or {}).get(key) or {}).get("file")
    if not isinstance(name, str) or not name:
        return None
    path = Path(name)
    if not path.is_file():
        path = production.root / name
    return path if path.is_file() else None


def _open(path: Path, stage: str):
    if stage == "clip":
        return _first_frame(path)
    try:
        import numpy as np
        from PIL import Image
        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"))
    except (OSError, ValueError):
        return None


def _first_frame(path: Path):
    import cv2
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok or frame is None:
        return None
    return frame


def _counts(spec: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in spec.get("cast") or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        counts[item["id"]] = _number(item)
    return counts


def _number(item: dict) -> int:
    raw = item.get("count", len(item.get("group") or []) or 1)
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return 1
    return number if number > 0 else 1

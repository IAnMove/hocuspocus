"""Count people on sampled frames and flag a duplicated person.

``qa.people`` decides ``ok``, ``retake``, or ``unreliable``. The model does not
count boxes. A jump such as one person becoming three is a retake. If YOLOX
cannot run, the verdict is ``unreliable`` and no count is invented. The
per-frame list is a workspace JSON; the reply is that file, its URL, and its
sha256.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException

from services.media_paths import MediaPathNotAllowed, resolve_permitted_media_path


OPERATION = "qa.people"
SAMPLE_COUNT = 8
JUMP = 2
_WORKSPACE = r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)"


class QaPeopleError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def command_catalog() -> list[dict]:
    payload = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
            "clip": {"type": "string", "minLength": 1, "maxLength": 2000},
            "expected": {
                "type": "integer",
                "minimum": 0,
                "description": "People expected in the clip. Omit when unknown.",
            },
        },
        "required": ["workspace", "clip"],
    }
    return [{
        "name": OPERATION,
        "version": 1,
        "domain": "qa",
        "mutation": False,
        "description": (
            "Count people on up to 8 sampled frames with the YOLOX weights in ckpts, "
            "on CPU only. Verdict ok, retake, or unreliable. retake when the count "
            "jumps by 2 or more between samples (one dancer becoming three) or when "
            "max_people is above or below expected (a group of 4 counted as 1). "
            "expected=1 with that jump is retake. "
            "unreliable when the detector cannot run; max_people and duplicate_jump "
            "are null and no count is invented. The per-frame list is a workspace "
            "JSON. The reply is frames_file, file, url, and sha256, not the list. "
            "Does not start a model on the GPU. "
            "invalid_command, invalid_workspace, invalid_clip, invalid_expected, "
            "media_not_found, path_not_allowed, unsupported_media, and "
            "clip_unreadable are stable errors."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "input": payload,
            },
            "required": ["version", "input"],
        },
    }]


def command_handlers(workspace_dir, uploads_dir, detect=None):
    async def qa_people(arguments: dict) -> dict:
        import asyncio

        try:
            return await asyncio.to_thread(
                execute, arguments, workspace_dir, uploads_dir, detect,
            )
        except QaPeopleError as error:
            raise HTTPException(error.status, {
                "code": error.code,
                "message": error.message,
                "retryable": False,
            }) from error

    return {OPERATION: qa_people}


def execute(arguments, workspace_dir, uploads_dir, detect=None) -> dict:
    payload = _require_input(arguments)
    workspace = _workspace(payload)
    clip = _clip(payload)
    expected = _expected(payload)
    root = workspace_dir(workspace)
    path = _resolve_clip(clip, workspace, root, uploads_dir())
    rows, reason = detect(path) if detect is not None else detect_clip(path)
    return _publish(root, workspace, clip, rows, reason, expected)


def score_boxes(frames: list, expected: int | None = None) -> dict:
    """Jump logic for boxes already in hand. Does not load YOLOX or read a clip."""
    counts = [_box_count(frame) for frame in frames]
    return verdict_for(counts, expected)


def verdict_for(counts: list[int] | None, expected: int | None) -> dict:
    if not counts:
        return {
            "verdict": "unreliable",
            "max_people": None,
            "expected": expected,
            "duplicate_jump": None,
        }
    jump = count_jumped(counts)
    maximum = max(counts)
    off = expected is not None and maximum != expected
    return {
        "verdict": "retake" if jump or off else "ok",
        "max_people": maximum,
        "expected": expected,
        "duplicate_jump": jump,
    }


def count_jumped(counts: list[int]) -> bool:
    """True when a later sample rises by at least two people."""
    if len(counts) < 2:
        return False
    previous = counts[0]
    for count in counts[1:]:
        if count >= previous + JUMP:
            return True
        previous = count
    return False


def detect_clip(path: str) -> tuple[list[dict] | None, str | None]:
    """Return per-frame rows, or (None, detector_unavailable) without a count."""
    try:
        frames = sample_frames(path)
    except QaPeopleError:
        raise
    except Exception:
        return None, "detector_unavailable"
    weights = find_weights()
    if not weights:
        return None, "detector_unavailable"
    try:
        session = open_detector(weights)
        return count_frames(session, frames), None
    except Exception:
        return None, "detector_unavailable"


def find_weights() -> str | None:
    try:
        from shared.utils.files_locator import locate_file
        found = locate_file("pose/yolox_l.onnx", error_if_none=False)
    except Exception:
        return None
    if isinstance(found, str) and os.path.isfile(found):
        return found
    return None


def open_detector(path: str):
    import onnxruntime as ort

    return ort.InferenceSession(path, providers=["CPUExecutionProvider"])


def count_frames(session, frames: list[dict]) -> list[dict]:
    counted = []
    for frame in frames:
        boxes = people_boxes(session, frame["image"])
        counted.append({
            "index": frame["index"],
            "time_s": frame["time_s"],
            "people": len(boxes),
            "boxes": boxes,
        })
    return counted


def people_boxes(session, image) -> list:
    from preprocessing.dwpose.onnxdet import inference_detector

    detected = inference_detector(session, image)
    if detected is None or len(detected) == 0:
        return []
    return [_box_xyxy(box) for box in detected]


def sample_frames(path: str, count: int = SAMPLE_COUNT) -> list[dict]:
    capture, cv2 = _open_capture(path)
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        fps = 1.0
    rows = []
    try:
        for index in _sample_indexes(total, count):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            rows.append({
                "index": int(index),
                "time_s": round(index / fps, 3),
                "image": frame,
            })
    finally:
        capture.release()
    if not rows:
        raise QaPeopleError("clip_unreadable", "Could not read the clip.")
    return rows


def _box_count(frame) -> int:
    if isinstance(frame, bool) or isinstance(frame, int):
        return int(frame)
    return len(frame)


def _box_xyxy(box) -> list[float]:
    return [round(float(value), 1) for value in box[:4]]


def _sample_indexes(total: int, count: int) -> list[int]:
    if total <= 0:
        return []
    if total <= count or count <= 1:
        return list(range(total if count > 1 else 1))
    span = total - 1
    return [round(step * span / (count - 1)) for step in range(count)]


def _open_capture(path: str):
    import cv2

    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        capture.release()
        raise QaPeopleError("clip_unreadable", "Could not read the clip.")
    return capture, cv2


def _publish(root, workspace: str, clip: str, rows, reason, expected) -> dict:
    counts = None if reason or rows is None else [row["people"] for row in rows]
    summary = verdict_for(counts, expected)
    stored = _store_frames(root, workspace, clip, [] if rows is None else rows, reason)
    summary.update(stored)
    return {"version": 1, "status": "completed", "operation": OPERATION, "result": summary}


def _store_frames(root, workspace: str, clip: str, rows: list, reason: str | None) -> dict:
    public = [_public_row(row) for row in rows]
    document = {
        "version": 1,
        "clip": clip,
        "detector": None if reason else "yolox_l.onnx",
        "frames": public,
    }
    if reason:
        document["reason"] = reason
    folder = Path(root)
    folder.mkdir(parents=True, exist_ok=True)
    name, digest = _write_json(folder, document)
    return {
        "frames_file": name,
        "file": name,
        "url": "/api/v1/file/" + quote(name) + "?workspace=" + quote(workspace, safe=""),
        "sha256": digest,
    }


def _public_row(row: dict) -> dict:
    return {
        "index": row.get("index"),
        "time_s": row.get("time_s"),
        "people": row.get("people"),
        "boxes": row.get("boxes") or [],
    }


def _write_json(folder: Path, document: dict) -> tuple[str, str]:
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    name = f"qa-people-{digest[:20]}.json"
    target = folder / name
    if not target.is_file():
        temporary = folder / f".{name}.tmp"
        temporary.write_bytes(raw)
        temporary.replace(target)
    return name, digest


def _require_input(arguments) -> dict:
    version_ok = isinstance(arguments, dict) and arguments.get("version") == 1
    payload = arguments.get("input") if isinstance(arguments, dict) else None
    if not version_ok or not isinstance(payload, dict):
        raise QaPeopleError("invalid_command", "Use version 1 and an input object.")
    return payload


def _workspace(payload: dict) -> str:
    import re

    workspace = payload.get("workspace")
    if not isinstance(workspace, str) or not re.fullmatch(_WORKSPACE, workspace):
        raise QaPeopleError("invalid_workspace", "workspace is required.")
    return workspace


def _clip(payload: dict) -> str:
    clip = payload.get("clip")
    if not isinstance(clip, str) or not clip.strip() or clip != clip.strip() or "\x00" in clip:
        raise QaPeopleError("invalid_clip", "clip is required.")
    return clip


def _expected(payload: dict) -> int | None:
    if "expected" not in payload or payload.get("expected") is None:
        return None
    value = payload.get("expected")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QaPeopleError("invalid_expected", "expected must be a non-negative integer.")
    return value


def _resolve_clip(clip: str, workspace: str, workspace_root: str, uploads_root: str) -> str:
    try:
        return resolve_permitted_media_path(
            clip,
            uploads_root=uploads_root,
            workspace_root=workspace_root,
            kinds=("video",),
            workspace_name=workspace,
        )
    except FileNotFoundError as error:
        raise QaPeopleError("media_not_found", "Clip was not found.", 404) from error
    except MediaPathNotAllowed as error:
        code = "unsupported_media" if str(error) == "Media type is not allowed" else "path_not_allowed"
        raise QaPeopleError(code, "Clip path is not allowed.") from error

"""qa.people flags a duplicated person without inventing a count.

The jump is tested on a synthetic box sequence (1, 1, 3). These tests do
not read app/outputs and do not start a detector.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.qa_people import (
    command_catalog,
    command_handlers,
    count_jumped,
    detect_clip,
    score_boxes,
    verdict_for,
)


ONE = [[0.0, 0.0, 10.0, 40.0]]
THREE = [
    [0.0, 0.0, 10.0, 40.0],
    [20.0, 0.0, 30.0, 40.0],
    [40.0, 0.0, 50.0, 40.0],
]
SYNTHETIC = [ONE, ONE, THREE]


def _layout(tmp_path: Path, detect=None):
    workspace = tmp_path / "outputs" / "clip"
    uploads = tmp_path / "uploads"
    workspace.mkdir(parents=True)
    uploads.mkdir()
    (workspace / "dance.mp4").write_bytes(b"not-a-decoded-clip")

    def workspace_dir(name: str) -> str:
        if name != "clip":
            raise HTTPException(status_code=400, detail="Invalid workspace name.")
        return str(workspace)

    handlers = command_handlers(workspace_dir, lambda: str(uploads), detect)
    return handlers, workspace


def _call(handlers, payload: dict) -> dict:
    return asyncio.run(handlers["qa.people"]({"version": 1, "input": payload}))


def _rows(frames: list) -> list[dict]:
    rows = []
    for index, boxes in enumerate(frames):
        rows.append({
            "index": index,
            "time_s": float(index),
            "people": len(boxes),
            "boxes": boxes,
        })
    return rows


def test_synthetic_boxes_1_1_3_with_expected_1_are_retake():
    decision = score_boxes(SYNTHETIC, expected=1)
    assert [len(frame) for frame in SYNTHETIC] == [1, 1, 3]
    assert score_boxes([1, 1, 3], expected=1) == decision
    assert decision["verdict"] == "retake"
    assert decision["duplicate_jump"] is True
    assert decision["max_people"] == 3
    assert decision["expected"] == 1
    assert count_jumped([1, 1, 3]) is True


def test_stable_single_person_is_ok_and_a_jump_without_expected_is_retake():
    stable = score_boxes([ONE, ONE, ONE], expected=1)
    assert stable["verdict"] == "ok"
    assert stable["duplicate_jump"] is False
    assert stable["max_people"] == 1
    jumped = score_boxes(SYNTHETIC, expected=None)
    assert jumped["verdict"] == "retake"
    assert jumped["duplicate_jump"] is True
    assert jumped["expected"] is None


def test_handler_writes_the_frame_list_and_returns_only_the_file(tmp_path):
    handlers, workspace = _layout(tmp_path, detect=lambda _path: (_rows(SYNTHETIC), None))
    body = _call(handlers, {"workspace": "clip", "clip": "dance.mp4", "expected": 1})
    assert body["status"] == "completed"
    assert body["operation"] == "qa.people"
    result = body["result"]
    assert result["verdict"] == "retake"
    assert result["max_people"] == 3
    assert result["expected"] == 1
    assert result["duplicate_jump"] is True
    assert set(result) == {
        "verdict", "max_people", "expected", "duplicate_jump",
        "frames_file", "file", "url", "sha256",
    }
    assert "frames" not in result
    assert result["frames_file"] == result["file"]
    assert result["url"].startswith("/api/v1/file/")
    assert "workspace=clip" in result["url"]
    stored = json.loads((workspace / result["file"]).read_text(encoding="utf-8"))
    assert stored["frames"] == _rows(SYNTHETIC)
    assert stored["detector"] == "yolox_l.onnx"
    digest = hashlib.sha256(
        json.dumps(stored, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result["sha256"] == digest


def test_missing_detector_does_not_invent_a_count(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.qa_people.sample_frames",
        lambda _path: [{"index": 0, "time_s": 0.0, "image": object()}],
    )
    monkeypatch.setattr("services.qa_people.find_weights", lambda: None)
    rows, reason = detect_clip("dance.mp4")
    assert rows is None
    assert reason == "detector_unavailable"
    assert verdict_for(None, 1) == {
        "verdict": "unreliable",
        "max_people": None,
        "expected": 1,
        "duplicate_jump": None,
    }

    handlers, workspace = _layout(tmp_path, detect=lambda _path: (None, "detector_unavailable"))
    result = _call(handlers, {"workspace": "clip", "clip": "dance.mp4", "expected": 1})["result"]
    assert result["verdict"] == "unreliable"
    assert result["max_people"] is None
    assert result["duplicate_jump"] is None
    stored = json.loads((workspace / result["file"]).read_text(encoding="utf-8"))
    assert stored["frames"] == []
    assert stored["reason"] == "detector_unavailable"
    assert stored["detector"] is None
    assert "people" not in json.dumps(stored)


def test_catalog_is_versioned_qa_people():
    operation = command_catalog()[0]
    assert operation["name"] == "qa.people"
    assert operation["version"] == 1
    assert operation["mutation"] is False
    schema = operation["inputSchema"]
    assert schema["properties"]["version"]["const"] == 1
    assert schema["required"] == ["version", "input"]
    assert schema["properties"]["input"]["required"] == ["workspace", "clip"]
    assert "expected" in schema["properties"]["input"]["properties"]


@pytest.mark.parametrize(
    ("payload", "code", "status"),
    [
        ({"workspace": "clip"}, "invalid_clip", 422),
        ({"workspace": "../clip", "clip": "dance.mp4"}, "invalid_workspace", 422),
        ({"workspace": "clip", "clip": "dance.mp4", "expected": True}, "invalid_expected", 422),
        ({"workspace": "clip", "clip": "dance.mp4", "expected": -1}, "invalid_expected", 422),
        ({"workspace": "clip", "clip": "../dance.mp4"}, "path_not_allowed", 422),
        ({"workspace": "clip", "clip": "missing.mp4"}, "media_not_found", 404),
        ({"workspace": "clip", "clip": "notes.txt"}, "unsupported_media", 422),
    ],
)
def test_stable_error_codes(tmp_path, payload, code, status):
    handlers, workspace = _layout(tmp_path)
    (workspace / "notes.txt").write_text("nope", encoding="utf-8")
    with pytest.raises(HTTPException) as caught:
        _call(handlers, payload)
    assert caught.value.status_code == status
    assert caught.value.detail["code"] == code
    assert caught.value.detail["retryable"] is False


def test_bad_version_is_invalid_command(tmp_path):
    handlers, _workspace = _layout(tmp_path)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["qa.people"]({"version": 2, "input": {"workspace": "clip", "clip": "dance.mp4"}}))
    assert caught.value.detail["code"] == "invalid_command"

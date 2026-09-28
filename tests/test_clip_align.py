"""clip.align places a driven clip from the score, without inventing lip-sync."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from services.clip_align import command_catalog, command_handlers


def _score() -> dict:
    return {
        "duration": 30.0,
        "bpm": 120,
        "beats": [12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0, 15.5],
        "lines": [
            {"text": "verse", "t0": 8.0, "t1": 12.5},
            {"text": "chorus", "t0": 12.5, "t1": 15.0, "words": [{"w": "hey", "t0": 12.5, "t1": 13.0}]},
            {"text": "after", "t0": 15.0, "t1": 20.0},
        ],
    }


def _run(tmp_path, score, *, range_start=12.5, duration=4.0, measure=None, clip="clip.mp4", extra=None):
    workspace = tmp_path / "demo"
    workspace.mkdir()
    (workspace / "clip.mp4").write_bytes(b"clip")
    (workspace / "score.json").write_text(json.dumps(score), encoding="utf-8")
    for name, data in (extra or {}).items():
        (workspace / name).write_bytes(data)
    handlers = command_handlers(
        lambda name: str(tmp_path / name),
        probe_duration=lambda _path: duration,
        measure=measure,
    )
    return asyncio.run(handlers["clip.align"]({
        "version": 1,
        "input": {
            "workspace": "demo",
            "clip": clip,
            "score_file": "score.json",
            "range_start": range_start,
        },
    }))


def test_section_at_12_5_keeps_a_4s_clip_inside(tmp_path):
    body = _run(tmp_path, _score())["result"]
    assert body["sourceStart"] == 12.5
    assert body["sync"] == 0
    assert body["verdict"] == "unreliable"
    assert body["reason"] == "lipsync_unavailable"
    assert body["trimStart"] == 0.0
    assert body["trimEnd"] == 2.5
    played_start = body["sourceStart"] + body["trimStart"]
    played_end = body["sourceStart"] + body["trimEnd"]
    assert played_start == 12.5
    assert played_end == 15.0
    assert played_end - played_start <= 4
    assert body["beat"] == 12.5


def test_catalog_is_versioned_clip_align():
    operation = command_catalog()[0]
    assert operation["name"] == "clip.align"
    assert operation["version"] == 1
    assert operation["mutation"] is False
    schema = operation["inputSchema"]
    assert schema["properties"]["version"]["const"] == 1
    assert schema["properties"]["input"]["required"] == ["workspace", "clip", "score_file", "range_start"]


def test_injected_lipsync_does_not_move_the_score_trim(tmp_path):
    seen = {}

    def measure(clip, audio, offset):
        seen["offset"] = offset
        seen["clip"] = clip
        return {"verdict": "ok", "suggested_sync_s": 0.08, "best_r": 0.5, "best_lag_s": 0.08}

    score = _score()
    score["vocals_file"] = "vocals.wav"
    body = _run(tmp_path, score, measure=measure, extra={"vocals.wav": b"wav"})["result"]
    assert seen["offset"] == 12.5
    assert body["sync"] == 0.08
    assert body["verdict"] == "ok"
    assert body["sourceStart"] == 12.5
    assert body["trimStart"] == 0.0
    assert body["trimEnd"] == 2.5
    assert "reason" not in body


def test_section_not_found(tmp_path):
    with pytest.raises(HTTPException) as caught:
        _run(tmp_path, _score(), range_start=28)
    assert caught.value.detail["code"] == "section_not_found"


def test_rejects_bad_version(tmp_path):
    handlers = command_handlers(lambda name: str(tmp_path / name), probe_duration=lambda _path: 4.0)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["clip.align"]({"version": 2, "input": {}}))
    assert caught.value.detail["code"] == "invalid_command"


def test_rejects_path_escape(tmp_path):
    with pytest.raises(HTTPException) as caught:
        _run(tmp_path, _score(), clip="../secret.mp4")
    assert caught.value.detail["code"] == "invalid_path"

"""production.status wait_s blocks on the status value, not a busy loop."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.music_production import STATUS, command_catalog, command_handlers
from services.production_wait import MAX_WAIT_S, calls_to_cover, normalize_wait_s, wait_for_status

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "agents" / "VIDEO_PRODUCTION_RUNBOOK.md"
HALF_HOUR = 30 * 60
FLIPS = (120, 900)


def _status_at(moment: float) -> str:
    if moment >= 900:
        return "completed"
    if moment >= 120:
        return "frames_ready"
    return "running"


def test_wait_s_is_an_integer_from_zero_to_300():
    assert normalize_wait_s(None) == 0
    assert normalize_wait_s(0) == 0
    assert normalize_wait_s(MAX_WAIT_S) == 300
    for bad in (True, False, 1.2, "30", -1, 301):
        with pytest.raises(HTTPException) as caught:
            normalize_wait_s(bad)
        assert caught.value.status_code == 422
        assert caught.value.detail["code"] == "invalid_command"


def test_status_schema_accepts_wait_s():
    operation = next(item for item in command_catalog() if item["name"] == STATUS)
    field = operation["inputSchema"]["properties"]["input"]["properties"]["wait_s"]
    required = operation["inputSchema"]["properties"]["input"]["required"]
    assert field["type"] == "integer"
    assert field["minimum"] == 0
    assert field["maximum"] == 300
    assert field["default"] == 0
    assert "wait_s" not in required


def test_runbook_polls_status_with_wait_s_300():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "Poll `production.status` with `wait_s` 300 instead of many short polls." in text


def test_flip_at_120_returns_early_and_eight_calls_cover_thirty_minutes(tmp_path):
    assert calls_to_cover(HALF_HOUR, 300, ()) == 6
    assert calls_to_cover(HALF_HOUR, 300, FLIPS) <= 8
    ends = asyncio.run(_follow(tmp_path))
    assert ends[0] == (120, "frames_ready")
    assert (900, "completed") in ends
    assert len(ends) == calls_to_cover(HALF_HOUR, 300, FLIPS)
    assert len(ends) <= 8
    assert 300 not in [moment for moment, _status in ends]


async def _follow(tmp_path: Path) -> list[tuple[float, str]]:
    path = tmp_path / "song.production.json"
    clock = {"t": 0.0}
    sleeps: list[float] = []

    def publish() -> None:
        payload = {"status": _status_at(clock["t"]), "log": [clock["t"]]}
        path.write_text(json.dumps(payload))

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds
        publish()

    publish()
    ends: list[tuple[float, str]] = []
    while clock["t"] < HALF_HOUR:
        state = await wait_for_status(path, 300, clock=lambda: clock["t"], sleep=sleep)
        ends.append((clock["t"], state["status"]))
    assert sleeps
    assert set(sleeps) == {1.0}
    assert sum(sleeps) == HALF_HOUR
    return ends


def test_zero_wait_reads_once_and_does_not_sleep(tmp_path):
    path = tmp_path / "song.production.json"
    path.write_text(json.dumps({"status": "running"}))

    async def boom(_seconds: float) -> None:
        raise AssertionError("slept")

    state = asyncio.run(wait_for_status(path, 0, clock=lambda: 0.0, sleep=boom))
    assert state["status"] == "running"


def test_status_handler_forwards_wait_s_and_does_not_wait_when_missing(tmp_path, monkeypatch):
    seen: dict = {}

    async def fake(path, wait_s=0, **_kwargs):
        seen["path"] = Path(path)
        seen["wait_s"] = wait_s
        return {"status": "running", "log": []}

    monkeypatch.setattr("services.music_production.wait_for_status", fake)
    (tmp_path / "clip.production.json").write_text(json.dumps({"status": "running"}))
    handlers = command_handlers(lambda _name: str(tmp_path), lambda: str(tmp_path), lambda: "http://127.0.0.1", lambda: "token")
    result = asyncio.run(handlers[STATUS]({"version": 1, "input": {"workspace": "ws", "production_id": "clip", "wait_s": 300}}))
    assert result["result"]["status"] == "running"
    assert seen["wait_s"] == 300
    assert seen["path"].name == "clip.production.json"

    asyncio.run(handlers[STATUS]({"version": 1, "input": {"workspace": "ws", "production_id": "clip"}}))
    assert seen["wait_s"] == 0

    seen["wait_s"] = None
    with pytest.raises(HTTPException) as missing:
        asyncio.run(handlers[STATUS]({"version": 1, "input": {"workspace": "ws", "production_id": "gone", "wait_s": 300}}))
    assert missing.value.status_code == 404
    assert seen["wait_s"] is None

    monkeypatch.undo()
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(handlers[STATUS]({"version": 1, "input": {"workspace": "ws", "production_id": "clip", "wait_s": 301}}))
    assert rejected.value.status_code == 422
    assert rejected.value.detail["code"] == "invalid_command"

"""production.cancel stops a live wait and leaves a resumable production."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.music_production import Production, _lock, _threads
from services.production_commands import CANCEL, extra_handlers
from services.production_control import disarm, request_cancel
from services.production_resume import load_running


def _spec() -> dict:
    return {
        "title": "Show",
        "song": {"lyrics": "la", "caption": "la", "duration": 8, "bpm": 120},
        "style": {},
        "shots": [{"key": "s0", "kind": "still", "still": "a.png"}],
    }


def _forget(key: str) -> None:
    with _lock:
        _threads.pop(key, None)
    workspace, production_id = key.split("/", 1)
    disarm(workspace, production_id)


def test_cancel_of_a_stopped_production_does_not_arm():
    from services import production_control
    assert request_cancel("ws", "gone", {}, threading.Lock()) is False
    assert "ws/gone" not in production_control._events


def test_cancel_command_is_not_running_when_the_thread_is_dead():
    handlers = extra_handlers(lambda _workspace: "/tmp", lambda: "/tmp", lambda: "http://127.0.0.1:9", lambda: "token")
    with pytest.raises(HTTPException) as caught:
        __import__("asyncio").run(handlers[CANCEL]({"version": 1, "input": {"workspace": "ws", "production_id": "gone"}}))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "not_running"


def test_cancel_stops_a_live_wait_within_two_seconds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "film"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    (root / "show.production.json").write_text('{"auto_resume": true, "spec": {"title": "Show"}}', encoding="utf-8")
    production = Production("film", "show", workspace_dir=lambda _name: str(root), uploads_dir=lambda: str(uploads), mcp=lambda _tool, _args: {"status": "running"})
    spec = _spec()
    entered = threading.Event()
    real_sleep = time.sleep

    def sleeper(seconds: float) -> None:
        entered.set()
        real_sleep(seconds)

    monkeypatch.setattr("services.music_production.time.sleep", sleeper)
    monkeypatch.setattr(Production, "score", lambda self: {"duration": 8, "bpm": 120, "beat": 0.5, "lines": []})
    for name in ("song", "analyze", "cast", "frames", "scenes", "package"):
        monkeypatch.setattr(Production, name, lambda self, *args, **kwargs: None)

    def blocking_clips(self, spec, windows, retake=()):
        self.wait({"s0": "job-1"}, poll=6)

    monkeypatch.setattr(Production, "clips", blocking_clips)
    key = "film/show"
    thread = threading.Thread(target=production.run, args=(spec,), name="production-show", daemon=True)
    try:
        with _lock:
            _threads[key] = thread
        thread.start()
        assert entered.wait(3)
        started = time.monotonic()
        assert request_cancel("film", "show", _threads, _lock) is True
        thread.join(2.5)
        elapsed = time.monotonic() - started
        assert elapsed < 2, elapsed
        assert not thread.is_alive()
        assert production.state["status"] == "cancelled"
        assert production.state["error"] is None
        assert production.state["spec"]["title"] == "Show"
        production.state["auto_resume"] = True
        production.save()
        assert load_running(production.path) is None

        monkeypatch.setattr(Production, "clips", lambda self, *args, **kwargs: None)
        monkeypatch.setattr(Production, "montage", lambda self, spec: self.state.__setitem__("final", "out.mp4"))
        production.run(spec)
        assert production.state["status"] == "completed"
        assert production.state["final"] == "out.mp4"
    finally:
        if thread.is_alive():
            request_cancel("film", "show", _threads, _lock)
            thread.join(8)
        _forget(key)

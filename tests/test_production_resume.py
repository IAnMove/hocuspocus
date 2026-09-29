"""A running production survives a server restart without another agent call."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.error
from pathlib import Path

import pytest

import services.music_production as music_production
from services.music_production import Production, command_handlers, loopback_mcp, status_summary
from services.production_resume import resume_on_startup

RUN = "production.run"


class _Body:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


def _spec() -> dict:
    return {"title": "t", "song": {"lyrics": "a", "caption": "pop", "duration": 30, "bpm": 120}, "style": {},
            "shots": [{"key": "s0", "kind": "h3", "line": 0, "frame": "f", "action": "sings"}]}


def _write(root: Path, production_id: str, state: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{production_id}.production.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _running(root: Path, production_id: str, **extra) -> Path:
    state = {"status": "running", "spec": _spec(), "song": {"file": "song.wav"}, "score": "song.score.json",
             "frames": {"s0": "frame.png"}, "clips": {}, "error": "URLError: <urlopen error [Errno 111] Connection refused>"}
    state.update(extra)
    return _write(root, production_id, state)


def _score(root: Path) -> None:
    (root / "song.score.json").write_text(json.dumps({
        "duration": 30, "beat": 0.5, "lines": [{"t0": 1.0, "t1": 3.0, "text": "a"}],
    }), encoding="utf-8")


def _dirs(tmp_path: Path):
    return (lambda name: str(tmp_path / name), lambda: str(tmp_path / "uploads"))


def _startup(tmp_path: Path, workspaces: list[dict], *, url: str = "http://127.0.0.1:9", token: str = "token"):
    workspace_dir, uploads_dir = _dirs(tmp_path)
    return resume_on_startup(lambda: workspaces, workspace_dir, uploads_dir, lambda: url, lambda: token)


def _forget(*keys: str) -> None:
    with music_production._lock:
        for key in keys:
            music_production._threads.pop(key, None)


def test_stopped_worker_resumes_mid_clips_without_another_agent_call(tmp_path, monkeypatch):
    workspace = tmp_path / "musical"
    path = _running(workspace, "show")
    _score(workspace)
    phases: list[str] = []
    entered = threading.Event()
    stop = threading.Event()
    continued = threading.Event()

    def clips(self, spec, windows, retake=(), pause=60):
        if not entered.is_set():
            phases.append("clips-stopped")
            entered.set()
            stop.wait(timeout=5)
            raise SystemExit
        phases.append("clips-resumed")
        self.state.setdefault("clips", {})["s0"] = {"file": "s0.mp4", "qa": {"verdict": "ok"}}
        continued.set()

    real_run = Production.run

    def run(self, spec, retake=(), through="all"):
        try:
            real_run(self, spec, retake, through)
        except SystemExit:
            return

    monkeypatch.setattr(Production, "clips", clips)
    monkeypatch.setattr(Production, "scenes", lambda self, spec, windows: None)

    def montage(self, spec):
        self.state["final"] = "video.mp4"

    monkeypatch.setattr(Production, "montage", montage)
    monkeypatch.setattr(Production, "run", run)

    workspace_dir, uploads_dir = _dirs(tmp_path)
    handlers = command_handlers(workspace_dir, uploads_dir, lambda: "http://127.0.0.1:9", lambda: "token")
    agent_calls: list = []
    payload = {"version": 1, "input": {"workspace": "musical", "production_id": "show", "spec": _spec(), "auto_resume": True}}

    async def agent(arguments):
        agent_calls.append(arguments)
        return await handlers[RUN](arguments)

    key = "musical/show"
    try:
        asyncio.run(agent(payload))
        assert entered.wait(timeout=2)
        worker = music_production._threads[key]
        assert worker.is_alive()
        stop.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert json.loads(path.read_text(encoding="utf-8"))["status"] == "running"

        def refuse_agent(*_args, **_kwargs):
            agent_calls.append("resume")
            raise AssertionError("resume must not call the agent")

        monkeypatch.setattr(music_production, "command_handlers", refuse_agent)
        resumed = _startup(tmp_path, [{"name": "musical", "path": str(workspace)}])
        assert resumed == [key]
        resumed_worker = music_production._threads[key]
        assert resumed_worker is not worker
        assert continued.wait(timeout=5)
        resumed_worker.join(timeout=5)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert phases == ["clips-stopped", "clips-resumed"]
        assert saved["status"] == "completed" and saved["error"] is None
        assert saved["clips"]["s0"]["file"] == "s0.mp4"
        assert agent_calls == [payload]
    finally:
        stop.set()
        _forget(key)


def test_completed_run_clears_error(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda *_: {})
    production.state = {"error": "URLError: <urlopen error [Errno 111] Connection refused>"}
    production.score = lambda: {"duration": 30, "lines": [], "beat": 0.5}
    for name in ("song", "analyze", "cast", "frames", "clips", "scenes"):
        setattr(production, name, lambda *args, **kwargs: None)

    def montage(_spec):
        production.state["final"] = "video.mp4"

    production.montage = montage
    production.run(_spec())
    assert production.state["status"] == "completed"
    assert production.state["error"] is None
    assert status_summary(production.state, "ws")["error"] is None


def test_a_run_without_a_video_keeps_the_previous_error(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda *_: {})
    production.state = {"error": "URLError: <urlopen error [Errno 111] Connection refused>"}
    production.score = lambda: {"duration": 30, "lines": [], "beat": 0.5}
    for name in ("song", "analyze", "cast", "frames", "clips", "scenes", "montage"):
        setattr(production, name, lambda *args, **kwargs: None)
    production.run(_spec())
    assert production.state["status"] == "failed"
    assert production.state["error"].startswith("URLError:")


def test_loopback_retries_urlerror_with_injected_backoff(monkeypatch):
    sleeps: list[float] = []
    calls = {"n": 0}

    def urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("refused")
        return _Body(b'{"result": {"structuredContent": {"ok": 1}}}')

    monkeypatch.setattr("services.production_resume.urllib.request.urlopen", urlopen)
    call = loopback_mcp(lambda: "http://127.0.0.1:9/", lambda: "tok", sleep=sleeps.append)
    assert call("status", {"job_id": "j"}) == {"ok": 1}
    assert sleeps == [5, 15]
    assert calls["n"] == 3


def test_loopback_retries_502_and_503_then_fails_without_a_fourth_try(monkeypatch):
    sleeps: list[float] = []
    codes = iter((502, 503, 502, 500))

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, next(codes), "gateway", None, None)

    monkeypatch.setattr("services.production_resume.urllib.request.urlopen", urlopen)
    call = loopback_mcp(lambda: "http://127.0.0.1:9", lambda: "tok", sleep=sleeps.append)
    try:
        call("generate", {})
    except urllib.error.HTTPError as error:
        assert error.code == 502
    else:
        raise AssertionError("gateway errors were not raised")
    assert sleeps == [5, 15, 45]


def test_loopback_does_not_retry_other_failures(monkeypatch):
    sleeps: list[float] = []

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 500, "no", None, None)

    monkeypatch.setattr("services.production_resume.urllib.request.urlopen", urlopen)
    call = loopback_mcp(lambda: "http://127.0.0.1:9", lambda: "tok", sleep=sleeps.append)
    try:
        call("generate", {})
    except urllib.error.HTTPError as error:
        assert error.code == 500
    else:
        raise AssertionError("HTTP 500 was swallowed")
    assert sleeps == []

    def explode(request, timeout):
        raise TimeoutError("slow")

    monkeypatch.setattr("services.production_resume.urllib.request.urlopen", explode)
    try:
        call("generate", {})
    except TimeoutError:
        pass
    else:
        raise AssertionError("TimeoutError was retried")
    assert sleeps == []


def test_resume_skips_stale_finished_live_and_inactive_mcp(tmp_path, monkeypatch):
    monkeypatch.setattr(Production, "run", lambda self, spec, retake=(), through="all": None)
    fresh = tmp_path / "fresh"
    stale = tmp_path / "stale"
    done = tmp_path / "done"
    live = tmp_path / "live"
    plain = tmp_path / "plain"
    _running(fresh, "keep", auto_resume=True)
    old = _running(stale, "old")
    _write(done, "done", {"status": "failed", "spec": _spec(), "error": "URLError: refused"})
    _running(live, "live")
    _write(plain, "note", {"status": "running", "note": "no spec"})
    moment = time.time()
    old_stamp = moment - (24 * 60 * 60) - 60
    os.utime(old, (old_stamp, old_stamp))
    hold = threading.Event()
    thread = threading.Thread(target=hold.wait, kwargs={"timeout": 5}, daemon=True)
    thread.start()
    key = "live/live"
    try:
        with music_production._lock:
            music_production._threads[key] = thread
        listed = [
            {"name": "fresh", "path": str(fresh)},
            {"name": "stale", "path": str(stale)},
            {"name": "done", "path": str(done)},
            {"name": "live", "path": str(live)},
            {"name": "plain", "path": str(plain)},
        ]
        assert _startup(tmp_path, listed, token="") == []
        assert _startup(tmp_path, listed, url="") == []
        resumed = _startup(tmp_path, listed)
        assert resumed == ["fresh/keep"]
        music_production._threads["fresh/keep"].join(timeout=2)
        assert music_production._threads[key] is thread
        assert "stale/old" not in music_production._threads
    finally:
        hold.set()
        thread.join(timeout=2)
        _forget(key, "fresh/keep")


def test_a_running_production_that_did_not_ask_to_resume_stays_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(Production, "run", lambda self, spec, retake=(), through="all": None)
    workspace = tmp_path / "quiet"
    _running(workspace, "show")
    listed = [{"name": "quiet", "path": str(workspace)}]
    monkeypatch.delenv("HOCUS_PRODUCTION_AUTORESUME", raising=False)
    assert _startup(tmp_path, listed) == []
    monkeypatch.setenv("HOCUS_PRODUCTION_AUTORESUME", "1")
    try:
        assert _startup(tmp_path, listed) == ["quiet/show"]
        music_production._threads["quiet/show"].join(timeout=2)
    finally:
        _forget("quiet/show")


def test_a_second_run_while_one_is_running_is_an_error(tmp_path, monkeypatch):
    from fastapi import HTTPException
    workspace_dir, uploads_dir = _dirs(tmp_path)
    (tmp_path / "musical").mkdir()
    handlers = command_handlers(workspace_dir, uploads_dir, lambda: "http://127.0.0.1:9", lambda: "token")
    release = threading.Event()
    started = threading.Event()

    def slow(self, spec, retake=(), through="all"):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(Production, "run", slow)
    payload = {"version": 1, "input": {"workspace": "musical", "production_id": "busy", "spec": _spec()}}
    try:
        asyncio.run(handlers[RUN](payload))
        assert started.wait(timeout=2)
        with pytest.raises(HTTPException) as error:
            asyncio.run(handlers[RUN](payload))
        assert error.value.status_code == 409 and error.value.detail["code"] == "already_running"
    finally:
        release.set()
        music_production._threads["musical/busy"].join(timeout=2)
        _forget("musical/busy")

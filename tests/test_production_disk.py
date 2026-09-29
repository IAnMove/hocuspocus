"""Disk guard and completed-run cleanup for production.run. No models and no MCP."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.music_production import Production, ProductionError, command_handlers
from services.production_disk import MIN_FREE_BYTES, require_free_disk

KEEP = ("song.wav", "a-best.mp4", "b-best.mp4", "scene-a.mp4", "scene-b.mp4", "final.mp4")
DROP = ("a-lose.mp4", "b-lose.mp4", "mv-slice-a-0.wav", "mv-slice-b-2.wav")


def _spec():
    return {"title": "t", "song": {"lyrics": "a\nb", "caption": "pop", "duration": 30, "bpm": 120}, "style": {},
            "shots": [{"key": "s0", "kind": "h3", "line": 0, "frame": "f", "action": "a"}]}


def _low(_path):
    return SimpleNamespace(free=MIN_FREE_BYTES - 1)


def _quiet(production, montage):
    production.song = lambda spec: None
    production.analyze = lambda spec: None
    production.cast = lambda spec: None
    production.frames = lambda spec, windows: None
    production.clips = lambda spec, windows, retake=(): None
    production.scenes = lambda spec, windows: None
    production.score = lambda: {"duration": 30.0, "lines": [{"t0": 0.0, "t1": 1.0}]}
    production.montage = montage


def _plant(production, *, fail: bool) -> None:
    for name in (*KEEP, *DROP):
        (production.root / name).write_bytes(b"take")
    production.state.update(
        song={"file": "song.wav"},
        clips={"a": {"file": "a-best.mp4"}, "b": {"file": "b-best.mp4"}},
        scenes={"a": {"file": "scene-a.mp4"}, "b": {"file": "scene-b.mp4"}},
        final="final.mp4",
    )
    if fail:
        raise RuntimeError("gpu")


def _names(production) -> set[str]:
    return {path.name for path in production.root.iterdir()}


def test_low_disk_rejects_before_any_mcp_call(tmp_path, monkeypatch):
    require_free_disk(tmp_path, disk_usage=lambda _path: SimpleNamespace(free=MIN_FREE_BYTES))
    with pytest.raises(ProductionError) as direct:
        require_free_disk(tmp_path, disk_usage=_low)
    assert direct.value.code == "disk_low"
    calls = []

    def loopback(_url, _token):
        def call(tool, _arguments):
            calls.append(tool)
            return {}
        return call

    monkeypatch.setattr("services.music_production.loopback_mcp", loopback)
    monkeypatch.setattr("services.production_disk.shutil.disk_usage", _low)
    handlers = command_handlers(lambda _name: str(tmp_path), lambda: str(tmp_path), lambda: "http://127.0.0.1:9", lambda: "token")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["production.run"]({"version": 1, "input": {"workspace": "ws", "production_id": "disk", "spec": _spec()}}))
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "disk_low"
    assert calls == []


def test_completed_run_keeps_only_chosen_files_and_failed_run_keeps_all(tmp_path):
    calls = []

    def build(production_id, fail):
        root = tmp_path / production_id
        root.mkdir()
        production = Production("ws", production_id, workspace_dir=lambda _name: str(root), uploads_dir=lambda: str(tmp_path / "uploads"),
                                mcp=lambda tool, _arguments: calls.append(tool))
        _quiet(production, lambda _spec: _plant(production, fail=fail))
        production.run(_spec())
        return production

    done = build("done", fail=False)
    assert done.state["status"] == "completed"
    assert _names(done) == set(KEEP) | {done.path.name}
    failed = build("fail", fail=True)
    assert failed.state["status"] == "failed"
    assert _names(failed) == set(KEEP) | set(DROP) | {failed.path.name}
    assert calls == []

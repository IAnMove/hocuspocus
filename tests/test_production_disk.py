"""Disk guard and completed-run cleanup for production.run. No models and no MCP."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.music_production import Production, ProductionError, command_handlers
from services.production_disk import MIN_FREE_BYTES, discard, release_completed, require_free_disk

KEEP = ("song.wav", "a-best.mp4", "b-best.mp4", "scene-a.mp4", "scene-b.mp4", "final.mp4")
LOSE = ("a-lose.mp4", "b-lose.mp4")
FOREIGN = ("other-prod.mp4", "user-ref.mov", "other-slice-x-0.wav")


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


def _slices(production_id: str) -> tuple[str, str]:
    return (f"{production_id}-slice-a-0.wav", f"{production_id}-slice-b-2.wav")


def _plant(production, *, fail: bool) -> None:
    slices = _slices(production.id)
    for name in (*KEEP, *LOSE, *FOREIGN, *slices):
        (production.root / name).write_bytes(b"take")
    production.state.update(
        song={"file": "song.wav"},
        clips={"a": {"file": "a-best.mp4"}, "b": {"file": "b-best.mp4"}},
        scenes={"a": {"file": "scene-a.mp4"}, "b": {"file": "scene-b.mp4"}},
        final="final.mp4",
        discarded=list(LOSE),
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
    assert _names(done) == set(KEEP) | set(FOREIGN) | {done.path.name}
    failed = build("fail", fail=True)
    assert failed.state["status"] == "failed"
    assert _names(failed) == set(KEEP) | set(LOSE) | set(FOREIGN) | set(_slices("fail")) | {failed.path.name}
    assert calls == []


def test_completed_run_does_not_delete_another_production_in_the_same_workspace(tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    for name in (*KEEP, *LOSE, "b-best-other.mp4", "other-slice-s0-0.wav", "mv-a-slice-s0-0.wav"):
        (root / name).write_bytes(b"take")
    state = {
        "status": "completed",
        "started": 100.0,
        "song": {"file": "song.wav"},
        "clips": {"a": {"file": "a-best.mp4"}},
        "scenes": {"a": {"file": "scene-a.mp4"}},
        "final": "final.mp4",
        "discarded": ["a-lose.mp4"],
    }
    release_completed(root, state, "mv-a")
    names = {path.name for path in root.iterdir()}
    assert "a-lose.mp4" not in names
    assert "mv-a-slice-s0-0.wav" not in names
    assert {"b-best-other.mp4", "other-slice-s0-0.wav", "b-lose.mp4", "a-best.mp4", "final.mp4"} <= names


def test_discard_records_unique_basenames():
    state: dict = {}
    discard(state, "takes/a-lose.mp4")
    discard(state, "a-lose.mp4")
    discard(state, "")
    discard(state, None)
    assert state["discarded"] == ["a-lose.mp4"]

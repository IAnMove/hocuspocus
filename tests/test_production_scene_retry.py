"""Scene export is tried twice; a second failure skips the montage."""
from __future__ import annotations

import json
import time

from services.music_production import Production


def _refuse_sleep(_seconds: float) -> None:
    raise AssertionError("scene export waited instead of retrying")


def _production(tmp_path, mcp):
    (tmp_path / "s.score.json").write_text(json.dumps({"duration": 4.0, "beat": 0.5, "lines": []}), encoding="utf-8")
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.edit = lambda doc, ops: doc
    production.state = {"score": "s.score.json", "song": {"file": "song.mp3"}}
    return production


def test_a_failed_receipt_is_exported_twice_and_the_file_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", _refuse_sleep)
    exported: list[str] = []
    receipts = iter([
        {"receipt": {"status": "failed", "artifacts": []}, "task": {"status": "failed"}},
        {"receipt": {"status": "completed", "artifacts": [{"name": "cover.mp4"}]}, "task": {"status": "completed"}},
    ])

    def mcp(tool, arguments):
        if tool == "scenes.video2d.export":
            exported.append(arguments["input"]["document"]["name"])
            return {"receipt": {"commandId": arguments["intent_id"]}}
        if tool == "scenes.video2d.export.receipt":
            return next(receipts)
        raise AssertionError(tool)

    production = _production(tmp_path, mcp)
    shot = {"key": "cover", "kind": "still", "still": "/cover.png", "i": 0, "t0": 0.0, "t1": 4.0}
    production.scenes({"shots": []}, [shot])
    assert exported == ["cover", "cover"]
    assert production.state["scenes"]["cover"]["file"] == "cover.mp4"
    assert production.state.get("status") != "failed"


def test_two_failures_set_scene_export_failed_and_skip_montage(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", _refuse_sleep)
    calls: list[str] = []
    exported: list[str] = []
    receipts = iter([
        {"receipt": {"status": "failed", "artifacts": []}, "task": {"status": "failed"}},
        {"receipt": {"status": "cancelled", "artifacts": []}, "task": {"status": "cancelled"}},
        {"receipt": {"status": "queued", "artifacts": []}, "task": None},
        {"receipt": {"status": "failed", "artifacts": []}, "task": {"status": "failed"}},
    ])

    def mcp(tool, arguments):
        calls.append(tool)
        if tool == "scenes.video2d.export":
            exported.append(arguments["input"]["document"]["name"])
            return {"receipt": {"commandId": arguments["intent_id"]}}
        if tool == "scenes.video2d.export.receipt":
            return next(receipts)
        if tool == "montages.save":
            return {"result": {"file": "out.montage.json"}}
        return {"result": {}}

    production = _production(tmp_path, mcp)
    for name in ("song", "analyze", "cast", "frames", "clips"):
        setattr(production, name, lambda *args, **kwargs: None)
    spec = {"title": "t", "song": {"lyrics": "a", "caption": "b", "duration": 10, "bpm": 100}, "style": {},
            "shots": [{"key": "b", "kind": "still", "still": "/b.png", "t0": 0},
                      {"key": "a", "kind": "still", "still": "/a.png", "t0": 2}]}
    production.run(spec)
    assert exported == ["b", "a", "b", "a"]
    assert production.state["status"] == "failed"
    assert production.state["error"] == "scene_export_failed: a, b"
    assert "montages.save" not in calls


def test_stale_final_does_not_complete_a_failed_retake(tmp_path, monkeypatch):
    """The runbook calls production.run again after review. A leftover final.mp4
    must not mark that retake completed or delete discarded takes."""
    monkeypatch.setattr(time, "sleep", _refuse_sleep)
    receipts = iter([
        {"receipt": {"status": "failed", "artifacts": []}, "task": {"status": "failed"}},
        {"receipt": {"status": "cancelled", "artifacts": []}, "task": {"status": "cancelled"}},
    ])

    def mcp(tool, arguments):
        if tool == "scenes.video2d.export":
            return {"receipt": {"commandId": arguments["intent_id"]}}
        if tool == "scenes.video2d.export.receipt":
            return next(receipts)
        if tool == "montages.save":
            raise AssertionError("montage must not run after scene export failed")
        return {"result": {}}

    production = _production(tmp_path, mcp)
    (tmp_path / "old-final.mp4").write_bytes(b"old")
    (tmp_path / "old-lose.mp4").write_bytes(b"lose")
    production.state.update(status="completed", final="old-final.mp4", discarded=["old-lose.mp4"])
    for name in ("song", "analyze", "cast", "frames", "clips"):
        setattr(production, name, lambda *args, **kwargs: None)
    spec = {"title": "t", "song": {"lyrics": "a", "caption": "b", "duration": 10, "bpm": 100}, "style": {},
            "shots": [{"key": "a", "kind": "still", "still": "/a.png", "t0": 0}]}
    production.run(spec)
    assert production.state["status"] == "failed"
    assert production.state["error"] == "scene_export_failed: a"
    assert production.state.get("final") == "old-final.mp4"
    assert (tmp_path / "old-final.mp4").exists()
    assert (tmp_path / "old-lose.mp4").exists()

"""Shot review, one-shot redo, and a closed LLM change plan. No GPU and no network."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routers.music_productions import create_music_productions_router
from services.music_production import Production, segments
from services.production_commands import extra_catalog, extra_handlers
from services.production_publication import publication_catalog, publication_handlers
from services.production_shot_redo import redo_shot, undo_shot
from services.production_shot_request import request_shot
from services.production_shot_review import ReviewError, set_lock, set_review, without_locked


def _score() -> dict:
    return {"duration": 20, "bpm": 120, "beat": 0.5, "recall": 0.8, "lines": [
        {"t0": 1.0, "t1": 3.0, "text": "hello night"},
        {"t0": 10.0, "t1": 12.0, "text": "cold street"},
    ]}


def _spec() -> dict:
    return {
        "title": "Night bus",
        "song": {"lyrics": "hello night", "caption": "night", "duration": 20, "bpm": 120},
        "style": {"lyric_style": {"color": "#111111"}},
        "shots": [
            {"key": "s0", "kind": "h3", "line": 0, "frame": "a face", "action": "sings", "seed": 1},
            {"key": "s1", "kind": "h3", "line": 1, "frame": "a street", "action": "walks", "seed": 2},
        ],
    }


def _build(tmp_path: Path):
    root = tmp_path / "film"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    (root / "take-a.mp4").write_bytes(b"take-a")
    (root / "take-b.mp4").write_bytes(b"take-b")
    (root / "old-frame.png").write_bytes(b"old-frame")
    (root / "score.json").write_text(json.dumps(_score()), encoding="utf-8")
    spec = _spec()
    state = {
        "status": "completed",
        "spec": spec,
        "score": "score.json",
        "montage_file": "show.montage.json",
        "frames": {"s0": "old-frame.png"},
        "clips": {
            "s0": {"file": "take-a.mp4", "qa": {"verdict": "ok"}, "url": "/api/v1/uploads/old.mp4"},
            "s1": {"file": "take-a.mp4", "qa": {"verdict": "ok"}, "url": "/api/v1/uploads/old-s1.mp4"},
        },
        "takes": {"s0": [{"file": "take-a.mp4", "take": 1}, {"file": "take-b.mp4", "take": 2}]},
        "scenes": {"s1": {"file": "old-s1.mp4", "intent": "export-s1", "fingerprint": "s1-keep"}},
        "scene_docs": {},
    }
    (root / "show.production.json").write_text(json.dumps(state), encoding="utf-8")
    (root / "show.shots.json").write_text(json.dumps({
        "version": 1, "production_id": "show", "shots": [
            {"key": "s0", "lyric": "hello night"},
            {"key": "s1", "lyric": "cold street"},
        ],
    }), encoding="utf-8")
    saved: list[dict] = []
    calls: list[str] = []
    intents: list[str] = []

    def mcp(tool: str, arguments: dict) -> dict:
        calls.append(tool)
        if tool == "generation.image":
            intents.append(str(arguments.get("intent_id")))
            (root / "frame-new.png").write_bytes(b"frame-new")
            return {"receipt": {"result": {"job_id": "job-frame"}}}
        if tool == "status":
            name = "frame-new.png" if arguments.get("job_id") == "job-frame" else "clip-new.mp4"
            return {"status": "completed", "output_files": [name]}
        if tool == "scenes.video2d.edit":
            return {"result": {"document": arguments["input"]["document"]}}
        if tool == "scenes.video2d.validate":
            return {"result": {"warnings": []}}
        if tool == "scenes.document.save":
            return {"result": {"name": "show-s0-abc.scene.json"}}
        if tool == "scenes.video2d.export":
            return {"receipt": {"commandId": "export-s0"}}
        if tool == "scenes.video2d.export.receipt":
            return {"receipt": {"artifacts": [{"name": "show-s0.mp4"}]}}
        if tool == "montages.get":
            return {"result": {"revision": 4, "montage": {"revision": 4, "clips": [
                {"id": "s0", "source": "/api/v1/file/old-s0.mp4?workspace=film", "origin": {"kind": "scene2d", "scene": "old.scene.json"}},
                {"id": "s1", "source": "/api/v1/file/old-s1.mp4?workspace=film", "origin": {"kind": "scene2d", "scene": "old-s1.scene.json"}},
            ]}}}
        if tool == "montages.save":
            saved.append(arguments["input"])
            return {"result": {"file": "show.montage.json", "revision": 5}}
        raise AssertionError(tool)

    production = Production("film", "show", workspace_dir=lambda _name: str(root), uploads_dir=lambda: str(uploads), mcp=mcp)
    return production, spec, root, saved, calls, intents


def _clip_job(root: Path, calls: list[str]):
    def clip_job(_spec, _window, _seed, _take=0):
        calls.append("clip_job")
        (root / "clip-new.mp4").write_bytes(b"clip-new")
        return "job-clip"
    return clip_job


def _files(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in root.iterdir() if path.is_file() and path.suffix in {".mp4", ".png"}}


def test_review_command_stamps_only_the_review_field(tmp_path: Path):
    _production, _spec_body, root, _saved, _calls, _intents = _build(tmp_path)
    handlers = extra_handlers(lambda _name: str(root), lambda: str(root / "uploads"), lambda: "", lambda: "")
    result = asyncio.run(handlers["production.shot.review"]({
        "version": 1, "input": {"workspace": "film", "production_id": "show", "shot": "s0", "status": "approved", "note": "good"},
    }))
    assert result["result"]["status"] == "approved"
    body = json.loads((root / "show.review.json").read_text(encoding="utf-8"))
    assert body["version"] == 1
    assert body["shots"]["s0"]["status"] == "approved"
    assert body["shots"]["s0"]["notes"][0]["text"] == "good"
    assert not (root / "show.review.json.tmp").exists()
    manifest = json.loads((root / "show.shots.json").read_text(encoding="utf-8"))
    rows = {row["key"]: row for row in manifest["shots"]}
    assert rows["s0"]["lyric"] == "hello night"
    assert rows["s0"]["review"]["status"] == "approved"
    assert "review" not in rows["s1"]
    locked = asyncio.run(handlers["production.shot.lock"]({
        "version": 1, "input": {"workspace": "film", "production_id": "show", "shot": "s0", "locked": True},
    }))
    assert locked["result"]["locked"] is True


def test_frame_redo_changes_one_shot_and_keeps_files(tmp_path: Path):
    production, spec, root, saved, calls, intents = _build(tmp_path)
    production.clip_job = _clip_job(root, calls)
    before = _files(root)
    result = redo_shot(production, spec, "s0", source="frame", frame_prompt="a warmer face", expected_revision=7)
    assert result["shot"] == "s0"
    assert spec["shots"][0]["frame"] == "a warmer face"
    assert spec["shots"][1]["frame"] == "a street"
    assert production.state["clips"]["s0"]["file"] == "clip-new.mp4"
    assert production.state["clips"]["s1"]["file"] == "take-a.mp4"
    assert production.state["scenes"]["s1"]["file"] == "old-s1.mp4"
    assert production.state["scenes"]["s1"]["fingerprint"] == "s1-keep"
    assert calls.count("scenes.video2d.export") == 1
    assert calls.count("generation.image") == 1
    assert calls.count("clip_job") == 1
    assert "-r" in intents[0]
    assert saved[0]["expected_revision"] == 7
    clips = {clip["id"]: clip for clip in saved[0]["montage"]["clips"]}
    assert clips["s0"]["origin"] == {"kind": "scene2d", "scene": "old.scene.json"}
    assert clips["s1"]["source"] == "/api/v1/file/old-s1.mp4?workspace=film"
    assert "take-a.mp4" not in production.state.get("discarded", [])
    assert "take-b.mp4" not in production.state.get("discarded", [])
    after = _files(root)
    assert after["take-a.mp4"] == before["take-a.mp4"]
    assert after["take-b.mp4"] == before["take-b.mp4"]
    assert after["old-frame.png"] == before["old-frame.png"]
    history = json.loads((root / "show.review.json").read_text(encoding="utf-8"))["shots"]["s0"]["history"]
    assert history[-1]["before"]["frame_prompt"] == "a face"
    assert history[-1]["after"]["frame_prompt"] == "a warmer face"
    undo = undo_shot(production, spec, "s0", result["history_id"])
    assert undo["restored"]["frame_prompt"] == "a face"
    assert spec["shots"][0]["frame"] == "a face"
    assert production.state["frames"]["s0"] == "old-frame.png"
    assert production.state["clips"]["s0"]["file"] == "take-a.mp4"
    kept = _files(root)
    assert kept["clip-new.mp4"] == b"clip-new"
    assert kept["old-frame.png"] == b"old-frame"
    assert kept["take-a.mp4"] == b"take-a"
    entries = json.loads((root / "show.review.json").read_text(encoding="utf-8"))["shots"]["s0"]["history"]
    assert [item["kind"] for item in entries] == ["redo", "undo"]


def test_scene_redo_does_not_call_image_or_clip_and_lock_blocks_it(tmp_path: Path):
    production, spec, root, saved, calls, _intents = _build(tmp_path)
    production.clip_job = _clip_job(root, calls)
    redo_shot(production, spec, "s0", source="scene")
    assert "generation.image" not in calls
    assert "clip_job" not in calls
    assert calls.count("scenes.video2d.export") == 1
    assert spec["shots"][1] == {"key": "s1", "kind": "h3", "line": 1, "frame": "a street", "action": "walks", "seed": 2}
    set_lock(root, "show", spec, "s0", True)
    with pytest.raises(ReviewError) as caught:
        redo_shot(production, spec, "s0", source="scene", frame_prompt="nope")
    assert caught.value.code == "shot_locked"
    assert spec["shots"][0]["frame"] == "a face"
    assert len(saved) == 1


def test_locked_shots_drop_out_of_the_runner(tmp_path: Path, monkeypatch):
    production, spec, root, _saved, _calls, _intents = _build(tmp_path)
    set_lock(root, "show", spec, "s0", True)
    kept = without_locked(production, [{"key": "s0", "kind": "h3"}, {"key": "s1", "kind": "h3"}])
    assert [item["key"] for item in kept] == ["s1"]
    seen: list[list[str]] = []

    def fake(_production, windows):
        seen.append([item.get("key") for item in windows])
        return []

    monkeypatch.setattr("services.production_shot_review.without_locked", fake)
    windows = [{"key": "s0", "kind": "h3"}, {"key": "s1", "kind": "h3"}]
    production.frames(spec, windows)
    production.clips(spec, windows)
    assert seen == [windows and ["s0", "s1"]] * 2


def test_scenes_keep_a_locked_shot_in_the_cut(tmp_path: Path):
    production, spec, root, _saved, calls, _intents = _build(tmp_path)
    set_lock(root, "show", spec, "s0", True)
    windows = [
        {**spec["shots"][0], "kind": "h3", "t0": 0.0, "t1": 4.0},
        {**spec["shots"][1], "kind": "h3", "t0": 10.0, "t1": 12.0},
    ]
    production.state.setdefault("scenes", {})["s0"] = {
        "file": "keep-s0.mp4", "dur": 1.0, "clip": "other.mp4", "fingerprint": "stale",
    }
    expected = [
        [shot["key"], start, end]
        for shot, start, end in segments(windows, production.score(), lambda key: key in production.state["clips"], [])
    ]
    production.scenes(spec, windows)
    assert production.state["segments"] == expected
    assert [row[0] for row in production.state["segments"]] == ["s0", "s1"]
    assert production.state["scenes"]["s0"]["file"] == "keep-s0.mp4"
    assert production.state["scenes"]["s0"]["fingerprint"] == "stale"
    assert calls.count("scenes.video2d.export") == 1


def _plan(changes: list, summary: str = "plan") -> str:
    return json.dumps({"summary": summary, "changes": changes})


def test_request_rejects_a_bad_plan_without_touching_another_shot(tmp_path: Path, monkeypatch):
    production, spec, root, _saved, _calls, _intents = _build(tmp_path)
    monkeypatch.setattr("services.llm_service.is_loaded", lambda: False)
    with pytest.raises(ReviewError) as missing:
        request_shot(production, spec, "s0", "delete takes and change s1")
    assert missing.value.code == "llm_unavailable"
    asked: list[str] = []

    def hostile(**kwargs):
        asked.append(kwargs["prompt"])
        return _plan([
            {"op": "note", "text": "fine"},
            {"op": "delete_takes"},
            {"op": "redo", "from": "scene", "shot": "s1"},
        ])

    with pytest.raises(ReviewError) as caught:
        request_shot(production, spec, "s0", "delete takes and change s1", apply=True, generate=hostile)
    assert caught.value.code == "plan_invalid"
    assert json.loads(asked[0])["instruction"] == "delete takes and change s1"
    assert spec["shots"][1]["frame"] == "a street"
    assert not (root / "show.review.json").exists()
    assert (root / "take-a.mp4").read_bytes() == b"take-a"
    assert (root / "take-b.mp4").read_bytes() == b"take-b"
    for bad in (
        _plan([{"op": "nope"}]),
        _plan([{"op": "note", "text": "a", "extra": True}]),
        _plan([{"op": "redo", "from": "frame", "frame_prompt": "/tmp/evil"}]),
        _plan([{"op": "redo", "from": "scene"}], summary="see /tmp/x"),
    ):
        with pytest.raises(ReviewError):
            request_shot(production, spec, "s0", "again", apply=True, generate=lambda **_kwargs: bad)
    assert not (root / "show.review.json").exists()


def test_request_previews_then_applies_a_note_and_reuses_a_clip_redo(tmp_path: Path):
    production, spec, root, _saved, calls, _intents = _build(tmp_path)
    production.clip_job = _clip_job(root, calls)

    def note(**_kwargs):
        return _plan([{"op": "note", "text": "delete takes"}], summary="keep the files")

    preview = request_shot(production, spec, "s0", "note it", apply=False, generate=note)
    assert preview["applied"] is False
    assert preview["cost_estimate"]["tokens"] is None
    assert preview["diff"][0]["text"] == "delete takes"
    assert not (root / "show.review.json").exists()
    applied = request_shot(production, spec, "s0", "note it", apply=True, generate=note)
    assert applied["applied"] is True
    assert (root / "take-a.mp4").read_bytes() == b"take-a"
    assert spec["shots"][1]["frame"] == "a street"
    notes = json.loads((root / "show.review.json").read_text(encoding="utf-8"))["shots"]["s0"]["notes"]
    assert notes[0]["text"] == "delete takes"

    def redo(**_kwargs):
        return _plan([{"op": "redo", "from": "clip"}], summary="new clip")

    first = request_shot(production, spec, "s0", "new clip", apply=True, generate=redo)
    second = request_shot(production, spec, "s0", "new clip", apply=True, generate=redo)
    assert first["reused"] is False
    assert second["reused"] is True
    assert calls.count("clip_job") == 1
    assert second["intent_id"] == first["intent_id"]
    history = json.loads((root / "show.review.json").read_text(encoding="utf-8"))["shots"]["s0"]["history"]
    assert any(str(item.get("intent_id", "")).endswith("#0") for item in history)


def test_publish_blocks_listed_shots_until_they_are_approved(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    public = tmp_path / "public"
    workspace.mkdir()
    public.mkdir()
    (workspace / "final.mp4").write_bytes(b"final")
    (workspace / "sheet.jpg").write_bytes(b"sheet")
    (workspace / "song.wav").write_bytes(b"song")
    spec = {"title": "Night", "shots": [{"key": "s0", "frame": "a", "action": "b"}, {"key": "s1", "frame": "c", "action": "d"}]}
    (workspace / "show.production.json").write_text(json.dumps({
        "status": "completed", "final": "final.mp4", "contact_sheet": "sheet.jpg",
        "song": {"file": "song.wav"}, "spec": spec,
    }), encoding="utf-8")
    (workspace / "show.shots.json").write_text(json.dumps({"version": 1, "shots": [{"key": "s0"}, {"key": "s1"}]}), encoding="utf-8")
    monkeypatch.setenv("HOCUS_PUBLICATION_ROOT", str(public))
    monkeypatch.setenv("HOCUS_PUBLICATION_BASE_URL", "http://127.0.0.1:8844")
    monkeypatch.delenv("HOCUS_PUBLICATION_SERVE", raising=False)
    handler = publication_handlers(lambda _ws: str(workspace))["production.publish"]
    arguments = {"version": 1, "input": {"workspace": "ws", "production_id": "show"}}
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handler(arguments))
    assert caught.value.detail["code"] == "review_incomplete"
    allowed = {"version": 1, "input": {**arguments["input"], "accept_unreviewed": True}}
    assert asyncio.run(handler(allowed))["status"] == "completed"
    set_review(workspace, "show", spec, "s0", "changes_requested")
    set_review(workspace, "show", spec, "s1", "approved")
    with pytest.raises(HTTPException) as still:
        asyncio.run(handler(arguments))
    assert still.value.detail["code"] == "review_incomplete"
    set_review(workspace, "show", spec, "s0", "approved")
    assert asyncio.run(handler(arguments))["status"] == "completed"
    (workspace / "show.shots.json").unlink()
    assert asyncio.run(handler({"version": 1, "input": {**arguments["input"], "slug": "older"}}))["status"] == "completed"


def test_catalog_and_rest_review(tmp_path: Path, monkeypatch):
    names = {item["name"] for item in extra_catalog()}
    assert {
        "production.shot.review", "production.shot.lock", "production.shot.redo",
        "production.shot.request", "production.shot.undo",
    } <= names
    for item in extra_catalog():
        schema = item["inputSchema"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["input"]["additionalProperties"] is False
    props = publication_catalog()[0]["inputSchema"]["properties"]["input"]["properties"]
    assert props["accept_unreviewed"]["type"] == "boolean"
    monkeypatch.setattr("services.llm_service.is_loaded", lambda: False)
    _production, _spec_body, root, _saved, _calls, _intents = _build(tmp_path)
    app = FastAPI()
    app.include_router(create_music_productions_router(
        workspace_dir=lambda name: str(root) if name == "film" else str(root / "missing"),
        uploads_dir=lambda: str(root / "uploads"),
        app_url=lambda: "http://127.0.0.1:9",
        token=lambda: "",
    ))
    client = TestClient(app)
    reviewed = client.post(
        "/api/v1/music-productions/show/shots/s0/review",
        params={"workspace": "film"}, json={"status": "approved", "note": "good"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "approved"
    detail = client.get("/api/v1/music-productions/show", params={"workspace": "film"})
    rows = {row["key"]: row for row in detail.json()["shots"]}
    assert rows["s0"]["review"]["status"] == "approved"
    denied = client.post(
        "/api/v1/music-productions/show/shots/s0/request",
        params={"workspace": "film"}, json={"instruction": "delete takes and change s1"},
    )
    assert denied.status_code == 422
    assert denied.json()["detail"] == {"code": "llm_unavailable", "message": "No app LLM is configured", "retryable": False}
    assert (root / "take-a.mp4").read_bytes() == b"take-a"

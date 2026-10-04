"""The music-production read model is not the Director /api/v1/productions catalog."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routers.music_productions import create_music_productions_router


def _client(root: Path, token: str = "") -> TestClient:
    app = FastAPI()
    app.include_router(create_music_productions_router(
        workspace_dir=lambda name: str(root) if name == "film" else str(root / "missing"),
        uploads_dir=lambda: str(root / "uploads"),
        app_url=lambda: "http://127.0.0.1:9",
        token=lambda: token,
    ))
    return TestClient(app)


def _write(root: Path) -> None:
    root.mkdir()
    (root / "uploads").mkdir()
    shots = [{"key": "s0", "lyric": "hello night", "sung": True, "takes": [{"file": "take-b.mp4", "r": 0.82}]}]
    (root / "show.shots.json").write_text(json.dumps({"version": 1, "production_id": "show", "shots": shots}), encoding="utf-8")
    (root / "show.production.json").write_text(json.dumps({
        "status": "cancelled",
        "spec": {"title": "Night bus", "song": {"duration": 20}, "shots": [{"key": "s0"}]},
        "contact_sheet": "sheet.jpg",
        "montage_file": "show.montage.json",
        "final": "show.mp4",
        "takes": {"s0": [{"file": "take-b.mp4", "r": 0.82}]},
    }), encoding="utf-8")


def test_list_and_detail_return_the_production_and_its_shots(tmp_path: Path):
    root = tmp_path / "film"
    _write(root)
    client = _client(root)
    listing = client.get("/api/v1/music-productions", params={"workspace": "film"})
    assert listing.status_code == 200
    card = listing.json()["productions"][0]
    assert card["production_id"] == "show"
    assert card["title"] == "Night bus"
    assert card["status"] == "cancelled"
    assert card["duration"] == 20
    assert card["contact_sheet"].endswith("sheet.jpg?workspace=film") or "sheet.jpg" in card["contact_sheet"]
    detail = client.get("/api/v1/music-productions/show", params={"workspace": "film"})
    assert detail.status_code == 200
    assert detail.json()["shots"] == json.loads((root / "show.shots.json").read_text(encoding="utf-8"))["shots"]
    assert detail.json()["shots"][0]["lyric"] == "hello night"


def test_use_take_of_a_missing_file_is_422_and_retake_without_mcp_is_503(tmp_path: Path):
    root = tmp_path / "film"
    _write(root)
    client = _client(root, token="token")
    missing = client.post(
        "/api/v1/music-productions/show/shots/s0/use-take",
        params={"workspace": "film"},
        json={"take_file": "take-b.mp4"},
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "take_not_found"
    denied = _client(root, token="")
    retake = denied.post("/api/v1/music-productions/show/shots/s0/retake", params={"workspace": "film"})
    assert retake.status_code == 503
    assert retake.json()["detail"]["code"] == "mcp_unavailable"


def test_shot_edits_refuse_while_the_production_thread_is_alive(tmp_path: Path):
    """Another take returns at once; a second Production.save would overwrite the live run."""
    import threading

    from services import music_production

    root = tmp_path / "film"
    _write(root)
    (root / "take-b.mp4").write_bytes(b"take")
    client = _client(root, token="token")
    hold = threading.Event()
    thread = threading.Thread(target=hold.wait, name="production-show", daemon=True)
    thread.start()
    music_production._threads["film/show"] = thread
    try:
        use_take = client.post(
            "/api/v1/music-productions/show/shots/s0/use-take",
            params={"workspace": "film"},
            json={"take_file": "take-b.mp4"},
        )
        update = client.post(
            "/api/v1/music-productions/show/shots/s0",
            params={"workspace": "film"},
            json={"camera": "camera-orbit"},
        )
        assert use_take.status_code == 409
        assert use_take.json()["detail"]["code"] == "already_running"
        assert update.status_code == 409
        assert update.json()["detail"]["code"] == "already_running"
        assert json.loads((root / "show.production.json").read_text(encoding="utf-8"))["status"] == "cancelled"
    finally:
        hold.set()
        thread.join(timeout=2)
        music_production._threads.pop("film/show", None)


def test_retake_refuses_while_a_shot_edit_holds_the_production(tmp_path: Path):
    """Use-take writes the same JSON a retake would; last save would drop one of them."""
    import asyncio

    from services import music_production
    from services.music_production import RUN, command_handlers
    from services.production_commands import occupy_edit, release_edit

    root = tmp_path / "film"
    _write(root)
    client = _client(root, token="token")
    key = occupy_edit(music_production, "film", "show")
    try:
        retake = client.post("/api/v1/music-productions/show/shots/s0/retake", params={"workspace": "film"})
        assert retake.status_code == 409
        assert retake.json()["detail"]["code"] == "already_running"
        handlers = command_handlers(lambda _name: str(root), lambda: str(root / "uploads"), lambda: "http://127.0.0.1:9", lambda: "token")
        with pytest.raises(HTTPException) as caught:
            asyncio.run(handlers[RUN]({"version": 1, "input": {"workspace": "film", "production_id": "show", "retake": ["s0"]}}))
        assert caught.value.status_code == 409
        assert caught.value.detail["code"] == "already_running"
        again = client.post(
            "/api/v1/music-productions/show/shots/s0/use-take",
            params={"workspace": "film"},
            json={"take_file": "take-b.mp4"},
        )
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "already_running"
    finally:
        release_edit(music_production, key)
        music_production._edits.pop("film/show", None)


def test_retake_of_a_locked_shot_keeps_completed_status(tmp_path: Path):
    from services.production_shot_review import record_decision

    root = tmp_path / "film"
    _write(root)
    path = root / "show.production.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["status"] = "completed"
    path.write_text(json.dumps(body), encoding="utf-8")
    record_decision(root, "show", "s0", locked=True)
    client = _client(root, token="token")
    retake = client.post("/api/v1/music-productions/show/shots/s0/retake", params={"workspace": "film"})
    assert retake.status_code == 422
    assert retake.json()["detail"]["code"] == "shot_locked"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "completed"


def test_request_without_apply_validates_the_plan_and_does_not_run_it(tmp_path: Path):
    root = tmp_path / "film"
    _write(root)
    client = _client(root, token="token")
    plan = {"summary": "note only", "changes": [{"op": "note", "text": "keep the take"}]}
    response = client.post(
        "/api/v1/music-productions/show/shots/s0/request",
        params={"workspace": "film"},
        json={"instruction": "keep it", "apply": False, "plan": plan},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is False
    assert body["plan"]["changes"][0]["text"] == "keep the take"
    assert not (root / "show.review.json").exists()


def test_request_apply_runs_the_posted_plan(tmp_path: Path):
    root = tmp_path / "film"
    _write(root)
    client = _client(root, token="token")
    plan = {"summary": "note only", "changes": [{"op": "note", "text": "keep the take"}]}
    response = client.post(
        "/api/v1/music-productions/show/shots/s0/request",
        params={"workspace": "film"},
        json={"instruction": "keep it", "apply": True, "plan": plan},
    )
    assert response.status_code == 200
    assert response.json()["applied"] is True
    notes = json.loads((root / "show.review.json").read_text(encoding="utf-8"))["shots"]["s0"]["notes"]
    assert notes == "keep the take"


def test_failed_use_take_releases_the_edit_slot(tmp_path: Path):
    from services import music_production

    root = tmp_path / "film"
    _write(root)
    client = _client(root, token="token")
    missing = client.post(
        "/api/v1/music-productions/show/shots/s0/use-take",
        params={"workspace": "film"},
        json={"take_file": "take-b.mp4"},
    )
    assert missing.status_code == 422
    assert "film/show" not in music_production._edits

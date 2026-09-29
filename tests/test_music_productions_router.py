"""The music-production read model is not the Director /api/v1/productions catalog."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
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

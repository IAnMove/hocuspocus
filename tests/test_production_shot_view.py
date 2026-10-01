"""Read-only shot view. Fixtures stand in for music, Director, Series and montage."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.production_projects import create_production_projects_router
from services.production_shot_view import shot_view
from services.story_library import read_story_library


def _write(path: Path, body: dict) -> None:
    path.write_text(json.dumps(body), encoding="utf-8")


def _production(root: Path, production_id: str, **extra) -> None:
    body = {"status": "completed", "spec": {"title": "Night bus"}, "origin": "file"}
    body.update(extra)
    _write(root / f"{production_id}.production.json", body)


def _view(root: Path, production_id: str):
    return shot_view(str(root), "film", production_id)


def _dump(view: dict) -> str:
    return json.dumps(view)


def test_music_shots_keep_the_selected_take_lyric_and_review(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1", project={"kind": "story", "id": "story-1"}, format="music_video", contact_sheet="sheet.jpg")
    _write(root / "clip1.shots.json", {"version": 1, "production_id": "clip1", "shots": [
        {"key": "s1", "start": 0, "end": 4.5, "lyric": "night bus", "clip": "take-b.mp4",
         "takes": [{"file": "take-a.mp4"}, {"file": "../secret.mp4"}, {"file": "take-b.mp4"}],
         "scene_doc": "s1.scene.json"},
        {"key": "s2", "lyric": "", "takes": [{"file": "/mnt/extras/private/nope.mp4"}]},
    ]})
    _write(root / "clip1.review.json", {"version": 1, "production_id": "clip1", "shots": {
        "s1": {"status": "approved", "locked": True, "notes": "keep the window"},
    }})

    view = _view(root, "clip1")
    assert view["project"] == {"kind": "story", "id": "story-1"}
    assert view["sources"] == ["music"]
    assert view["shot_count"] == 2
    first, second = view["shots"]
    assert first["text"] == "night bus" and first["text_kind"] == "lyric"
    assert first["duration"] == 4.5
    assert first["selected_take_id"] == "take-b.mp4"
    assert [item["file"] for item in first["takes"]] == ["take-a.mp4", "take-b.mp4"]
    assert first["review"]["status"] == "approved" and first["review"]["locked"] is True
    assert first["scene"] == {"kind": "scene2d", "id": "s1.scene.json"}
    assert second["text"] is None and second["scene"] is None and second["review"] is None
    assert second["takes"][0]["file"] == "nope.mp4"
    assert str(tmp_path) not in _dump(view)
    assert ".." not in _dump(view)
    again = _view(root, "clip1")
    assert again["shots"][0]["selected_take_id"] == first["selected_take_id"]


def test_director_clips_do_not_invent_a_lyric_and_keep_stale(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _write(root / "_director_pipeline_bus.json", {
        "pipeline_id": "bus", "production_id": "bus", "status": "completed", "title": "Bus",
        "clips": [{
            "shot_id": "c1", "video_filename": "old.mp4", "selected_video_filename": "new.mp4",
            "video_stale": True,
            "video_attempts": [{"id": "old.mp4", "filename": "old.mp4"}, {"filename": "new.mp4"}],
        }],
    })
    view = _view(root, "bus")
    shot = view["shots"][0]
    assert view["sources"] == ["director"]
    assert shot["text"] is None and shot["duration"] is None and shot["scene"] is None
    assert shot["selected_take_id"] == "new.mp4"
    assert shot["montage"] == {"stale": True}
    assert shot["review"] is None
    assert str(tmp_path) not in _dump(view)


def test_music_list_is_not_duplicated_by_a_director_snapshot(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1")
    _write(root / "clip1.shots.json", {"shots": [{"key": "s1", "lyric": "only"}]})
    _write(root / "_director_pipeline_clip1.json", {
        "pipeline_id": "clip1", "production_id": "clip1",
        "clips": [{"shot_id": "s1", "video_stale": False}, {"shot_id": "other"}],
    })
    view = _view(root, "clip1")
    assert [shot["id"] for shot in view["shots"]] == ["s1"]
    assert view["shots"][0]["text"] == "only"
    assert view["shots"][0]["montage"] == {"stale": False}
    assert "director" in view["sources"] and "music" in view["sources"]


def test_series_episode_shots_do_not_create_a_story(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "ep-prod", project={"kind": "episode", "id": "ep1"}, status="running")
    _write(root / ".series-library-v1.json", {"seriesById": {"show": {"episodesById": {"ep1": {"shots": [{
        "id": "sh1", "order": 3, "durationSeconds": 5, "sceneId": "scene_1",
        "dialogueBeats": [{"text": "hola"}, {"text": ""}],
        "action": "walks",
        "approvedAttemptId": "a2",
        "attempts": [
            {"id": "a1", "status": "failed", "outputAssetIds": ["a1.mp4"]},
            {"id": "a2", "status": "completed", "reviewDecision": "approved", "outputAssetIds": ["../a2.mp4"]},
        ],
    }]}}}}})
    view = _view(root, "ep-prod")
    shot = view["shots"][0]
    assert view["sources"] == ["series"]
    assert view["status"] == "running"
    assert shot["order"] == 3 and shot["duration"] == 5
    assert shot["text"] == "hola" and shot["text_kind"] == "dialogue"
    assert shot["selected_take_id"] == "a2"
    assert shot["takes"][1]["file"] is None
    assert shot["technical_status"] == "completed"
    assert shot["review"]["status"] == "approved"
    assert shot["scene"] == {"kind": None, "id": "scene_1"}
    assert not (root / ".story-library-v1.json").exists()
    assert read_story_library(str(root))["projects"] == {}


def test_montage_keeps_scene_kinds_and_does_not_invent_stale(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "cut", montage_file="cut.montage.json", status="completed")
    _write(root / "cut.montage.json", {"clips": [
        {"id": "wide", "source": "/api/v1/file/wide.mp4?workspace=film", "trimStart": 0, "trimEnd": 2,
         "origin": {"kind": "scene2d", "scene": "wide.scene.json", "productionId": "cut", "shotId": "wide"}},
        {"id": "close", "source": "close.mp4", "lyric": "stay",
         "origin": {"kind": "scene3d", "scene": "close.scene.json", "productionId": "cut", "shotId": "close"},
         "takes": [{"id": "t1", "source": "close.mp4"}]},
    ]})
    view = _view(root, "cut")
    wide, close = view["shots"]
    assert view["sources"] == ["montage"]
    assert wide["scene"] == {"kind": "scene2d", "id": "wide.scene.json"}
    assert wide["duration"] == 2 and wide["montage"] is None and wide["text"] is None
    assert wide["selected_take_id"] == "wide.mp4"
    assert close["scene"]["kind"] == "scene3d" and close["text"] == "stay"
    assert close["selected_take_id"] == "t1"
    assert "no_shots" not in view["limits"]


def test_missing_and_unreadable_sources_do_not_invent_shots(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "early", status="running")
    running = _view(root, "early")
    assert running["shots"] == [] and running["status"] == "running"
    assert "no_shots" in running["limits"]
    assert running["shots"] == []

    _production(root, "broken", status="failed")
    (root / "broken.shots.json").write_text("{", encoding="utf-8")
    broken = _view(root, "broken")
    assert broken["shots"] == []
    assert "shots_unreadable" in broken["limits"]
    assert _view(root, "missing") is None


def test_shot_list_is_bounded(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "long")
    _write(root / "long.shots.json", {"shots": [{"key": f"s{index}", "lyric": "x"} for index in range(230)]})
    view = _view(root, "long")
    assert view["truncated"] is True
    assert len(view["shots"]) == 200
    assert view["shot_count"] == 230
    assert "shot_list_truncated" in view["limits"]


def test_http_shots_are_read_only(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1", status="completed")
    _write(root / "clip1.shots.json", {"shots": [{"key": "s1", "lyric": "night"}]})
    app = FastAPI()
    app.include_router(create_production_projects_router(
        workspace_dir=lambda name: str(root) if name == "film" else str(tmp_path / "missing"),
    ))
    client = TestClient(app)
    found = client.get("/api/v1/production-projects/clip1/shots", params={"workspace": "film"})
    assert found.status_code == 200
    assert found.json()["shots"][0]["text"] == "night"
    assert client.get("/api/v1/production-projects/nope/shots", params={"workspace": "film"}).status_code == 404
    assert client.get("/api/v1/production-projects/clip1/shots", params={"workspace": "other"}).status_code == 404
    assert not (root / ".story-library-v1.json").exists()

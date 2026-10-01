"""Shot actions reuse the stored records. They do not render or delete takes."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.production_projects import create_production_projects_router
from services.production_shot_actions import ActionError, perform
from services.production_shot_view import shot_view
from services.story_library import read_story_library


def _write(path: Path, body: dict) -> None:
    path.write_text(json.dumps(body), encoding="utf-8")


def _production(root: Path, production_id: str, **extra) -> None:
    body = {"status": "completed", "spec": {"title": "Night bus"}, "origin": "file"}
    body.update(extra)
    _write(root / f"{production_id}.production.json", body)


def _manifest(root: Path) -> None:
    _write(root / "clip1.shots.json", {"version": 1, "production_id": "clip1", "montage": "cut.montage.json", "shots": [
        {"key": "s1", "lyric": "night bus", "clip": "take-a.mp4", "takes": [{"file": "take-a.mp4"}, {"file": "take-b.mp4"}]},
        {"key": "s2", "lyric": "stay", "clip": "s2.mp4", "takes": [{"file": "s2.mp4"}]},
    ]})
    _write(root / "cut.montage.json", {"revision": 1, "clips": [
        {"id": "s1", "source": "old-export.mp4"},
        {"id": "s2", "source": "s2.mp4"},
    ]})


def _act(root: Path, shot: str, body: dict):
    return perform(str(root), "film", "clip1", shot, body)


def _shot(root: Path, shot_id: str) -> dict:
    view = shot_view(str(root), "film", "clip1")
    return next(item for item in view["shots"] if item["id"] == shot_id)


def test_select_marks_one_export_stale_and_keeps_the_other_shot(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1", project={"kind": "story", "id": "story-1"})
    _manifest(root)
    (root / "take-b.mp4").write_bytes(b"take")

    selected = _act(root, "s1", {"action": "select", "take": "take-b.mp4", "expected_revision": 0})
    assert selected["applied"] is True and selected["revision"] == 1
    manifest = json.loads((root / "clip1.shots.json").read_text(encoding="utf-8"))
    first, second = manifest["shots"]
    assert first["clip"] == "take-b.mp4" and first["video_stale"] is True
    assert [item["file"] for item in first["takes"]] == ["take-a.mp4", "take-b.mp4"]
    assert second["clip"] == "s2.mp4" and "video_stale" not in second
    montage = json.loads((root / "cut.montage.json").read_text(encoding="utf-8"))
    assert montage["clips"][0]["source"] == "old-export.mp4"
    assert montage["clips"][0]["video_stale"] is True
    assert montage["clips"][1]["source"] == "s2.mp4"
    assert (root / "take-b.mp4").is_file()
    view = _shot(root, "s1")
    assert view["selected_take_id"] == "take-b.mp4" and view["montage"]["stale"] is True


def test_stale_revision_does_not_change_the_selection(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1")
    _manifest(root)
    _act(root, "s1", {"action": "select", "take": "take-b.mp4", "expected_revision": 0})
    try:
        _act(root, "s1", {"action": "select", "take": "take-a.mp4", "expected_revision": 0})
    except ActionError as error:
        assert error.code == "stale_revision"
    else:
        raise AssertionError("expected stale_revision")
    manifest = json.loads((root / "clip1.shots.json").read_text(encoding="utf-8"))
    assert manifest["shots"][0]["clip"] == "take-b.mp4"


def test_locked_shot_refuses_select_undo_and_reexport(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1")
    _manifest(root)
    locked = _act(root, "s1", {"action": "lock", "locked": True})
    assert locked["applied"] is True and locked["locked"] is True
    before = (root / "clip1.shots.json").read_text(encoding="utf-8")
    for body in (
        {"action": "select", "take": "take-b.mp4", "expected_revision": 0},
        {"action": "undo", "history_id": "missing", "expected_revision": 0},
        {"action": "reexport", "expected_revision": 0},
    ):
        try:
            _act(root, "s1", body)
        except ActionError as error:
            assert error.code == "shot_locked"
        else:
            raise AssertionError(body["action"])
    assert (root / "clip1.shots.json").read_text(encoding="utf-8") == before


def test_undo_restores_the_previous_take_and_keeps_the_file(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1")
    _manifest(root)
    (root / "take-a.mp4").write_bytes(b"a")
    (root / "take-b.mp4").write_bytes(b"b")
    _act(root, "s1", {"action": "select", "take": "take-b.mp4", "expected_revision": 0})
    history = _shot(root, "s1")["review"]["history_id"]
    restored = _act(root, "s1", {"action": "undo", "history_id": history, "expected_revision": 1})
    assert restored["applied"] is True
    manifest = json.loads((root / "clip1.shots.json").read_text(encoding="utf-8"))
    assert manifest["shots"][0]["clip"] == "take-a.mp4"
    assert "video_stale" not in manifest["shots"][0]
    assert (root / "take-a.mp4").read_bytes() == b"a"
    assert (root / "take-b.mp4").read_bytes() == b"b"
    montage = json.loads((root / "cut.montage.json").read_text(encoding="utf-8"))
    assert montage["clips"][0]["video_stale"] is False
    assert montage["clips"][0]["source"] == "old-export.mp4"


def test_undo_refuses_a_runner_history_snapshot(tmp_path: Path):
    """Catalog undo must not write a runner clip dict into shots.json."""
    from services.production_shot_review import record_decision

    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1")
    _manifest(root)
    record_decision(str(root), "clip1", "s1", snapshot={
        "frame": "f.png",
        "clip": {"file": "take-b.mp4"},
        "scene": {"file": "s.mp4"},
        "shot": {"key": "s1"},
    })
    history = _shot(root, "s1")["review"]["history_id"]
    try:
        _act(root, "s1", {"action": "undo", "history_id": history, "expected_revision": 0})
    except ActionError as error:
        assert error.code == "history_incompatible"
    else:
        raise AssertionError("expected history_incompatible")
    manifest = json.loads((root / "clip1.shots.json").read_text(encoding="utf-8"))
    assert manifest["shots"][0]["clip"] == "take-a.mp4"
    assert isinstance(manifest["shots"][0]["clip"], str)


def test_undo_after_reexport_restores_the_previous_montage_source(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1")
    _manifest(root)
    (root / "take-a.mp4").write_bytes(b"a")
    (root / "take-b.mp4").write_bytes(b"b")
    (root / "old-export.mp4").write_bytes(b"old")
    _act(root, "s1", {"action": "select", "take": "take-b.mp4", "expected_revision": 0})
    _act(root, "s1", {"action": "reexport", "expected_revision": 1})
    history = _shot(root, "s1")["review"]["history_id"]
    restored = _act(root, "s1", {"action": "undo", "history_id": history, "expected_revision": 2})
    assert restored["applied"] is True
    manifest = json.loads((root / "clip1.shots.json").read_text(encoding="utf-8"))
    montage = json.loads((root / "cut.montage.json").read_text(encoding="utf-8"))
    assert manifest["shots"][0]["clip"] == "take-b.mp4"
    assert manifest["shots"][0]["video_stale"] is True
    assert manifest["shots"][1]["clip"] == "s2.mp4"
    assert montage["clips"][0]["source"] == "old-export.mp4"
    assert montage["clips"][0]["video_stale"] is True
    assert montage["clips"][1]["source"] == "s2.mp4"
    assert (root / "old-export.mp4").read_bytes() == b"old"
    assert (root / "take-b.mp4").read_bytes() == b"b"


def test_reexport_updates_only_the_selected_montage_clip(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1")
    _manifest(root)
    _act(root, "s1", {"action": "select", "take": "take-b.mp4", "expected_revision": 0})
    exported = _act(root, "s1", {"action": "reexport", "expected_revision": 1})
    assert exported["applied"] is True
    manifest = json.loads((root / "clip1.shots.json").read_text(encoding="utf-8"))
    montage = json.loads((root / "cut.montage.json").read_text(encoding="utf-8"))
    assert manifest["shots"][0]["video_stale"] is False
    assert montage["clips"][0]["source"] == "take-b.mp4" and montage["clips"][0]["video_stale"] is False
    assert montage["clips"][1]["source"] == "s2.mp4"
    assert manifest["shots"][1]["clip"] == "s2.mp4"
    assert _shot(root, "s1")["montage"]["stale"] is False


def test_request_without_apply_does_not_change_the_shot(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1")
    _manifest(root)
    before = (root / "clip1.shots.json").read_text(encoding="utf-8")
    preview = _act(root, "s1", {"action": "request", "plan": {"action": "select", "take": "take-b.mp4"}, "apply": False})
    assert preview == {"plan": {"action": "select", "take": "take-b.mp4"}, "applied": False}
    assert (root / "clip1.shots.json").read_text(encoding="utf-8") == before
    try:
        _act(root, "s1", {"action": "regenerate", "expected_revision": 0})
    except ActionError as error:
        assert error.code == "regenerate_needs_runner"
    else:
        raise AssertionError("regenerate")
    assert (root / "clip1.shots.json").read_text(encoding="utf-8") == before


def test_apply_runs_the_shown_plan(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1")
    _manifest(root)
    applied = _act(root, "s1", {
        "action": "request",
        "apply": True,
        "expected_revision": 0,
        "plan": {"action": "select", "take": "take-b.mp4"},
    })
    assert applied["applied"] is True
    assert applied["plan"] == {"action": "select", "take": "take-b.mp4"}
    manifest = json.loads((root / "clip1.shots.json").read_text(encoding="utf-8"))
    assert manifest["shots"][0]["clip"] == "take-b.mp4"


def test_series_selection_is_refused_and_review_does_not_rewrite_the_episode(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "epshot", project={"kind": "episode", "id": "ep1"})
    library = {"episodes": [{"id": "ep1", "shots": [{"id": "s1", "action": "wait", "attempts": []}]}]}
    _write(root / ".series-library-v1.json", library)
    before = (root / ".series-library-v1.json").read_text(encoding="utf-8")
    try:
        perform(str(root), "film", "epshot", "s1", {"action": "select", "take": "take-b.mp4", "expected_revision": 0})
    except ActionError as error:
        assert error.code == "origin_unsupported"
    else:
        raise AssertionError("series select")
    assert (root / ".series-library-v1.json").read_text(encoding="utf-8") == before
    reviewed = perform(str(root), "film", "epshot", "s1", {"action": "review", "status": "approved"})
    assert reviewed["applied"] is True and reviewed["status"] == "approved"
    assert json.loads((root / ".series-library-v1.json").read_text(encoding="utf-8")) == library
    assert read_story_library(str(root))["projects"] == {}


def test_director_selection_marks_stale_without_dropping_attempts(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _write(root / "_director_pipeline_bus.json", {
        "pipeline_id": "bus", "production_id": "bus", "status": "completed", "title": "Bus",
        "clips": [{
            "shot_id": "c1", "video_filename": "old.mp4", "selected_video_filename": "old.mp4",
            "video_attempts": [{"filename": "old.mp4"}, {"filename": "new.mp4"}],
        }],
    })
    selected = perform(str(root), "film", "bus", "c1", {"action": "select", "take": "new.mp4", "expected_revision": 0})
    assert selected["applied"] is True
    body = json.loads((root / "_director_pipeline_bus.json").read_text(encoding="utf-8"))
    clip = body["clips"][0]
    assert clip["selected_video_filename"] == "new.mp4"
    assert clip["video_filename"] == "old.mp4" and clip["video_stale"] is True
    assert len(clip["video_attempts"]) == 2
    exported = perform(str(root), "film", "bus", "c1", {"action": "reexport", "expected_revision": 1})
    assert exported["applied"] is True
    clip = json.loads((root / "_director_pipeline_bus.json").read_text(encoding="utf-8"))["clips"][0]
    assert clip["video_filename"] == "new.mp4" and clip["video_stale"] is False
    view = shot_view(str(root), "film", "bus")
    assert view["shots"][0]["selected_take_id"] == "new.mp4"
    assert view["shots"][0]["montage"]["stale"] is False


def test_http_action_reports_a_stale_revision(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    _production(root, "clip1")
    _manifest(root)
    app = FastAPI()
    app.include_router(create_production_projects_router(workspace_dir=lambda name: str(root) if name == "film" else str(tmp_path / "missing")))
    client = TestClient(app)
    denied = client.post("/api/v1/production-projects/clip1/shots/s1", json={
        "workspace": "film", "action": "select", "take": "take-b.mp4", "expected_revision": 4,
    })
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "stale_revision"
    assert json.loads((root / "clip1.shots.json").read_text(encoding="utf-8"))["shots"][0]["clip"] == "take-a.mp4"
    assert not (root / ".story-library-v1.json").exists()

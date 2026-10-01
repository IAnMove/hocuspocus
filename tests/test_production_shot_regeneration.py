import json

import pytest

from services.production_shot_actions import ActionError, perform
from services.production_shot_regeneration import regeneration_target
from services.production_shot_review import record_decision


def fixture(root, kind="h3"):
    state = {"status": "completed", "spec": {"title": "Clip", "shots": [{"key": "s1", "kind": kind}]}}
    (root / "clip1.production.json").write_text(json.dumps(state))
    manifest = {"revision": 3, "shots": [{"key": "s1", "clip": "old.mp4", "takes": [{"file": "old.mp4"}]}]}
    (root / "clip1.shots.json").write_text(json.dumps(manifest))


@pytest.mark.parametrize("kind,mode", [("h3", "clip"), ("scene3d", "scene"), ("still", "frame")])
def test_regeneration_selects_the_existing_single_shot_operation_without_writing(tmp_path, kind, mode):
    fixture(tmp_path, kind)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    result = perform(str(tmp_path), "film", "clip1", "s1", {"action": "regenerate", "expected_revision": 3})
    assert result["applied"] is False
    assert result["regeneration"] == {"executor": "http", "path": "/api/v1/music-productions/clip1/shots/s1/redo?workspace=film",
                                      "body": {"from": mode, "shared_review": {"production_id": "clip1", "shot_id": "s1", "expected_revision": 3}}}
    assert {path.name: path.read_bytes() for path in tmp_path.glob("*.json")} == before


def test_regeneration_rejects_lock_and_stale_revision(tmp_path):
    fixture(tmp_path)
    with pytest.raises(ActionError, match="stale_revision"):
        regeneration_target(str(tmp_path), "film", "clip1", "s1", {"expected_revision": 2})
    record_decision(str(tmp_path), "clip1", "s1", locked=True)
    with pytest.raises(ActionError, match="shot_locked"):
        regeneration_target(str(tmp_path), "film", "clip1", "s1", {"expected_revision": 3})


def test_generator_rechecks_a_lock_added_after_the_target_was_prepared(tmp_path):
    from fastapi import HTTPException
    from services.production_shot_regeneration import guard_shared_regeneration
    fixture(tmp_path)
    prepared = regeneration_target(str(tmp_path), "film", "clip1", "s1", {"expected_revision": 3})
    record_decision(str(tmp_path), "clip1", "s1", locked=True)
    with pytest.raises(HTTPException) as error:
        guard_shared_regeneration(str(tmp_path), "film", prepared["regeneration"]["body"])
    assert error.value.detail["code"] == "shot_locked"


@pytest.mark.parametrize("endpoint,mode", [
    ("/api/v1/music-productions/clip1/shots/s1/redo", "clip"),
    ("/api/v1/music-productions/clip1/shots/s2/redo", "clip"),
    ("/api/v1/music-productions/clip1/shots/s1/redo", "scene"),
])
def test_guard_cannot_authorize_another_shot_or_generation_mode(tmp_path, endpoint, mode):
    from fastapi import HTTPException
    from services.production_shot_regeneration import guard_shared_regeneration
    fixture(tmp_path)
    body = regeneration_target(str(tmp_path), "film", "clip1", "s1", {"expected_revision": 3})["regeneration"]["body"]
    body["from"] = mode
    if endpoint.endswith("/s1/redo") and mode == "clip":
        guard_shared_regeneration(str(tmp_path), "film", body, endpoint)
    else:
        with pytest.raises(HTTPException) as error:
            guard_shared_regeneration(str(tmp_path), "film", body, endpoint)
        assert error.value.detail["code"] == "invalid_request"


def test_director_identity_resolves_to_exact_clip_index(tmp_path):
    from services.production_run import adapt_pipeline_record
    state = {"pipeline_id": "abc123", "workspace": "film", "status": "completed", "revision": 2,
             "clips": [{"shot_id": "s1", "video_filename": "a.mp4"}, {"shot_id": "s2", "video_filename": "b.mp4"}]}
    identifier = adapt_pipeline_record(state)["production"]["id"]
    state["production_id"] = identifier
    (tmp_path / "_director_pipeline_abc123.json").write_text(json.dumps(state))
    result = regeneration_target(str(tmp_path), "film", identifier, "s2", {"expected_revision": 2})
    assert result["regeneration"]["path"] == "/api/v1/director/pipelines/abc123/clips/1/rerun-video"


def test_series_regeneration_targets_only_one_generated_shot(tmp_path):
    from services.production_generation_link import attach_episode
    from services.series_library import create_series_project, create_series_episode, write_series_library
    series = create_series_project("film", title="Series")
    episode = create_series_episode(series)
    episode["script"] = [{"id": "scene1", "locationId": ""}]
    episode["shots"] = [{"id": "s1", "sceneId": "scene1", "productionMethod": "generated_video", "order": 1}]
    series["episodesById"][episode["id"]] = episode
    write_series_library(str(tmp_path), {"workspaceId": "film", "seriesById": {series["id"]: series},
                                      "seriesOrder": [series["id"]]}, "film")
    registered = attach_episode(str(tmp_path), "film", episode, {})
    result = regeneration_target(str(tmp_path), "film", registered["production_id"], "s1", {"expected_revision": 0})
    assert result["regeneration"]["body"]["shotIds"] == ["s1"]
    assert result["regeneration"]["body"]["mode"] == "selected"


def test_publishing_a_retake_preserves_the_other_shot_and_montage(tmp_path):
    from types import SimpleNamespace
    from services.production_shot_regeneration import publish_music_regeneration
    fixture(tmp_path)
    path = tmp_path / "clip1.shots.json"
    document = json.loads(path.read_text())
    other = {"key": "s2", "clip": "other.mp4", "takes": [{"file": "other.mp4"}]}
    document["shots"].append(other)
    path.write_text(json.dumps(document))
    montage = tmp_path / "cut.montage.json"
    montage.write_text('{"clips":[{"id":"s1","source":"old.mp4"}]}')
    before = montage.read_bytes()
    production = SimpleNamespace(root=tmp_path, id="clip1", state={
        "clips": {"s1": {"file": "new.mp4"}}, "takes": {"s1": [{"file": "new.mp4"}]}})
    publish_music_regeneration(production, "s1", "clip")
    saved = json.loads(path.read_text())
    assert saved["revision"] == 4
    assert saved["shots"][0]["clip"] == "new.mp4"
    assert [take["file"] for take in saved["shots"][0]["takes"]] == ["old.mp4", "new.mp4"]
    assert saved["shots"][0]["video_stale"] is True
    assert saved["shots"][1] == other
    assert montage.read_bytes() == before


def test_frame_regeneration_refreshes_the_still_preview_and_marks_export_stale(tmp_path):
    from types import SimpleNamespace
    from services.production_shot_regeneration import publish_music_regeneration
    from services.production_shot_view import shot_view
    fixture(tmp_path, "still")
    document = {"revision": 3, "shots": [{"key": "s1", "kind": "still", "start_frame": "old.png"}]}
    (tmp_path / "clip1.shots.json").write_text(json.dumps(document))
    publish_music_regeneration(SimpleNamespace(root=tmp_path, id="clip1", state={"frames": {"s1": "new.png"}}), "s1", "frame")
    shot = shot_view(str(tmp_path), "film", "clip1")["shots"][0]
    assert shot["selected_take_id"] == "new.png"
    assert shot["montage"]["stale"] is True


def test_imported_clip_has_no_regeneration_engine(tmp_path):
    from services.production_shot_view import shot_view
    fixture(tmp_path, "clip")
    document = {"revision": 3, "shots": [{"key": "s1", "kind": "clip", "clip": "old.mp4"}]}
    (tmp_path / "clip1.shots.json").write_text(json.dumps(document))
    shot = shot_view(str(tmp_path), "film", "clip1")["shots"][0]
    assert next(action for action in shot["actions"] if action["action"] == "regenerate")["enabled"] is False
    with pytest.raises(ActionError, match="imported clip"):
        regeneration_target(str(tmp_path), "film", "clip1", "s1", {"expected_revision": 3})

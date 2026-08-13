import copy
import json
from pathlib import Path
import re

import pytest

from services.series_library import (
    SeriesConflictError,
    append_shot_render_attempt,
    approve_episode_render_attempts,
    approve_shot_render_attempt,
    commit_canon_delta,
    create_series_episode,
    create_series_project,
    duplicate_series_project,
    import_story_project,
    normalize_series_library,
    read_series_library,
    reject_shot_render_attempt,
    series_for_episode_snapshot,
    validate_series_asset_uri,
    write_series_library,
    update_shot_render_attempt,
)


EXAMPLE = Path(__file__).parents[1] / "docs" / "series-lab" / "example-series-library-v1.json"


def example_library():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_constructors_produce_ids_defaults_and_frozen_snapshot():
    series = create_series_project("default")
    episode = create_series_episode(series)
    assert re.fullmatch(r"series_[0-9a-f]{32}", series["id"])
    assert series["provider"]["videoModel"] == "minimax_h3_legacy"
    assert series["provider"]["useGlobalProfile"] is True
    assert series["provider"]["videoSettings"]["orientation"] == "landscape"
    assert re.fullmatch(r"episode_[0-9a-f]{32}", episode["id"])
    assert episode["canonSnapshot"]["revision"] == series["canon"]["revision"]
    series["canon"]["worldSummary"] = "Changed later"
    assert episode["canonSnapshot"]["worldSummary"] == ""


def test_episode_snapshot_freezes_entity_definitions_references_and_provider():
    series = create_series_project("default")
    series["characters"] = [{
        "id": "char_a", "name": "Ada", "approval": "approved",
        "referenceAssetIds": ["asset_a"], "wardrobeVariants": [], "currentState": {},
    }]
    series["locations"] = [{
        "id": "loc_a", "name": "Lab", "approval": "approved",
        "referenceAssetIds": [], "variants": [], "currentState": {},
    }]
    series["assets"] = {
        "asset_a": {
            "id": "asset_a", "workspaceId": "default", "kind": "image",
            "uri": "assets/series/ada.png", "ownerType": "character", "ownerId": "char_a",
            "isDerivedThumbnail": False, "metadata": {},
        },
    }
    episode = create_series_episode(series)
    assert episode["canonSnapshot"]["characters"][0]["name"] == "Ada"
    assert episode["canonSnapshot"]["assets"]["asset_a"]["uri"] == "assets/series/ada.png"
    series["characters"][0]["name"] = "Changed later"
    series["assets"]["asset_a"]["uri"] = "assets/series/changed.png"
    frozen = series_for_episode_snapshot(series, episode)
    assert frozen["characters"][0]["name"] == "Ada"
    assert frozen["assets"]["asset_a"]["uri"] == "assets/series/ada.png"


def test_example_normalizes_and_preserves_unknown_fields():
    value = example_library()
    value["futureRoot"] = {"kept": True}
    project = value["seriesById"]["series_signal"]
    project["futureField"] = "kept"
    normalized = normalize_series_library(value, "default")
    result = normalized["seriesById"]["series_signal"]
    assert normalized["futureRoot"] == {"kept": True}
    assert result["futureField"] == "kept"
    assert result["characters"][0]["referenceAssetIds"] == ["asset_mara"]
    assert result["episodesById"]["episode_1"]["canonSnapshot"]["revision"] == 1


def test_workspace_is_authoritative_and_isolated(tmp_path):
    value = example_library()
    value["workspaceId"] = "other"
    with pytest.raises(ValueError, match="does not match"):
        write_series_library(str(tmp_path), value, "default")

    value["workspaceId"] = "default"
    stored = write_series_library(str(tmp_path), value, "default")
    assert read_series_library(str(tmp_path), "default") == stored
    assert (tmp_path / ".series-library-v1.json").is_file()


@pytest.mark.parametrize("uri", [
    "../secret.png", "outputs/../secret.png", "/tmp/secret.png", "data:image/png;base64,x",
    "http://example.com/file.png", "assets\\secret.png",
])
def test_asset_uri_rejects_unsafe_sources(uri):
    with pytest.raises(ValueError):
        validate_series_asset_uri(uri)


def test_episode_order_repair_is_deterministic():
    value = example_library()
    series = value["seriesById"]["series_signal"]
    clone = copy.deepcopy(series["episodesById"]["episode_1"])
    clone.update({"id": "episode_2", "number": 2})
    clone["script"] = []
    clone["shots"] = []
    series["episodesById"]["episode_2"] = clone
    series["seasons"][0]["episodeOrder"] = ["missing", "episode_1", "episode_1"]
    first = normalize_series_library(value, "default")
    second = normalize_series_library(first, "default")
    assert first["seriesById"]["series_signal"]["seasons"][0]["episodeOrder"] == [
        "episode_1", "episode_2",
    ]
    assert second == first


def test_duplicate_live_graph_ids_are_rejected_before_persistence():
    value = example_library()
    series = value["seriesById"]["series_signal"]
    duplicate = copy.deepcopy(series["characters"][0])
    series["characters"].append(duplicate)

    with pytest.raises(ValueError, match="duplicate id"):
        normalize_series_library(value, "default")


def test_legacy_shot_dialogue_ids_are_migrated_away_from_script_ids():
    value = example_library()

    normalized = normalize_series_library(value, "default")
    episode = normalized["seriesById"]["series_signal"]["episodesById"]["episode_1"]
    script_ids = {
        line["id"] for scene in episode["script"] for line in scene.get("dialogue", [])
    }
    shot_ids = {
        line["id"] for shot in episode["shots"] for line in shot.get("dialogueBeats", [])
    }

    assert script_ids.isdisjoint(shot_ids)


def test_unknown_shot_scene_is_rejected_during_library_normalization():
    value = example_library()
    shot = value["seriesById"]["series_signal"]["episodesById"]["episode_1"]["shots"][0]
    shot["sceneId"] = "missing_scene"

    with pytest.raises(ValueError, match="uses unknown scene"):
        normalize_series_library(value, "default")


@pytest.mark.parametrize(("mutate", "message"), [
    (
        lambda project: project["relationships"][0].update({"fromCharacterId": "missing_character"}),
        "unknown character",
    ),
    (
        lambda project: project["episodesById"]["episode_1"]["script"][0].update(
            {"locationId": "missing_location"}
        ),
        "unknown location",
    ),
    (
        lambda project: project["episodesById"]["episode_1"]["shots"][0].update(
            {"continuityFromShotId": "missing_shot"}
        ),
        "unknown shot",
    ),
    (
        lambda project: project["episodesById"]["episode_1"]["shots"][0]["attempts"][0].update(
            {"outputAssetIds": ["missing_asset"]}
        ),
        "unknown asset",
    ),
])
def test_broken_live_graph_references_are_rejected(mutate, message):
    value = example_library()
    mutate(value["seriesById"]["series_signal"])

    with pytest.raises(ValueError, match=message):
        normalize_series_library(value, "default")


def test_saved_shot_duration_uses_the_same_h3_contract_as_rendering():
    value = example_library()
    shot = value["seriesById"]["series_signal"]["episodesById"]["episode_1"]["shots"][0]
    shot["durationSeconds"] = 8

    normalized = normalize_series_library(value, "default")

    saved = normalized["seriesById"]["series_signal"]["episodesById"]["episode_1"]["shots"][0]
    assert saved["durationSeconds"] == 10


def test_story_import_is_new_draft_with_provenance_and_no_source_mutation():
    story = {
        "id": "story-1", "title": "Source", "premise": "A premise", "allowClipText": True,
        "world": {"summary": "World", "rules": ["No magic"], "locations": []},
        "characters": [], "relationships": [], "assets": {},
        "productions": [{"id": "old-film"}],
    }
    original = copy.deepcopy(story)
    series = import_story_project(story, "default")
    assert story == original
    assert series["id"].startswith("series_")
    assert series["importSource"]["sourceStoryId"] == "story-1"
    assert series["importSource"]["historicalProductionIds"] == ["old-film"]
    assert series["allowClipText"] is True
    assert series["characters"] == []


def test_duplicate_does_not_copy_episode_attempt_history():
    series = normalize_series_library(example_library(), "default")["seriesById"]["series_signal"]
    duplicate = duplicate_series_project(series)
    assert duplicate["id"] != series["id"]
    assert duplicate["episodesById"] == {}
    assert duplicate["seasons"][0]["episodeOrder"] == []


def test_canon_delta_requires_explicit_accept_and_increments_once():
    series = normalize_series_library(example_library(), "default")["seriesById"]["series_signal"]
    untouched = commit_canon_delta(series, "episode_1", {}, 1)
    assert untouched["canon"]["revision"] == 1
    assert untouched["canon"]["currentFacts"] == []

    committed = commit_canon_delta(series, "episode_1", {"fact_signal_human": "accepted"}, 1)
    assert committed["canon"]["revision"] == 2
    assert committed["canon"]["currentFacts"][0]["status"] == "approved"
    assert series["canon"]["revision"] == 1


def test_canon_optimistic_revision_conflict_and_old_snapshot_survives():
    series = normalize_series_library(example_library(), "default")["seriesById"]["series_signal"]
    with pytest.raises(SeriesConflictError, match="revision changed"):
        commit_canon_delta(series, "episode_1", {"fact_signal_human": "accepted"}, 0)
    updated = commit_canon_delta(series, "episode_1", {"fact_signal_human": "accepted"}, 1)
    assert updated["episodesById"]["episode_1"]["canonSnapshot"]["revision"] == 1
    assert updated["canon"]["revision"] == 2


def test_shot_retry_appends_attempt_and_approval_is_explicit():
    shot = normalize_series_library(example_library(), "default")["seriesById"]["series_signal"][
        "episodesById"
    ]["episode_1"]["shots"][1]
    first, attempt = append_shot_render_attempt(
        shot, manifest={"strategy": "references"}, model="minimax_h3_ref2va",
        settings={"durationSeconds": 8}, seed=42,
    )
    second, retry = append_shot_render_attempt(
        first, manifest={"strategy": "references"}, model="minimax_h3_ref2va",
        settings={"durationSeconds": 8}, seed=42, retry_count=1,
    )
    assert len(second["attempts"]) == len(shot["attempts"]) + 2
    assert attempt["id"] != retry["id"]
    assert re.fullmatch(r"attempt_[0-9a-f]{32}", attempt["id"])
    assert re.fullmatch(r"attempt_[0-9a-f]{32}", retry["id"])
    assert "approvedAttemptId" not in second
    with pytest.raises(ValueError, match="completed"):
        approve_shot_render_attempt(second, retry["id"])
    completed = update_shot_render_attempt(
        second, retry["id"], status="completed", outputAssetIds=["asset_video"],
        completedAt="2026-08-09T00:00:00Z", elapsedMs=1234,
    )
    approved = approve_shot_render_attempt(completed, retry["id"])
    assert approved["approvedAttemptId"] == retry["id"]
    assert approved["attempts"][-1]["reviewDecision"] == "approved"
    rejected = reject_shot_render_attempt(approved, retry["id"])
    assert "approvedAttemptId" not in rejected
    assert rejected["attempts"][-1]["reviewDecision"] == "rejected"
    assert approved["attempts"][0:len(shot["attempts"])] == shot["attempts"]


def test_bulk_attempt_approval_is_atomic_and_rejects_duplicate_shots():
    shot_a = {
        "id": "shot-a", "attempts": [{
            "id": "attempt-a", "status": "completed", "outputAssetIds": ["asset-a"],
        }],
    }
    shot_b = {
        "id": "shot-b", "attempts": [{
            "id": "attempt-b", "status": "failed", "outputAssetIds": [],
        }],
    }
    episode = {"id": "episode-1", "shots": [shot_a, shot_b]}
    original = copy.deepcopy(episode)

    with pytest.raises(ValueError, match="Only a completed"):
        approve_episode_render_attempts(episode, [
            {"shotId": "shot-a", "attemptId": "attempt-a"},
            {"shotId": "shot-b", "attemptId": "attempt-b"},
        ])
    assert episode == original

    approved = approve_episode_render_attempts(episode, [
        {"shotId": "shot-a", "attemptId": "attempt-a"},
    ])
    assert approved["shots"][0]["approvedAttemptId"] == "attempt-a"
    assert "approvedAttemptId" not in episode["shots"][0]

    with pytest.raises(ValueError, match="more than once"):
        approve_episode_render_attempts(episode, [
            {"shotId": "shot-a", "attemptId": "attempt-a"},
            {"shotId": "shot-a", "attemptId": "attempt-a"},
        ])

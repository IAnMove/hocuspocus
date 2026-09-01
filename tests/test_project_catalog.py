from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.project_catalog import (
    ProjectCatalogError,
    adapt_character_kit_library,
    adapt_project_file,
    adapt_series_library,
    adapt_story_library,
    scan_project_catalog,
    validate_project_record,
)


def test_story_adapter_preserves_identity_subtype_and_active_state():
    records = adapt_story_library({
        "version": 2,
        "revision": 7,
        "activeId": "story-1",
        "projects": {
            "story-1": {
                "id": "story-1",
                "title": "The server sings",
                "projectType": "music_video",
                "createdAt": "2026-09-01T01:00:00Z",
                "updatedAt": "2026-09-01T02:00:00Z",
            },
        },
    }, "night")

    assert records[0]["id"] == "story-1"
    assert records[0]["kind"] == "story"
    assert records[0]["subtype"] == "music_video"
    assert records[0]["metadata"] == {"active": True, "library_revision": 7}
    assert records[0]["sources"][0]["key"] == "story:story-1"


def test_series_adapter_exposes_series_and_episode_parent_identity():
    records = adapt_series_library({
        "schema": "series-library",
        "version": 1,
        "workspaceId": "night",
        "seriesOrder": ["series-1"],
        "seriesById": {
            "series-1": {
                "id": "series-1",
                "title": "Night Shift",
                "revision": 3,
                "seasons": [],
                "episodesById": {
                    "episode-1": {
                        "id": "episode-1",
                        "title": "The lost ping",
                        "seasonId": "season-1",
                    },
                },
            },
        },
    }, "night")

    by_id = {item["id"]: item for item in records}
    assert by_id["series-1"]["metadata"]["episode_count"] == 1
    assert by_id["episode-1"]["parent"] == {"kind": "series", "id": "series-1"}
    assert by_id["episode-1"]["subtype"] == "series_episode"


def test_legacy_scene_identity_is_deterministic_without_rewriting_source():
    scene = {"version": 1, "name": "Server cathedral", "layers": [{}, {}]}
    first = adapt_project_file("cathedral.scene.json", scene, "default", modified_at=10)
    second = adapt_project_file("cathedral.scene.json", scene, "default", modified_at=20)

    assert first["id"] == second["id"]
    assert first["id"].startswith("project_legacy_")
    assert first["kind"] == "scene3d"
    assert first["revision"] is None
    assert first["metadata"]["layer_count"] == 2


def test_character_kit_adapter_indexes_the_durable_server_library():
    records = adapt_character_kit_library({
        "version": 1,
        "revision": 4,
        "activeId": "magda",
        "kits": {
            "magda": {
                "version": 1,
                "id": "magda",
                "name": "Magda Root",
                "style": "cutout",
                "poses": {},
                "mouth": {},
                "eyes": {},
                "anchors": {},
                "provenance": [],
            },
        },
    }, "night")

    assert records[0]["id"] == "magda"
    assert records[0]["kind"] == "character_kit"
    assert records[0]["subtype"] == "cutout"
    assert records[0]["metadata"] == {
        "active": True, "library_revision": 4, "pose_count": 0,
    }


def test_catalog_indexes_existing_stores_without_exposing_host_paths(tmp_path: Path):
    root = tmp_path / "outputs"
    root.mkdir()
    (root / ".story-library-v1.json").write_text(json.dumps({
        "version": 2, "revision": 1, "activeId": "story-1",
        "projects": {"story-1": {"id": "story-1", "title": "Story"}},
    }), encoding="utf-8")
    (root / ".series-library-v1.json").write_text(json.dumps({
        "schema": "series-library", "version": 1, "workspaceId": "default",
        "seriesOrder": [], "seriesById": {},
    }), encoding="utf-8")
    (root / "comic.comic.json").write_text(json.dumps({
        "id": "comic-1", "title": "Comic", "version": 2, "pages": [],
    }), encoding="utf-8")
    (root / "scene.scene.json").write_text(json.dumps({
        "version": 1, "name": "Scene", "layers": [],
    }), encoding="utf-8")

    result = scan_project_catalog([{"workspace_id": "default", "path": str(root)}])

    assert result["total"] == 3
    assert {item["kind"] for item in result["projects"]} == {"story", "comic", "scene3d"}
    assert str(tmp_path) not in json.dumps(result)
    assert result["warnings"] == []


def test_catalog_merges_same_project_across_workspace_sources(tmp_path: Path):
    roots = []
    for workspace in ("alpha", "beta"):
        directory = tmp_path / workspace
        directory.mkdir()
        (directory / ".story-library-v1.json").write_text(json.dumps({
            "version": 2, "revision": 1, "activeId": "shared",
            "projects": {"shared": {"id": "shared", "title": "Shared story"}},
        }), encoding="utf-8")
        roots.append({"workspace_id": workspace, "path": str(directory)})

    result = scan_project_catalog(roots)

    assert result["total"] == 1
    assert result["projects"][0]["workspace_ids"] == ["alpha", "beta"]
    assert len(result["projects"][0]["sources"]) == 2


def test_catalog_filters_searches_paginates_and_rejects_unknown_kind(tmp_path: Path):
    root = tmp_path / "outputs"
    root.mkdir()
    for index in range(3):
        (root / f"comic-{index}.comic.json").write_text(json.dumps({
            "id": f"comic-{index}", "title": f"Server comic {index}",
            "version": 2, "pages": [],
        }), encoding="utf-8")

    result = scan_project_catalog(
        [{"workspace_id": "default", "path": str(root)}],
        search="server", kind="comic", limit=1, offset=1,
    )
    assert result["total"] == 3
    assert len(result["projects"]) == 1
    assert validate_project_record(result["projects"][0])["kind"] == "comic"
    with pytest.raises(ProjectCatalogError, match="Unsupported project kind"):
        scan_project_catalog([], kind="magic")


def test_catalog_reports_invalid_sources_without_leaking_error_details(tmp_path: Path):
    root = tmp_path / "outputs"
    root.mkdir()
    (root / ".story-library-v1.json").write_text("not json", encoding="utf-8")

    result = scan_project_catalog([{"workspace_id": "default", "path": str(root)}])

    assert result["projects"] == []
    assert result["warnings"] == [{
        "workspace_id": "default",
        "source": ".story-library-v1.json",
        "error": "JSONDecodeError",
    }]

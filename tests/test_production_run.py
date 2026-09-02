from app.services.production_run import adapt_pipeline_record, build_production_run_catalog


def test_legacy_pipeline_splits_stable_production_and_run_identities():
    pipeline = {
        "id": "pipe-1", "pipeline_type": "music_video", "status": "running",
        "workspace": "night", "scene_description": "Server anthem", "clip_count": 5,
        "created_at": 1_700_000_000,
    }
    first = adapt_pipeline_record(pipeline)
    second = adapt_pipeline_record(pipeline)

    assert first == second
    assert first["production"]["id"].startswith("production_legacy_")
    assert first["run"]["id"].startswith("run_legacy_")
    assert first["run"]["production_id"] == first["production"]["id"]
    assert first["run"]["correlations"]["pipeline_id"] == "pipe-1"
    assert first["production"]["plan"]["clip_count"] == 5


def test_explicit_production_groups_distinct_retry_runs():
    catalog = build_production_run_catalog([
        {"id": "pipe-1", "production_id": "production-1", "run_id": "run-1", "attempt": 1, "status": "failed"},
        {"id": "pipe-2", "production_id": "production-1", "run_id": "run-2", "attempt": 2, "status": "completed"},
    ])

    assert len(catalog["productions"]) == 1
    assert catalog["productions"][0]["run_ids"] == ["run-1", "run-2"]
    assert {item["id"] for item in catalog["runs"]} == {"run-1", "run-2"}


def test_project_relationship_and_terminal_timing_are_preserved():
    adapted = adapt_pipeline_record({
        "pipeline_id": "pipe-comic", "comic_id": "comic-1", "status": "completed",
        "created_at": 1_700_000_000, "completed_at": 1_700_000_120,
        "output_files": ["movie.mp4"],
    }, "default")

    assert adapted["production"]["project"] == {"kind": "comic", "id": "comic-1"}
    assert adapted["run"]["completed_at"] == "2023-11-14T22:15:20Z"
    assert adapted["run"]["output_count"] == 1


def test_pipeline_without_identity_is_rejected():
    try:
        adapt_pipeline_record({})
    except ValueError as error:
        assert "identity" in str(error)
    else:
        raise AssertionError("identity-less pipeline was accepted")


def test_corrupt_legacy_counts_degrade_without_breaking_the_catalog():
    adapted = adapt_pipeline_record({
        "id": "pipe-corrupt", "clip_count": "many", "attempt": False,
        "output_count": "unknown", "output_files": ["one.mp4"],
    })

    assert adapted["production"]["plan"]["clip_count"] == 0
    assert adapted["run"]["attempt"] == 1
    assert adapted["run"]["output_count"] == 1

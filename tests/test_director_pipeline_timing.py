from unittest.mock import patch

from app.services import director_pipeline


def test_pipeline_phase_timer_resets_only_when_phase_changes():
    original_pipelines = director_pipeline._pipelines
    director_pipeline._pipelines = {
        "timed": {
            "phase": "generating_images",
            "phase_started_at": 100.0,
            "updated_at": 100.0,
        }
    }
    try:
        with patch.object(director_pipeline.time, "time", return_value=125.0):
            director_pipeline._update_pipeline(
                "timed",
                progress={"current": 1, "total": 4},
            )

        pipeline = director_pipeline._pipelines["timed"]
        assert pipeline["phase_started_at"] == 100.0
        assert pipeline["updated_at"] == 125.0

        with patch.object(director_pipeline.time, "time", return_value=140.0):
            director_pipeline._update_pipeline(
                "timed",
                phase="generating_video",
                progress={"current": 0, "total": 4},
            )

        pipeline = director_pipeline._pipelines["timed"]
        assert pipeline["phase_started_at"] == 140.0
        assert pipeline["updated_at"] == 140.0
    finally:
        director_pipeline._pipelines = original_pipelines


def test_pipeline_phase_timer_is_initialized_for_legacy_live_state():
    original_pipelines = director_pipeline._pipelines
    director_pipeline._pipelines = {"legacy": {"phase": "planning"}}
    try:
        with patch.object(director_pipeline.time, "time", return_value=250.0):
            director_pipeline._update_pipeline("legacy", status="running")

        pipeline = director_pipeline._pipelines["legacy"]
        assert pipeline["phase_started_at"] == 250.0
        assert pipeline["updated_at"] == 250.0
    finally:
        director_pipeline._pipelines = original_pipelines

import json
from pathlib import Path
from unittest.mock import patch

from app.services import director_pipeline


def test_pipeline_timing_metadata_normalizes_live_terminal_state():
    timings = director_pipeline.pipeline_timing_metadata({
        "created_at": 100.0,
        "_completed_at": 410.125,
        "_prompt_generation_time_sec": 12.345,
        "_image_generation_time_sec": 45.6,
        "_video_generation_time_sec": 200.0,
        "_assembly_time_sec": None,
    })

    assert timings == {
        "total_time_sec": 310.12,
        "prompt_generation_time_sec": 12.35,
        "image_generation_time_sec": 45.6,
        "video_generation_time_sec": 200.0,
        "assembly_time_sec": None,
    }


def test_final_output_sidecar_persists_total_and_phase_timings(tmp_path: Path):
    sidecar_path = tmp_path / "final.meta.json"
    sidecar_path.write_text(json.dumps({
        "params": {"model_type": "minimax_h3", "resolution": "960x544"},
        "generation_mode": "video",
    }), encoding="utf-8")
    pipeline = {
        "id": "timed-final",
        "created_at": 100.0,
        "_completed_at": 410.0,
        "_prompt_generation_time_sec": 10.0,
        "_image_generation_time_sec": 20.0,
        "_video_generation_time_sec": 250.0,
        "_assembly_time_sec": 5.0,
    }

    assert director_pipeline.persist_pipeline_output_timing(
        str(tmp_path),
        "final.mp4",
        pipeline,
    )

    saved = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert saved["generation_time"] == 310.0
    assert saved["generation_timings"] == {
        "total_time_sec": 310.0,
        "prompt_generation_time_sec": 10.0,
        "image_generation_time_sec": 20.0,
        "video_generation_time_sec": 250.0,
        "assembly_time_sec": 5.0,
    }
    assert saved["director_pipeline_id"] == "timed-final"
    assert saved["params"]["director_pipeline_id"] == "timed-final"


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


def test_pipeline_stage_times_accumulate_across_resumed_work():
    original_pipelines = director_pipeline._pipelines
    director_pipeline._pipelines = {
        "timed": {
            "_video_generation_time_sec": 12.5,
            "updated_at": 100.0,
        }
    }
    try:
        with patch.object(director_pipeline.time, "time", return_value=150.0):
            director_pipeline._accumulate_pipeline_time(
                "timed",
                "_video_generation_time_sec",
                7.25,
            )

        pipeline = director_pipeline._pipelines["timed"]
        assert pipeline["_video_generation_time_sec"] == 19.75
        assert pipeline["updated_at"] == 150.0
    finally:
        director_pipeline._pipelines = original_pipelines

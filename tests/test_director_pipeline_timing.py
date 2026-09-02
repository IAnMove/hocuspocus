import json
from pathlib import Path
from unittest.mock import patch

from app.services import director_pipeline
from app.services.asset_manifest import (
    SCHEMA_NAME,
    publish_generation_sidecar,
    read_asset_manifest,
)


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
        "total_time_sec": 257.95,
        "prompt_generation_time_sec": 12.35,
        "image_generation_time_sec": 45.6,
        "video_generation_time_sec": 200.0,
        "assembly_time_sec": None,
    }


def test_pipeline_timing_legacy_checkpoint_falls_back_to_wall_clock():
    timings = director_pipeline.pipeline_timing_metadata({
        "created_at": 100.0,
        "completed_at": 410.125,
    })

    assert timings["total_time_sec"] == 310.12
    assert timings["prompt_generation_time_sec"] is None
    assert timings["image_generation_time_sec"] is None
    assert timings["video_generation_time_sec"] is None
    assert timings["assembly_time_sec"] is None


def test_final_output_sidecar_persists_total_and_phase_timings(tmp_path: Path):
    sidecar_path = tmp_path / "final.meta.json"
    sidecar_path.write_text(json.dumps({
        "params": {},
        "generation_mode": "video",
    }), encoding="utf-8")
    (tmp_path / "final.mp4").write_bytes(b"video")
    pipeline = {
        "id": "timed-final",
        "created_at": 100.0,
        "_completed_at": 410.0,
        "_prompt_generation_time_sec": 10.0,
        "_image_generation_time_sec": 20.0,
        "_video_generation_time_sec": 250.0,
        "_assembly_time_sec": 5.0,
        "video_model": "minimax_h3_legacy",
        "video_params": {"resolution": "960x544"},
        "director_resolution_preset": "540p",
        "director_aspect_ratio": "16:9",
    }

    assert director_pipeline.persist_pipeline_output_timing(
        str(tmp_path),
        "final.mp4",
        pipeline,
    )

    saved = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert saved["generation_time"] == 285.0
    assert saved["generation_timings"] == {
        "total_time_sec": 285.0,
        "prompt_generation_time_sec": 10.0,
        "image_generation_time_sec": 20.0,
        "video_generation_time_sec": 250.0,
        "assembly_time_sec": 5.0,
    }
    assert saved["generation_timing_basis"] == "active_stages"
    assert saved["director_pipeline_id"] == "timed-final"
    assert saved["params"]["director_pipeline_id"] == "timed-final"
    assert saved["params"]["model_type"] == "minimax_h3_legacy"
    assert saved["params"]["resolution"] == "960x544"
    assert saved["params"]["director_resolution_preset"] == "540p"
    assert saved["params"]["director_aspect_ratio"] == "16:9"
    assert saved["schema"] == SCHEMA_NAME
    assert saved["origin"]["tool"] == "director"
    assert saved["origin"]["actor"] == "unknown"


def test_final_output_timing_preserves_canonical_asset_id(tmp_path: Path):
    media = tmp_path / "final.mp4"
    media.write_bytes(b"video")
    published = publish_generation_sidecar(
        media,
        {
            "params": {"director_pipeline_id": "timed-stable"},
            "generation_mode": "video",
        },
        workspace_id="night-shift",
        tool="director",
    )
    original_id = json.loads(published.read_text(encoding="utf-8"))["asset"]["id"]
    pipeline = {
        "id": "timed-stable",
        "workspace": "night-shift",
        "created_at": 100.0,
        "_completed_at": 410.0,
        "_prompt_generation_time_sec": 10.0,
        "_image_generation_time_sec": 20.0,
        "_video_generation_time_sec": 250.0,
        "_assembly_time_sec": 5.0,
    }

    assert director_pipeline.persist_pipeline_output_timing(
        str(tmp_path), "final.mp4", pipeline,
    )
    assert director_pipeline.persist_pipeline_output_timing(
        str(tmp_path), "final.mp4", pipeline,
    )

    saved = json.loads((tmp_path / "final.meta.json").read_text(encoding="utf-8"))
    loaded = read_asset_manifest(media, workspace_id="night-shift")
    assert saved["schema"] == SCHEMA_NAME
    assert saved["asset"]["id"] == original_id
    assert saved["director_pipeline_id"] == "timed-stable"
    assert saved["params"]["director_pipeline_id"] == "timed-stable"
    assert loaded is not None
    assert loaded["asset"]["id"] == original_id
    assert loaded["origin"]["tool"] == "director"
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"]["workspace_id"] == "night-shift"
    assert loaded["origin"].get("project") is None
    assert loaded["origin"].get("production") is None


def test_output_enrichment_restores_missing_model_and_resolution():
    enriched = director_pipeline.enrich_output_metadata_with_pipeline_timing(
        {
            "params": {"director_pipeline_id": "restored"},
            "generation_time": 23_594.67,
        },
        {
            "pipeline_id": "restored",
            "created_at": 100.0,
            "completed_at": 23_694.67,
            "video_model": "ltx2_22B_distilled_1_1",
            "video_params": {"resolution": "1280x704"},
            "director_resolution_preset": "720p",
            "director_aspect_ratio": "16:9",
            "prompt_generation_time_sec": 247.44,
            "image_generation_time_sec": 0.0,
            "video_generation_time_sec": 1256.99,
        },
    )

    assert enriched["generation_time"] == 1504.43
    assert enriched["params"]["model_type"] == "ltx2_22B_distilled_1_1"
    assert enriched["params"]["resolution"] == "1280x704"
    assert enriched["params"]["director_resolution_preset"] == "720p"
    assert enriched["params"]["director_aspect_ratio"] == "16:9"


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


def test_director_assembly_sidecar_publishes_canonical_manifest(tmp_path: Path):
    first = tmp_path / "minimax_h3_pipe-22_multiclip.mp4"
    second = tmp_path / "minimax_h3_pipe-22_multiclip-b.mp4"
    first.write_bytes(b"video-a")
    second.write_bytes(b"video-b")
    sidecar = {
        "params": {
            "model_type": "minimax_h3",
            "resolution": "960x544",
            "source_clips": ["clip-a.mp4", "clip-b.mp4"],
            "director_pipeline_id": "pipe-22",
            "pipeline_type": "short_film_story",
            "production_kind": "story",
            "result_kind": "video",
            "director_generation_mode": "direct_video",
            "direct_video_master_prompt": "a joined short",
            "api_key": "secret",
        },
        "generation_mode": "video",
        "result_kind": "video",
        "created_at": 1_700_000_100,
    }

    director_pipeline._write_director_assembly_sidecar(
        str(first), sidecar, "night-shift",
    )
    published = tmp_path / "minimax_h3_pipe-22_multiclip.meta.json"
    raw = json.loads(published.read_text(encoding="utf-8"))
    loaded = read_asset_manifest(first, workspace_id="night-shift")

    assert raw["schema"] == SCHEMA_NAME
    assert raw["params"]["director_pipeline_id"] == "pipe-22"
    assert raw["generation_mode"] == "video"
    assert raw["result_kind"] == "video"
    assert "secret" not in published.read_text(encoding="utf-8")
    assert loaded is not None
    assert loaded["origin"]["tool"] == "director"
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"]["workspace_id"] == "night-shift"
    assert loaded["origin"].get("project") is None
    assert loaded["origin"].get("production") is None
    assert loaded["execution"]["pipeline_id"] == "pipe-22"
    first_id = loaded["asset"]["id"]

    director_pipeline._write_director_assembly_sidecar(
        str(first), sidecar, "night-shift",
    )
    director_pipeline._write_director_assembly_sidecar(
        str(second), sidecar, "night-shift",
    )
    assert read_asset_manifest(first, workspace_id="night-shift")["asset"]["id"] == first_id
    assert read_asset_manifest(second, workspace_id="night-shift")["asset"]["id"] != first_id

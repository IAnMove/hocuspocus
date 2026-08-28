import json
import os
import time

from app.services import director_pipeline


def _write_media_with_sidecar(directory, stem, pipeline_id, job_id, created_at):
    media = directory / f"{stem}.mp4"
    media.write_bytes(b"x" * 2048)
    (directory / f"{stem}.meta.json").write_text(
        json.dumps({
            "director_pipeline_id": pipeline_id,
            "job_id": job_id,
            "created_at": created_at,
        }),
        encoding="utf-8",
    )
    return media.name


def test_finished_multiclip_is_adopted_by_timed_out_checkpoint(tmp_path):
    pipeline_id = "recover42"
    state_path = tmp_path / f"_director_pipeline_{pipeline_id}.json"
    state = {
        "pipeline_id": pipeline_id,
        "status": "failed",
        "completed_at": 1,
        "clips": [
            {"index": 0, "video_filename": None},
            {"index": 1, "video_filename": None},
        ],
        "output_files": [],
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    first = _write_media_with_sidecar(
        tmp_path, "2026-01-01-00h00m01s_clip", pipeline_id, "job42", 10,
    )
    second = _write_media_with_sidecar(
        tmp_path, "2026-01-01-00h00m02s_clip", pipeline_id, "job42", 10,
    )
    final = _write_media_with_sidecar(
        tmp_path, "2026-01-01-00h00m03s_multiclip", pipeline_id, "job42", 10,
    )

    recovered = director_pipeline._reconcile_pipeline_state_file(
        str(state_path), state,
    )

    assert recovered["status"] == "completed"
    assert recovered["output_files"] == [final]
    assert [clip["video_filename"] for clip in recovered["clips"]] == [first, second]
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "completed"
    assert persisted["recovery_note"].startswith("Recovered completed")


def test_generation_timeout_is_based_on_inactivity_not_total_runtime():
    jobs = {}
    previous = (
        director_pipeline._jobs,
        director_pipeline._run_generation,
        director_pipeline._wgp,
    )

    def progressing_generation(job_id):
        job = jobs[job_id]
        job["status"] = "running"
        for step in range(4):
            time.sleep(0.05)
            job["step"] = step + 1
            job["message"] = f"step {step + 1}"
            job["last_progress_at"] = time.time()
        job["output_files"] = ["finished.mp4"]
        job["status"] = "completed"
        job["last_progress_at"] = time.time()

    try:
        director_pipeline._jobs = jobs
        director_pipeline._run_generation = progressing_generation
        director_pipeline._wgp = None
        result = director_pipeline._submit_and_wait(
            {},
            timeout_s=0.1,
            out_dir=".",
        )
    finally:
        (
            director_pipeline._jobs,
            director_pipeline._run_generation,
            director_pipeline._wgp,
        ) = previous

    assert result == ["finished.mp4"]


def test_preview_checkpoint_recovers_without_starting_video(tmp_path):
    pipeline_id = "preview42"
    state_path = tmp_path / f"_director_pipeline_{pipeline_id}.json"
    preview = {
        "index": 0,
        "image_filename": "comic_panel_0001.png",
        "prompt": "FROZEN PREVIEW PROMPT",
        "input_resolution": "1280x704",
        "output_resolution": "1280x704",
    }
    state_path.write_text(
        json.dumps({
            "pipeline_id": pipeline_id,
            "status": "preview_ready",
            "created_at": 10,
            "preview_clips": [preview],
            "clips": [{
                "index": 0,
                "planned_clip": {"start": 0, "end": 3},
                "image_prompt": "",
                "video_prompt": "original",
                "effective_video_prompt": "FROZEN PREVIEW PROMPT",
                "effective_video_frames": 73,
                "start_image_filename": "comic_panel_0001.png",
                "end_image_filename": None,
            }],
            "output_files": [],
            "_params_snapshot": {
                "pipeline_type": "comic_movie",
                "comic_preflight_only": True,
                "auto_mode": True,
            },
        }),
        encoding="utf-8",
    )

    try:
        ok, message = director_pipeline.resume_pipeline(
            pipeline_id,
            str(tmp_path),
        )
        recovered = director_pipeline.get_pipeline(pipeline_id)
        assert ok
        assert message == "recovered_preview"
        assert recovered["status"] == "preview_ready"
        assert recovered["phase"] == "preview_ready"
        assert recovered["preview_clips"] == [preview]
        assert (
            recovered["clip_plans"][0]["_effective_video_prompt"]
            == "FROZEN PREVIEW PROMPT"
        )
    finally:
        director_pipeline._pipelines.pop(pipeline_id, None)


def test_pipeline_history_is_scoped_to_selected_workspace(tmp_path):
    default_state = tmp_path / "_director_pipeline_default01.json"
    default_state.write_text(
        json.dumps({
            "pipeline_id": "default01",
            "status": "completed",
            "pipeline_type": "comic_movie",
            "clips": [],
        }),
        encoding="utf-8",
    )
    other = tmp_path / "other"
    other.mkdir()
    (other / "_director_pipeline_other001.json").write_text(
        json.dumps({
            "pipeline_id": "other001",
            "status": "preview_ready",
            "pipeline_type": "comic_movie",
            "comic_id": "comic-other",
            "clips": [],
        }),
        encoding="utf-8",
    )

    assert [item["id"] for item in director_pipeline.list_pipeline_states(
        str(tmp_path), "default",
    )] == ["default01"]
    other_items = director_pipeline.list_pipeline_states(str(tmp_path), "other")
    assert [item["id"] for item in other_items] == ["other001"]
    assert other_items[0]["comic_id"] == "comic-other"


def test_pipeline_list_paginates_newest_first_without_opening_the_rest(tmp_path):
    older = tmp_path / "_director_pipeline_older.json"
    newer = tmp_path / "_director_pipeline_newer.json"
    older.write_text(json.dumps({
        "pipeline_id": "older",
        "status": "completed",
        "pipeline_type": "music_video",
        "clips": [],
    }), encoding="utf-8")
    newer.write_text(json.dumps({
        "pipeline_id": "newer",
        "status": "crashed",
        "pipeline_type": "music_video",
        "clips": [{"index": 0}],
    }), encoding="utf-8")
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_700_000_100, 1_700_000_100))

    assert director_pipeline.count_pipeline_states(str(tmp_path), "default") == 2
    page = director_pipeline.list_pipeline_states(str(tmp_path), "default", limit=1, offset=0)
    assert [item["id"] for item in page] == ["newer"]
    rest = director_pipeline.list_pipeline_states(str(tmp_path), "default", limit=1, offset=1)
    assert [item["id"] for item in rest] == ["older"]

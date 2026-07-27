import json
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

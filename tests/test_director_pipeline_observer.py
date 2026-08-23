"""Model-free regressions for Director's push-based task publication."""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.abspath(os.path.join(_HERE, "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services import director_pipeline as pipeline  # noqa: E402
from services.task_manager import current_task_context  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_director_wiring():
    previous = (
        pipeline._jobs,
        pipeline._run_generation,
        pipeline._cancel_generation,
        pipeline._wgp,
        pipeline._gen_lock,
        pipeline._active_gen_states,
        pipeline._pipeline_state_observer,
    )
    yield
    (
        pipeline._jobs,
        pipeline._run_generation,
        pipeline._cancel_generation,
        pipeline._wgp,
        pipeline._gen_lock,
        pipeline._active_gen_states,
        pipeline._pipeline_state_observer,
    ) = previous


def _stub_fresh_pipeline_preflight(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "_resolve_fresh_shot_image_policy",
        lambda _params: pipeline.SHOT_IMAGE_GENERATE,
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_director_models",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline,
        "_create_director_video_execution_profile",
        lambda *_args, **_kwargs: {},
    )


def test_start_publishes_before_worker_and_remembers_canonical_ids(
    monkeypatch,
    tmp_path,
):
    _stub_fresh_pipeline_preflight(monkeypatch)
    events = []

    def observe(snapshot, workspace):
        assert pipeline._pipeline_lock.acquire(blocking=False)
        pipeline._pipeline_lock.release()
        assert pipeline._pipelines[snapshot["id"]]["id"] == snapshot["id"]
        events.append(("published", snapshot["status"], workspace))
        return {
            "id": f"task-director-{snapshot['id']}",
            "root_id": f"root-director-{snapshot['id']}",
        }

    def start_worker(pid, *, resume=False):
        live = pipeline._pipelines[pid]
        events.append(("worker", live["task_id"], live["root_task_id"]))

    monkeypatch.setattr(pipeline, "_start_pipeline_worker", start_worker)
    pipeline.init(
        {},
        lambda _job_id: None,
        SimpleNamespace(save_path=str(tmp_path)),
        state_observer=observe,
    )

    pid = pipeline.start_pipeline({"pipeline_type": "music_video"})
    try:
        assert events == [
            ("published", "running", "default"),
            (
                "worker",
                f"task-director-{pid}",
                f"root-director-{pid}",
            ),
        ]
        assert pipeline._pipelines[pid]["task_id"] == f"task-director-{pid}"
        assert (
            pipeline._pipelines[pid]["root_task_id"]
            == f"root-director-{pid}"
        )
    finally:
        pipeline._pipelines.pop(pid, None)


def test_update_pushes_terminal_snapshot_outside_registry_lock(tmp_path):
    pid = "observer-terminal"
    observed = []

    def observe(snapshot, workspace):
        assert pipeline._pipeline_lock.acquire(blocking=False)
        pipeline._pipeline_lock.release()
        observed.append((snapshot, workspace))

    pipeline.init(
        {},
        lambda _job_id: None,
        SimpleNamespace(save_path=str(tmp_path)),
        state_observer=observe,
    )
    pipeline._pipelines[pid] = {
        "id": pid,
        "status": "running",
        "phase": "generating_video",
        "workspace": None,
        "out_dir": str(tmp_path),
        "params": {"pipeline_type": "music_video"},
        "progress": {"current": 0, "total": 1, "message": "Rendering"},
    }
    try:
        assert pipeline._update_pipeline(
            pid,
            status="completed",
            phase="completed",
            output_files=["movie.mp4"],
        )
        snapshot, workspace = observed[-1]
        assert workspace == "default"
        assert snapshot["status"] == "completed"
        assert snapshot["output_files"] == ["movie.mp4"]
        assert snapshot["pipeline_type"] == "music_video"
        assert "params" not in snapshot
    finally:
        pipeline._pipelines.pop(pid, None)


def test_worker_restores_director_task_context_for_nested_llm_calls(
    monkeypatch,
    tmp_path,
):
    pid = "observer-context"
    captured = {}
    pipeline._pipelines[pid] = {
        "id": pid,
        "task_id": "task-director-context",
        "root_task_id": "task-director-root",
        "workspace": "music-workspace",
        "out_dir": str(tmp_path),
    }

    def fake_run(run_pid, resume=False):
        captured.update(current_task_context())
        captured["pid"] = run_pid
        captured["resume"] = resume

    monkeypatch.setattr(pipeline, "_run_pipeline", fake_run)
    try:
        pipeline._run_pipeline_worker(pid, resume=True)
    finally:
        pipeline._pipelines.pop(pid, None)

    assert captured["pid"] == pid
    assert captured["resume"] is True
    assert captured["task_id"] == "task-director-context"
    assert captured["root_task_id"] == "task-director-root"
    assert captured["workspace"] == "music-workspace"
    assert captured["workspace_dir"] == str(tmp_path)
    assert current_task_context() == {}


def test_worker_start_failure_is_pushed_as_terminal_state(
    monkeypatch,
    tmp_path,
):
    pid = "observer-start-failure"
    observed = []

    class BrokenThread:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def start(self):
            raise RuntimeError("thread unavailable")

    pipeline.init(
        {},
        lambda _job_id: None,
        SimpleNamespace(save_path=str(tmp_path)),
        state_observer=lambda snapshot, _workspace: observed.append(snapshot),
    )
    pipeline._pipelines[pid] = {
        "id": pid,
        "status": "running",
        "phase": "planning",
        "workspace": None,
        "out_dir": str(tmp_path),
        "params": {"pipeline_type": "music_video"},
        "progress": {},
    }
    monkeypatch.setattr(pipeline.threading, "Thread", BrokenThread)
    monkeypatch.setattr(pipeline, "_save_pipeline_state", lambda _pid: True)
    try:
        with pytest.raises(RuntimeError, match="thread unavailable"):
            pipeline._start_pipeline_worker(pid)
        assert observed[-1]["status"] == "failed"
        assert observed[-1]["phase"] == "failed"
        assert "thread unavailable" in observed[-1]["error"]
        assert pid not in pipeline._pipeline_threads
    finally:
        pipeline._pipelines.pop(pid, None)
        pipeline._pipeline_threads.pop(pid, None)


def test_preview_recovery_publishes_rehydrated_and_terminal_snapshots(
    monkeypatch,
    tmp_path,
):
    pid = "observer-recovery"
    preview = {
        "index": 0,
        "image_filename": "panel.png",
        "prompt": "Frozen prompt",
    }
    (tmp_path / f"_director_pipeline_{pid}.json").write_text(
        json.dumps({
            "pipeline_id": pid,
            "status": "preview_ready",
            "workspace": "default",
            "created_at": 10,
            "preview_clips": [preview],
            "clips": [{
                "planned_clip": {"start": 0, "end": 3},
                "image_prompt": "panel",
                "video_prompt": "camera move",
                "start_image_filename": "panel.png",
            }],
            "_params_snapshot": {
                "pipeline_type": "comic_movie",
                "comic_preflight_only": True,
            },
        }),
        encoding="utf-8",
    )
    observed = []
    monkeypatch.setattr(
        pipeline,
        "_validate_director_models",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline,
        "_saved_director_video_execution_profile",
        lambda *_args, **_kwargs: {},
    )
    pipeline.init(
        {},
        lambda _job_id: None,
        SimpleNamespace(save_path=str(tmp_path)),
        state_observer=lambda snapshot, _workspace: (
            observed.append(snapshot.copy())
            or {
                "task_id": f"task-{pid}",
                "root_task_id": f"root-{pid}",
            }
        ),
    )

    try:
        ok, message = pipeline.resume_pipeline(pid, str(tmp_path))
        assert (ok, message) == (True, "recovered_preview")
        assert [item["status"] for item in observed[-2:]] == [
            "running",
            "preview_ready",
        ]
        assert pipeline._pipelines[pid]["task_id"] == f"task-{pid}"
        assert pipeline._pipelines[pid]["root_task_id"] == f"root-{pid}"
    finally:
        pipeline._pipelines.pop(pid, None)

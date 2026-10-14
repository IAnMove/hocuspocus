"""Model-free regression coverage for observable audio-analysis jobs."""
from __future__ import annotations

import asyncio
import copy
from contextlib import contextmanager
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services import audio_analysis
from services import audio_jobs
from services.resource_scheduler import ResourceAcquireCancelled
import routers.audio as audio_routes


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"


class _DeferredThread:
    def __init__(self, *, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        return None


class _Request:
    def __init__(self, body: dict):
        self.body = body

    async def json(self):
        return self.body


def _lane(key: str):
    return SimpleNamespace(key=key)


def _resource_scheduler(acquire):
    return SimpleNamespace(
        local_gpu_lane=lambda _index: _lane("local_gpu:0"),
        cpu_lane=lambda name: _lane(f"local_cpu:{name}"),
        coordinator=SimpleNamespace(acquire=acquire),
        ResourceAcquireCancelled=ResourceAcquireCancelled,
    )


def _job(*, status: str = "queued", workspace: str = "default") -> dict:
    job_id = "audio-analysis-123456abcdef"
    return {
        "id": job_id,
        "task_id": f"task-audio-analysis-{job_id}",
        "root_task_id": f"task-audio-analysis-{job_id}",
        "workspace": workspace,
        "status": status,
        "phase": status,
        "message": status,
        "progress": 0,
        "step": 0,
        "total_steps": 10,
        "result": None,
        "error": None,
        "acquired_resources": [],
        "created_at": time.time(),
        "_cancel_requested": False,
    }


def _bind(monkeypatch, jobs: dict, lock: threading.RLock) -> None:
    """Point both modules at one registry and one lock, the launch arrangement."""
    monkeypatch.setattr(audio_jobs, "_jobs", jobs)
    monkeypatch.setattr(audio_routes, "_jobs", jobs)
    monkeypatch.setattr(audio_jobs, "_audio_analysis_jobs_lock", lock)
    monkeypatch.setattr(audio_routes, "_audio_analysis_jobs_lock", lock)


def test_cancel_wins_atomically_over_a_late_completed_update(monkeypatch):
    job = _job(status="running")
    published: list[dict] = []
    _bind(monkeypatch, {job["id"]: job}, threading.RLock())
    monkeypatch.setattr(
        audio_jobs,
        "_publish_audio_analysis_job",
        lambda snapshot: published.append(copy.deepcopy(snapshot)),
    )
    update = audio_jobs._audio_analysis_job_update

    job["_cancel_requested"] = True
    update(job["id"], status="cancelling", phase="cancelling")
    result = update(
        job["id"],
        status="completed",
        phase="completed",
        result={"duration": 12},
        progress=100,
        finished_at=time.time(),
    )

    assert result["status"] == "cancelled"
    assert result["result"] is None
    assert result["error"] is None
    assert result["acquired_resources"] == []
    assert published[-1]["status"] == "cancelled"


def test_precancelled_job_never_acquires_a_resource_or_runs_analysis(monkeypatch):
    job = _job(status="cancelled")
    job["_cancel_requested"] = True
    acquired = []

    def acquire(*_args, **_kwargs):
        acquired.append(True)
        raise AssertionError("cancelled job acquired a resource")

    _bind(monkeypatch, {job["id"]: job}, threading.RLock())
    monkeypatch.setattr(audio_jobs, "resource_scheduler", _resource_scheduler(acquire))
    monkeypatch.setattr(
        audio_analysis,
        "analyze",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("cancelled job ran analysis")
        ),
    )

    audio_jobs._run_audio_analysis_job(job["id"], {
        "audio_path": "/unused.wav",
        "transcribe": True,
    })

    assert not acquired
    assert job["status"] == "cancelled"


def test_worker_publishes_waiting_acquired_and_terminal_resource_states(monkeypatch):
    job = _job()
    acquired_calls = []

    @contextmanager
    def acquire(lane, **kwargs):
        acquired_calls.append((lane.key, kwargs["task_id"]))
        yield

    published: list[dict] = []
    _bind(monkeypatch, {job["id"]: job}, threading.RLock())
    monkeypatch.setattr(audio_jobs, "resource_scheduler", _resource_scheduler(acquire))
    monkeypatch.setattr(
        audio_jobs,
        "_publish_audio_analysis_job",
        lambda snapshot: published.append(copy.deepcopy(snapshot)),
    )
    callback = {"value": None}
    monkeypatch.setattr(
        audio_analysis, "set_progress_callback",
        lambda value: callback.__setitem__("value", value),
    )
    monkeypatch.setattr(audio_analysis, "clear_progress", lambda: None)

    def analyze(**_kwargs):
        callback["value"]("transcribing", "Transcribing audio")
        return {"duration": 12}

    monkeypatch.setattr(audio_analysis, "analyze", analyze)
    audio_jobs._run_audio_analysis_job(job["id"], {
        "audio_path": "/unused.wav",
        "transcribe": True,
    })

    assert acquired_calls == [("local_gpu:0", job["task_id"])]
    waiting = next(item for item in published if item["status"] == "waiting_resource")
    running = next(item for item in published if item["status"] == "running")
    terminal = published[-1]
    assert waiting["acquired_resources"] == []
    assert running["acquired_resources"] == ["local_gpu:0"]
    assert terminal["status"] == "completed"
    assert terminal["acquired_resources"] == []


def test_prepare_hook_failure_finishes_the_job_instead_of_leaving_it_waiting(monkeypatch):
    job = _job()

    class BrokenLease:
        def __enter__(self):
            raise RuntimeError("prepare hook failed")

        def __exit__(self, *_args):
            return False

    _bind(monkeypatch, {job["id"]: job}, threading.RLock())
    monkeypatch.setattr(
        audio_jobs,
        "resource_scheduler",
        _resource_scheduler(lambda *_args, **_kwargs: BrokenLease()),
    )

    audio_jobs._run_audio_analysis_job(job["id"], {
        "audio_path": "/unused.wav",
        "transcribe": False,
    })

    assert job["status"] == "failed"
    assert "prepare hook failed" in job["error"]
    assert job["finished_at"]
    assert job["acquired_resources"] == []


def test_start_preserves_workspace_and_supplied_task_hierarchy(tmp_path, monkeypatch):
    audio_path = tmp_path / "song.wav"
    audio_path.write_bytes(b"RIFF")
    published = []
    resolved = []
    jobs: dict = {}
    _bind(monkeypatch, jobs, threading.RLock())
    monkeypatch.setattr(audio_routes, "_get_active_workspace", lambda: "default")
    monkeypatch.setattr(
        audio_routes,
        "_resolve_request_media_path",
        lambda value, **kwargs: resolved.append((value, kwargs["workspace"])) or value,
    )
    monkeypatch.setattr(
        audio_routes,
        "_publish_audio_analysis_job",
        lambda job: published.append(copy.deepcopy(job)),
    )
    monkeypatch.setattr(audio_routes, "_run_audio_analysis_job", lambda *_args: None)
    monkeypatch.setattr(
        audio_routes, "resource_scheduler", _resource_scheduler(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(audio_routes, "threading", SimpleNamespace(Thread=_DeferredThread))

    result = asyncio.run(audio_routes.start_audio_analysis_job(_Request({
        "audio_path": str(audio_path),
        "workspace": "project-a",
        "task_id": "task-audio-child",
        "root_task_id": "task-director-root",
        "parent_task_id": "task-director-root",
        "project_id": "story-1",
        "transcribe": True,
    })))

    job = jobs[result["job_id"]]
    assert result["task_id"] == "task-audio-child"
    assert result["root_task_id"] == "task-director-root"
    assert job["parent_task_id"] == "task-director-root"
    assert job["workspace"] == "project-a"
    assert job["project_id"] == "story-1"
    assert resolved == [(str(audio_path), "project-a")]
    assert published[0]["resource_lane"] == "local_gpu:0"


def test_get_and_cancel_do_not_cross_workspace_boundaries(monkeypatch):
    job = _job(workspace="project-a")
    _bind(monkeypatch, {job["id"]: job}, threading.RLock())
    monkeypatch.setattr(audio_routes, "_get_active_workspace", lambda: "project-a")
    monkeypatch.setattr(audio_routes, "_workspace_dir", lambda workspace=None: str(workspace or "project-a"))

    with pytest.raises(HTTPException) as error:
        audio_routes.get_audio_analysis_job(job["id"], "project-b")
    assert error.value.status_code == 404

    result = audio_routes.cancel_audio_analysis_job(job["id"], "project-a")
    assert result["status"] == "cancelled"
    assert job["_cancel_requested"] is True


def test_legacy_reconnect_and_cancel_cover_all_audio_active_states():
    source = LAUNCH.read_text(encoding="utf-8")
    cancel = source.split("def cancel_job", 1)[1].split("@api.get(\"/api/v1/jobs\")", 1)[0]
    listing = source.split("def list_jobs", 1)[1].split("def _recovery_job_summary", 1)[0]

    assert "return cancel_audio_analysis_job(job_id)" in cancel
    assert '("queued", "waiting_resource", "running", "cancelling")' in listing

from __future__ import annotations

import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.services import model3d_service, rig_service


_REAL_THREAD = threading.Thread


class _DeferredThread:
    """Keep watchdogs deterministic; the test owns the real worker thread."""

    def __init__(self, *_args, **_kwargs):
        pass

    def start(self):
        return None


class _BlockingStdout:
    def __init__(
        self,
        terminated: threading.Event,
        allow_worker_exit: threading.Event,
    ) -> None:
        self._terminated = terminated
        self._allow_worker_exit = allow_worker_exit

    def __iter__(self):
        return self

    def __next__(self):
        if not self._terminated.wait(timeout=3):
            raise AssertionError("test worker was not terminated")
        if not self._allow_worker_exit.wait(timeout=3):
            raise AssertionError("test worker safe boundary was not released")
        raise StopIteration


class _BlockingProcess:
    pid = 12345

    def __init__(self, allow_worker_exit: threading.Event) -> None:
        self.terminated = threading.Event()
        self.stdout = _BlockingStdout(self.terminated, allow_worker_exit)
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return -15 if self.terminated.is_set() else None

    def wait(self, timeout=None):
        if not self.terminated.wait(timeout=timeout):
            raise subprocess.TimeoutExpired("test-worker", timeout)
        return -15

    def terminate(self):
        self.terminate_calls += 1
        self.terminated.set()

    def kill(self):
        self.kill_calls += 1
        self.terminated.set()


@pytest.fixture(autouse=True)
def isolated_job_registries():
    registries = (
        (model3d_service._lock, model3d_service._jobs, model3d_service._processes),
        (rig_service._lock, rig_service._jobs, rig_service._processes),
    )
    snapshots = []
    for lock, jobs, processes in registries:
        with lock:
            snapshots.append((dict(jobs), dict(processes)))
            jobs.clear()
            processes.clear()
    try:
        yield
    finally:
        for (lock, jobs, processes), (saved_jobs, saved_processes) in zip(
            registries, snapshots, strict=True
        ):
            with lock:
                jobs.clear()
                jobs.update(saved_jobs)
                processes.clear()
                processes.update(saved_processes)


def _seed_case(kind: str, tmp_path: Path, monkeypatch):
    output_dir = tmp_path / kind / "outputs"
    jobs_dir = tmp_path / kind / "jobs"
    job_id = f"{kind}-cancel-race"

    if kind == "model3d":
        service = model3d_service
        request = service._prepare_request(
            {"prompt": "A small arcade cabinet"}, {}, None
        )
        job = {
            "job_id": job_id,
            "task_id": service._canonical_task_id(job_id),
            "root_task_id": service._canonical_task_id(job_id),
            "status": "queued",
            "progress": 0.0,
            "phase": "queued",
            "message": "Queued Hunyuan3D generation",
            "operation": "generate",
            "model_id": request["model"]["id"],
            "created_at": time.time(),
            "updated_at": time.time(),
            "request": request,
        }
        monkeypatch.setattr(service, "HF_CACHE_DIR", tmp_path / kind / "cache")
        dummy_ref = tmp_path / kind / "minimax-ref.png"
        dummy_ref.parent.mkdir(parents=True, exist_ok=True)
        dummy_ref.write_bytes(b"png")
        monkeypatch.setattr(
            service,
            "_condition_text_job_with_minimax",
            lambda *_args, **_kwargs: str(dummy_ref),
        )
        # Keep this cancellation race focused on the spawn boundary. Importing
        # wgp merely to discover an optional provider key cold-loads torch and
        # can consume the entire synchronization timeout on CI.
        monkeypatch.setattr(service, "_minimax_api_key", lambda: "")
    else:
        service = rig_service
        source = tmp_path / kind / "source.glb"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"source")
        request = {
            "engine": "procedural",
            "workspace": "default",
            "source": str(source),
            "rig_profile": "prop",
            "animations": ["idle"],
            "spine_joints": 5,
            "axis_mode": "auto",
            "weight_falloff": 2.0,
        }
        job = {
            "job_id": job_id,
            "task_id": service._canonical_task_id(job_id),
            "root_task_id": service._canonical_task_id(job_id),
            "status": "queued",
            "progress": 0.0,
            "phase": "queued",
            "message": "Queued rig job",
            "engine": "procedural",
            "created_at": time.time(),
            "updated_at": time.time(),
            "request": request,
        }

    monkeypatch.setattr(service, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(service.threading, "Thread", _DeferredThread)
    with service._lock:
        service._jobs[job_id] = job
    return service, job_id, output_dir


def _install_immediate_lane(service, job_id, monkeypatch):
    lane_released = threading.Event()
    release_snapshots = []

    @contextmanager
    def immediate_acquire(*_args, **_kwargs):
        try:
            yield
        finally:
            release_snapshots.append(service.get_job(job_id))
            lane_released.set()

    monkeypatch.setattr(
        service.resource_scheduler.coordinator,
        "acquire",
        immediate_acquire,
    )
    return lane_released, release_snapshots


@pytest.mark.parametrize("kind", ["model3d", "rig"])
def test_cancel_before_atomic_spawn_never_launches_subprocess(
    kind,
    tmp_path,
    monkeypatch,
):
    service, job_id, output_dir = _seed_case(kind, tmp_path, monkeypatch)
    lane_released, _release_snapshots = _install_immediate_lane(
        service, job_id, monkeypatch
    )
    reached_spawn_boundary = threading.Event()
    release_spawn_boundary = threading.Event()
    popen_calls = []
    original_spawn = service._spawn_worker_if_active

    def blocked_spawn(*args, **kwargs):
        reached_spawn_boundary.set()
        if not release_spawn_boundary.wait(timeout=3):
            raise AssertionError("spawn boundary was not released")
        return original_spawn(*args, **kwargs)

    def unexpected_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        raise AssertionError("cancelled job must not launch a subprocess")

    monkeypatch.setattr(service, "_spawn_worker_if_active", blocked_spawn)
    monkeypatch.setattr(service.subprocess, "Popen", unexpected_popen)

    worker = _REAL_THREAD(
        target=service._run_job,
        args=(job_id, str(output_dir)),
        daemon=True,
    )
    worker.start()
    assert reached_spawn_boundary.wait(timeout=3)

    cancelled = service.cancel_job(job_id)
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"

    release_spawn_boundary.set()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert popen_calls == []
    assert lane_released.is_set()
    assert service.get_job(job_id)["status"] == "cancelled"
    assert job_id not in service._processes


@pytest.mark.parametrize("kind", ["model3d", "rig"])
def test_cancel_after_spawn_waits_for_worker_safe_boundary(
    kind,
    tmp_path,
    monkeypatch,
):
    service, job_id, output_dir = _seed_case(kind, tmp_path, monkeypatch)
    lane_released, release_snapshots = _install_immediate_lane(
        service, job_id, monkeypatch
    )
    spawned = threading.Event()
    allow_worker_exit = threading.Event()
    process = _BlockingProcess(allow_worker_exit)

    def blocking_popen(*_args, **_kwargs):
        spawned.set()
        return process

    monkeypatch.setattr(service.subprocess, "Popen", blocking_popen)

    worker = _REAL_THREAD(
        target=service._run_job,
        args=(job_id, str(output_dir)),
        daemon=True,
    )
    worker.start()
    assert spawned.wait(timeout=3)

    cancelling = service.cancel_job(job_id)
    assert cancelling is not None
    # Preserve the existing public status union so current clients continue
    # polling. The phase communicates deferred cancellation until the worker
    # and its resource lane have actually settled.
    assert cancelling["status"] == "running"
    assert cancelling["phase"] == "cancelling"
    assert "cancel_requested" not in cancelling
    assert process.terminate_calls == 1
    assert not lane_released.is_set()
    assert job_id in service._processes
    assert not service._update_job(
        job_id,
        status="running",
        phase="running",
        message="late worker progress",
    )
    assert service.get_job(job_id)["phase"] == "cancelling"

    allow_worker_exit.set()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert lane_released.is_set()
    assert len(release_snapshots) == 1
    assert release_snapshots[0]["status"] == "running"
    assert release_snapshots[0]["phase"] == "cancelling"
    assert process.kill_calls == 0
    assert job_id not in service._processes
    settled = service.get_job(job_id)
    assert settled is not None
    assert settled["status"] == "cancelled"
    assert "request" not in service._jobs[job_id]

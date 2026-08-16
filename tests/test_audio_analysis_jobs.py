"""Model-free regression coverage for observable audio-analysis jobs."""
from __future__ import annotations

import ast
import asyncio
import copy
from contextlib import contextmanager
import os
import re
import threading
import time
import traceback
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import audio_analysis
from services.resource_scheduler import ResourceAcquireCancelled


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "launch.py"
TREE = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))


def _function(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            clone = copy.deepcopy(node)
            clone.decorator_list = []
            return clone
    raise AssertionError(f"Function {name!r} not found")


def _load(*names: str, namespace: dict) -> dict:
    module = ast.Module(body=[_function(name) for name in names], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(LAUNCH), "exec"), namespace)
    return namespace


class _HTTPException(Exception):
    def __init__(self, *, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


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


def _namespace(job: dict, acquire, published: list[dict]) -> dict:
    return {
        "_jobs": {job["id"]: job},
        "_audio_analysis_jobs_lock": threading.RLock(),
        "_AUDIO_ANALYSIS_ACTIVE": {"queued", "waiting_resource", "running", "cancelling"},
        "_AUDIO_ANALYSIS_TERMINAL": {"completed", "failed", "cancelled"},
        "_AUDIO_ANALYSIS_STEPS": {
            "loading_audio": 1,
            "transcribing": 6,
            "finalizing": 9,
        },
        "copy": copy,
        "snapshot_job": copy.deepcopy,
        "resource_scheduler": _resource_scheduler(acquire),
        "threading": threading,
        "time": time,
        "traceback": traceback,
        "_publish_audio_analysis_job": lambda snapshot: published.append(
            copy.deepcopy(snapshot)
        ),
    }


def test_cancel_wins_atomically_over_a_late_completed_update():
    job = _job(status="running")
    published: list[dict] = []
    namespace = _namespace(job, lambda *_args, **_kwargs: None, published)
    update = _load("_audio_analysis_job_update", namespace=namespace)[
        "_audio_analysis_job_update"
    ]

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

    published: list[dict] = []
    namespace = _namespace(job, acquire, published)
    _load(
        "_audio_analysis_job_update",
        "_run_audio_analysis_job",
        namespace=namespace,
    )
    monkeypatch.setattr(
        audio_analysis,
        "analyze",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("cancelled job ran analysis")
        ),
    )

    namespace["_run_audio_analysis_job"](job["id"], {
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
    namespace = _namespace(job, acquire, published)
    _load(
        "_audio_analysis_job_update",
        "_run_audio_analysis_job",
        namespace=namespace,
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
    namespace["_run_audio_analysis_job"](job["id"], {
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


def test_prepare_hook_failure_finishes_the_job_instead_of_leaving_it_waiting():
    job = _job()

    class BrokenLease:
        def __enter__(self):
            raise RuntimeError("prepare hook failed")

        def __exit__(self, *_args):
            return False

    published: list[dict] = []
    namespace = _namespace(job, lambda *_args, **_kwargs: BrokenLease(), published)
    _load(
        "_audio_analysis_job_update",
        "_run_audio_analysis_job",
        namespace=namespace,
    )

    namespace["_run_audio_analysis_job"](job["id"], {
        "audio_path": "/unused.wav",
        "transcribe": False,
    })

    assert job["status"] == "failed"
    assert "prepare hook failed" in job["error"]
    assert job["finished_at"]
    assert job["acquired_resources"] == []


def test_start_preserves_workspace_and_supplied_task_hierarchy(tmp_path):
    audio_path = tmp_path / "song.wav"
    audio_path.write_bytes(b"RIFF")
    published = []
    resolved = []
    namespace = {
        "HTTPException": _HTTPException,
        "_jobs": {},
        "_audio_analysis_jobs_lock": threading.RLock(),
        "_get_active_workspace": lambda: "default",
        "_workspace_dir": lambda workspace=None: str(tmp_path / str(workspace or "default")),
        "_resolve_request_media_path": lambda value, **kwargs: (
            resolved.append((value, kwargs["workspace"])) or value
        ),
        "_publish_audio_analysis_job": lambda job: published.append(copy.deepcopy(job)),
        "_run_audio_analysis_job": lambda *_args: None,
        "resource_scheduler": _resource_scheduler(lambda *_args, **_kwargs: None),
        "os": os,
        "re": re,
        "threading": SimpleNamespace(Thread=_DeferredThread),
        "time": time,
        "uuid": uuid,
    }
    start = _load("start_audio_analysis_job", namespace=namespace)[
        "start_audio_analysis_job"
    ]

    result = asyncio.run(start(_Request({
        "audio_path": str(audio_path),
        "workspace": "project-a",
        "task_id": "task-audio-child",
        "root_task_id": "task-director-root",
        "parent_task_id": "task-director-root",
        "project_id": "story-1",
        "transcribe": True,
    })))

    job = namespace["_jobs"][result["job_id"]]
    assert result["task_id"] == "task-audio-child"
    assert result["root_task_id"] == "task-director-root"
    assert job["parent_task_id"] == "task-director-root"
    assert job["workspace"] == "project-a"
    assert job["project_id"] == "story-1"
    assert resolved == [(str(audio_path), "project-a")]
    assert published[0]["resource_lane"] == "local_gpu:0"


def test_get_and_cancel_do_not_cross_workspace_boundaries():
    job = _job(workspace="project-a")
    published: list[dict] = []
    namespace = _namespace(job, lambda *_args, **_kwargs: None, published)
    namespace.update({
        "HTTPException": _HTTPException,
        "_get_active_workspace": lambda: "project-a",
        "_workspace_dir": lambda workspace=None: str(workspace or "project-a"),
    })
    _load(
        "_audio_analysis_job_update",
        "get_audio_analysis_job",
        "cancel_audio_analysis_job",
        namespace=namespace,
    )

    with pytest.raises(_HTTPException) as error:
        namespace["get_audio_analysis_job"](job["id"], "project-b")
    assert error.value.status_code == 404

    result = namespace["cancel_audio_analysis_job"](job["id"], "project-a")
    assert result["status"] == "cancelled"
    assert job["_cancel_requested"] is True


def test_legacy_reconnect_and_cancel_cover_all_audio_active_states():
    source = LAUNCH.read_text(encoding="utf-8")
    cancel = source.split("def cancel_job", 1)[1].split("@api.get(\"/api/v1/jobs\")", 1)[0]
    listing = source.split("def list_jobs", 1)[1].split("def _recovery_job_summary", 1)[0]

    assert "return cancel_audio_analysis_job(job_id)" in cancel
    assert '("queued", "waiting_resource", "running", "cancelling")' in listing

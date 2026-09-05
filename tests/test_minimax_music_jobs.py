"""Model-free coverage for the asynchronous MiniMax Music job contract."""
from __future__ import annotations

import ast
import copy
import os
import threading
import time
import traceback
import uuid
from pathlib import Path
from types import SimpleNamespace

from services import minimax_music_service, resource_scheduler


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"
TREE = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))


def _function(name: str) -> ast.FunctionDef:
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


class _DeferredThread:
    def __init__(self, *, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        return None


class _HTTPException(Exception):
    def __init__(self, *, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _ExecutionModeError(ValueError):
    pass


def _base_namespace(tmp_path: Path) -> dict:
    jobs: dict[str, dict] = {}
    lock = threading.RLock()
    return {
        "copy": copy,
        "os": os,
        "re": __import__("re"),
        "threading": threading,
        "time": time,
        "traceback": traceback,
        "uuid": uuid,
        "resource_scheduler": resource_scheduler,
        "execution_mode": SimpleNamespace(
            ExecutionModeError=_ExecutionModeError,
            validate_remote_provider=lambda _workspace, _provider: None,
        ),
        "wgp": SimpleNamespace(server_config={
            "services": {"minimax_api_key": "secret"},
        }),
        "_minimax_music_jobs": jobs,
        "_minimax_music_jobs_lock": lock,
        "_MINIMAX_MUSIC_TERMINAL": {
            "completed", "failed", "cancelled", "interrupted",
        },
        "_persist_minimax_music_job": lambda _job: None,
        "_publish_minimax_music_job": lambda _job: None,
        "_workspace_dir": lambda _workspace=None: str(tmp_path),
    }


def _job(job_id: str, count: int = 2) -> dict:
    task_id = f"task-minimax-music-{job_id}"
    now = time.time()
    return {
        "jobId": job_id,
        "taskId": task_id,
        "rootTaskId": task_id,
        "workspace": "default",
        "status": "queued",
        "phase": "queued",
        "message": "Queued",
        "current": 0,
        "total": count,
        "progress": 0,
        "candidates": [],
        "output_files": [],
        "children": [{
            "jobId": f"{job_id}-candidate-{index + 1}",
            "taskId": f"{task_id}-candidate-{index + 1}",
            "rootTaskId": task_id,
            "parentTaskId": task_id,
            "workspace": "default",
            "status": "queued",
            "phase": "queued",
            "message": "Queued",
            "current": 0,
            "total": 1,
            "progress": 0,
            "output_files": [],
            "createdAt": now,
            "updatedAt": now,
        } for index in range(count)],
        "createdAt": now,
        "updatedAt": now,
        "_cancel_requested": False,
        "request": {
            "prompt": "cinematic dream pop",
            "lyrics": "[Verse]\nAcross the night",
            "instrumental": False,
            "model": "music-3.0",
            "reference_audio_path": None,
        },
    }


def test_start_returns_a_durable_job_before_provider_work(tmp_path):
    namespace = _base_namespace(tmp_path)
    published = []
    namespace.update({
        "HTTPException": _HTTPException,
        "_get_active_workspace": lambda: "default",
        "_safe_join": lambda root, name: os.path.join(root, name),
        "_persist_minimax_music_job": lambda job: published.append(("persist", job["jobId"])),
        "_publish_minimax_music_job": lambda job: published.append(("publish", job["jobId"])),
        "_run_minimax_music_job": lambda _job_id: None,
        "_public_minimax_music_job": lambda job: {
            key: value for key, value in job.items()
            if key not in {"request", "_cancel_requested"}
        },
        "threading": SimpleNamespace(
            Thread=_DeferredThread,
        ),
    })
    start = _load("start_story_music_candidates_job", namespace=namespace)[
        "start_story_music_candidates_job"
    ]

    before = time.monotonic()
    result = start({
        "prompt": "cinematic dream pop",
        "lyrics": "[Verse]\nAcross the night",
        "count": 3,
        "workspace": "default",
    })
    elapsed = time.monotonic() - before

    assert elapsed < 0.25
    assert result["status"] == "queued"
    assert result["total"] == 3
    assert result["taskId"] == result["rootTaskId"]
    assert result["jobId"] in namespace["_minimax_music_jobs"]
    assert published == [
        ("persist", result["jobId"]),
        ("publish", result["jobId"]),
    ]


def test_start_rejects_a_non_numeric_candidate_count_as_bad_input(tmp_path):
    namespace = _base_namespace(tmp_path)
    namespace.update({
        "HTTPException": _HTTPException,
        "_get_active_workspace": lambda: "default",
        "_safe_join": lambda root, name: os.path.join(root, name),
        "_run_minimax_music_job": lambda _job_id: None,
        "_public_minimax_music_job": lambda job: job,
        "threading": SimpleNamespace(Thread=_DeferredThread),
    })
    start = _load("start_story_music_candidates_job", namespace=namespace)[
        "start_story_music_candidates_job"
    ]

    try:
        start({
            "prompt": "cinematic dream pop",
            "lyrics": "[Verse]\nAcross the night",
            "count": "many",
        })
    except _HTTPException as error:
        assert error.status_code == 400
        assert "integer from 1 to 3" in error.detail
    else:
        raise AssertionError("Invalid candidate count should return HTTP 400")


def test_worker_runs_one_correlated_provider_operation_per_candidate(
    tmp_path, monkeypatch,
):
    namespace = _base_namespace(tmp_path)
    _load(
        "_minimax_music_job_update",
        "_minimax_music_child_update",
        "_minimax_music_claim_candidate",
        "_finish_unstarted_music_children",
        "_run_minimax_music_job",
        namespace=namespace,
    )
    job_id = "minimax-music-123456abcdef"
    namespace["_minimax_music_jobs"][job_id] = _job(job_id, 2)
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        index = len(calls)
        return [{
            "filename": f"candidate-{index}.mp3",
            "audio_path": str(tmp_path / f"candidate-{index}.mp3"),
            "duration_seconds": 60,
            "provider": "minimax",
            "model": "music-3.0",
            "task_id": kwargs["task_id"],
            "root_task_id": kwargs["root_task_id"],
        }]

    monkeypatch.setattr(minimax_music_service, "generate_candidates", generate)
    namespace["_run_minimax_music_job"](job_id)

    completed = namespace["_minimax_music_jobs"][job_id]
    assert completed["status"] == "completed"
    assert completed["current"] == 2
    assert len(calls) == 2
    assert [call["count"] for call in calls] == [1, 1]
    assert [call["task_id"] for call in calls] == [
        child["taskId"] for child in completed["children"]
    ]
    assert all(child["status"] == "completed" for child in completed["children"])


def test_cancellation_during_provider_call_preserves_returned_audio_and_stops_queue(
    tmp_path, monkeypatch,
):
    namespace = _base_namespace(tmp_path)
    _load(
        "_minimax_music_job_update",
        "_minimax_music_child_update",
        "_minimax_music_claim_candidate",
        "_finish_unstarted_music_children",
        "_run_minimax_music_job",
        namespace=namespace,
    )
    job_id = "minimax-music-fedcba654321"
    namespace["_minimax_music_jobs"][job_id] = _job(job_id, 2)
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        namespace["_minimax_music_jobs"][job_id]["_cancel_requested"] = True
        return [{
            "filename": "preserved.mp3",
            "audio_path": str(tmp_path / "preserved.mp3"),
            "duration_seconds": 60,
            "provider": "minimax",
            "model": "music-3.0",
            "task_id": kwargs["task_id"],
            "root_task_id": kwargs["root_task_id"],
        }]

    monkeypatch.setattr(minimax_music_service, "generate_candidates", generate)
    namespace["_run_minimax_music_job"](job_id)

    cancelled = namespace["_minimax_music_jobs"][job_id]
    assert cancelled["status"] == "cancelled"
    assert cancelled["current"] == 1
    assert [item["filename"] for item in cancelled["candidates"]] == [
        "preserved.mp3",
    ]
    assert len(calls) == 1
    assert cancelled["children"][0]["status"] == "completed"
    assert cancelled["children"][1]["status"] == "cancelled"


def test_cancelled_waiter_cannot_regress_to_running_or_claim_provider(tmp_path):
    namespace = _base_namespace(tmp_path)
    _load(
        "_minimax_music_job_update",
        "_minimax_music_child_update",
        "_minimax_music_claim_candidate",
        namespace=namespace,
    )
    job_id = "minimax-music-aabbccddeeff"
    job = _job(job_id, 1)
    job.update(
        status="cancelled",
        phase="cancelled",
        _cancel_requested=True,
        finishedAt=time.time(),
    )
    job["children"][0].update(status="cancelled", phase="cancelled")
    namespace["_minimax_music_jobs"][job_id] = job

    namespace["_minimax_music_job_update"](
        job_id, status="running", phase="requesting",
    )
    claimed = namespace["_minimax_music_claim_candidate"](
        job_id, 0, "remote:https://api.minimax.io",
    )

    assert claimed is None
    assert namespace["_minimax_music_jobs"][job_id]["status"] == "cancelled"
    assert (
        namespace["_minimax_music_jobs"][job_id]["children"][0]["status"]
        == "cancelled"
    )

"""Atomic safe-boundary tests for asynchronous MiniMax image jobs."""

from __future__ import annotations

import ast
import copy
import threading
import time
from pathlib import Path


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "launch.py"
TREE = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))


def _function(name: str) -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            clone = copy.deepcopy(node)
            clone.decorator_list = []
            return clone
    raise AssertionError(f"Function {name!r} not found")


def _load(*names: str, namespace: dict) -> dict:
    module = ast.Module(
        body=[_function(name) for name in names],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    exec(compile(module, str(LAUNCH), "exec"), namespace)
    return namespace


def _namespace() -> dict:
    return {
        "copy": copy,
        "threading": threading,
        "time": time,
        "_minimax_image_jobs": {},
        "_minimax_image_jobs_lock": threading.RLock(),
        "_publish_minimax_image_job": lambda _job: None,
    }


def _job() -> dict:
    return {
        "jobId": "minimax-image-aabbccddeeff",
        "taskId": "task-minimax-image-aabbccddeeff",
        "status": "waiting_resource",
        "phase": "waiting_resource",
        "message": "Waiting",
        "_cancel_requested": False,
        "acquired_resources": [],
        "updatedAt": time.time(),
    }


def test_provider_claim_is_atomic_and_observable():
    namespace = _namespace()
    _load("_minimax_image_claim_provider", namespace=namespace)
    job = _job()
    namespace["_minimax_image_jobs"][job["jobId"]] = job

    claimed = namespace["_minimax_image_claim_provider"](
        job["jobId"], "remote:https://api.minimax.io",
    )

    assert claimed is not None
    assert claimed["status"] == "running"
    assert claimed["acquired_resources"] == [
        "remote:https://api.minimax.io",
    ]


def test_cancelled_waiter_cannot_regress_or_start_paid_provider_call():
    namespace = _namespace()
    _load(
        "_minimax_image_job_update",
        "_minimax_image_claim_provider",
        namespace=namespace,
    )
    job = _job()
    job.update(
        status="cancelled",
        phase="cancelled",
        _cancel_requested=True,
        finishedAt=time.time(),
    )
    namespace["_minimax_image_jobs"][job["jobId"]] = job

    namespace["_minimax_image_job_update"](
        job["jobId"], status="running", phase="requesting",
    )
    claimed = namespace["_minimax_image_claim_provider"](
        job["jobId"], "remote:https://api.minimax.io",
    )

    assert claimed is None
    assert namespace["_minimax_image_jobs"][job["jobId"]]["status"] == "cancelled"

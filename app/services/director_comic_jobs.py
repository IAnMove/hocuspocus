"""Comic plan job store for the full server.

The job dictionary, the active-job set and their lock stay here. The
workspace helper, the LLM routing calls and the Activity publisher are
injected by the full server and are the same objects the rest of the server
uses. ``director_comic_plan`` is injected too: this module does not import
the router. This module does not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
import traceback

from fastapi import HTTPException

# Injected by bind_director_comic_runtime. None until the full server binds them.
wgp = None
_effective_llm_routing = None
_ensure_llm_loaded = None
_workspace_dir = None
director_comic_plan = None
_publish_generic_legacy_task = None


# Comic planning can take several minutes on CPU-hosted Ollama models.  Keep
# the synchronous endpoint above for API compatibility, but let the WebUI use
# a background job so it receives an immediate acknowledgement and can show
# honest server-side state instead of waiting on one opaque HTTP request.
_comic_plan_jobs: dict[str, dict] = {}
_comic_plan_jobs_lock = threading.Lock()
_comic_plan_active_jobs: set[str] = set()


def _comic_plan_checkpoint_dir(workspace: str | None = None) -> str:
    path = os.path.join(_workspace_dir(workspace), ".comic-plan-checkpoints")
    os.makedirs(path, exist_ok=True)
    return path


def _comic_plan_checkpoint_path(job_id: str, workspace: str | None = None) -> str | None:
    if not re.fullmatch(r"comic-plan-job-[a-f0-9]{12}", job_id or ""):
        return None
    return os.path.join(_comic_plan_checkpoint_dir(workspace), f"{job_id}.json")


def _persist_comic_plan_job(job: dict) -> None:
    path = _comic_plan_checkpoint_path(
        str(job.get("jobId") or ""),
        str(job.get("workspace") or "default"),
    )
    if not path:
        return
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except Exception as exc:
        print(f"[Comic Director] Could not persist checkpoint {path}: {exc}")
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass


def _load_comic_plan_job(job_id: str, workspace: str | None = None) -> dict | None:
    path = _comic_plan_checkpoint_path(job_id, workspace)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            job = json.load(handle)
        return job if isinstance(job, dict) else None
    except Exception as exc:
        print(f"[Comic Director] Could not load checkpoint {path}: {exc}")
        return None


def _comic_plan_job_update(job_id: str, **patch) -> None:
    snapshot = None
    with _comic_plan_jobs_lock:
        job = _comic_plan_jobs.get(job_id)
        if job is not None:
            job.update(patch)
            job["updatedAt"] = time.time()
            snapshot = copy.deepcopy(job)
    if snapshot is not None:
        _persist_comic_plan_job(snapshot)
        publisher = globals().get("_publish_generic_legacy_task")
        if callable(publisher):
            try:
                publisher(snapshot, "comic-plan")
            except Exception as exc:
                print(f"[Task registry] Could not publish comic plan {job_id}: {exc}")


def _run_comic_plan_job_inner(job_id: str, body: dict) -> None:
    services = wgp.server_config.get("services", {})
    requested_provider = str(body.get("writingProvider") or "maestro").strip().lower()
    external = requested_provider not in ("", "maestro", "internal", "local")
    global_provider, global_model, _global_remote_url = _effective_llm_routing(services)
    provider = requested_provider if external else global_provider
    model = (
        str(body.get("writingModel") or (
            "deepseek-v4-pro" if provider == "deepseek"
            else "MiniMax-M3" if provider == "minimax"
            else "default"
        ))
        if external
        else global_model or "default"
    )
    try:
        print(f"[Comic Director {job_id}] Starting plan with provider={provider}, model={model}")
        _comic_plan_job_update(
            job_id,
            status="loading_llm",
            message=f"Connecting to {provider} LLM ({model})…",
            provider=provider,
            model=model,
        )
        if not external:
            _ensure_llm_loaded()
        _comic_plan_job_update(
            job_id,
            status="planning",
            message="The LLM is writing the page, panel and dialogue plan…",
        )
        result = director_comic_plan(body, job_id=job_id)
        _comic_plan_job_update(
            job_id,
            status="completed",
            message="Comic plan generated and validated.",
            result=result,
            finishedAt=time.time(),
        )
        print(f"[Comic Director {job_id}] Plan completed")
    except HTTPException as exc:
        print(f"[Comic Director {job_id}] Plan failed: {exc.detail}")
        _comic_plan_job_update(
            job_id,
            status="failed",
            message=str(exc.detail),
            error=str(exc.detail),
            finishedAt=time.time(),
        )
    except Exception as exc:
        print(f"[Comic Director {job_id}] Plan failed: {exc}")
        traceback.print_exc()
        _comic_plan_job_update(
            job_id,
            status="failed",
            message=f"Comic planning failed: {exc}",
            error=f"Comic planning failed: {exc}",
            finishedAt=time.time(),
        )


def _run_comic_plan_job(job_id: str, body: dict) -> None:
    """Run one claimed Comic planner and restore its canonical task context."""
    with _comic_plan_jobs_lock:
        _comic_plan_active_jobs.add(job_id)
        job = copy.deepcopy(_comic_plan_jobs.get(job_id) or {})
    try:
        from services.task_manager import task_context_scope

        workspace = str(job.get("workspace") or body.get("workspace") or "default")
        task_id = str(
            job.get("taskId") or f"task-comic-plan-{job_id}"
        )
        root_task_id = str(job.get("rootTaskId") or task_id)
        with task_context_scope(
            task_id=task_id,
            root_task_id=root_task_id,
            workspace=workspace,
            workspace_dir=_workspace_dir(workspace),
        ):
            _run_comic_plan_job_inner(job_id, body)
    finally:
        with _comic_plan_jobs_lock:
            _comic_plan_active_jobs.discard(job_id)


def _start_comic_plan_worker(
    job_id: str,
    body: dict,
    *,
    thread_name: str,
) -> bool:
    """Atomically prevent duplicate Comic planner threads in this process."""
    with _comic_plan_jobs_lock:
        if job_id in _comic_plan_active_jobs:
            return False
        _comic_plan_active_jobs.add(job_id)
    thread = threading.Thread(
        target=_run_comic_plan_job,
        args=(job_id, dict(body)),
        name=thread_name,
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        with _comic_plan_jobs_lock:
            _comic_plan_active_jobs.discard(job_id)
        raise
    return True

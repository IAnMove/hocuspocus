"""Queue recovery for generation jobs.

The handlers and helpers moved out of ``app/_launch_runtime.py`` without a body
edit. The full server calls ``bind`` once, after the objects these functions
read exist, and before the startup cleanup thread. ``_reset_canonical_task_for_resume``
is a forwarder: tests replace that name on the server module after import.
"""
import threading
import time

# Injected by bind(); None until the full server binds them.
_cancel_h3_idle_release = None
_durable_generation_queue = None
_image_generation_commands = None
_jobs = None
_list_workspaces = None
_new_generation_job = None
_persist_generation_job = None
_queue_recovery_lock = None
_reset_canonical_task_for_resume = None
_run_generation_with_preparation = None
_scene2d_export = None
_task_registry = None
_workspace_dir = None
_world3d_export = None


def bind(**names):
    """Take the full server's objects these functions use."""
    global _cancel_h3_idle_release, _durable_generation_queue, _image_generation_commands, _jobs
    global _list_workspaces, _new_generation_job, _persist_generation_job, _queue_recovery_lock
    global _reset_canonical_task_for_resume, _run_generation_with_preparation, _scene2d_export
    global _task_registry, _workspace_dir, _world3d_export
    _cancel_h3_idle_release = names["_cancel_h3_idle_release"]
    _durable_generation_queue = names["_durable_generation_queue"]
    _image_generation_commands = names["_image_generation_commands"]
    _jobs = names["_jobs"]
    _list_workspaces = names["_list_workspaces"]
    _new_generation_job = names["_new_generation_job"]
    _persist_generation_job = names["_persist_generation_job"]
    _queue_recovery_lock = names["_queue_recovery_lock"]
    _reset_canonical_task_for_resume = names["_reset_canonical_task_for_resume"]
    _run_generation_with_preparation = names["_run_generation_with_preparation"]
    _scene2d_export = names["_scene2d_export"]
    _task_registry = names["_task_registry"]
    _workspace_dir = names["_workspace_dir"]
    _world3d_export = names["_world3d_export"]


def _recovery_job_summary(record: dict) -> dict:
    params = record.get("params") if isinstance(record.get("params"), dict) else {}
    prompt = str(params.get("prompt") or params.get("lyrics") or "").strip()
    return {
        "job_id": str(record.get("id") or ""),
        "previous_status": str(record.get("status") or "queued"),
        "created_at": float(record.get("created_at") or 0),
        "workspace": str(record.get("workspace") or "default"),
        "model_type": str(params.get("model_type") or ""),
        "generation_mode": str(params.get("generation_mode") or ""),
        "prompt_preview": prompt[:240],
    }

def get_generation_queue_recovery():
    """Return crash leftovers that are not active in this server process."""
    with _queue_recovery_lock:
        _image_generation_commands.restore_recovery(item["name"] for item in _list_workspaces())
        candidates = _image_generation_commands.filter_recovery(
            _durable_generation_queue.list(exclude_ids=_jobs.keys()))
    return {"jobs": [_recovery_job_summary(record) for record in candidates]}

def _queue_recovered_generation(record: dict):
    """Put one durable leftover back on the live queue without starting it.

    Returns ``(job, created)``. ``created`` is false when that id is already
    live, so resume cannot start a second worker for the same leftover.
    """
    job_id = str(record.get("id") or "").strip()
    params = record.get("params")
    if not job_id or not isinstance(params, dict) or not params.get("model_type"):
        if job_id:
            _durable_generation_queue.remove(job_id)
        return None, False
    existing = _jobs.get(job_id)
    if existing is not None:
        return existing, False
    workspace = str(record.get("workspace") or "default")
    _reset_canonical_task_for_resume(
        workspace,
        f"task-generation-{job_id}",
    )
    job = _new_generation_job(
        params,
        workspace,
        job_id=job_id,
        created_at=float(record.get("created_at") or time.time()),
        recovered=True,
        reserve_generation=not isinstance(
            params.get("_h3_window_plan_pending"), dict,
        ),
        provenance=record.get("provenance") if isinstance(record.get("provenance"), dict) else None,
    )
    _jobs[job_id] = job
    _persist_generation_job(job)
    _cancel_h3_idle_release()
    return job, True

def resume_generation_queue():
    """Requeue persisted requests in their original submission order.

    An interrupted running request restarts from its beginning: model runtimes
    do not expose a portable mid-diffusion checkpoint.
    """
    resumed: list[dict] = []
    threads: list[threading.Thread] = []
    with _queue_recovery_lock:
        _image_generation_commands.restore_recovery(item["name"] for item in _list_workspaces())
        candidates = _image_generation_commands.filter_recovery(
            _durable_generation_queue.list(exclude_ids=_jobs.keys()))
        for record in candidates:
            job, created = _queue_recovered_generation(record)
            if not created or job is None:
                continue
            threads.append(threading.Thread(
                target=_run_generation_with_preparation,
                args=(job["id"],),
                name=f"recovered-generation-{job['id']}",
                daemon=False,
            ))
            resumed.append(_recovery_job_summary(record))

        # Populate the complete in-memory queue before any worker can finish,
        # then start in saved order so the existing GPU mutex serialises it.
        for thread in threads:
            thread.start()
    return {"resumed": resumed, "count": len(resumed)}

def discard_generation_queue():
    """Clear only inactive recovery candidates; never cancel live work."""
    with _queue_recovery_lock:
        _image_generation_commands.restore_recovery(item["name"] for item in _list_workspaces())
        _image_generation_commands.discard_recovery(
            _durable_generation_queue.list(exclude_ids=_jobs.keys()))
        removed = _durable_generation_queue.discard(exclude_ids=_jobs.keys())
    return {"discarded": removed}

def _prepare_generation_leftovers(records):
    _image_generation_commands.restore_recovery(item["name"] for item in _list_workspaces())
    return _image_generation_commands.filter_recovery(records)

def _start_recovered_generation(job):
    threading.Thread(
        target=_run_generation_with_preparation,
        args=(job["id"],),
        name=f"recovered-generation-{job['id']}",
        daemon=False,
    ).start()

def _discard_generation_leftover(record):
    _image_generation_commands.discard_recovery([record])
    _durable_generation_queue.remove(str(record.get("id") or ""))

def _release_intermediates_at_startup() -> None:
    """Frames of published exports, raw voice takes and stale temp folders go; live and resumable work is kept."""
    from services.workspace_cleanup import startup_cleanup
    from services.world3d_export import staging_token
    names = [item.get("name") for item in _list_workspaces() if isinstance(item, dict) and item.get("name")]
    startup_cleanup(names, _workspace_dir, _task_registry, {_world3d_export.operation, _scene2d_export.operation}, staging_token)

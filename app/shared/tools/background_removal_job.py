"""Lifecycle worker for the Tools background-removal operation.

The runtime injects its existing GPU/FIFO and Activity callbacks. Keeping the
worker here prevents the launch module from growing another post-processing
implementation while preserving the same cancellation and task semantics as
upscale and revoice.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, MutableMapping
from contextlib import AbstractContextManager
from typing import Any

from .background_removal import remove_background_file


class BackgroundRemovalJobHooks:
    """Runtime-owned lifecycle seams used by the isolated worker."""

    def __init__(
        self,
        *,
        generation_slot: Callable[[MutableMapping[str, Any]], AbstractContextManager[bool]],
        try_start: Callable[..., bool],
        update_job: Callable[..., bool],
        finish_job: Callable[..., bool],
        is_cancel_requested: Callable[[MutableMapping[str, Any]], bool],
        record_job_outputs: Callable[..., Any],
        register_abort_state: Callable[..., bool],
        unregister_abort_state: Callable[..., None],
        acknowledge_cancel: Callable[..., bool] | None = None,
        active_states: MutableMapping[str, MutableMapping[str, Any]],
        publish_sidecar: Callable[[dict[str, Any], str, dict[str, Any]], None],
        simulated_artifact: Callable[..., str] | None = None,
    ) -> None:
        self.generation_slot = generation_slot
        self.try_start = try_start
        self.update_job = update_job
        self.finish_job = finish_job
        self.is_cancel_requested = is_cancel_requested
        self.record_job_outputs = record_job_outputs
        self.register_abort_state = register_abort_state
        self.unregister_abort_state = unregister_abort_state
        self.acknowledge_cancel = acknowledge_cancel
        self.active_states = active_states
        self.publish_sidecar = publish_sidecar
        self.simulated_artifact = simulated_artifact


def build_background_removal_job(
    *,
    job_id: str,
    workspace: str,
    output_dir: str,
    source_path: str,
    source_filename: str,
    source_workspace: str,
    source_asset_id: str,
    uploads_root: str,
    source_root: str,
    provenance: dict[str, Any],
    instruction: str,
) -> dict[str, Any]:
    """Build the shared queue record consumed by the Tools worker."""
    return {
        "id": job_id,
        "status": "queued",
        "progress": 0,
        "step": 0,
        "total_steps": 0,
        "phase": "",
        "message": "Queued (background removal)",
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "params": {
            "source": source_filename,
            "source_asset_id": source_asset_id,
            "source_filename": source_filename,
            "source_workspace": source_workspace,
            "instruction": instruction,
            "model": "u2net",
            "model_type": "rembg-u2net",
            "provider": "local",
            "generation_mode": "image",
            "capability": "remove_background",
            "_non_durable_tool": "remove_background",
            "_source_path": source_path,
            "_uploads_root": uploads_root,
            "_workspace_root": source_root,
            "_destination_workspace_root": output_dir,
        },
        "output_files": [],
        "error": None,
        "workspace": workspace,
        "out_dir": output_dir,
        "provenance": provenance,
    }


def _public_params(params: MutableMapping[str, Any]) -> dict[str, Any]:
    """Drop private host paths before writing a durable asset sidecar."""
    return {
        str(key): value
        for key, value in params.items()
        if not str(key).startswith("_")
    }


def _remove_output(path: str | None) -> None:
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _settle_cancel(
    job: MutableMapping[str, Any],
    *,
    hooks: BackgroundRemovalJobHooks,
    output_path: str | None = None,
) -> bool:
    """Remove partial output and settle a cancellation when the host supports it."""
    _remove_output(output_path)
    if hooks.acknowledge_cancel is not None:
        hooks.acknowledge_cancel(job)
    return False


def run_remove_background_job(
    job: MutableMapping[str, Any],
    *,
    hooks: BackgroundRemovalJobHooks,
) -> bool:
    """Run one queued background-removal job through the shared lifecycle."""
    job_id = str(job.get("id") or "")
    abort_state: dict[str, Any] = {"abort": False}
    registered = False
    output_path: str | None = None

    with hooks.generation_slot(job) as acquired:
        if not acquired:
            return False
        try:
            if not hooks.try_start(
                job,
                message="Preparing background removal…",
                phase="Preparing",
            ):
                return False
            started_at = float(job.get("started_at") or time.time())
            registered = hooks.register_abort_state(
                job,
                job_id,
                hooks.active_states,
                abort_state,
            )
            if not registered:
                # Cancellation can win in the small window after try_start
                # and before the worker registers its abort state.  The
                # normal lifecycle worker acknowledges that race explicitly;
                # keep Tools from leaving a job in ``cancelling`` forever.
                if hooks.acknowledge_cancel is not None:
                    hooks.acknowledge_cancel(job)
                return False

            # A cancellation may land immediately after the abort state is
            # registered. Settle it before validating or touching the source
            # so a cancelled request cannot be reported as an input failure.
            if hooks.is_cancel_requested(job):
                return _settle_cancel(job, hooks=hooks)

            params = job.get("params") if isinstance(job.get("params"), dict) else {}
            workspace = str(job.get("workspace") or "default")
            output_dir = str(job.get("out_dir") or "")
            source_path = str(params.get("_source_path") or params.get("source") or "")
            uploads_root = str(params.get("_uploads_root") or "")
            workspace_root = str(params.get("_workspace_root") or output_dir)
            destination_workspace_root = str(
                params.get("_destination_workspace_root") or output_dir
            )
            model = str(params.get("model") or "u2net")

            if not source_path:
                hooks.finish_job(
                    job,
                    "failed",
                    error="Image source is required",
                    message="Error: image source is required",
                )
                return False
            if not output_dir:
                hooks.finish_job(
                    job,
                    "failed",
                    error="Output workspace is unavailable",
                    message="Error: output workspace is unavailable",
                )
                return False

            def progress(message: str, value: int, step: int, total: int) -> None:
                hooks.update_job(
                    job,
                    message=message,
                    progress=value,
                    step=step,
                    total_steps=total,
                    phase="Background removal",
                )

            if hooks.is_cancel_requested(job):
                return _settle_cancel(job, hooks=hooks)
            if hooks.simulated_artifact is not None and str(
                params.get("_execution_mode") or "real"
            ) == "simulate":
                output_path = hooks.simulated_artifact(
                    {**params, "generation_mode": "image"},
                    output_dir,
                    job_id,
                    progress=progress,
                    cancelled=lambda: hooks.is_cancel_requested(job),
                )
                result: dict[str, Any] = {
                    "path": output_path,
                    "filename": os.path.basename(output_path),
                    "original": os.path.basename(source_path),
                    "width": None,
                    "height": None,
                    "alpha": None,
                    "method": "simulation",
                    "model": model,
                }
            else:
                if not hooks.update_job(
                    job,
                    message="Removing image background (U2Net)…",
                    phase="Background removal",
                    progress=10,
                ):
                    return False
                result = remove_background_file(
                    source_path,
                    uploads_root=uploads_root,
                    workspace_root=workspace_root,
                    output_dir=output_dir,
                    destination_workspace_root=destination_workspace_root,
                    model=model,
                )
                output_path = str(result.get("path") or "")

            if hooks.is_cancel_requested(job):
                return _settle_cancel(job, hooks=hooks, output_path=output_path)
            filename = str(result.get("filename") or "")
            if not output_path or not filename:
                raise RuntimeError("Background removal did not produce an output")
            hooks.record_job_outputs(job, [filename])

            elapsed = max(0.0, time.time() - started_at)
            public_params = _public_params(params)
            public_params.update({
                "model_type": "rembg-u2net",
                "provider": "local",
                "generation_mode": "image",
                "source_asset_id": params.get("source_asset_id"),
                "source_filename": params.get("source_filename") or result.get("original"),
            })
            simulated = str(params.get("_execution_mode") or "real") == "simulate"
            sidecar = {
                "params": public_params,
                "generation_mode": "image",
                "tool": "remove_background",
                "capability": params.get("capability") or "remove_background",
                "tool_source": params.get("source_filename") or result.get("original"),
                "job_id": job_id,
                "task_id": job.get("task_id"),
                "root_task_id": job.get("root_task_id") or job.get("task_id"),
                "output_filename": filename,
                "generation_time": elapsed,
                "created_at": job.get("created_at") or time.time(),
                "queued_at": job.get("created_at"),
                "started_at": started_at,
                "completed_at": time.time(),
                "status": "completed",
                "simulated": simulated,
                "execution_mode": "simulate" if simulated else "real",
                "inputs": [{
                    "id": params.get("source_asset_id"),
                    "kind": "image",
                    "uri": params.get("source_filename") or result.get("original"),
                    "role": "source",
                }],
                "parents": [{
                    "id": params.get("source_asset_id"),
                    "kind": "image",
                    "uri": params.get("source_filename") or result.get("original"),
                    "role": "source",
                }],
                "transformations": [{
                    "type": "background_removal",
                    "backend": "rembg",
                    "model": result.get("model") or model,
                    "method": result.get("method") or "rembg-u2net",
                }],
                "technical": {
                    "width": result.get("width"),
                    "height": result.get("height"),
                    "alpha": result.get("alpha"),
                    "output": "transparent_png",
                },
            }
            # A missing source ID is only possible for an unmanaged upload;
            # never emit a malformed lineage reference in that case.
            sidecar["inputs"] = [
                item for item in sidecar["inputs"] if item.get("id")
            ]
            sidecar["parents"] = [
                item for item in sidecar["parents"] if item.get("id")
            ]
            hooks.publish_sidecar(job, output_path, sidecar)
            return hooks.finish_job(
                job,
                "completed",
                progress=100,
                phase="",
                message="Done · background removed",
            )
        except InterruptedError:
            return _settle_cancel(job, hooks=hooks, output_path=output_path)
        except Exception as exc:
            _remove_output(output_path)
            hooks.finish_job(job, "failed", error=str(exc), message=f"Error: {exc}")
            return False
        finally:
            if registered:
                hooks.unregister_abort_state(job_id, hooks.active_states, abort_state)


__all__ = ["BackgroundRemovalJobHooks", "run_remove_background_job"]

"""Run one queued ``minimax:`` image job: call MiniMax Image-01 and settle the job like any other generation.

The job is an ordinary generation job (same id, task, receipt, status, cancel, queue recovery). Two things differ:
it is never registered in the local GPU queue, and its worker waits for an HTTP answer instead of a model. A cancel that
arrives while the request is in flight cannot recall it, so the job ends ``cancelled`` and the picture that came back is
deleted (the provider already counted the call).
"""
from __future__ import annotations

import os
import time
import traceback
from collections.abc import Callable, Mapping
from typing import Any

from services.asset_manifest import sidecar_path
from services.job_lifecycle import (
    acknowledge_cancel,
    finish_job,
    is_cancel_requested,
    record_job_outputs,
    try_start,
)
from services.minimax_h3_image_service import is_h3_image_model
from services.minimax_image_service import (
    MODEL_ID,
    MiniMaxImageError,
    aspect_ratio_for_resolution,
    generate_image,
    local_image_data_uri,
)
from services.remote_image_generation import KEY_MISSING, api_key, is_remote_image_params, lane_key


def is_remote_image_job(job: Any) -> bool:
    return isinstance(job, Mapping) and is_remote_image_params(job.get("params"))


def _forget(path: str) -> None:
    for target in (path, str(sidecar_path(path))):
        try:
            os.remove(target)
        except OSError:
            pass


def _sidecar(job: Mapping[str, Any], params: Mapping[str, Any], result: Mapping[str, Any], started: float) -> dict[str, Any]:
    return {
        "params": {
            "prompt": result["prompt"],
            "model_type": result.get("model_type") or MODEL_ID,
            "provider": "minimax",
            "resolution": result.get("size") or params.get("resolution"),
            "aspect_ratio": result["aspect_ratio"],
            "subject_reference": bool(result.get("subject_reference")),
            "generation_mode": "image",
            **({"revised_prompt": result["revised_prompt"]} if result.get("revised_prompt") else {}),
        },
        "generation_mode": "image",
        "job_id": job.get("id"),
        "task_id": job.get("task_id"),
        "root_task_id": job.get("root_task_id") or job.get("task_id"),
        "output_filename": result["name"],
        "generation_time": round(time.time() - started, 2),
        "created_at": time.time(),
    }


def _image01_request(job: Mapping[str, Any], params: Mapping[str, Any], key: str) -> dict[str, Any]:
    references = [item for item in params.get("image_refs") or [] if item]
    resolution = str(params.get("resolution") or "")
    return {
        "api_key": key,
        "prompt": str(params.get("prompt") or ""),
        "aspect_ratio": str(params.get("aspect_ratio") or aspect_ratio_for_resolution(resolution)),
        "output_dir": str(job["out_dir"]),
        "subject_reference": local_image_data_uri(str(references[0])) if references else "",
        "filename_prefix": "minimax-image-01",
        "task_id": str(job.get("task_id") or ""),
        "root_task_id": str(job.get("root_task_id") or job.get("task_id") or ""),
        "output_name": params.get("output_filename") or params.get("output_name") or None,
    }


def _request(job: Mapping[str, Any], params: Mapping[str, Any], services: Mapping[str, Any]) -> dict[str, Any]:
    key = api_key(services)
    if not key:
        raise MiniMaxImageError(KEY_MISSING, 409)
    model = str(params.get("model_type") or "")
    if is_h3_image_model(model):
        return _h3_request(job, params, key, model)
    if model != MODEL_ID:
        raise MiniMaxImageError(f"Unknown MiniMax image model: {model}", 422)
    return _image01_request(job, params, key)


def _h3_request(job: Mapping[str, Any], params: Mapping[str, Any], key: str, model: str) -> dict[str, Any]:
    return {
        "api_key": key,
        "model_type": model,
        "prompt": str(params.get("prompt") or ""),
        "resolution": str(params.get("resolution") or ""),
        "output_dir": str(job["out_dir"]),
        "reference_paths": [item for item in params.get("image_refs") or [] if item],
        "disable_prompt_enhanced": bool(params.get("disable_prompt_enhanced")),
        "task_id": str(job.get("task_id") or ""),
        "root_task_id": str(job.get("root_task_id") or job.get("task_id") or ""),
        "output_name": params.get("output_filename") or params.get("output_name") or None,
    }


def _call(request: dict[str, Any]) -> dict[str, Any]:
    if is_h3_image_model(request.get("model_type")):
        from services.minimax_h3_image_service import generate_image as generate_h3_image

        return generate_h3_image(**request)
    return generate_image(**request)


def _generate(job: dict[str, Any], services: Mapping[str, Any], publish_sidecar: Callable[..., Any]) -> bool:
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    notes = [str(item) for item in params.get("_remote_notes") or []]
    request = _request(job, params, services)
    started = time.time()
    result = _call(request)
    if is_cancel_requested(job):
        _forget(result["path"])
        return False
    record_job_outputs(job, [result["name"]])
    try:
        publish_sidecar(job, result["path"], _sidecar(job, params, result, started))
    except Exception as exc:
        print(f"[MiniMax image] sidecar publish failed for {result['name']}: {exc}")
    message = "Done" + (" · " + "; ".join(notes) if notes else "")
    return finish_job(job, "completed", progress=100, step=1, total_steps=1, phase="", message=message)


def run_remote_image_job(
    job: dict[str, Any],
    *,
    services: Callable[[], Mapping[str, Any]],
    publish_sidecar: Callable[..., Any],
    remove_persisted: Callable[[dict[str, Any]], Any],
) -> bool:
    """Start, call the API, settle. Returns True when the job completed."""
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    h3 = is_h3_image_model(params.get("model_type"))
    label = "MiniMax H3-Image" if h3 else "MiniMax Image-01"
    refs = [item for item in params.get("image_refs") or [] if item]
    with_refs = ""
    if refs and h3:
        with_refs = f" with {len(refs)} reference picture" + ("s" if len(refs) != 1 else "")
    elif refs:
        with_refs = " with 1 character reference"
    try:
        started = try_start(
            job, phase=f"Calling {label}", progress=10, step=0, total_steps=1,
            message=f"Calling {label} (remote, no GPU){with_refs}",
            acquired_resources=[lane_key()],
        )
        return bool(started and _generate(job, services(), publish_sidecar))
    except Exception as exc:
        if not isinstance(exc, MiniMaxImageError):
            traceback.print_exc()
        finish_job(job, "failed", error=str(exc), message=f"Error: {exc}")
        return False
    finally:
        # No abort registration exists for an HTTP call: this settles a cancel that arrived meanwhile.
        acknowledge_cancel(job)
        remove_persisted(job)

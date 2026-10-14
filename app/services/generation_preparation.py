"""Generation preparation, the simulated executor and the local GPU handoff.

The three functions moved out of ``app/_launch_runtime.py`` without a body
edit. The full server calls ``bind`` once, after the image-command service
exists, and before startup cleanup. ``_run_generation`` is a forwarder:
tests replace that name on the server module after import, and the
preparation worker calls it.
"""
import copy
import gc
import os
import time
import traceback

import torch
from fastapi import HTTPException

from services import execution_mode, minimax_h3_service, resource_scheduler
from services.job_lifecycle import (
    acknowledge_cancel,
    finish_job,
    is_cancel_requested,
    record_job_outputs,
    try_requeue,
    try_start,
    update_job,
)

# Injected by bind(); None until the full server binds them.
_PUBLIC_LLM_PROVIDERS = None
_effective_llm_routing = None
_ensure_llm_loaded = None
_image_generation_commands = None
_jobs = None
_persist_generation_job = None
_publish_generation_sidecar_for_studio_job = None
_remove_persisted_generation_job = None
_run_generation = None
_workspace_dir = None
wgp = None


def bind(**names):
    """Take the full server's objects these functions use."""
    global _PUBLIC_LLM_PROVIDERS, _effective_llm_routing, _ensure_llm_loaded
    global _image_generation_commands, _jobs, _persist_generation_job
    global _publish_generation_sidecar_for_studio_job, _remove_persisted_generation_job
    global _run_generation, _workspace_dir, wgp
    _PUBLIC_LLM_PROVIDERS = names["_PUBLIC_LLM_PROVIDERS"]
    _effective_llm_routing = names["_effective_llm_routing"]
    _ensure_llm_loaded = names["_ensure_llm_loaded"]
    _image_generation_commands = names["_image_generation_commands"]
    _jobs = names["_jobs"]
    _persist_generation_job = names["_persist_generation_job"]
    _publish_generation_sidecar_for_studio_job = names["_publish_generation_sidecar_for_studio_job"]
    _remove_persisted_generation_job = names["_remove_persisted_generation_job"]
    _run_generation = names["_run_generation"]
    _workspace_dir = names["_workspace_dir"]
    wgp = names["wgp"]


def _prepare_local_gpu_owner(
    _lane: resource_scheduler.ResourceLane,
    _task_id: str,
    description: str,
) -> None:
    """Hand GPU 0 to one engine without retaining incompatible runtimes."""
    owner_kind = resource_scheduler.gpu_engine_kind(description)
    is_legacy_h3 = owner_kind == resource_scheduler.GPU_ENGINE_H3_LEGACY
    is_wgp_generation = owner_kind == resource_scheduler.GPU_ENGINE_WGP
    is_local_llm = owner_kind == resource_scheduler.GPU_ENGINE_LOCAL_LLM

    if not is_legacy_h3:
        minimax_h3_service.cancel_idle_shutdown()
        minimax_h3_service.stop_runtime()
    released_wgp = False
    if not is_wgp_generation and (
        getattr(wgp, "wan_model", None) is not None
        or getattr(wgp, "offloadobj", None) is not None
    ):
        print(
            f"[Resources] Releasing WGP runtime before "
            f"{description or 'the next local GPU owner'}"
        )
        wgp.release_model()
        released_wgp = True
    if not is_local_llm:
        try:
            from services import llm_service
            llm_status = llm_service.get_status()
            if (
                llm_status.get("provider") == "local"
                and str(llm_status.get("device") or "").startswith("cuda")
            ):
                llm_service.unload_model()
        except Exception as exc:
            print(f"[Resources] Local CUDA LLM cleanup skipped: {exc}")
    # release_model() already flushes Torch caches and performs collection.
    # Repeating that native teardown immediately was both redundant and, when
    # handing ACE-Step to isolated H3 ConvRot, could finalize extension-owned
    # objects twice at the exact boundary where the process previously died.
    if not released_wgp:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

def _run_generation_with_preparation(job_id: str) -> bool:
    """Finish deferred, non-GPU preparation before entering generation FIFO.

    H3 window planning may load an LLM or call a remote provider.  It must not
    block ``POST /generate`` and it must not reserve the scarce video lane
    while doing so.  The pending request is persisted inside the job params so
    crash recovery can replay this same worker before starting inference.
    """
    job = _jobs.get(job_id)
    if not isinstance(job, dict):
        return False
    try:
        native_worker = _image_generation_commands.native_worker(job)
    except HTTPException as error:
        finish_job(job, "failed", error=str(error.detail), message="Command recovery could not be verified")
        return False
    if native_worker is not None:
        return bool(native_worker(job_id))
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    pending = params.get("_h3_window_plan_pending")
    if not isinstance(pending, dict):
        return bool(_run_generation(job_id))
    if is_cancel_requested(job):
        _remove_persisted_generation_job(job)
        return False
    if not try_start(
        job,
        phase="planning",
        message="Planning H3 window-by-window prompts with the writing model…",
        acquired_resources=[],
    ):
        if is_cancel_requested(job):
            _remove_persisted_generation_job(job)
        return False

    _persist_generation_job(job)
    planner_llm = None
    try:
        from services import llm_service as planner_llm
        from services.h3_window_planner import plan_h3_sliding_windows

        def _plan_windows():
            try:
                _ensure_llm_loaded()
            except Exception as load_error:
                # The planner has a deterministic fallback, so a missing
                # optional LLM must not make an otherwise valid H3 job fail.
                print(
                    "[MiniMax H3] Planner LLM unavailable; using fallback: "
                    f"{load_error}"
                )
            services = wgp.server_config.get("services", {})
            provider = _effective_llm_routing(services)[0]
            nsfw = (
                services.get("nsfw_mode", False)
                and provider not in _PUBLIC_LLM_PROVIDERS
            )
            expected_count = int(pending.get("expected_count") or 0)
            if expected_count <= 0:
                raise RuntimeError("H3 window plan has no target windows")
            print(
                f"[MiniMax H3] Planning {expected_count} window-local prompts "
                "after VRAM-safe geometry "
                f"({int(pending.get('window_frames') or 0)} frames/window)."
            )
            result = plan_h3_sliding_windows(
                str(params.get("prompt") or ""),
                model_type=str(pending.get("model_type") or ""),
                resolution=str(pending.get("resolution") or ""),
                total_frames=int(pending.get("total_frames") or 0),
                window_frames=int(pending.get("window_frames") or 0),
                overlap_frames=int(pending.get("overlap_frames") or 0),
                discard_frames=int(pending.get("discard_frames") or 0),
                fps=float(pending.get("fps") or 24),
                has_start_image=bool(pending.get("has_start_image")),
                has_end_image=bool(pending.get("has_end_image")),
                image_paths=list(pending.get("image_paths") or []) or None,
                nsfw=bool(nsfw),
                planning_style=str(pending.get("planning_style") or "faithful"),
                h3_audio_policy=str(pending.get("h3_audio_policy") or "native"),
                reference_context=str(pending.get("reference_context") or ""),
            )
            prompts = result.get("window_prompts") if isinstance(result, dict) else None
            if (
                not isinstance(prompts, list)
                or len(prompts) != expected_count
                or not all(isinstance(item, str) and item.strip() for item in prompts)
            ):
                raise RuntimeError(
                    "H3 window planner returned an incomplete prompt plan "
                    f"({len(prompts) if isinstance(prompts, list) else 0}/"
                    f"{expected_count})"
                )
            return result, list(prompts)

        # Correlate any child LLM call with the visible generation root.  The
        # fallback keeps model-free tests and older embedded callers working.
        try:
            from services.task_manager import task_context_scope
        except Exception:
            planned, window_prompts = _plan_windows()
        else:
            with task_context_scope(
                task_id=job.get("task_id"),
                root_id=job.get("root_task_id") or job.get("task_id"),
                workspace=job.get("workspace") or "default",
                workspace_dir=job.get("out_dir")
                or _workspace_dir(job.get("workspace") or "default"),
            ):
                planned, window_prompts = _plan_windows()

        if is_cancel_requested(job):
            _remove_persisted_generation_job(job)
            return False
        prepared_params = copy.deepcopy(params)
        prepared_params.pop("_h3_window_plan_pending", None)
        prepared_params["minimax_h3_window_storyboard"] = True
        prepared_params["h3_window_prompts"] = window_prompts
        prepared_params["h3_window_plan_signature"] = str(
            pending.get("signature") or ""
        )
        prepared_params["h3_window_plan"] = planned
        if not update_job(
            job,
            params=prepared_params,
            phase="planning",
            message=(
                f"H3 prompt plan ready ({len(window_prompts)} windows); "
                "queuing video generation…"
            ),
        ):
            _remove_persisted_generation_job(job)
            return False
        _persist_generation_job(job)
        if not try_requeue(
            job,
            phase="waiting_resource",
            message="H3 prompt plan ready · waiting for the local video GPU…",
            started_at=None,
        ):
            _remove_persisted_generation_job(job)
            return False
        _persist_generation_job(job)
        return bool(_run_generation(job_id))
    except Exception as error:
        traceback.print_exc()
        if not is_cancel_requested(job):
            finish_job(
                job,
                "failed",
                error=str(error),
                message=f"H3 window planning failed: {error}",
                phase="planning",
            )
        _remove_persisted_generation_job(job)
        return False
    finally:
        # A local writing model cannot remain beside H3's 20B/33B runtime.
        if planner_llm is not None:
            try:
                if (
                    planner_llm.is_loaded()
                    and planner_llm.get_status().get("provider") == "local"
                ):
                    planner_llm.unload_model()
            except Exception as unload_error:
                print(f"[MiniMax H3] Planner LLM unload skipped: {unload_error}")
        # Deferred planning has no abort-state registration. Confirm terminal
        # cancellation only after the planner call and its model cleanup have
        # both returned.
        acknowledge_cancel(job)

def _run_simulated_generation(job: dict, *, finalize: bool) -> bool:
    """Replace only expensive inference while retaining the real job path."""
    params = job.get("params") if isinstance(job.get("params"), dict) else {}

    def publish_progress(message: str, value: int, step: int, total: int) -> None:
        update_job(
            job,
            message=message,
            progress=value,
            step=step,
            total_steps=total,
            phase="Simulated inference",
        )

    try:
        generated_path = execution_mode.create_artifact(
            params,
            job["out_dir"],
            str(job["id"]),
            progress=publish_progress,
            cancelled=lambda: is_cancel_requested(job),
        )
    except InterruptedError:
        # Cancellation is settled by _run_generation's finally block, after
        # the simulated executor has stopped and shared cleanup has completed.
        return False
    output_name = os.path.basename(generated_path)
    record_job_outputs(job, [output_name])
    tool_job = str(params.get("_non_durable_tool") or "") in {"upscale", "revoice"}
    sidecar_params = params
    if tool_job:
        # Simulation still exercises the real queue/task/manifest path, but
        # host filesystem paths and uploaded voice references must never enter
        # the durable sidecar.
        sidecar_params = {
            key: value
            for key, value in params.items()
            if not str(key).startswith("_")
            and key not in {"source_path", "video_path", "voice_ref_paths"}
        }
    sidecar = {
        "params": sidecar_params,
        "generation_mode": params.get("generation_mode"),
        "tool": "tools" if tool_job else None,
        "capability": params.get("capability") if tool_job else None,
        "job_id": job.get("id"),
        "task_id": job.get("task_id"),
        "root_task_id": job.get("root_task_id") or job.get("task_id"),
        "output_filename": output_name,
        "generation_time": 0,
        "created_at": time.time(),
        "simulated": True,
        "execution_mode": "simulate",
    }
    if tool_job:
        sidecar["inputs"] = params.get("inputs") or []
        sidecar["parents"] = params.get("parents") or []
        sidecar["transformations"] = params.get("transformations") or []
    _publish_generation_sidecar_for_studio_job(job, generated_path, sidecar)
    if not finalize:
        return update_job(
            job,
            progress=99,
            step=0,
            total_steps=0,
            phase="Finalizing",
            message="Simulated inference complete · finalizing…",
        )
    return finish_job(
        job,
        "completed",
        progress=100,
        step=0,
        total_steps=0,
        phase="",
        message="Done · simulated artifact",
    )

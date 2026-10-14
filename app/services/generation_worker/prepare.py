"""The start of a generation run: the frame, the GPU slot, the preflight and the task manifest.

Part of the generation worker (``services.generation_worker``). The functions are the bodies that
``_run_generation`` and its phases had in ``app/_launch_runtime.py``, moved without edits. The objects
they use from the full server are injected by ``bind`` (called by ``bind_generation_worker``) and are
the same objects the rest of the server uses; this module does not import WanGP, a router or
``_launch_runtime``.
"""

import os
import time
import traceback
from services import execution_mode, minimax_h3_service, safe_download
from services.job_lifecycle import (
    acknowledge_cancel,
    finish_job,
    is_cancel_requested,
    record_job_outputs,
    register_abort_state,
    try_start,
    unregister_abort_state,
    update_job,
)
from services.media_paths import resolve_voice_ref_paths
from services.generation_worker.tasks import _run_generation_queue

# Injected by bind(); None until the full server binds them.
_active_gen_states = None
_apply_per_job_coefficient = None
_cancel_h3_idle_release = None
_coordinated_generation_slot = None
_ensure_managed_loras_present = None
_interrupt_wan_model = None
_is_legacy_h3_model = None
_is_minimax_h3_model = None
_jobs = None
_local_gpu_lane = None
_persist_generation_job = None
_publish_generation_sidecar_for_studio_job = None
_release_h3_when_queue_allows = None
_release_legacy_h3_when_queue_allows = None
_remove_persisted_generation_job = None
_resolve_video_editor_source = None
_restore_base_coefficient = None
_run_sfx_generation = None
_run_simulated_generation = None
_workspace_dir = None
wgp = None


def bind(**names):
    """Take the full server's objects this module uses (see bind_generation_worker)."""
    global _active_gen_states, _apply_per_job_coefficient, _cancel_h3_idle_release
    global _coordinated_generation_slot, _ensure_managed_loras_present, _interrupt_wan_model
    global _is_legacy_h3_model, _is_minimax_h3_model, _jobs, _local_gpu_lane
    global _persist_generation_job, _publish_generation_sidecar_for_studio_job
    global _release_h3_when_queue_allows, _release_legacy_h3_when_queue_allows
    global _remove_persisted_generation_job, _resolve_video_editor_source, _restore_base_coefficient
    global _run_sfx_generation, _run_simulated_generation, _workspace_dir, wgp
    _active_gen_states = names["_active_gen_states"]
    _apply_per_job_coefficient = names["_apply_per_job_coefficient"]
    _cancel_h3_idle_release = names["_cancel_h3_idle_release"]
    _coordinated_generation_slot = names["_coordinated_generation_slot"]
    _ensure_managed_loras_present = names["_ensure_managed_loras_present"]
    _interrupt_wan_model = names["_interrupt_wan_model"]
    _is_legacy_h3_model = names["_is_legacy_h3_model"]
    _is_minimax_h3_model, _jobs = names["_is_minimax_h3_model"], names["_jobs"]
    _local_gpu_lane = names["_local_gpu_lane"]
    _persist_generation_job = names["_persist_generation_job"]
    _publish_generation_sidecar_for_studio_job = names["_publish_generation_sidecar_for_studio_job"]
    _release_h3_when_queue_allows = names["_release_h3_when_queue_allows"]
    _release_legacy_h3_when_queue_allows = names["_release_legacy_h3_when_queue_allows"]
    _remove_persisted_generation_job = names["_remove_persisted_generation_job"]
    _resolve_video_editor_source = names["_resolve_video_editor_source"]
    _restore_base_coefficient = names["_restore_base_coefficient"]
    _run_sfx_generation = names["_run_sfx_generation"]
    _run_simulated_generation = names["_run_simulated_generation"]
    _workspace_dir, wgp = names["_workspace_dir"], names["wgp"]


class _GenerationRun:
    """The locals of one `_run_generation` call that cross from one phase function to the next.

    `_run_generation` keeps the slot, try, except and finally frame; the phases chain by tail
    calls (`return _run_generation_<next>(st)`), so every early `return False` of a phase is still
    the return of the whole call. A phase starts by reading the locals it needs from `st` and
    ends by writing the ones later phases read. Fields are set by the phase that assigns them.
    """

    def __init__(self, job_id, job, finalize, AsyncStream, async_run, inspect):
        self.job_id, self.job, self.finalize = job_id, job, finalize
        self.AsyncStream, self.async_run, self.inspect = AsyncStream, async_run, inspect
        self.active_task_timer = self.abort_state = None


def _run_generation(job_id: str, *, finalize: bool = True) -> bool:
    """Build and run a job, optionally deferring success finalization."""
    from shared.utils.thread_utils import AsyncStream, async_run
    import inspect

    job = _jobs[job_id]
    start_time = None
    active_task_timer = None
    abort_state = None
    st = _GenerationRun(job_id, job, finalize, AsyncStream, async_run, inspect)

    with _coordinated_generation_slot(job) as acquired:
        if not acquired:
            return False
        try:
            return _run_generation_start(st)

        except Exception as e:
            active_task_timer = st.active_task_timer
            if active_task_timer is not None:
                active_task_timer.finish("failed")
            traceback.print_exc()
            failure_updates = {
                "error": str(e),
                "message": f"Error: {e}",
            }
            # Tag with OOM info — see _run_sfx_generation for rationale.
            try:
                from services.oom_detect import detect_oom
                _coef = float(wgp.server_config.get("vram_safety_coefficient", 0.80))
                _oom = detect_oom(e, _coef)
                if _oom:
                    failure_updates["oom_info"] = _oom
            except Exception:
                pass
            finish_job(job, "failed", **failure_updates)
            return False
        finally:
            abort_state = st.abort_state
            # Restore the persisted base coefficient so the next job
            # starts from the user's auto-tuned value, not whatever
            # this job's adjustment left it at.
            _restore_base_coefficient()
            if abort_state is not None:
                # Unregistration is the cancellation acknowledgement. Keep it
                # after per-job cleanup so `cancelled` never means inference is
                # still unwinding.
                unregister_abort_state(
                    job_id, _active_gen_states, abort_state,
                )
            else:
                acknowledge_cancel(job)
            # If no other jobs are running, sync save_path to the current active
            # workspace (which may have changed while this job was running).
            if not _active_gen_states:
                active_dir = _workspace_dir()
                wgp.save_path = active_dir
                wgp.image_save_path = active_dir
            # The generation itself is terminal now. Remove its request before
            # optional model-idle cleanup so a shutdown during cleanup cannot
            # offer a duplicate completed job for recovery.
            _remove_persisted_generation_job(job)
            finished_model_type = job.get("params", {}).get("model_type")
            if (
                _is_legacy_h3_model(finished_model_type)
                and not job.get("params", {}).get("_director_pipeline_id")
            ):
                _release_legacy_h3_when_queue_allows(job_id)
            elif (
                _is_minimax_h3_model(finished_model_type)
                and not _is_legacy_h3_model(finished_model_type)
                and not job.get("params", {}).get("_director_pipeline_id")
            ):
                _release_h3_when_queue_allows(job_id)


def _run_generation_start(st):
    """Take the GPU slot, build the job state and register the abort handle."""
    abort_state, finalize, job, job_id = st.abort_state, st.finalize, st.job, st.job_id
    try:
        if not try_start(
            job,
            message=(
                "Restarting recovered job from the beginning…"
                if job.get("recovered") else "Preparing..."
            ),
            acquired_resources=[_local_gpu_lane.key],
        ):
            return False
        # Active generation timing begins only after this job owns the GPU
        # slot. Time spent waiting in the submission queue is deliberately
        # excluded from gallery metadata and completion logs.
        start_time = float(job.get("started_at") or time.time())
        _persist_generation_job(job)
        if execution_mode.policy().simulated:
            return _run_simulated_generation(job, finalize=finalize)
        _cancel_h3_idle_release()
        legacy_h3_job = _is_legacy_h3_model(
            job.get("params", {}).get("model_type")
        )
        # Never retain the isolated Comfy runtime beside a native WGP
        # model. Adjacent Legacy jobs still reuse it through FIFO.
        if legacy_h3_job:
            minimax_h3_service.cancel_idle_shutdown()
        else:
            minimax_h3_service.stop_runtime()

        # Per-job VRAM coefficient adjustment applies only to WGP jobs.
        if not legacy_h3_job:
            _apply_per_job_coefficient(job)

        # Build minimal state (same structure as CLI mode, line 11935 of wgp.py)
        state = {
            "gen": {
                "queue": [],
                "in_progress": False,
                "abort": False,
                "file_list": [],
                "artifact_list": [],
                "file_settings_list": [],
                "audio_file_list": [],
                "audio_file_settings_list": [],
                "selected": 0,
                "audio_selected": 0,
                "prompt_no": 0,
                "prompts_max": 0,
                "repeat_no": 0,
                "total_generation": 1,
                "window_no": 0,
                "total_windows": 0,
                "progress_status": "",
                "process_status": "process:main",
            },
            "loras": [],
        }

        # Build task manifest from user params
        raw_params = job["params"].copy()

        # Register the exact state before any model work. Legacy owns a
        # Comfy prompt interrupt; native models use WGP's interrupt flag.
        # Keep abort_state None until registration succeeds: the finally of
        # _run_generation treats a non-None value as owned, and unregistering
        # a dict that was never registered does not acknowledge a cancel that
        # landed after try_start (the job would stay "Cancelling" forever).
        pending_abort = state["gen"]
        if legacy_h3_job:
            interrupt_model = minimax_h3_service.cancel
        else:
            interrupt_model = (
                None if raw_params.get("sfx_mode") else _interrupt_wan_model
            )
        if not register_abort_state(
            job,
            job_id,
            _active_gen_states,
            pending_abort,
            interrupt_model=interrupt_model,
        ):
            return False
        abort_state = pending_abort
    finally:
        st.abort_state = abort_state
    st.legacy_h3_job, st.raw_params, st.start_time = legacy_h3_job, raw_params, start_time
    st.state = state
    return _run_generation_legacy_h3(st)


def _run_generation_legacy_h3(st):
    """Run a legacy H3 job through its isolated Comfy runtime."""
    finalize, job, job_id, legacy_h3_job = st.finalize, st.job, st.job_id, st.legacy_h3_job
    raw_params, start_time = st.raw_params, st.start_time
    # The quality route is the proven previous-Maestro implementation:
    # fixed INT8 ConvRot pair, isolated ComfyUI, 20 steps, no Turbo/cache.
    if legacy_h3_job:
        if raw_params.get("video_source"):
            if not update_job(
                job,
                message="Capturing the source video's final frame…",
                phase="Preparing",
            ):
                return False
            source_path = _resolve_video_editor_source(
                raw_params["video_source"]
            )
            anchor = minimax_h3_service.prepare_extend_anchor(
                raw_params,
                job_id,
                source_path,
                os.path.join(os.getcwd(), "uploads"),
            )
            job["params"] = raw_params.copy()
            ignored = anchor["ignored_references"]
            ignored_note = (
                f"; ignored {ignored} other reference(s)"
                if ignored else ""
            )
            print(
                f"[H3 Legacy] Extend anchor at {anchor['time']:.3f}s "
                f"({anchor['path']}){ignored_note}."
            )

        # The coordinator hand-off already released any WGP-owned
        # runtime before entering this branch. Do not repeat native
        # model/cache teardown here: H3 itself runs in an isolated
        # sidecar and only needs the now-exclusive GPU lease.
        minimax_h3_service.cancel_idle_shutdown()

        def _legacy_h3_progress(
            message: str,
            value: int,
            step: int = 0,
            total: int = 0,
        ) -> None:
            update_job(
                job,
                message=message,
                progress=max(0, min(100, int(value))),
                step=max(0, int(step)),
                total_steps=max(0, int(total)),
                phase="H3 Legacy sampling" if total > 0 else "",
            )

        with safe_download.cancellable_downloads(
            lambda: is_cancel_requested(job),
        ):
            generated = minimax_h3_service.generate(
                raw_params,
                job_id,
                job["out_dir"],
                _legacy_h3_progress,
                lambda: is_cancel_requested(job),
                keep_runtime=True,
            )
        if is_cancel_requested(job):
            return False

        output_names = [os.path.basename(path) for path in generated]
        record_job_outputs(job, output_names)
        upload_filenames = {}
        for key in ("image_start", "image_end", "video_source"):
            value = raw_params.get(key)
            if isinstance(value, str) and value:
                upload_filenames[key] = os.path.basename(value)
        sidecar = {
            "params": raw_params,
            "upload_filenames": upload_filenames,
            "generation_mode": "video",
            "job_id": job_id,
            "task_id": job.get("task_id"),
            "root_task_id": job.get("root_task_id") or job.get("task_id"),
            "generation_time": round(time.time() - start_time),
            "created_at": time.time(),
        }
        director_pipeline_id = raw_params.get("_director_pipeline_id")
        if director_pipeline_id:
            sidecar["director_pipeline_id"] = director_pipeline_id
        for path in generated:
            file_sidecar = dict(sidecar)
            file_sidecar["output_filename"] = os.path.basename(path)
            _publish_generation_sidecar_for_studio_job(job, path, file_sidecar)

        if not finalize:
            return update_job(
                job,
                progress=99,
                step=0,
                total_steps=0,
                phase="Finalizing",
                message="Finalizing...",
            )
        return finish_job(
            job,
            "completed",
            progress=100,
            step=0,
            total_steps=0,
            phase="",
            message="Done",
        )
    return _run_generation_configure(st)


def _run_generation_configure(st):
    """Preflight: SFX shortcut and the downloads the model needs before it loads."""
    job, raw_params, start_time = st.job, st.raw_params, st.start_time
    # Inject progressive pipeline setting from services config (applies to all paths)
    _services_cfg = wgp.server_config.get("services", {})
    # ── SFX mode: standalone MMAudio generation ──────────────────
    # When sfx_mode is set, bypass the normal video generation pipeline
    # and run MMAudio directly (with or without a source video).
    if raw_params.get("sfx_mode"):
        _run_sfx_generation(job, raw_params, start_time)
        return job.get("status") == "completed"

    # Temporal-depth control has its own optional 458 MB / 1.54 GB
    # preprocessor checkpoint. Provision it before wgp loads the much
    # larger generation model; otherwise a fresh install spends
    # minutes loading LTX and only then fails on the missing file.
    try:
        from services.managed_preprocessors import (
            ensure_video_depth_checkpoint,
            uses_temporal_depth,
        )

        if uses_temporal_depth(raw_params):
            ensure_video_depth_checkpoint(
                wgp.server_config.get(
                    "depth_anything_v2_variant", "vitl"
                ),
                progress=lambda msg: update_job(job, message=msg),
            )
            update_job(job, message="Preparing temporal-depth control…")
    except Exception as e:
        finish_job(job, "failed", error=str(e), message=str(e))
        return False

    # H3 Full and Pruned checkpoints use different AdaLN widths. Any
    # H3 LoRA may therefore need the small revision-pinned affine fit
    # before MMGP preprocesses it. Provision both known compressed
    # widths up front; this is a ~2 MB one-time setup and also covers
    # manually imported/CivitAI adapters, not just managed Turbo.
    try:
        _h3_model_def = wgp.get_model_def(
            raw_params.get("model_type")
        ) or {}
        if (
            str(_h3_model_def.get("architecture") or "").startswith(
                "minimax_h3"
            )
            and raw_params.get("activated_loras")
        ):
            from services.managed_preprocessors import (
                ensure_minimax_h3_lora_affine_maps,
            )

            ensure_minimax_h3_lora_affine_maps(
                "ref2va"
                if _h3_model_def.get("omni_reference")
                else "fl2va",
                progress=lambda msg: update_job(job, message=msg),
            )
            update_job(job, message="Preparing MiniMax H3 LoRAs…")
    except Exception as e:
        finish_job(job, "failed", error=str(e), message=str(e))
        return False

    # Safety net for managed auto-download LoRAs (e.g. Edit Anything):
    # fetch the file on first use if the frontend's proactive download
    # hasn't finished yet, so the user doesn't hit a "file not found"
    # error. No-op (one dict lookup) for jobs without a managed LoRA.
    try:
        _ensure_managed_loras_present(
            raw_params.get("activated_loras"),
            raw_params.get("model_type"),
            progress=lambda msg: update_job(job, message=msg),
        )
    except Exception as e:
        finish_job(job, "failed", error=str(e), message=str(e))
        return False
    return _run_generation_manifest(st)


def _run_generation_manifest(st):
    """Pop the internal settings and build the task manifest (shot-aware edit, multi-clip or single)."""
    job, job_id, raw_params = st.job, st.job_id, st.raw_params
    # For video: extract film grain settings and apply as post-processing
    # after generation (avoids 3x slowdown from pipeline re-processing).
    # For images: leave film grain in params so the pipeline applies it inline
    # (single image is instant, no slowdown issue).
    gen_mode = raw_params.get("generation_mode", "video")
    if gen_mode != "image":
        pp_film_grain_intensity = raw_params.pop("film_grain_intensity", 0)
        pp_film_grain_saturation = raw_params.pop("film_grain_saturation", 0.5)
    else:
        pp_film_grain_intensity = 0
        pp_film_grain_saturation = 0.5

    # FlashVSR upscaling is deferred to a whole-file post-pass (below):
    # one continuous temporal pass over the assembled video instead of
    # per-sliding-window chunks — FlashVSR's temporal state no longer
    # resets at window boundaries (detail "pop" at seams), and it stops
    # competing with the diffusion model for VRAM between windows.
    # Lanczos/VAE methods keep the inline per-window path (cheap,
    # stateless), and images keep inline upsampling (single frame).
    pp_spatial_upsampling = ""
    if gen_mode != "image":
        _su_val = str(raw_params.get("spatial_upsampling") or "")
        if "flashvsr" in _su_val:
            pp_spatial_upsampling = _su_val
            raw_params.pop("spatial_upsampling", None)

    # Voice clone postprocessing (SeedVC) — replaces 1 or 2 voices
    # in the generated video's audio with user-supplied reference
    # voice(s). Driven by three params (set by the UI):
    #   voice_clone_enabled: bool
    #   voice_clone_refs:    list[str] of uploaded voice ref file paths
    #   voice_clone_mode:    "single" or "two"
    # Pop them out of raw_params so they don't leak into the
    # generation handler (other handlers don't understand them).
    pp_voice_clone_enabled = bool(raw_params.pop("voice_clone_enabled", False))
    pp_voice_clone_refs = resolve_voice_ref_paths(
        raw_params.pop("voice_clone_refs", None) or [],
        uploads_root=os.path.join(os.getcwd(), "uploads"),
        workspace_root=_workspace_dir(job.get("workspace")),
    )
    pp_voice_clone_mode = raw_params.pop("voice_clone_mode", "single")

    defer_output_publication = bool(
        raw_params.pop("_defer_output_publication", False)
    )
    recast_shot_manifest = raw_params.pop(
        "_recast_shot_manifest",
        None,
    )
    repaint_shot_manifest = raw_params.pop(
        "_repaint_shot_manifest",
        None,
    )
    outpaint_shot_manifest = raw_params.pop(
        "_outpaint_shot_manifest",
        None,
    )
    if recast_shot_manifest is not None:
        shot_manifest = recast_shot_manifest
        shot_workflow = "Recast"
    elif repaint_shot_manifest is not None:
        shot_manifest = repaint_shot_manifest
        shot_workflow = "Repaint"
    else:
        shot_manifest = outpaint_shot_manifest
        shot_workflow = "Outpaint"

    if outpaint_shot_manifest is not None:
        # Internal Outpaint shots must not run the continuous job's
        # postprocessor against the complete source video. The final
        # shot-aware worker restores one pristine audio track only
        # after all exact-length clips have been assembled.
        raw_params["_outpaint_preserve_audio"] = False
        raw_params["_outpaint_source_video"] = None
        raw_params["_outpaint_lock_source_pixels"] = False
        raw_params["_outpaint_trim_smear"] = False

    # Shot-aware edits supply exact per-shot guides and settings. They
    # run through the ordinary task engine but defer concatenation and
    # publication to their finishing worker.
    if shot_manifest is not None:
        import copy

        if not isinstance(shot_manifest, list):
            finish_job(
                job,
                "failed",
                error=f"{shot_workflow} shot manifest is invalid",
                message=f"{shot_workflow} shot preparation failed",
            )
            return False
        generated_entries = [
            entry
            for entry in shot_manifest
            if isinstance(entry, dict)
            and isinstance(entry.get("params"), dict)
        ]
        if not generated_entries:
            finish_job(
                job,
                "failed",
                error=(
                    f"{shot_workflow} shot manifest contains no "
                    "generated shots"
                ),
                message=f"{shot_workflow} shot preparation failed",
            )
            return False

        manifest = []
        group_id = f"{shot_workflow.casefold()}_shots_{job_id}"
        for sequence_index, entry in enumerate(generated_entries):
            wgp.task_id += 1
            shot_params = copy.deepcopy(raw_params)
            shot_params.update(copy.deepcopy(entry["params"]))
            shot_params["multi_prompts_gen_type"] = 0
            shot_params["multi_clip_info"] = {
                "group_id": group_id,
                "index": int(entry.get(
                    "shot_index",
                    sequence_index,
                )),
                "total": len(generated_entries),
                "defer_concat": True,
                "progress_label": "Shot",
            }
            manifest.append({
                "id": wgp.task_id,
                "params": shot_params,
                "plugin_data": {},
            })

    # Multi-clip mode: split single request into per-clip tasks
    elif raw_params.get("multi_prompts_gen_type") == 3:
        (_mc_bounded_director, _mc_fs, _mc_latent, _mc_min_f, _mc_model_def, _mc_trim_end_frames,
         clip_count, cumulative_offset, group_id, image_ends, image_starts, last_se_clip_end_image,
         manifest, multi_clip_audio_start_sec, multi_clip_concat_audio, per_clip_continuations,
         per_clip_frames, per_clip_h3_references, per_clip_keyframes, per_clip_negative_prompts,
         per_clip_seeds, preserve_se_duration_per_clip, prompt_lines, sw_size,
         total_trimmed_frames) = _run_generation_multiclip_plan(
                raw_params)
        for i in range(clip_count):
            clip_end, clip_params, has_end = _run_generation_clip_params(
                    _mc_bounded_director, i, image_ends, image_starts, per_clip_continuations,
                    per_clip_h3_references, per_clip_negative_prompts, per_clip_seeds, prompt_lines,
                    raw_params)
            (cumulative_offset, last_se_clip_end_image,
             total_trimmed_frames) = _run_generation_clip_frames(
                    _mc_bounded_director, _mc_fs, _mc_latent, _mc_min_f, _mc_model_def,
                    _mc_trim_end_frames, clip_count, clip_end, clip_params, cumulative_offset,
                    group_id, has_end, i, last_se_clip_end_image, manifest,
                    multi_clip_audio_start_sec, multi_clip_concat_audio, per_clip_frames,
                    per_clip_keyframes, preserve_se_duration_per_clip, sw_size,
                    total_trimmed_frames)

        _run_generation_tail_clip(
                _mc_trim_end_frames, clip_count, cumulative_offset, group_id,
                last_se_clip_end_image, manifest, multi_clip_audio_start_sec,
                multi_clip_concat_audio, prompt_lines, raw_params, total_trimmed_frames)
    else:
        wgp.task_id += 1
        # SE trim: if end image is set, mark tail frames for trimming
        # (removes distorted frames from end-frame conditioning)
        has_end_image = raw_params.get("image_end") not in (None, "", [])
        try:
            _single_model_def = wgp.get_model_def(
                raw_params.get("model_type", "")
            ) or {}
        except Exception:
            _single_model_def = {}
        if (
            has_end_image
            and raw_params.get("video_length")
            and bool(_single_model_def.get("director_trim_end_frames", True))
        ):
            model_type = raw_params.get("model_type", "")
            try:
                _, fs, _ = wgp.get_model_min_frames_and_step(model_type)
            except Exception:
                fs = 8  # LTX-2 default
            raw_params["trim_tail_frames"] = fs

        manifest = [{
            "id": wgp.task_id,
            "params": raw_params,
            "plugin_data": {},
        }]
    st.defer_output_publication, st.manifest = defer_output_publication, manifest
    st.pp_film_grain_intensity = pp_film_grain_intensity
    st.pp_film_grain_saturation = pp_film_grain_saturation
    st.pp_spatial_upsampling = pp_spatial_upsampling
    st.pp_voice_clone_enabled, st.pp_voice_clone_mode = pp_voice_clone_enabled, pp_voice_clone_mode
    st.pp_voice_clone_refs = pp_voice_clone_refs
    return _run_generation_queue(st)


def _run_generation_multiclip_plan(raw_params):
    """Read the multi-clip request: prompts, images, per-clip lists, frame lattice."""
    prompt_text = raw_params.get("prompt", "")
    # Use clip boundary separator if present (Director v2 with sliding window support),
    # otherwise fall back to newline split (Studio mode / legacy Director)
    CLIP_SEPARATOR = "\n---CLIP_BOUNDARY---\n"
    if CLIP_SEPARATOR in prompt_text:
        prompt_lines = [p.strip() for p in prompt_text.split(CLIP_SEPARATOR) if p.strip()]
    else:
        prompt_lines = [l.strip() for l in prompt_text.split("\n") if l.strip()]
    image_starts = raw_params.get("image_start", [])
    if not isinstance(image_starts, list):
        image_starts = [image_starts] if image_starts else []
    image_ends = raw_params.get("image_end", [])
    if not isinstance(image_ends, list):
        image_ends = [image_ends] if image_ends else []
    sw_size = raw_params.get("sliding_window_size", raw_params.get("video_length", 121))
    per_clip_frames = raw_params.pop("per_clip_frames", None)  # optional per-clip durations
    per_clip_seeds = raw_params.pop("per_clip_seeds", None)
    per_clip_negative_prompts = raw_params.pop(
        "per_clip_negative_prompts",
        None,
    )
    per_clip_keyframes = raw_params.pop("per_clip_keyframes", None)  # optional keyframe injection per clip
    preserve_se_duration_per_clip = bool(
        raw_params.pop("_se_preserve_duration_per_clip", False)
    )
    per_clip_h3_references = raw_params.pop(
        "per_clip_minimax_h3_references", None,
    )
    per_clip_continuations = raw_params.pop(
        "per_clip_continue_from_previous", None,
    )
    multi_clip_concat_audio = raw_params.pop(
        "multi_clip_concat_audio", None,
    )
    multi_clip_audio_start_sec = raw_params.pop("multi_clip_audio_start_sec", 0.0)
    group_id = f"mc_{int(time.time())}_{raw_params.get('seed', 0)}"
    clip_count = max(
        len(prompt_lines),
        len(image_starts),
        len(per_clip_h3_references or []),
        len(per_clip_continuations or []),
        1,
    )

    # Get model latent_size for frame quantization — wgp.py quantizes
    # video_length to (n-1)//latent_size*latent_size+1, so we must match
    # that here to keep cumulative audio offsets in sync with actual output.
    _mc_model_type = raw_params.get("model_type", "")
    try:
        _mc_min_f, _mc_fs, _mc_latent = wgp.get_model_min_frames_and_step(_mc_model_type)
    except Exception:
        _mc_min_f, _mc_fs, _mc_latent = 17, 8, 8
    try:
        _mc_model_def = wgp.get_model_def(_mc_model_type) or {}
    except Exception:
        _mc_model_def = {}
    _mc_bounded_director = str(
        _mc_model_def.get("director_video_strategy") or "rolling_window"
    ) in {"bounded_start_end", "omni_reference"}
    _mc_trim_end_frames = bool(
        _mc_model_def.get("director_trim_end_frames", True)
    )

    manifest = []
    # Director timelines can begin after a silent intro. Preserve
    # that source-audio origin for every clip's conditioning; the
    # ordinary Studio path continues to default to frame zero.
    try:
        cumulative_offset = max(
            0, int(raw_params.get("audio_frame_offset", 0) or 0),
        )
        multi_clip_audio_start_sec = max(
            0.0, float(multi_clip_audio_start_sec or 0),
        )
    except (TypeError, ValueError):
        cumulative_offset = 0
        multi_clip_audio_start_sec = 0.0
    total_trimmed_frames = 0
    last_se_clip_end_image = None  # track last clip's end image for tail compensation
    return (_mc_bounded_director, _mc_fs, _mc_latent, _mc_min_f, _mc_model_def, _mc_trim_end_frames,
            clip_count, cumulative_offset, group_id, image_ends, image_starts,
            last_se_clip_end_image, manifest, multi_clip_audio_start_sec, multi_clip_concat_audio,
            per_clip_continuations, per_clip_frames, per_clip_h3_references, per_clip_keyframes,
            per_clip_negative_prompts, per_clip_seeds, preserve_se_duration_per_clip, prompt_lines,
            sw_size, total_trimmed_frames)


def _run_generation_clip_params(
        _mc_bounded_director, i, image_ends, image_starts, per_clip_continuations,
        per_clip_h3_references, per_clip_negative_prompts, per_clip_seeds, prompt_lines,
        raw_params):
    """Parameters of clip `i`: seed, prompts, images, continuation."""
    wgp.task_id += 1
    clip_params = raw_params.copy()
    if per_clip_seeds and i < len(per_clip_seeds):
        try:
            clip_params["seed"] = int(per_clip_seeds[i])
        except (TypeError, ValueError):
            pass
    if (
        isinstance(per_clip_negative_prompts, list)
        and i < len(per_clip_negative_prompts)
    ):
        clip_params["negative_prompt"] = str(
            per_clip_negative_prompts[i] or ""
        )
    clip_params["prompt"] = prompt_lines[i] if i < len(prompt_lines) else (prompt_lines[-1] if prompt_lines else "")
    clip_params["image_start"] = image_starts[i] if i < len(image_starts) else None
    clip_end = image_ends[i] if i < len(image_ends) else None
    clip_params["image_end"] = clip_end if clip_end else None
    if per_clip_h3_references is not None:
        if i >= len(per_clip_h3_references):
            raise ValueError(
                f"Missing MiniMax H3 reference manifest for clip {i + 1}."
            )
        clip_params["minimax_h3_references"] = (
            per_clip_h3_references[i]
        )
    # Set per-clip image_prompt_type based on which images are present
    has_start = bool(clip_params.get("image_start"))
    has_end = bool(clip_end)
    if has_start and has_end:
        clip_params["image_prompt_type"] = "SE"
    elif has_start:
        clip_params["image_prompt_type"] = "S"
    elif has_end:
        clip_params["image_prompt_type"] = "E"
    # Rolling-window multi-clip keeps its historic automatic
    # continuation. Bounded models opt in per clip: Director
    # uses this for duration-split FL2VA segments or an
    # explicitly planned literal continuation, never across
    # an ordinary editorial cut.
    if not has_start and i > 0:
        bounded_continuation = bool(
            per_clip_continuations
            and i < len(per_clip_continuations)
            and per_clip_continuations[i]
        )
        if not _mc_bounded_director or bounded_continuation:
            clip_params["_continuation"] = True
            if bounded_continuation:
                clip_params["_continuation_tail_skip"] = 0
    return clip_end, clip_params, has_end


def _run_generation_clip_frames(
        _mc_bounded_director, _mc_fs, _mc_latent, _mc_min_f, _mc_model_def, _mc_trim_end_frames,
        clip_count, clip_end, clip_params, cumulative_offset, group_id, has_end, i,
        last_se_clip_end_image, manifest, multi_clip_audio_start_sec, multi_clip_concat_audio,
        per_clip_frames, per_clip_keyframes, preserve_se_duration_per_clip, sw_size,
        total_trimmed_frames):
    """Frame count, tail trim and audio offset of clip `i`; add it to the manifest."""
    clip_frames = per_clip_frames[i] if per_clip_frames and i < len(per_clip_frames) else sw_size
    if _mc_bounded_director:
        clip_frames = int(clip_frames)
        _mc_max_f = int(
            _mc_model_def.get("frames_maximum") or clip_frames
        )
        if not (
            _mc_min_f <= clip_frames <= _mc_max_f
            and (clip_frames - _mc_min_f) % max(1, _mc_fs) == 0
        ):
            raise ValueError(
                f"Clip {i + 1} has {clip_frames} frames, outside "
                f"the selected model's {_mc_min_f}-{_mc_max_f} "
                f"frame lattice (step {_mc_fs})."
            )
    else:
        # Quantize to valid frame count (same formula as wgp.py)
        clip_frames = (clip_frames - 1) // _mc_latent * _mc_latent + 1
        clip_frames = max(clip_frames, _mc_min_f)
    # SE mode: mark tail frames for trimming (removes end-frame
    # conditioning distortion at tensor level before saving)
    trim_tail = 0
    if has_end and _mc_trim_end_frames:
        trim_tail = _mc_fs
        last_se_clip_end_image = clip_end
        if preserve_se_duration_per_clip:
            # `clip_frames` is the requested visible duration.
            # Generate one conditioning step more so removing
            # the distorted SE tail leaves that duration intact.
            clip_frames = (
                (clip_frames + trim_tail - 1)
                // _mc_latent
                * _mc_latent
                + 1
            )
    clip_params["video_length"] = clip_frames
    clip_params["trim_tail_frames"] = trim_tail
    clip_params["audio_frame_offset"] = cumulative_offset
    cumulative_offset += clip_frames - trim_tail  # advance by post-trim frames for audio sync
    if not preserve_se_duration_per_clip:
        total_trimmed_frames += trim_tail
    clip_params["multi_clip_info"] = {
        "group_id": group_id,
        "index": i,
        "total": clip_count,
        "cumulative_offset": True,
        "audio_start_sec": multi_clip_audio_start_sec,
        "concat_audio_path": multi_clip_concat_audio,
    }
    # If the clip prompt has newlines (window_prompts), use mode 1 (per-window)
    # Otherwise mode 0 (single task)
    clip_prompt = clip_params.get("prompt", "")
    clip_params["multi_prompts_gen_type"] = 1 if "\n" in clip_prompt else 0
    # Keyframe injection: add image_refs and frames_positions for this clip
    if per_clip_keyframes and i < len(per_clip_keyframes) and per_clip_keyframes[i]:
        kf_paths = per_clip_keyframes[i]
        clip_params["image_refs"] = kf_paths
        # Position each keyframe at "L" (last frame of each window)
        clip_params["frames_positions"] = " ".join(["L"] * len(kf_paths))
        # Enable frames injection mode
        existing_vpt = clip_params.get("video_prompt_type", "")
        if "KFI" not in existing_vpt:
            clip_params["video_prompt_type"] = existing_vpt + "KFI"
    manifest.append({
        "id": wgp.task_id,
        "params": clip_params,
        "plugin_data": {},
    })
    return cumulative_offset, last_se_clip_end_image, total_trimmed_frames


def _run_generation_tail_clip(
        _mc_trim_end_frames, clip_count, cumulative_offset, group_id, last_se_clip_end_image,
        manifest, multi_clip_audio_start_sec, multi_clip_concat_audio, prompt_lines, raw_params,
        total_trimmed_frames):
    """Add the tail clip that makes up the frames the SE trim removed."""
    # Compensation tail clip: if SE trimming removed frames, generate a
    # short extra clip (start-frame only, no SE distortion) to fill the gap
    # so the final video matches the full audio duration.
    if total_trimmed_frames > 0 and _mc_trim_end_frames:
        # Snap to valid frame count for the model
        model_type = raw_params.get("model_type", "")
        try:
            min_f, fs, _ = wgp.get_model_min_frames_and_step(model_type)
        except Exception:
            min_f, fs = 9, 8  # LTX-2 defaults
        # Round up to nearest valid frame count (must be >= min_frames)
        tail_frames = max(min_f, ((total_trimmed_frames - 1) // fs) * fs + 1)
        if tail_frames < min_f:
            tail_frames = min_f

        wgp.task_id += 1
        tail_params = raw_params.copy()
        # Use last clip's prompt and last clip's end image as start frame
        tail_params["prompt"] = prompt_lines[-1] if prompt_lines else ""
        tail_params["image_start"] = last_se_clip_end_image
        tail_params["image_end"] = None
        tail_params["image_prompt_type"] = "S"  # start-only, no SE distortion
        tail_params["video_length"] = tail_frames
        tail_params["trim_tail_frames"] = 0
        tail_params["audio_frame_offset"] = cumulative_offset
        tail_params["multi_clip_info"] = {
            "group_id": group_id,
            "index": clip_count,
            "total": clip_count + 1,
            "cumulative_offset": True,
            "audio_start_sec": multi_clip_audio_start_sec,
            "concat_audio_path": multi_clip_concat_audio,
        }
        tail_params["multi_prompts_gen_type"] = 0

        # Update all previous clips' total count to include the tail
        for m in manifest:
            m["params"]["multi_clip_info"]["total"] = clip_count + 1

        manifest.append({
            "id": wgp.task_id,
            "params": tail_params,
            "plugin_data": {},
        })
        print(f"[Multi-Clip] SE trim compensation: lost {total_trimmed_frames} frames across {clip_count} clips, adding tail clip of {tail_frames} frames")

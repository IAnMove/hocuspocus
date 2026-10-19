"""Studio generation submission.

``generate`` is the launch handler, moved verbatim. The full server binds the
names below in ``create_studio_generate_router`` before a request. The handler
looks ``_job_leftovers`` up on this module, so launch assigns that same object
here when it builds it.
"""

import os
import threading

from fastapi import HTTPException, Request

# Bound by the router factory. None until the full server mounts the route.
_cancel_h3_idle_release = None
_get_active_workspace = None
_get_cached_hardware = None
_is_character_sheet_engine = None
_is_legacy_h3_model = None
_is_minimax_h3_model = None
_jobs = None
_new_generation_job = None
_normalize_image_prompt_type = None
_normalize_video_prompt_type = None
_persist_generation_job = None
_recommended_minimax_h3_encoder = None
_run_generation_with_preparation = None
_workspace_collection_registry = None
_workspace_dir = None
_job_leftovers = None
ensure_generation_priority = None
execution_mode = None
minimax_h3_service = None
wgp = None


async def generate(request: Request):
    """Submit a generation job. Returns immediately with a job_id."""
    from services.generation_provenance import normalize_submission_provenance

    body = await request.json()
    if isinstance(body, dict):
        try:
            ensure_generation_priority(body)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    provenance = normalize_submission_provenance(body.pop("provenance", None), trusted_tool=getattr(request, "trusted_tool", None))
    try:
        from services.generation_output_name import OutputNameError, apply_output_name
        apply_output_name(body)
    except OutputNameError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": error.code, "message": str(error), "retryable": False},
        ) from error
    collection_id = provenance.get("workspace_id")
    if collection_id and not _workspace_collection_registry.get(collection_id):
        raise HTTPException(status_code=400, detail="Unknown Workspace collection")
    # Execution mode is a boot-time trust boundary, never a request option.
    # Discard spoofed private fields before validating the captured workspace.
    body.pop("_execution_mode", None)
    requested_workspace = body.get("workspace") or _get_active_workspace()
    try:
        execution_mode.validate_generation(requested_workspace)
    except execution_mode.ExecutionModeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    body["_execution_mode"] = execution_mode.policy().mode
    h3_window_plan_response = None

    is_sfx = body.get("sfx_mode")
    if not body.get("model_type"):
        raise HTTPException(status_code=400, detail="model_type is required")
    if body.get("model_type") == "viggle_animate":
        body["prompt"] = "Viggle character replacement"
    if not is_sfx and not body.get("prompt"):
        raise HTTPException(status_code=400, detail="prompt is required")
    # SFX virtual models (mmaudio_*) are frontend-only; skip backend model validation
    if not is_sfx and wgp.get_model_def(body["model_type"]) is None:
        raise HTTPException(status_code=400, detail=f"Unknown model: {body['model_type']}")

    legacy_h3 = _is_legacy_h3_model(body["model_type"])
    try:
        _base_model_type = wgp.get_base_model_type(body["model_type"])
    except Exception:
        _base_model_type = body.get("model_type")
    _generation_model_def = wgp.get_model_def(body["model_type"]) or {}
    from services.model_selectors import InvalidSelector, validate_submitted_selectors
    try:
        validate_submitted_selectors(body, _generation_model_def)
    except InvalidSelector as error:
        raise HTTPException(status_code=400, detail=error.detail) from error
    from services.wangp_submission import prepare_generation_inputs
    try:
        prepare_generation_inputs(body, _generation_model_def, requested_workspace,
                                  uploads_dir=os.path.join(os.getcwd(), "uploads"),
                                  workspace_dir=_workspace_dir(requested_workspace),
                                  prepared_images=getattr(request, "prepared_studio_images", False) is True,
                                  prepared_speech=(getattr(request, "prepared_studio_speech", False) is True
                                                   or getattr(request, "prepared_studio_audio", False) is True))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        from services.h3_runtime_policy import normalize_optional_conditioning
        normalize_optional_conditioning(body, _generation_model_def)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if legacy_h3:
        character_sheet = _is_character_sheet_engine(body)
        body.setdefault("resolution", minimax_h3_service.DEFAULTS["resolution"])
        body.setdefault("video_length", minimax_h3_service.DEFAULTS["video_length"])
        body.setdefault(
            "h3_audio_prompt",
            minimax_h3_service.DEFAULTS["h3_audio_prompt"],
        )
        body.update({
            "h3_model_profile": "quality",
            "h3_allow_low_memory_fallback": False,
            "num_inference_steps": 25 if character_sheet else 20,
            "flow_shift": 12.0,
            "h3_audio_shift": 3.0,
            "guidance_scale": 1.0,
            # The original Character Sheet workflow has a separate Turbo
            # LoRA. Maestro's native Turbo adapter is not interchangeable, so
            # never let that global checkbox leak into this isolated route.
            "minimax_h3_turbo_mode": False,
            "activated_loras": [],
            "loras_multipliers": "",
            "skip_steps_cache_type": "",
        })
        if character_sheet:
            if not isinstance(body.get("image_refs"), list) or not any(body["image_refs"]):
                raise HTTPException(
                    status_code=400,
                    detail="Character Sheet engine requires at least one image reference.",
                )
            body.update({
                "resolution": "768x1344",
                "video_length": 124,
                "h3_reference_mode": "references",
                "h3_ref_image_size": "max",
            })
        else:
            for key in (
                "minimax_h3_text_encoder",
                "skip_steps_multiplier",
                "skip_steps_start_step_perc",
                "minimax_h3_window_storyboard",
                "h3_window_prompts",
                "h3_window_plan_signature",
                "h3_window_plan",
                "minimax_h3_references",
                "per_clip_minimax_h3_references",
                "minimax_h3_reference_detail",
            ):
                body.pop(key, None)

    if _is_minimax_h3_model(body.get("model_type")):
        from services.minimax_h3_duration import (
            apply_h3_dialogue_duration,
            apply_h3_vocal_timeline,
            h3_dialogue_split_error,
        )

        dialogue_duration_contract = apply_h3_dialogue_duration(
            body,
            _generation_model_def,
            preserve_requested=body.get("minimax_h3_audio_policy", "native") != "legacy",
        )
        if dialogue_duration_contract and dialogue_duration_contract.get("requires_split"):
            raise HTTPException(
                status_code=400,
                detail=h3_dialogue_split_error(dialogue_duration_contract),
            )
        apply_h3_vocal_timeline(body, _generation_model_def)

    if _generation_model_def.get("omni_reference"):
        from models.minimax_h3.ref2va import validate_reference_manifest

        try:
            per_clip_references = body.get("per_clip_minimax_h3_references")
            if per_clip_references is not None:
                if not isinstance(per_clip_references, list) or not per_clip_references:
                    raise ValueError(
                        "Per-clip MiniMax H3 references must contain one manifest per shot."
                    )
                body["per_clip_minimax_h3_references"] = [
                    validate_reference_manifest(manifest, require_files=True)
                    for manifest in per_clip_references
                ]
            else:
                body["minimax_h3_references"] = validate_reference_manifest(
                    body.get("minimax_h3_references"),
                    require_files=True,
                )
            detail = str(body.get("minimax_h3_reference_detail") or "match").strip().lower()
            if detail not in {"match", "max"}:
                raise ValueError("Reference detail must be 'match' or 'max'.")
            body["minimax_h3_reference_detail"] = detail
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    if (
        not legacy_h3
        and str(_generation_model_def.get("architecture") or "").startswith("minimax_h3")
    ):
        variants = _generation_model_def.get("minimax_h3_text_encoder_variants") or {}
        selected_encoder = str(
            body.get("minimax_h3_text_encoder")
            or _recommended_minimax_h3_encoder(body["model_type"], _generation_model_def)
        )
        if selected_encoder not in variants:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown MiniMax H3 text encoder '{selected_encoder}'. "
                    f"Choose one of: {', '.join(variants)}."
                ),
            )
        body["minimax_h3_text_encoder"] = selected_encoder
        try:
            from services.h3_runtime_policy import normalize_h3_runtime_request
            if normalize_h3_runtime_request(body, _generation_model_def):
                print(
                    "[MiniMax H3 Turbo] Experimental preset enabled: "
                    f"{body['num_inference_steps']} steps, "
                    f"LoRA strength {body['loras_multipliers'].split()[-1]}."
                )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        from models.minimax_h3.minimax_h3_handler import (
            apply_h3_window_memory_policy,
            h3_runtime_preflight,
        )

        h3_hardware = _get_cached_hardware()
        h3_runtime_advisory = h3_runtime_preflight(
            _generation_model_def,
            h3_hardware,
        )
        if h3_runtime_advisory:
            print(
                "[MiniMax H3] PERFORMANCE WARNING: "
                f"{h3_runtime_advisory['message']}"
            )
        h3_window_adjustment = apply_h3_window_memory_policy(
            body,
            _generation_model_def,
            h3_hardware,
        )
        if h3_window_adjustment:
            if h3_window_adjustment.get("unsupported"):
                raise HTTPException(
                    status_code=400,
                    detail=h3_window_adjustment["message"],
                )
            print(
                "[MiniMax H3] VRAM-aware FL2VA window: "
                f"{h3_window_adjustment['checkpoint'].title()} checkpoint, "
                f"{h3_window_adjustment['gpu_vram_gb']:.1f} GB, "
                f"{h3_window_adjustment['resolution']}, "
                f"{h3_window_adjustment['requested_window_frames']} -> "
                f"{h3_window_adjustment['effective_window_frames']} frames. "
                "Requested output duration is unchanged."
            )

        # H3 First/Last continuation passes need genuinely different prompts.
        # A timing wrapper around one full-shot prompt still lets the model see
        # (and prematurely perform) every later action.  Plan after the VRAM
        # policy has finalized the real pass length, then pass an explicit
        # prompt array to wgp's existing per-window selector.
        h3_storyboard_enabled = body.get("minimax_h3_window_storyboard", True) is not False
        h3_is_multi_clip = int(body.get("multi_prompts_gen_type") or 0) == 3
        try:
            h3_total_frames = int(body.get("video_length") or 0)
            h3_window_frames = int(body.get("sliding_window_size") or h3_total_frames or 0)
            h3_overlap_frames = int(body.get("sliding_window_overlap") or 0)
            h3_discard_frames = int(body.get("sliding_window_discard_last_frames") or 0)
        except (TypeError, ValueError):
            h3_total_frames = h3_window_frames = h3_overlap_frames = h3_discard_frames = 0
        h3_needs_storyboard = (
            h3_storyboard_enabled
            and (not _generation_model_def.get("omni_reference") or body.get("minimax_h3_reference_sequence") is True)
            and not h3_is_multi_clip
            and h3_total_frames > h3_window_frames > 0
        )
        if h3_needs_storyboard and _generation_model_def.get("omni_reference"):
            from services.h3_runtime_policy import reference_context
            body["h3_reference_context"] = reference_context(body.get("minimax_h3_references") or [])
        if h3_needs_storyboard:
            from services.h3_window_planner import (
                compute_h3_window_boundaries,
                h3_window_plan_signature,
            )

            h3_fps = float(_generation_model_def.get("fps", 24) or 24)
            h3_start_value = body.get("image_start")
            h3_end_value = body.get("image_end")
            h3_has_start = bool(h3_start_value)
            h3_has_end = bool(h3_end_value)
            h3_expected_signature = h3_window_plan_signature(
                str(body.get("prompt") or ""),
                model_type=str(body.get("model_type") or ""),
                resolution=str(body.get("resolution") or ""),
                total_frames=h3_total_frames,
                window_frames=h3_window_frames,
                overlap_frames=h3_overlap_frames,
                discard_frames=h3_discard_frames,
                fps=h3_fps,
                has_start_image=h3_has_start,
                has_end_image=h3_has_end,
                planning_style=str(body.get("minimax_h3_planning_style") or "faithful"),
                h3_audio_policy=str(body.get("minimax_h3_audio_policy") or "native"),
                reference_context=str(body.get("h3_reference_context") or ""),
            )
            h3_expected_count = len(
                compute_h3_window_boundaries(
                    h3_total_frames,
                    h3_window_frames,
                    fps=h3_fps,
                    overlap_frames=h3_overlap_frames,
                    discard_frames=h3_discard_frames,
                )
            )
            cached_prompts = body.get("h3_window_prompts")
            cached_plan = body.get("h3_window_plan")
            cached_is_valid = (
                isinstance(cached_prompts, list)
                and len(cached_prompts) == h3_expected_count
                and all(isinstance(item, str) and item.strip() for item in cached_prompts)
                and body.get("h3_window_plan_signature") == h3_expected_signature
            )
            if cached_is_valid:
                print(f"[MiniMax H3] Reusing reviewed {h3_expected_count}-window prompt plan.")
                if isinstance(cached_plan, dict):
                    h3_window_plan_response = cached_plan
            else:
                h3_images = [ref["path"] for ref in (body.get("minimax_h3_references") or []) if ref.get("type") == "image" and ref.get("path") and os.path.isfile(ref["path"])]
                for value in (h3_start_value, h3_end_value):
                    if isinstance(value, (list, tuple)):
                        value = value[0] if value else None
                    if isinstance(value, str) and value and os.path.isfile(value):
                        h3_images.append(value)
                # Planning can involve loading an LLM and a remote completion.
                # Persist the exact geometry and perform that work only after
                # the API has returned a visible, cancellable canonical task.
                body["_h3_window_plan_pending"] = {
                    "signature": h3_expected_signature,
                    "planning_style": body.get("minimax_h3_planning_style", "faithful"),
                    "h3_audio_policy": body.get("minimax_h3_audio_policy", "native"),
                    "reference_context": body.get("h3_reference_context", ""),
                    "expected_count": h3_expected_count,
                    "model_type": str(body.get("model_type") or ""),
                    "resolution": str(body.get("resolution") or ""),
                    "total_frames": h3_total_frames,
                    "window_frames": h3_window_frames,
                    "overlap_frames": h3_overlap_frames,
                    "discard_frames": h3_discard_frames,
                    "fps": h3_fps,
                    "has_start_image": h3_has_start,
                    "has_end_image": h3_has_end,
                    "image_paths": h3_images,
                }
                body.pop("h3_window_prompts", None)
                body.pop("h3_window_plan_signature", None)
                body.pop("h3_window_plan", None)

            body["minimax_h3_window_storyboard"] = True
            if cached_is_valid:
                body.pop("_h3_window_plan_pending", None)
                body["h3_window_prompts"] = list(cached_prompts)
                body["h3_window_plan_signature"] = h3_expected_signature
                if h3_window_plan_response is not None:
                    body["h3_window_plan"] = h3_window_plan_response
            # An explicitly reviewed plan may have been created moments ago
            # by the Enhance button, leaving the local planner resident. H3
            # inference needs that VRAM; the planner is cheap to reload later.
            try:
                from services import llm_service as _h3_planner_llm

                if (
                    _h3_planner_llm.is_loaded()
                    and _h3_planner_llm.get_status().get("provider") == "local"
                ):
                    _h3_planner_llm.unload_model()
            except Exception as unload_error:
                print(f"[MiniMax H3] Planner LLM release skipped: {unload_error}")
        else:
            body.pop("_h3_window_plan_pending", None)
            body.pop("h3_window_prompts", None)
            body.pop("h3_window_plan_signature", None)
            body.pop("h3_window_plan", None)

    # Defense: normalize video_prompt_type so flags whose required input
    # is missing get stripped before wgp.py's validation rejects the job.
    # This catches stale UI state (e.g. "I" persisting in a saved snapshot
    # after the user cleared their reference image) so users don't have to
    # manually wipe localStorage to recover.
    _normalize_video_prompt_type(body)
    # Same defense for image_prompt_type. Catches the user-reported bug
    # where image_prompt_type='S' persisted after the user cleared the
    # start-image preview (or never set one), causing wgp to reject T2V
    # generations with "You must provide a Start Image" instead of
    # falling back to T2V as Maestro's UX promises.
    _normalize_image_prompt_type(body)

    # ── SCAIL-2 operating guards ────────────────────────────────────
    # The React UI exposes no fps or audio controls for the SCAIL-2
    # class, so these keys can only reach the request via defaults
    # hydration — which Load Settings happily overwrites with values
    # recorded in pre-v1.3 sidecars (user-reported: restored jobs came
    # out 16fps/silent/6.4s even after the hydration fix). The server
    # is the durable place to hold the model's operating contract:
    #   1. Output follows the control video's fps (force_fps=control).
    #   2. The control video's audio is remuxed in (audio_prompt_type
    #      R) unless the request carries a real audio source (ABXK).
    #   3. video_length is recomputed from the UI's _duration_seconds
    #      at the guide's REAL fps, so "10s" means 10 seconds of the
    #      source no matter which fps the client assumed.
    #   4. sliding_window_size is clamped to the model's 81-frame
    #      training window — larger windows add VRAM risk (the whole
    #      driving window rides along as in-context tokens) without
    #      adding quality, and stale restores carried inflated values.
    try:
        _scail2_bmt = wgp.get_base_model_type(body.get("model_type"))
    except Exception:
        _scail2_bmt = None
    if _scail2_bmt in ("scail2_14B", "scail2_1.3B"):
        if not body.get("force_fps"):
            body["force_fps"] = "control"
        _apt = body.get("audio_prompt_type") or ""
        if not any(l in _apt for l in "ABXKR"):
            body["audio_prompt_type"] = "R"
        _guide = body.get("video_guide")
        _dur = body.get("_duration_seconds")
        if _guide and _dur and body.get("force_fps") == "control":
            try:
                if os.path.isfile(_guide):
                    from shared.utils.utils import get_video_info
                    _gfps, _, _, _gframes = get_video_info(_guide)
                    if _gfps and float(_gfps) > 0:
                        _gfps = float(_gfps)
                        # Cap the follow rate at 30fps: a 60fps source would
                        # double frames (and windows) for no visible gain —
                        # user report: a 10s test ran as 8 windows because
                        # the source was 60fps. wgp resamples the guide to
                        # the forced integer rate.
                        _fps_used = _gfps
                        if _gfps > 30.5:
                            _fps_used = 30.0
                            body["force_fps"] = "30"
                            print(f"[generate] SCAIL-2 fps cap: {_gfps:.6g}fps guide → generating at 30fps")
                        _want = int(round(float(_dur) * _fps_used))
                        if _gframes:
                            _want = min(_want, int(int(_gframes) * _fps_used / _gfps))
                        if _want >= 5 and _want != int(body.get("video_length") or 0):
                            print(
                                f"[generate] SCAIL-2 duration: video_length "
                                f"{body.get('video_length')} → {_want} "
                                f"({_dur}s × {_fps_used:.6g}fps)"
                            )
                            body["video_length"] = _want
            except Exception as _sferr:
                print(f"[generate] SCAIL-2 guide fps probe skipped: {_sferr}")
        try:
            _sw = int(body.get("sliding_window_size") or 0)
        except (TypeError, ValueError):
            _sw = 0
        if _sw > 81:
            print(f"[generate] SCAIL-2 window clamp: sliding_window_size {_sw} → 81")
            body["sliding_window_size"] = 81

    # ── Sliding-window safety bump ──────────────────────────────────
    # User-reported bug: a 19.6s audio upload in Studio Mode caused
    # video_length and sliding_window_size to both be auto-set to
    # 470 frames (19.6 * 24fps), but the clip generated as TWO sliding
    # windows with a stutter at the end. Root cause: wgp.py internally
    # quantizes both values to (k * latent_size + 1) form (line ~6725).
    # Floating-point rounding in the UI's Math.round(s * fps) compute
    # can land video_length and sliding_window_size on opposite sides
    # of a latent step boundary, triggering `video_length >
    # sliding_window_size` and forcing a multi-window split that wasn't
    # intended.
    #
    # Fix: if sliding_window_size is set and ≤ video_length + latent_size,
    # bump it to (video_length + latent_size + 1) so the post-quantize
    # comparison `video_length > sliding_window_size` always evaluates
    # false for single-window clips. Direct API callers benefit too —
    # not just the UI — because the safety net is at the endpoint.
    try:
        _video_length = int(body.get("video_length") or 0)
        _sliding_window = int(body.get("sliding_window_size") or 0)
        if _video_length > 0 and _sliding_window > 0:
            try:
                _, _, _latent = wgp.get_model_min_frames_and_step(body["model_type"])
            except Exception:
                _latent = 8
            # Safety bump ONLY applies to single-window-intent cases —
            # i.e. sliding_window_size is close to video_length. The
            # original bug fired when the user picked duration ≈ window
            # (e.g. both 470 frames) and float rounding pushed one above
            # the other after quantization, splitting a single-window
            # clip into two.
            #
            # CRITICAL: the OLD condition `_sliding_window <= _video_length
            # + _latent` was wrong — it fired for EVERY legitimate
            # sliding-window case where the window is much smaller than
            # the video (e.g. 120s clip with 20s windows: 500 ≤ 3000+8
            # → True → bump to 3009 → forces ENTIRE 120s into one window).
            # User-reported regression 2026-05-18.
            #
            # Correct condition: only bump when sliding_window_size is
            # within one latent step of video_length on EITHER side —
            # that's the actual quantize-boundary danger zone. For
            # legitimate sliding-window gens (sliding much smaller than
            # video) leave the values alone.
            if (
                not _generation_model_def.get(
                    "sliding_window_exact_total_frames",
                    False,
                )
                and (_video_length - _latent)
                <= _sliding_window
                <= (_video_length + _latent)
            ):
                _new_sw = _video_length + _latent + 1
                print(
                    f"[generate] Sliding-window safety bump: "
                    f"sliding_window_size {_sliding_window} → {_new_sw} "
                    f"(video_length={_video_length}, latent_size={_latent}). "
                    f"Prevents off-by-quantization window split that "
                    f"causes a stutter at the end of single-window clips."
                )
                body["sliding_window_size"] = _new_sw
    except Exception as _swerr:
        # Defensive: never let the bump break job submission. Log and
        # carry on with the user's original values.
        print(f"[generate] Sliding-window safety bump skipped: {_swerr}")

    # Capture workspace at submission time — NOT at execution time
    workspace = body.pop("workspace", None) or _get_active_workspace()
    leftovers = globals().get("_job_leftovers")
    if leftovers is not None:
        duplicate = leftovers.duplicate_for_submit(body, workspace)
        if duplicate is not None:
            if callable(getattr(request, "admit_generation_command", None)):
                raise HTTPException(status_code=409, detail=duplicate)
            return duplicate
    admission = getattr(request, "admit_generation_command", None)
    if callable(admission):
        return admission(body, workspace, provenance)
    job_out_dir = _workspace_dir(workspace)

    h3_preplan_pending = isinstance(
        body.get("_h3_window_plan_pending"), dict,
    )
    job = _new_generation_job(
        body,
        workspace,
        reserve_generation=not h3_preplan_pending,
        provenance=provenance,
    )
    job_id = job["id"]
    job["out_dir"] = job_out_dir
    _jobs[job_id] = job
    # Persist before the worker starts so a power loss in the tiny gap between
    # API acknowledgement and thread scheduling cannot lose the request.
    _persist_generation_job(job)

    # Cancel the matching runtime release as soon as work enters FIFO.
    if legacy_h3:
        minimax_h3_service.cancel_idle_shutdown()
    _cancel_h3_idle_release()

    # Non-daemon so generation survives browser disconnect during overnight runs
    thread = threading.Thread(
        target=_run_generation_with_preparation,
        args=(job_id,),
        daemon=False,
    )
    thread.start()

    response = {
        "job_id": job_id,
        "task_id": job.get("task_id"),
        "root_task_id": job.get("root_task_id") or job.get("task_id"),
        "status": "queued",
    }
    if h3_window_plan_response is not None:
        response["h3_window_plan"] = h3_window_plan_response
    return response

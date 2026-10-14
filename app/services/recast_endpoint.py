"""POST /api/v1/recast.

The body below is the launch function, verbatim. Collaborators that live in
other modules are imported. Launch's own objects arrive through bind(), called
once. _run_generation and _get_cached_hardware are forwarders: both are defined
later in launch, and the rig replaces the worker on launch after import.
"""

import asyncio, os, threading, time, traceback, uuid

from fastapi import HTTPException, Request
from services import execution_mode
from services.job_lifecycle import (
    finish_job, is_cancel_requested, register_abort_state, try_requeue,
    try_start, unregister_abort_state, update_job,
)
from services.recast_masks import (
    _RECAST_MASK_COLORS, _build_recast_character_mask, _count_recast_mask_people,
    _normalize_recast_character_mappings,
)
from services.recast_reference_compose import (
    _build_recast_native_people_conditioning, _build_recast_target_group_reference,
    _enable_recast_dynamic_source_scene_reference,
)
from services.recast_reference_prepare import (
    _RECAST_FAST_MODEL_TYPE, _RECAST_LEGACY_FAST_MODEL_TYPE,
    _RECAST_RELIGHTING_LORA_FILENAME, _RECAST_WARMUP_FRAMES, _build_recast_prompt,
    _normalize_recast_lora_settings, _normalize_recast_person_count,
    _normalize_recast_resolution_profile, _prepare_recast_reference_conditioning,
    _recast_resolution_for_source, _recast_window_size_for_profile, _resolve_recast_media,
)
from services.recast_shot_manifest import _build_recast_shot_manifest
from services.recast_shot_planning import (
    _plan_recast_shot_segments, _recast_probe_needs_bystander_tracking,
)
from services.recast_shot_run import _run_recast_shot_generation
from services.studio_generate import generate

# Free launch names, one slot each. bind() fills them.
wgp = None
_active_gen_states = None
_coordinated_generation_slot = None
_generation_job_acceptance = None
_get_active_workspace = None
_get_cached_hardware = None
_normalize_scail2_guidance_scale = None
_normalize_scail2_inference_steps = None
_register_manual_generation_job = None
_run_generation = None
_workspace_dir = None


def bind(*, wgp, _active_gen_states, _coordinated_generation_slot, _generation_job_acceptance, _get_active_workspace, _get_cached_hardware, _normalize_scail2_guidance_scale, _normalize_scail2_inference_steps, _register_manual_generation_job, _run_generation, _workspace_dir):
    """Take the launch objects this module reads. Launch calls this once."""
    globals().update(wgp=wgp, _active_gen_states=_active_gen_states, _coordinated_generation_slot=_coordinated_generation_slot, _generation_job_acceptance=_generation_job_acceptance, _get_active_workspace=_get_active_workspace, _get_cached_hardware=_get_cached_hardware, _normalize_scail2_guidance_scale=_normalize_scail2_guidance_scale, _normalize_scail2_inference_steps=_normalize_scail2_inference_steps, _register_manual_generation_job=_register_manual_generation_job, _run_generation=_run_generation, _workspace_dir=_workspace_dir)


async def recast_endpoint(request: Request):
    """Submit a Recast job: replace a person in an existing video with the
    character from a reference image (SCAIL-2 Replace mode). The colored
    person mask is built automatically with SAM3 keyword tracking as a
    pre-step INSIDE the job thread — tracking a 10s clip takes about a
    minute, so the endpoint returns a job_id immediately and the job's
    message reflects detection progress.

    Body: {
        video_path: str, ref_image_path?: str,
        character_mappings?: [{
            target: str, ref_image_path: str,
            additional_ref_image_paths?: list[str],
        }],
        target?: str ("who to replace" keyword, default "person"),
        person_count?: int (legacy grouped replacement count, 1-5),
        additional_ref_image_paths?: list[str] (legacy same-character views),
        reference_aligned_to_source?: bool (reference is an edited first frame),
        auto_face_detail?: bool (derive a tighter identity view when no
            additional view is supplied; default true),
        protect_bystanders?: bool (strict post-composite; default false),
        preserve_bystanders?: bool (single-reference native multi-person
            identity conditioning; default true),
        isolate_reference?: bool (neutralize unrelated reference background;
            default true),
        enhance_prompt?: bool (rewrite and append identity/scene continuity
            guidance; default false),
        use_relighting?: bool (optional official SCAIL-2 Relighting LoRA;
            default false),
        resolution_profile?: str ("480p", "512p", or "704p"; changes spatial
            resolution and, at 704p, the adaptive window size; never model or
            step schedule),
        prompt?: str (describe the completed video, not an edit command),
        start_time?: float, end_time?: float  (optional trim),
        model_type?: str (default scail2_14B_recast_fast),
        negative_prompt?: str, seed?: int,
        num_inference_steps?: int, guidance_scale?: float,
        activated_loras?: list, loras_multipliers?: str,
        workspace?: str,
    }
    """
    body = await request.json()
    if body.get("model_type") == "viggle_animate":
        from services.wangp_submission import JsonRequest, prepare_viggle_recast, resolve_wangp_media, wangp_media_url
        import subprocess as viggle_subprocess
        try:
            params = await asyncio.to_thread(
                prepare_viggle_recast, body,
                lambda value, workspace: resolve_wangp_media(value, workspace, uploads_dir=os.path.join(os.getcwd(), "uploads"), workspace_dir=_workspace_dir(workspace)),
                os.path.join(os.getcwd(), "uploads"),
                lambda path: wangp_media_url(path, body.get("workspace"), uploads_dir=os.path.join(os.getcwd(), "uploads"), workspace_dir=_workspace_dir(body.get("workspace"))),
            )
        except (ValueError, OSError, viggle_subprocess.SubprocessError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return await generate(JsonRequest(params, trusted_tool=getattr(request, "trusted_tool", None)))
    workspace = body.get("workspace")

    video_path = _resolve_recast_media(body.get("video_path"), workspace)
    if not video_path:
        raise HTTPException(status_code=400, detail=f"Video not found: {body.get('video_path')}")
    try:
        character_mappings, explicit_character_mappings = (
            _normalize_recast_character_mappings(body, workspace)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    ref_image_path = character_mappings[0]["ref_image_path"]
    target = character_mappings[0]["target"]
    person_count = (
        len(character_mappings)
        if explicit_character_mappings
        else _normalize_recast_person_count(body.get("person_count"))
    )
    reference_aligned_to_source = character_mappings[0][
        "reference_aligned_to_source"
    ]
    # Native SCAIL output is the default. Strict pixel lock remains available
    # as an expert fallback, but compositing source pixels over a freshly
    # rendered frame can create visible lighting/color seams.
    protect_bystanders = body.get("protect_bystanders") is True
    # Older saved jobs used ``preserve_scene_reference`` for an experimental
    # full-frame reference. Keep that input as a compatibility alias, but the
    # implementation now builds one neutral group reference containing only
    # the requested replacement and color-mapped people.
    if "preserve_bystanders" in body:
        preserve_bystanders = body.get("preserve_bystanders") is True
    elif "preserve_scene_reference" in body:
        preserve_bystanders = body.get("preserve_scene_reference") is True
    else:
        preserve_bystanders = True
    isolate_reference = body.get("isolate_reference") is not False
    auto_face_detail = body.get("auto_face_detail") is not False
    enhance_prompt = body.get("enhance_prompt") is True
    use_relighting = body.get("use_relighting") is True
    mask_colors = _RECAST_MASK_COLORS[:person_count]
    original_video_path = video_path

    # Optional trim — outpaint's frame-accurate re-encode pattern. The
    # trimmed clip becomes the canonical guide so the SAM3 mask and the
    # generation windows stay 1:1 with the frames actually used.
    trim_start = body.get("start_time")
    trim_end = body.get("end_time")
    if trim_start is not None and trim_end is not None:
        try:
            trim_start_f = float(trim_start)
            trim_end_f = float(trim_end)
            if trim_end_f - trim_start_f > 0.05 and trim_start_f >= 0:
                import subprocess
                trim_dir = os.path.join(os.getcwd(), "uploads")
                os.makedirs(trim_dir, exist_ok=True)
                trimmed_path = os.path.join(trim_dir, f"recast_trim_{uuid.uuid4().hex[:8]}.mp4")
                cmd = [
                    "ffmpeg", "-y", "-i", video_path,
                    "-ss", f"{trim_start_f:.3f}",
                    "-to", f"{trim_end_f:.3f}",
                    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "192k",
                    trimmed_path,
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                if proc.returncode == 0 and os.path.isfile(trimmed_path):
                    print(f"[Recast] Trimmed source to [{trim_start_f:.2f}s, {trim_end_f:.2f}s] -> {os.path.basename(trimmed_path)}")
                    video_path = trimmed_path
                else:
                    print(f"[Recast] Trim failed (continuing with full clip): {proc.stderr[:200]}")
        except (TypeError, ValueError) as e:
            print(f"[Recast] Invalid trim params: {e}")

    try:
        import decord
        vr = decord.VideoReader(video_path)
        fps = vr.get_avg_fps() or 25
        total_frames = len(vr)
        probe_frame = vr[0].asnumpy()
        del vr
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read video: {e}")

    resolution_profile = _normalize_recast_resolution_profile(
        body.get("resolution_profile"),
    )
    recast_width, recast_height = _recast_resolution_for_source(
        probe_frame,
        resolution_profile,
    )
    recast_resolution = f"{recast_width}x{recast_height}"
    print(
        f"[Recast] Resolution profile {resolution_profile} -> "
        f"{recast_resolution}; model and step schedule remain independent."
    )
    recast_vram_gb = 0.0
    try:
        recast_vram_gb = float(
            _get_cached_hardware().get("gpu_vram_gb", 0.0),
        )
    except (TypeError, ValueError, AttributeError):
        recast_vram_gb = 0.0
    recast_window_size = _recast_window_size_for_profile(
        resolution_profile,
        recast_vram_gb,
    )
    if recast_window_size <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "704p Recast currently requires at least 16 GB of VRAM. "
                f"Detected {recast_vram_gb:.1f} GB; select 512p or 480p."
            ),
        )
    if resolution_profile == "704p":
        hardware_label = (
            f"{recast_vram_gb:.1f} GB VRAM"
            if recast_vram_gb > 0
            else "unknown VRAM"
        )
        print(
            f"[Recast] Adaptive 704p window: {hardware_label} -> "
            f"{recast_window_size} frames with 5-frame overlap."
        )

    requested_model_type = body.get("model_type") or _RECAST_FAST_MODEL_TYPE
    # Settings saved before the dedicated Recast model existed selected the
    # general I2V-accelerated SCAIL Fast model. Transparently migrate those
    # jobs to the dedicated, corrected native-replacement recipe instead of
    # recreating the incompatible hybrid that caused weak replacements.
    model_type = (
        _RECAST_FAST_MODEL_TYPE
        if requested_model_type == _RECAST_LEGACY_FAST_MODEL_TYPE
        else requested_model_type
    )
    if wgp.get_model_def(model_type) is None:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model_type}")
    recast_fast = model_type == _RECAST_FAST_MODEL_TYPE
    # Both Recast profiles use SCAIL-2's native replacement conditioning.
    # Fast differs only in the official I2V LightX operating point; the base
    # model remains available as the full 40-step comparison.
    recast_conditioning = "native_replace_fast" if recast_fast else "native_replace"
    duration_s = total_frames / fps if fps else 0

    # Cap the follow rate at 30fps (same rationale as the generate guard):
    # a 60fps source doubles frames and windows for no visible gain. wgp
    # resamples the guide (and the SAM3 mask video, which carries the
    # source fps) to the forced integer rate.
    recast_force_fps = "control"
    gen_frames = total_frames
    if fps and float(fps) > 30.5:
        recast_force_fps = "30"
        gen_frames = int(round(duration_s * 30.0))
        print(f"[Recast] fps cap: {float(fps):.6g}fps source → generating at 30fps ({gen_frames} frames)")

    raw_recast_prompt = str(body.get("prompt") or "").strip()
    try:
        prompt = _build_recast_prompt(
            raw_recast_prompt, person_count, enhance=enhance_prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    activated_loras, loras_multipliers, use_relighting = (
        _normalize_recast_lora_settings(
            body.get("activated_loras"),
            body.get("loras_multipliers"),
            use_relighting,
        )
    )
    if use_relighting:
        relighting_index = next(
            index
            for index, name in enumerate(activated_loras)
            if str(name).replace("\\", "/").rsplit("/", 1)[-1].casefold()
            == _RECAST_RELIGHTING_LORA_FILENAME.casefold()
        )
        relighting_weight = loras_multipliers.split()[relighting_index]
        print(
            "[Recast] SCAIL-2 Relighting LoRA enabled with single-phase "
            f"weight {relighting_weight}."
        )

    serialized_mappings = [
        {
            "id": mapping["id"],
            "target": mapping["target"],
            "ref_image_path": mapping["ref_image_path"],
            "additional_ref_image_paths": list(
                mapping.get("additional_ref_image_paths", []),
            ),
            "reference_aligned_to_source": mapping[
                "reference_aligned_to_source"
            ],
        }
        for mapping in character_mappings
    ]
    initial_reference_paths = [
        path
        for mapping in character_mappings
        for path in [
            mapping["ref_image_path"],
            *mapping.get("additional_ref_image_paths", []),
        ]
    ]
    inference_steps = _normalize_scail2_inference_steps(
        body.get("num_inference_steps"),
        8 if recast_fast else 40,
    )
    # The Fast LightX recipe is CFG-distilled, but its denoising step count is
    # intentionally user-adjustable for quality/speed experiments.
    guidance_scale = (
        1.0
        if recast_fast
        else _normalize_scail2_guidance_scale(
            body.get("guidance_scale"),
            5.0,
        )
    )
    print(
        f"[Recast] Sampling: {inference_steps} steps, "
        f"guidance {guidance_scale:g} "
        f"({'Fast distilled' if recast_fast else 'HQ'})."
    )

    gen_params = {
        "prompt": prompt,
        "model_type": model_type,
        "negative_prompt": body.get("negative_prompt", ""),
        "seed": body.get("seed", -1),
        "activated_loras": activated_loras,
        "loras_multipliers": loras_multipliers,
        "guidance_scale": guidance_scale,
        "num_inference_steps": inference_steps,
        "flow_shift": 1 if recast_fast else 3,
        "sample_solver": "unipc",
        "generation_mode": "video",
        "edit_sub_mode": "recast",
        # The 0 is SCAIL-2's native Replace 1-5 People flag. The reference is
        # identity conditioning only; it must never become the output canvas.
        "video_prompt_type": f"V0{person_count}AI",
        "image_prompt_type": "",
        "video_guide": video_path,
        # video_mask is filled by the detection pre-step below.
        "image_refs": initial_reference_paths,
        "video_length": gen_frames,
        "_duration_seconds": duration_s,
        "resolution": recast_resolution,
        "force_fps": recast_force_fps,
        "audio_prompt_type": "R",
        "sliding_window_size": recast_window_size,
        "sliding_window_overlap": 5,
        "settings_version": 2.57,
        "custom_settings": {
            "image_ref_keyword_content": "human character",
            "scail2_animate_preprocessing": "raw",
            "scail2_recast_conditioning": "native_replace",
            # The detection pre-step prepares exact RGB/mask pairs.  Runtime
            # isolation stays off so it cannot harden the already-preserved
            # soft alpha edges a second time.
            "scail2_primary_reference_people": 1,
            "scail2_isolate_reference_background": False,
            "scail2_reference_alpha_path": "",
            # Recast gives CLIP the untouched primary image. When isolation is
            # requested, SCAIL-2 also encodes that original through the VAE and
            # retains its latent features inside the semantic subject mask;
            # the neutral reference remains outside the subject.
            "scail2_clip_reference_path": "",
            "scail2_identity_latent_isolation": isolate_reference,
            # Zero keeps the identity-preserving VAE blend on the ordinary
            # primary target reference. Native group preservation moves that
            # target reference to slot one and updates this index accordingly.
            "scail2_identity_latent_reference_index": 0,
            # Generate a disposable reverse-motion pre-roll from the first
            # control/mask frames, then remove it before output assembly.
            "scail2_recast_warmup_frames": _RECAST_WARMUP_FRAMES,
            # Establish identity and scene with all prepared references in
            # window one. Continuations use the primary SCAIL reference plus
            # clean generated overlap to avoid cumulative multi-ref artifacts.
            "scail2_primary_only_continuations": True,
        },
        # UI restore keys for the gallery Edits filter + Load Settings.
        "edit_video_path": original_video_path,
        "edit_start_time": float(trim_start) if trim_start is not None else 0.0,
        "edit_end_time": float(trim_end) if trim_end is not None else duration_s,
        "edit_recast_target": target,
        "edit_recast_person_count": person_count,
        "edit_recast_character_mappings": serialized_mappings,
        "edit_recast_conditioning_people": person_count,
        "edit_recast_ref_path": ref_image_path,
        "edit_recast_ref_aligned": reference_aligned_to_source,
        "edit_recast_isolate_reference": isolate_reference,
        "edit_recast_auto_face_detail": auto_face_detail,
        "edit_recast_enhance_prompt": enhance_prompt,
        "edit_recast_raw_prompt": raw_recast_prompt,
        "edit_recast_protect_bystanders": protect_bystanders,
        "edit_recast_preserve_bystanders": preserve_bystanders,
        "edit_recast_use_relighting": use_relighting,
        "edit_recast_resolution_profile": resolution_profile,
        "edit_recast_output_resolution": [recast_width, recast_height],
        "edit_recast_sliding_window_size": recast_window_size,
        "edit_recast_conditioning": recast_conditioning,
        "edit_recast_warmup_frames": _RECAST_WARMUP_FRAMES,
        # Consumed by _run_generation's deterministic Recast finishing pass.
        "_recast_protect_bystanders": protect_bystanders,
        "_recast_source_video": video_path,
    }

    workspace_name = workspace or _get_active_workspace()
    job_out_dir = _workspace_dir(workspace_name)
    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
        "phase": "", "message": "Queued (recast)", "created_at": time.time(),
        "params": gen_params, "output_files": [], "error": None,
        "workspace": workspace_name, "out_dir": job_out_dir,
    }
    _register_manual_generation_job(job)
    initial_probe_frame = probe_frame

    def _run_recast():
        abort_state = {"abort": False}
        shot_temp_dir = None
        shot_final_out_dir = None
        # The timeline-aware branch selects a later frame and therefore
        # reassigns ``probe_frame`` below. Initialize the resulting local from
        # the endpoint's decoded first frame before either branch reads it.
        probe_frame = initial_probe_frame
        try:
            # The SAM3 tracking pass is GPU work. Take the generation lock
            # for the detection phase so queued recasts don't run their
            # propagate_in_video passes concurrently with (and on top of)
            # the active job's denoising — user report: several queued
            # recasts all tracked at once and everything crawled. The lock
            # is released before _run_generation, which re-acquires it for
            # the generation phase; a waiting job may slip its detection in
            # between, but everything stays strictly one-GPU-task-at-a-time.
            with _coordinated_generation_slot(
                job, description="HocusPocus Lab GPU preparation · recast",
            ) as acquired:
                if not acquired:
                    return
                if not try_start(
                    job,
                    phase="Detecting target",
                    message=f"Finding {person_count} '{target}' subject{'s' if person_count != 1 else ''} in the video...",
                ):
                    return
                if not register_abort_state(
                    job, job_id, _active_gen_states, abort_state,
                ):
                    return
                from shared import magic_mask
                mapped_tracking = None
                mapping_anchors = None
                native_reference_frame_index = 0
                scene_anchor_frame = probe_frame
                scene_anchor_mask = None
                shot_aware_recast_required = False
                cast_transition_count = 0
                if explicit_character_mappings:
                    tracking_progress = {"bucket": -1}

                    def _abort_mapped_tracking():
                        if is_cancel_requested(job):
                            raise InterruptedError(
                                "Recast character tracking was cancelled",
                            )

                    def _mapped_tracking_progress(
                        mapping_index, mapping_total, done, total,
                    ):
                        percent = min(
                            100,
                            max(
                                0,
                                int(round(
                                    100
                                    * (
                                        mapping_index
                                        + float(done) / max(1, total)
                                    )
                                    / max(1, mapping_total)
                                )),
                            ),
                        )
                        bucket = percent // 5
                        if bucket == tracking_progress["bucket"]:
                            return
                        tracking_progress["bucket"] = bucket
                        if not update_job(
                            job,
                            phase="Tracking timeline",
                            message=(
                                "Finding mapped characters across shots... "
                                f"{percent}%"
                            ),
                        ):
                            raise InterruptedError(
                                "Recast character tracking was cancelled",
                            )

                    try:
                        mapped_tracking = _build_recast_character_mask(
                            video_path,
                            character_mappings,
                            os.path.join(os.getcwd(), "uploads"),
                            progress_callback=_mapped_tracking_progress,
                            abort_callback=_abort_mapped_tracking,
                        )
                    except InterruptedError:
                        return

                    tracking_fps = float(
                        mapped_tracking.get("fps") or fps or 25.0
                    )
                    cast_transition_hold_frames = max(
                        4,
                        min(
                            12,
                            int(round(max(1.0, tracking_fps) * 0.2)),
                        ),
                    )
                    cast_preview = _plan_recast_shot_segments(
                        mapped_tracking["mapping_masks"],
                        mapped_tracking["shot_ranges"],
                        split_cast_transitions=True,
                        min_cast_run_frames=cast_transition_hold_frames,
                    )
                    cast_transition_count = max(
                        0,
                        len(cast_preview) - int(mapped_tracking["shot_count"]),
                    )
                    shot_aware_recast_required = (
                        int(mapped_tracking["shot_count"]) > 1
                        or cast_transition_count > 0
                    )
                    common_index = mapped_tracking["common_frame_index"]
                    scene_index = mapped_tracking["scene_anchor_index"]
                    native_reference_frame_index = (
                        common_index
                        if common_index is not None
                        else scene_index
                    )
                    probe_frame = mapped_tracking["source_frames"][
                        native_reference_frame_index
                    ]
                    probe_mask = mapped_tracking["mask_frames"][
                        native_reference_frame_index
                    ]
                    scene_anchor_frame = mapped_tracking["source_frames"][
                        scene_index
                    ]
                    scene_anchor_mask = mapped_tracking["mask_frames"][
                        scene_index
                    ]
                    mapping_anchors = []
                    for summary in mapped_tracking["mapping_summaries"]:
                        anchor_index = summary["anchor_frame_index"]
                        mapping_anchors.append({
                            "frame_index": anchor_index,
                            "source_frame": mapped_tracking["source_frames"][
                                anchor_index
                            ],
                            "source_mask": mapped_tracking["mask_frames"][
                                anchor_index
                            ],
                        })
                    job["params"]["edit_recast_timeline_anchors"] = [
                        dict(summary)
                        for summary in mapped_tracking["mapping_summaries"]
                    ]
                    job["params"]["edit_recast_recovered_shots"] = [
                        dict(item)
                        for item in mapped_tracking.get(
                            "recovered_shots",
                            [],
                        )
                    ]
                    job["params"]["edit_recast_shot_ranges"] = [
                        list(bounds)
                        for bounds in mapped_tracking["shot_ranges"]
                    ]
                    job["params"]["edit_recast_shot_count"] = (
                        mapped_tracking["shot_count"]
                    )
                    job["params"]["edit_recast_common_frame_index"] = (
                        common_index
                    )
                    job["params"]["edit_recast_timeline_aware"] = (
                        mapped_tracking["timeline_aware"]
                    )
                    job["params"]["edit_recast_cast_transition_count"] = (
                        cast_transition_count
                    )
                    print(
                        "[Recast] Timeline discovery mapped "
                        f"{person_count} character"
                        f"{'s' if person_count != 1 else ''} across "
                        f"{mapped_tracking['shot_count']} shot"
                        f"{'s' if mapped_tracking['shot_count'] != 1 else ''}; "
                        + (
                            f"shared anchor frame={common_index}."
                            if common_index is not None
                            else "no shared frame; using per-character anchors."
                        )
                    )
                    if cast_transition_count:
                        print(
                            "[Recast] Found "
                            f"{cast_transition_count} stable cast change"
                            f"{'s' if cast_transition_count != 1 else ''} "
                            "inside a camera shot; hidden identity pre-rolls "
                            "will initialize late entrants without splitting "
                            "the visible shot."
                        )
                    matched_people = person_count
                else:
                    probe_mask = magic_mask.generate_keyword_masks(
                        probe_frame[None], target, no_hole=True,
                        colorize_objects=True,
                        color_palette=mask_colors,
                        max_colored_objects=person_count,
                    )[0]
                    matched_people = _count_recast_mask_people(
                        probe_mask, mask_colors,
                    )
                    scene_anchor_mask = probe_mask
                if matched_people < person_count:
                    finish_job(
                        job,
                        "failed",
                        error=(
                            f"Found {matched_people} of {person_count} requested "
                            f"'{target}' subjects in the first frame. Try "
                            "another description, lower the person count, or "
                            "adjust the trim start."
                        ),
                        message="Not enough targets found",
                    )
                    return
                native_group_supported = (
                    not explicit_character_mappings
                    or (
                        not shot_aware_recast_required
                        and mapped_tracking["shot_count"] == 1
                        and mapped_tracking["common_frame_index"] is not None
                    )
                )
                map_native_bystanders = (
                    preserve_bystanders
                    and native_group_supported
                    and _recast_probe_needs_bystander_tracking(
                        probe_frame,
                        probe_mask,
                        person_count,
                    )
                )
                job["params"]["edit_recast_bystander_tracking"] = (
                    "full"
                    if map_native_bystanders
                    else (
                        "timeline_scene"
                        if preserve_bystanders and not native_group_supported
                        else "not_needed"
                    )
                )
                if preserve_bystanders and not map_native_bystanders:
                    if not native_group_supported:
                        print(
                            "[Recast] Multi-shot/separate-appearance mapping "
                            "will preserve surrounding people with per-window "
                            "source-scene anchors instead of one contradictory "
                            "group reference."
                        )
                    else:
                        print(
                            "[Recast] Anchor-frame probe found no additional "
                            "bystanders; skipping the second full SAM3 pass."
                        )
                if is_cancel_requested(job):
                    return
                if not update_job(
                    job,
                    phase="Preparing references",
                    message="Preparing exact SCAIL-2 reference crops and masks...",
                ):
                    return
                prepared_refs = _prepare_recast_reference_conditioning(
                    character_mappings,
                    probe_mask,
                    os.path.join(os.getcwd(), "uploads"),
                    job_id,
                    isolate_reference=isolate_reference,
                    selected_count=person_count,
                    auto_face_detail=auto_face_detail,
                    source_frame=probe_frame,
                    reference_canvas=(recast_width, recast_height),
                    mapping_anchors=mapping_anchors,
                )
                job["params"]["image_refs"] = prepared_refs["image_refs"]
                job["params"]["custom_settings"][
                    "scail2_reference_mask_path"
                ] = prepared_refs["primary_mask"]
                job["params"]["custom_settings"][
                    "scail2_additional_reference_mask_paths"
                ] = prepared_refs["additional_masks"]
                job["params"]["custom_settings"][
                    "scail2_reference_expected_colors"
                ] = prepared_refs["expected_colors"]
                job["params"]["custom_settings"][
                    "scail2_clip_reference_path"
                ] = prepared_refs["clip_identity_ref"]
                target_group_reference = None
                if explicit_character_mappings and person_count > 1:
                    target_group_reference = (
                        _build_recast_target_group_reference(
                            prepared_refs,
                            os.path.join(os.getcwd(), "uploads"),
                            job_id,
                            person_count,
                            shared_source_frame=(
                                probe_frame
                                if common_index is not None
                                else None
                            ),
                            shared_semantic_mask=(
                                probe_mask
                                if common_index is not None
                                else None
                            ),
                        )
                    )
                    # SCAIL-2 was trained to map several semantic colors from
                    # one primary multi-person reference. Keep the individual
                    # full/detail views as supporting evidence rather than
                    # asking the experimental multi-reference path to decide
                    # which unrelated identity owns each color.
                    job["params"]["image_refs"] = [
                        target_group_reference["image"],
                        *prepared_refs["image_refs"],
                    ]
                    job["params"]["custom_settings"][
                        "scail2_reference_mask_path"
                    ] = target_group_reference["mask"]
                    job["params"]["custom_settings"][
                        "scail2_additional_reference_mask_paths"
                    ] = [
                        prepared_refs["primary_mask"],
                        *prepared_refs["additional_masks"],
                    ]
                    job["params"]["custom_settings"][
                        "scail2_reference_expected_colors"
                    ] = [
                        None,
                        *prepared_refs["expected_colors"],
                    ]
                    job["params"]["custom_settings"][
                        "scail2_primary_reference_people"
                    ] = person_count
                    job["params"]["custom_settings"][
                        "scail2_identity_latent_reference_index"
                    ] = 1
                    job["params"]["edit_recast_cast_reference"] = (
                        target_group_reference["image"]
                    )
                    job["params"]["edit_recast_cast_mask"] = (
                        target_group_reference["mask"]
                    )
                    job["params"]["edit_recast_cast_mode"] = (
                        target_group_reference["mode"]
                    )
                    job["params"]["edit_recast_conditioning_people"] = (
                        person_count
                    )
                    print(
                        "[Recast] Built one native color-mapped cast "
                        f"reference for {person_count} characters "
                        f"({target_group_reference['mode']})."
                    )
                job["params"]["edit_recast_prepared_refs"] = list(
                    prepared_refs["image_refs"],
                )
                job["params"]["edit_recast_clip_identity_ref"] = (
                    prepared_refs["clip_identity_ref"]
                )
                job["params"]["edit_recast_auto_face_detail_refs"] = list(
                    prepared_refs["auto_face_detail_refs"],
                )
                job["params"]["edit_recast_reference_canvas"] = list(
                    prepared_refs["reference_canvas"],
                )
                source_scene_reference = None

                def _ensure_source_scene_reference(reason):
                    nonlocal source_scene_reference
                    if source_scene_reference is not None:
                        return source_scene_reference
                    source_scene_reference = (
                        _enable_recast_dynamic_source_scene_reference(
                            job["params"],
                            scene_anchor_frame,
                            scene_anchor_mask,
                            person_count,
                            os.path.join(os.getcwd(), "uploads"),
                            job_id,
                        )
                    )
                    job["params"][
                        "edit_recast_source_scene_reference_reason"
                    ] = reason
                    if (
                        explicit_character_mappings
                        and mapped_tracking["timeline_aware"]
                    ):
                        job["params"]["custom_settings"][
                            "scail2_timeline_source_scene_reference"
                        ] = True
                        job["params"][
                            "edit_recast_source_scene_conditioning"
                        ] = "per_window_timeline_reference"
                    print(
                        "[Recast] Enabled source-scene anchoring "
                        f"({reason}; hidden="
                        f"{source_scene_reference['hidden_fraction']:.1%}, "
                        f"margin={source_scene_reference['expansion_pixels']}px)."
                    )
                    return source_scene_reference

                print(
                    "[Recast] Prepared "
                    f"{len(prepared_refs['image_refs'])} exact reference "
                    "view(s) with paired semantic masks and an identity-first "
                    "primary VAE/CLIP image"
                    + (
                        f", including {len(prepared_refs['auto_face_detail_refs'])} "
                        "automatic face-detail view(s)."
                        if prepared_refs["auto_face_detail_refs"]
                        else "."
                    )
                )
                if explicit_character_mappings:
                    mask_path = mapped_tracking["video_mask"]
                else:
                    if not update_job(
                        job,
                        phase="Tracking targets",
                        message=(
                            f"Tracking '{target}' across "
                            f"{total_frames} frames..."
                        ),
                    ):
                        return
                    mask_path, _ = magic_mask.generate_video_mask(
                        video_path, target,
                        colorize_objects=True,
                        color_palette=mask_colors,
                        max_colored_objects=person_count,
                        background_color=(255, 255, 255),
                        output_dir=os.path.join(os.getcwd(), "uploads"),
                    )
                if is_cancel_requested(job):
                    return
                job["params"]["video_mask"] = mask_path
                if not map_native_bystanders:
                    _ensure_source_scene_reference(
                        "no separate bystander pass needed",
                    )
                if map_native_bystanders:
                    if not update_job(
                        job,
                        message="Mapping the other people for native preservation...",
                        phase="Mapping surrounding people",
                    ):
                        return

                    mapping_progress = {"bucket": -1}

                    def _native_people_progress(done, total):
                        percent = min(
                            100,
                            max(0, int(round(100 * float(done) / max(1, total)))),
                        )
                        bucket = percent // 5
                        if bucket == mapping_progress["bucket"]:
                            return
                        mapping_progress["bucket"] = bucket
                        if not update_job(
                            job,
                            message=f"Mapping the other people... {percent}%",
                            phase="Mapping surrounding people",
                        ):
                            raise InterruptedError("Recast bystander mapping was cancelled")

                    try:
                        native_people = _build_recast_native_people_conditioning(
                            video_path,
                            mask_path,
                            person_count,
                            os.path.join(os.getcwd(), "uploads"),
                            job_id,
                            target_references=prepared_refs[
                                "primary_target_refs"
                            ],
                            progress_callback=_native_people_progress,
                            reference_frame_index=(
                                native_reference_frame_index
                            ),
                        )
                    except InterruptedError:
                        return
                    except Exception as native_error:
                        # Native preservation is an enhancement. If broad
                        # person mapping is ambiguous, retain the known-good
                        # target-only Recast instead of failing the whole job.
                        print(
                            "[Recast] Native bystander conditioning unavailable; "
                            f"continuing target-only: {native_error}"
                        )
                        traceback.print_exc()
                        _ensure_source_scene_reference(
                            "native bystander mapping unavailable",
                        )
                    else:
                        if is_cancel_requested(job):
                            return
                        if native_people["reference_image"]:
                            job["params"]["video_mask"] = native_people["video_mask"]
                            target_image_refs = list(
                                prepared_refs["image_refs"],
                            )
                            target_mask_paths = [
                                prepared_refs["primary_mask"],
                                *prepared_refs["additional_masks"],
                            ]
                            target_expected_colors = list(
                                prepared_refs["expected_colors"],
                            )
                            # The color-mapped group is now the primary
                            # reference adjacent to the video timeline. Large
                            # target and face-detail views remain as supporting
                            # references, so bystander identity no longer
                            # arrives through a contradictory target-free frame.
                            job["params"]["image_refs"] = [
                                native_people["reference_image"],
                                *target_image_refs,
                            ]
                            job["params"]["custom_settings"][
                                "scail2_reference_mask_path"
                            ] = native_people["reference_mask"]
                            job["params"]["custom_settings"][
                                "scail2_additional_reference_mask_paths"
                            ] = target_mask_paths
                            job["params"]["custom_settings"][
                                "scail2_reference_expected_colors"
                            ] = [None, *target_expected_colors]
                            job["params"]["custom_settings"][
                                "scail2_primary_reference_people"
                            ] = native_people["conditioning_count"]
                            job["params"]["custom_settings"][
                                "scail2_identity_latent_reference_index"
                            ] = 1
                            job["params"]["video_prompt_type"] = (
                                f"V0{native_people['conditioning_count']}AI"
                            )
                            job["params"]["edit_recast_conditioning_people"] = (
                                native_people["conditioning_count"]
                            )
                            job["params"]["edit_recast_group_reference"] = (
                                native_people["reference_image"]
                            )
                            job["params"]["edit_recast_group_mask"] = (
                                native_people["reference_mask"]
                            )
                            print(
                                "[Recast] Native group conditioning mapped "
                                f"{native_people['conditioning_count']} people "
                                f"(targets={person_count}, "
                                f"bystanders={len(native_people['assignments'])})"
                            )
                        else:
                            _ensure_source_scene_reference(
                                "no additional bystanders survived full tracking",
                            )
                            print(
                                "[Recast] No additional visible bystanders fit "
                                "the native five-person conditioning limit."
                            )

                if (
                    explicit_character_mappings
                    and shot_aware_recast_required
                ):
                    if not update_job(
                        job,
                        phase="Preparing cast-aware segments",
                        message=(
                            "Preparing shot and cast-specific character "
                            "references..."
                        ),
                    ):
                        return
                    import secrets
                    import shutil
                    import tempfile

                    try:
                        resolved_seed = int(job["params"].get("seed", -1))
                    except (TypeError, ValueError):
                        resolved_seed = -1
                    if resolved_seed < 0:
                        resolved_seed = secrets.randbelow(1_000_000_000)
                    job["params"]["seed"] = resolved_seed

                    generation_fps = (
                        30.0
                        if recast_force_fps == "30"
                        else float(mapped_tracking.get("fps") or fps or 25.0)
                    )
                    try:
                        minimum_frames, _frame_step, latent_size = (
                            wgp.get_model_min_frames_and_step(model_type)
                        )
                    except Exception:
                        minimum_frames, latent_size = 5, 4

                    shot_temp_dir = tempfile.mkdtemp(
                        prefix="maestro-recast-shots-",
                    )
                    try:
                        shot_manifest = _build_recast_shot_manifest(
                            job["params"],
                            mapped_tracking,
                            prepared_refs,
                            shot_temp_dir,
                            job_id,
                            reference_canvas=(
                                recast_width,
                                recast_height,
                            ),
                            target_frame_count=gen_frames,
                            generation_fps=generation_fps,
                            minimum_frames=minimum_frames,
                            latent_size=latent_size,
                        )
                    except Exception:
                        shutil.rmtree(
                            shot_temp_dir,
                            ignore_errors=True,
                        )
                        raise

                    final_out_dir = job.get("out_dir") or _workspace_dir(
                        workspace_name,
                    )
                    shot_final_out_dir = final_out_dir
                    job["params"].update({
                        "_defer_output_publication": True,
                        "_recast_shot_manifest": shot_manifest["tasks"],
                        "_recast_shot_temp_dir": shot_temp_dir,
                        "_recast_final_out_dir": final_out_dir,
                        "_recast_shot_bundle": {
                            "shots": shot_manifest["shots"],
                            "published_shots": shot_manifest[
                                "published_shots"
                            ],
                            "frame_count": shot_manifest["frame_count"],
                            "fps": shot_manifest["fps"],
                            "camera_shot_count": shot_manifest[
                                "camera_shot_count"
                            ],
                            "cast_transition_count": shot_manifest[
                                "cast_transition_count"
                            ],
                            "resolved_seed": resolved_seed,
                        },
                        "edit_recast_shot_aware": True,
                        "edit_recast_shot_plan": shot_manifest[
                            "published_shots"
                        ],
                    })
                    if job["params"].get("_recast_protect_bystanders"):
                        print(
                            "[Recast] Strict pixel-lock fallback is disabled "
                            "for shot-aware generation; native shot references "
                            "preserve the surrounding scene."
                        )
                        job["params"]["_recast_protect_bystanders"] = False
                    # Generated shots and their references are disposable.
                    # Point the normal task engine at the private directory;
                    # the finishing worker publishes only the final join.
                    job["out_dir"] = shot_temp_dir
                    generated_count = len(shot_manifest["tasks"])
                    passthrough_count = sum(
                        1
                        for shot in shot_manifest["shots"]
                        if shot["mode"] == "passthrough"
                    )
                    print(
                        "[Recast] Shot-aware plan prepared "
                        f"{len(shot_manifest['shots'])} generation segments "
                        f"from {shot_manifest['camera_shot_count']} camera "
                        "shot"
                        f"{'s' if shot_manifest['camera_shot_count'] != 1 else ''} "
                        f"with {shot_manifest['cast_transition_count']} stable "
                        "cast transition"
                        f"{'s' if shot_manifest['cast_transition_count'] != 1 else ''} "
                        f"({generated_count} generated, "
                        f"{passthrough_count} source passthrough), "
                        f"{shot_manifest['frame_count']} exact output frames "
                        f"at {shot_manifest['fps']:.6g}fps."
                    )
        except Exception as e:
            traceback.print_exc()
            if shot_temp_dir and os.path.isdir(shot_temp_dir):
                import shutil

                shutil.rmtree(shot_temp_dir, ignore_errors=True)
                if shot_final_out_dir:
                    job["out_dir"] = shot_final_out_dir
            finish_job(
                job,
                "failed",
                error=f"Target detection failed: {e}",
                message="Detection failed",
            )
            return
        finally:
            if abort_state is not None:
                unregister_abort_state(job_id, _active_gen_states, abort_state)

        if not try_requeue(job, message="Queued (recast)", phase=""):
            if shot_temp_dir and os.path.isdir(shot_temp_dir):
                import shutil

                shutil.rmtree(shot_temp_dir, ignore_errors=True)
                if shot_final_out_dir:
                    job["out_dir"] = shot_final_out_dir
            return
        if job["params"].get("_recast_shot_manifest"):
            _run_recast_shot_generation(job_id)
        else:
            _run_generation(job_id)

    thread = (
        threading.Thread(target=_run_generation, args=(job_id,), daemon=False)
        if execution_mode.policy().simulated
        else threading.Thread(target=_run_recast, daemon=False)
    )
    thread.start()

    return {
        "job_id": job_id,
        "status": "queued",
        "frames": total_frames,
        "target": target,
        "person_count": person_count,
        "resolution_profile": resolution_profile,
        "resolution": recast_resolution,
        "sliding_window_size": recast_window_size,
        "num_inference_steps": inference_steps,
        "guidance_scale": guidance_scale,
        **_generation_job_acceptance(job),
    }

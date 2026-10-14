"""Standalone MMAudio sound-effect generation.

Launch keeps the name the worker calls. ``wgp``, ``os``, ``time``, ``copy``,
``traceback``, the cancel and job helpers, and the sidecar publisher are
read from launch's globals at call time, so a test that patches them is
seen. ``check_sfx_models(globals(), variant)`` therefore sees this module's
``wgp``, which is that same launch object.
"""
from __future__ import annotations

from services.generation_launch_binding import bindable

wgp = bindable("wgp")
os = bindable("os")
time = bindable("time")
copy = bindable("copy")
traceback = bindable("traceback")
is_cancel_requested = bindable("is_cancel_requested")
update_job = bindable("update_job")
finish_job = bindable("finish_job")
new_media_files = bindable("new_media_files")
record_job_outputs = bindable("record_job_outputs")
_task_registry = bindable("_task_registry")
_publish_generation_sidecar_for_studio_job = bindable("_publish_generation_sidecar_for_studio_job")


def _run_sfx_generation(job: dict, raw_params: dict, start_time: float):
    """Run standalone MMAudio SFX generation (called from _run_generation when sfx_mode is set).

    Handles two modes:
    - Video-guided: upload a video clip → MMAudio generates matching SFX audio
    - Text-only: prompt + duration → MMAudio generates audio from text description
    """
    try:
        if is_cancel_requested(job):
            return False
        if not update_job(
            job, message="Preparing MMAudio...", phase="Preparing MMAudio",
        ):
            return False

        from services.studio_sfx_execution import prepared_sfx_execution
        from services.studio_sfx_commands import check_sfx_models
        typed_sfx = prepared_sfx_execution(
            job, raw_params, registry=_task_registry(job["workspace"]),
            check_models=lambda variant: check_sfx_models(globals(), variant),
        )

        out_dir = job.get("out_dir") or wgp.save_path
        os.makedirs(out_dir, exist_ok=True)
        wgp.save_path = out_dir
        print(f"[SFX {job.get('job_id', '')}] save_path locked to: {out_dir}")
        before = set(os.listdir(out_dir)) if os.path.isdir(out_dir) else set()

        variant = raw_params.get("_mmaudio_variant")
        prompt = raw_params.get("MMAudio_prompt", "") or raw_params.get("prompt", "")
        neg_prompt = raw_params.get("MMAudio_neg_prompt", "")
        seed = raw_params.get("seed", -1)
        duration = raw_params.get("duration_seconds", 10)
        text_weight = float(raw_params.get("sfx_text_weight", 1.0))
        video_path = raw_params.get("video_guide") or None  # Normalize empty string to None

        # Resolve video_guide path if it's a relative upload path
        if video_path and not os.path.isabs(video_path):
            candidate = os.path.join("uploads", video_path)
            if os.path.isfile(candidate):
                video_path = candidate

        if video_path and not os.path.isfile(video_path):
            if typed_sfx:
                raise ValueError("The admitted SFX video is no longer available")
            print(f"[SFX] Warning: video_guide not found: {video_path}, falling back to text-only")
            video_path = None

        # If video provided, derive duration from it
        if typed_sfx:
            # The admission records the inspected guide duration and exact
            # source identity. Do not rederive it or silently cap the request.
            pass
        elif video_path:
            try:
                import decord
                vr = decord.VideoReader(video_path)
                fps = vr.get_avg_fps()
                duration = len(vr) / fps if fps > 0 else duration
                del vr
                print(f"[SFX] Video: {video_path} ({duration:.1f}s)")
            except Exception as e:
                print(f"[SFX] Could not read video duration: {e}")
        else:
            # MMAudio generates max ~20s per pass (VRAM and quality constraints)
            MAX_SFX_DURATION = 20.0
            if duration > MAX_SFX_DURATION:
                print(f"[SFX] Text-only: capping duration from {duration}s to {MAX_SFX_DURATION}s (MMAudio limit)")
                duration = MAX_SFX_DURATION
            print(f"[SFX] Text-only mode, duration={duration}s")

        # Get MMAudio settings with variant override
        mmaudio_enabled, _, mmaudio_persistence, mmaudio_model_name, mmaudio_model_path = \
            wgp.get_mmaudio_settings(wgp.server_config, variant_override=variant)

        if not mmaudio_enabled and variant is None:
            finish_job(
                job,
                "failed",
                error="MMAudio is not enabled in server configuration",
                message="Error: MMAudio not enabled. Enable it in Settings → Extensions.",
            )
            return False

        # Typed commands require installed dependencies, checked again above.
        # Keep legacy provisioning until its callers have been migrated.
        if not typed_sfx:
            if not update_job(
                job, message="Downloading MMAudio models...", phase="Downloading models",
            ):
                return False
            wgp.download_mmaudio(variant_override=variant)
        if is_cancel_requested(job):
            return False

        # Generate output filename — .mp4 when remuxing onto video, .wav for text-only.
        # A validated output_name (stored as output_filename) replaces the prompt stem.
        seed_val = seed if seed >= 0 else int(time.time()) % 100000
        safe_prompt = "".join(c if c.isalnum() or c in " _-" else "" for c in (prompt or "sfx"))[:40].strip().replace(" ", "_")
        has_video = video_path is not None
        out_ext = ".mp4" if has_video else ".wav"
        requested_name = raw_params.get("output_filename") or raw_params.get("output_name")
        base_filename = requested_name or f"sfx_{safe_prompt}_{seed_val}{out_ext}"
        output_path = wgp.get_available_filename(out_dir, base_filename, force_extension=out_ext)

        # Run MMAudio
        if not update_job(
            job,
            message="Generating sound effects...",
            phase="MMAudio Generation",
            progress=10,
        ):
            return False
        print(f"[SFX] Running MMAudio: prompt='{prompt}', neg='{neg_prompt}', "
              f"duration={duration:.1f}s, model={mmaudio_model_name}, video={'yes' if video_path else 'no'}")

        from postprocessing.mmaudio.mmaudio import video_to_audio
        persist = mmaudio_persistence == wgp.MMAUDIO_PERSIST_RAM

        video_to_audio(
            video=video_path,  # None for text-only mode
            prompt=prompt,
            negative_prompt=neg_prompt,
            seed=seed,
            num_steps=25,
            cfg_strength=float(raw_params.get("guidance_scale", 4.5)),
            duration=duration,
            save_path=output_path,
            persistent_models=persist,
            audio_file_only=not has_video,  # Remux onto video when provided, WAV-only for text mode
            model_name=mmaudio_model_name,
            model_path=mmaudio_model_path,
            text_weight=text_weight,
        )
        # Publish files even when cancellation arrived during MMAudio's
        # non-cooperative call; terminal status/message remain untouched.
        new_files = new_media_files(out_dir, before)
        record_job_outputs(job, new_files)
        if is_cancel_requested(job):
            return False

        # Save sidecar metadata
        elapsed = time.time() - start_time
        for fname in new_files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in {".wav", ".mp3", ".flac", ".mp4"}:
                continue
            sidecar = {
                "params": copy.deepcopy(raw_params) if typed_sfx else {
                    "prompt": prompt,
                    "MMAudio_prompt": prompt,
                    "MMAudio_neg_prompt": neg_prompt,
                    "seed": seed,
                    "model_type": f"mmaudio_{variant or 'v2'}",
                    "duration_seconds": duration,
                    "sfx_mode": True,
                },
                "upload_filenames": {"video_guide": os.path.basename(video_path)} if video_path else {},
                "generation_mode": "audio",
                "job_id": job.get("job_id", ""),
                "generation_time": round(elapsed),
                "created_at": time.time(),
            }
            _publish_generation_sidecar_for_studio_job(
                job, os.path.join(out_dir, fname), sidecar,
            )

        completed = finish_job(
            job,
            "completed",
            progress=100,
            step=0,
            total_steps=0,
            phase="",
            message="Done",
        )
        print(f"[SFX] Completed in {wgp.format_time(elapsed)}: {output_path}")
        return completed

    except Exception as e:
        traceback.print_exc()
        failure_updates = {"error": str(e), "message": f"Error: {e}"}
        # Tag the failure with OOM info if applicable so the UI can
        # surface the OOM recovery banner. detect_oom returns None
        # for non-OOM failures, in which case oom_info stays absent.
        try:
            from services.oom_detect import detect_oom
            _coef = float(wgp.server_config.get("vram_safety_coefficient", 0.80))
            _oom = detect_oom(e, _coef)
            if _oom:
                failure_updates["oom_info"] = _oom
        except Exception:
            pass  # Never fail a failure handler
        finish_job(job, "failed", **failure_updates)
        return False

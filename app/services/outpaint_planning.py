"""Outpaint sampling, timing, canvas geometry and shot planning.

The function bodies are the ones that used to live in ``_launch_runtime``.
Names they still read from launch are bound once, at call time.
"""

def _resolve_outpaint_sampling(
    body, base_model_type, model_def, model_defaults,
):
    """Resolve model-aware Outpaint steps and guidance.

    Outpaint used to omit the Studio Advanced values and independently fall
    back to 8 steps. That is valid for distilled LTX-2, but LTXV 13B Dev
    rejects fewer than 20 steps. Use each model's own defaults, honor locked
    schedules, and reject invalid API input before it reaches the queue.
    """
    model_def = model_def if isinstance(model_def, dict) else {}
    model_defaults = (
        model_defaults if isinstance(model_defaults, dict) else {}
    )
    default_steps = (
        model_def.get("num_inference_steps")
        or model_defaults.get("num_inference_steps")
        or 8
    )
    default_guidance = (
        model_def.get("guidance_scale")
        or model_defaults.get("guidance_scale")
        or 1.0
    )

    try:
        default_steps = int(default_steps)
        default_guidance = float(default_guidance)
        if model_def.get("lock_inference_steps", False):
            inference_steps = default_steps
        else:
            inference_steps = int(
                body.get("num_inference_steps", default_steps)
            )
        if model_def.get("lock_guidance_scale", False):
            guidance_scale = default_guidance
        else:
            guidance_scale = float(
                body.get("guidance_scale", default_guidance)
            )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Inference Steps and Guidance Scale must be numeric."
        ) from error

    if inference_steps <= 0:
        raise ValueError("Inference Steps must be greater than zero.")
    if (
        base_model_type == "ltxv_13B"
        and not model_def.get("lock_inference_steps", False)
        and inference_steps < 20
    ):
        raise ValueError(
            "LTX Video 13B requires at least 20 inference steps."
        )
    return inference_steps, guidance_scale


def _resolve_outpaint_video_timing(
    source_frames,
    source_fps,
    model_def,
    reference_fps=None,
):
    """Resolve Outpaint duration, FPS, and the model's 8n+1 frame grid.

    The short-form Diffusers LTX-2.3 Outpaint demo resamples every source to
    24 fps.  ``reference_fps`` remains available for reproducing that narrow
    demo contract and rounds *up* to the next complete latent group so the
    source tail is not discarded. Maestro's production video path omits it:
    preserving source timing produced materially better long-form continuity
    and lets the normal sliding-window path carry clips beyond one window.
    """
    model_def = model_def if isinstance(model_def, dict) else {}
    try:
        fallback_fps = float(model_def.get("fps") or 25)
    except (TypeError, ValueError):
        fallback_fps = 25.0
    if not math.isfinite(fallback_fps) or fallback_fps <= 0:
        fallback_fps = 25.0

    try:
        source_frame_count = max(1, int(source_frames))
    except (TypeError, ValueError):
        source_frame_count = 1
    try:
        source_rate = float(source_fps)
    except (TypeError, ValueError):
        source_rate = fallback_fps
    if not math.isfinite(source_rate) or source_rate <= 0:
        source_rate = fallback_fps
    uses_reference_rate = reference_fps is not None
    if uses_reference_rate:
        try:
            target_fps = float(reference_fps)
        except (TypeError, ValueError):
            target_fps = 24.0
        if not math.isfinite(target_fps) or target_fps <= 0:
            target_fps = 24.0
    else:
        target_fps = source_rate

    duration = source_frame_count / source_rate
    try:
        minimum_frames = max(
            1,
            int(model_def.get("frames_minimum") or 1),
        )
    except (TypeError, ValueError):
        minimum_frames = 1
    try:
        frame_step = max(
            1,
            int(
                model_def.get("latent_size")
                or model_def.get("frames_steps")
                or 1
            ),
        )
    except (TypeError, ValueError):
        frame_step = 1

    nominal_frames = max(
        float(minimum_frames),
        (
            duration * target_fps
            if uses_reference_rate
            else float(source_frame_count)
        ),
    )
    if uses_reference_rate:
        # The reference loader clamps samples past EOF to the final source
        # frame.  Preserve that behavior instead of dropping up to seven
        # source frames when converting to LTX's causal temporal grid.
        latent_steps = max(
            0,
            int(math.ceil((nominal_frames - 1) / frame_step)),
        )
    else:
        latent_steps = max(
            0,
            int((nominal_frames - 1) // frame_step),
        )
    target_frames = max(
        minimum_frames,
        latent_steps * frame_step + 1,
    )
    return duration, target_fps, target_frames


def _resolve_ltx2_outpaint_reference_model(requested_model_type):
    """Select the best locally available model for official Outpaint.

    Lightricks' published two-stage graph uses the LTX-2.3 Dev transformer
    with the Distilled 1.1 LoRA at 0.5.  Keep an explicitly selected Dev
    model.  When the UI supplied a baked-Distilled model, prefer a compatible
    Dev checkpoint only when it is already installed; otherwise retain the
    requested model as a no-download compatibility fallback.
    """

    from urllib.parse import unquote, urlparse
    from shared.utils import files_locator as fl

    requested_def = wgp.get_model_def(requested_model_type) or {}
    requested_is_dev = bool(
        requested_def.get("architecture") == "ltx2_22B"
        and requested_def.get("ltx2_pipeline", "two_stage")
        != "distilled"
    )
    if requested_is_dev:
        return requested_model_type

    requested_lower = str(requested_model_type or "").lower()
    dev_candidates = (
        ("ltx2_22B_fp8", "ltx2_22B_1_1", "ltx2_22B")
        if "fp8" in requested_lower
        else ("ltx2_22B_1_1", "ltx2_22B_fp8", "ltx2_22B")
    )
    seen = set()
    for candidate in dev_candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        candidate_def = wgp.get_model_def(candidate) or {}
        if (
            candidate_def.get("architecture") != "ltx2_22B"
            or candidate_def.get("ltx2_pipeline", "two_stage")
            == "distilled"
        ):
            continue
        urls = wgp.get_model_recursive_prop(
            candidate,
            "URLs",
            return_list=True,
        )
        for url in urls or []:
            filename = os.path.basename(
                unquote(urlparse(str(url)).path)
            )
            if (
                filename
                and fl.locate_file(filename, error_if_none=False)
                is not None
            ):
                return candidate
    return requested_model_type




_OUTPAINT_PIXEL_BUDGETS = {
    "480p": 480 * 848,
    "540p": 540 * 960,
    "720p": 720 * 1280,
    "1080p": 1088 * 1920,
}

# A 257-frame 704x1280 two-stage Outpaint is the largest composition verified
# to fit a 24 GB card with Maestro's normal streaming profile.
# Keep larger canvases within the same approximate pixel-frame activation
# budget by shortening each diffusion window. This affects peak VRAM, not the
# total clip length; the existing sliding-window path covers the remainder.
_OUTPAINT_SINGLE_STAGE_REFERENCE_PIXELS = 704 * 1280
_OUTPAINT_SINGLE_STAGE_REFERENCE_FRAMES = 257


def _cap_outpaint_single_stage_window(
    requested_frames,
    target_width,
    target_height,
    window_min=17,
    window_max=501,
):
    requested_frames = max(1, int(requested_frames))
    target_pixels = max(1, int(target_width) * int(target_height))
    window_min = max(1, int(window_min))
    window_max = max(window_min, int(window_max))
    capped = max(window_min, min(window_max, requested_frames))
    if target_pixels <= _OUTPAINT_SINGLE_STAGE_REFERENCE_PIXELS:
        return capped

    pixel_frame_budget = (
        _OUTPAINT_SINGLE_STAGE_REFERENCE_PIXELS
        * _OUTPAINT_SINGLE_STAGE_REFERENCE_FRAMES
    )
    safe_frames = max(window_min, int(pixel_frame_budget / target_pixels))
    # LTX-2's causal temporal grid is 1 + 8k frames. Keeping the window on
    # that grid prevents downstream rounding from increasing it again.
    safe_frames = 1 + max(0, (safe_frames - 1) // 8) * 8
    safe_frames = max(window_min, min(window_max, safe_frames))
    return min(capped, safe_frames)


def _resolve_outpaint_canvas_geometry(
    src_w,
    src_h,
    pad_top,
    pad_bottom,
    pad_left,
    pad_right,
    resolution_preset="auto",
    alignment=64,
):
    """Resolve one grid-aligned Outpaint canvas and protected source rect.

    LTX-2's VAE works on a 64-pixel spatial grid. Previously the endpoint
    computed padding against an arbitrary target (for example 896x1593)
    and wgp silently floored that target later (to 896x1536). The model and
    source-overlay coordinates consequently described different canvases.

    Scale the complete composition uniformly, snap the final canvas once,
    then derive fractional padding percentages from that exact canvas.
    """
    src_w = max(1, int(src_w))
    src_h = max(1, int(src_h))
    pad_top = max(0, int(pad_top))
    pad_bottom = max(0, int(pad_bottom))
    pad_left = max(0, int(pad_left))
    pad_right = max(0, int(pad_right))
    alignment = max(1, int(alignment))

    composed_w = src_w + pad_left + pad_right
    composed_h = src_h + pad_top + pad_bottom
    target_w = float(composed_w)
    target_h = float(composed_h)
    preset = str(resolution_preset or "auto").lower()
    if preset in _OUTPAINT_PIXEL_BUDGETS:
        scale = (
            _OUTPAINT_PIXEL_BUDGETS[preset]
            / max(1.0, target_w * target_h)
        ) ** 0.5
        target_w *= scale
        target_h *= scale

    def _align(value):
        return max(
            alignment,
            int(math.floor((float(value) / alignment) + 0.5))
            * alignment,
        )

    final_w = _align(target_w)
    final_h = _align(target_h)

    # Uniformly fit the requested composition into the aligned canvas. Any
    # few grid-rounding pixels left over are centered around the composition,
    # preserving both the source aspect and the user's source placement.
    scale = min(
        final_w / max(1.0, float(composed_w)),
        final_h / max(1.0, float(composed_h)),
    )
    fitted_w = composed_w * scale
    fitted_h = composed_h * scale
    composition_x = (final_w - fitted_w) / 2.0
    composition_y = (final_h - fitted_h) / 2.0
    overlay_x = int(round(composition_x + pad_left * scale))
    overlay_y = int(round(composition_y + pad_top * scale))
    overlay_w = max(1, int(round(src_w * scale)))
    overlay_h = max(1, int(round(src_h * scale)))
    overlay_x = max(0, min(overlay_x, final_w - overlay_w))
    overlay_y = max(0, min(overlay_y, final_h - overlay_h))

    resolved_left = overlay_x
    resolved_top = overlay_y
    resolved_right = max(0, final_w - overlay_x - overlay_w)
    resolved_bottom = max(0, final_h - overlay_y - overlay_h)
    dims = (
        100.0 * resolved_top / overlay_h,
        100.0 * resolved_bottom / overlay_h,
        100.0 * resolved_left / overlay_w,
        100.0 * resolved_right / overlay_w,
    )

    # Re-resolve through the same helper inference uses. These coordinates
    # are retained for legacy overlay metadata and make any float rounding
    # difference observable instead of allowing two geometries to diverge.
    from shared.utils.utils import get_outpainting_frame_location

    (
        model_overlay_h,
        model_overlay_w,
        model_overlay_y,
        model_overlay_x,
    ) = get_outpainting_frame_location(
        final_h,
        final_w,
        list(dims),
        1,
    )
    return {
        "final_w": final_w,
        "final_h": final_h,
        "dims": dims,
        "overlay_w": int(model_overlay_w),
        "overlay_h": int(model_overlay_h),
        "overlay_x": int(model_overlay_x),
        "overlay_y": int(model_overlay_y),
        "requested_w": composed_w,
        "requested_h": composed_h,
    }


def _format_outpaint_percentage(value):
    text = f"{float(value):.8f}".rstrip("0").rstrip(".")
    return text or "0"


def _detect_outpaint_video_shot_ranges(
    source_video, target_frame_count, *, abort_callback=None,
    min_shot_frames=4, absolute_cut_threshold=0.12,
):
    """Stream a video into tiny thumbnails and return hard-cut ranges.

    Outpaint only needs camera-cut boundaries, not the full-resolution frame
    tensor that Recast keeps for SAM tracking. Retaining 64x36 RGB thumbnails
    bounds memory while deliberately reusing Recast's proven adaptive cut
    scoring. ``target_frame_count`` matches the exact timeline LTX will
    generate; any source tail outside its causal 8n+1 grid is ignored just as
    it is by the ordinary continuous Outpaint path.
    """
    import cv2
    import numpy as np

    frame_limit = max(1, int(target_frame_count))
    capture = cv2.VideoCapture(str(source_video))
    if not capture.isOpened():
        capture.release()
        raise ValueError(
            f"Outpaint could not open the source video: {source_video}"
        )

    thumbnails = []
    try:
        while len(thumbnails) < frame_limit:
            if abort_callback is not None:
                abort_callback()
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            thumbnail = cv2.resize(
                frame,
                (64, 36),
                interpolation=cv2.INTER_AREA,
            )
            thumbnails.append(cv2.cvtColor(thumbnail, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()

    decoded_count = len(thumbnails)
    if decoded_count <= 0:
        raise ValueError("Outpaint source video contains no decodable frames.")
    if decoded_count < frame_limit:
        raise ValueError(
            "Outpaint source ended before its planned timeline "
            f"({decoded_count}/{frame_limit} frames)."
        )

    return _detect_recast_shot_ranges(
        np.stack(thumbnails),
        min_shot_frames=min_shot_frames,
        absolute_cut_threshold=absolute_cut_threshold,
    )


def _build_outpaint_shot_filter(
    start_frame, end_frame, pad_frames, fps,
):
    """Build an exact-frame, CFR filter for one lossless internal guide."""
    start = int(start_frame)
    end = int(end_frame)
    padding = max(0, int(pad_frames))
    rate = float(fps)
    if start < 0 or end <= start:
        raise ValueError("Outpaint shot frame bounds are invalid.")
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Outpaint shot FPS must be positive.")
    rate_text = f"{rate:.12g}"
    return (
        f"trim=start_frame={start}:end_frame={end},"
        f"setpts=N/({rate_text}*TB),"
        f"tpad=stop_mode=clone:stop={padding}"
    )


def _write_outpaint_shot_guide(
    source_video, output_path, *, start_frame, end_frame, pad_frames,
    fps, abort_callback=None,
):
    """Write one frame-exact, lossless H.264 guide without loading it whole."""
    import subprocess

    if abort_callback is not None:
        abort_callback()
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    filter_graph = _build_outpaint_shot_filter(
        start_frame,
        end_frame,
        pad_frames,
        fps,
    )
    ffmpeg_bin = os.environ.get("FFMPEG_BINARY", "ffmpeg")
    expected_frames = (
        int(end_frame) - int(start_frame) + max(0, int(pad_frames))
    )
    timeout = max(
        120,
        min(900, int(math.ceil(expected_frames / float(fps) * 10.0))),
    )
    command = [
        ffmpeg_bin,
        "-y",
        "-v",
        "error",
        "-i",
        str(source_video),
        "-map",
        "0:v:0",
        "-vf",
        filter_graph,
        "-an",
        "-map_metadata",
        "0",
        # The generated margins are color-sensitive. CRF 0 prevents an
        # intermediate guide encode from softening or shifting the protected
        # source before the IC-LoRA sees it.
        "-c:v",
        "libx264",
        "-crf",
        "0",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if abort_callback is not None:
        abort_callback()
    if completed.returncode != 0 or not os.path.isfile(output_path):
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        detail = (completed.stderr or "unknown ffmpeg error").strip()
        raise RuntimeError(
            "Could not prepare Outpaint camera shot: " + detail[:500]
        )

    actual_frames = _recast_video_frame_count(output_path)
    if actual_frames != expected_frames:
        try:
            os.remove(output_path)
        except OSError:
            pass
        raise RuntimeError(
            "Outpaint camera-shot guide changed timeline length "
            f"({actual_frames}/{expected_frames} frames)."
        )
    return output_path


def _build_outpaint_shot_manifest(
    base_params, source_video, shot_ranges, output_dir, job_id, *,
    target_frame_count, generation_fps, minimum_frames, latent_size,
    guide_writer=None, progress_callback=None, abort_callback=None,
):
    """Create exact-length official Outpaint tasks for every camera shot."""
    target_count = int(target_frame_count)
    if target_count <= 0:
        raise ValueError("Outpaint target timeline must contain frames.")
    ranges = [
        (int(bounds[0]), int(bounds[1]))
        for bounds in (shot_ranges or [])
    ]
    if not ranges:
        ranges = [(0, target_count)]
    cursor = 0
    for start, end in ranges:
        if start != cursor or end <= start or end > target_count:
            raise ValueError(
                "Outpaint camera shots must cover one contiguous timeline."
            )
        cursor = end
    if cursor != target_count:
        raise ValueError(
            "Outpaint camera shots do not cover the complete timeline."
        )

    writer = guide_writer or _write_outpaint_shot_guide
    os.makedirs(output_dir, exist_ok=True)
    tasks = []
    plans = []
    total_shots = len(ranges)
    for shot_index, (start, end) in enumerate(ranges):
        if abort_callback is not None:
            abort_callback()
        if progress_callback is not None:
            progress_callback(shot_index, total_shots)
        exact_frames = end - start
        generated_frames, trim_tail = _quantize_recast_shot_frame_count(
            exact_frames,
            minimum_frames,
            latent_size,
        )
        guide_path = os.path.join(
            output_dir,
            f"outpaint_{job_id}_shot_{shot_index + 1}_guide.mp4",
        )
        writer(
            source_video,
            guide_path,
            start_frame=start,
            end_frame=end,
            pad_frames=trim_tail,
            fps=generation_fps,
            abort_callback=abort_callback,
        )
        tasks.append({
            "shot_index": shot_index,
            "params": {
                "video_guide": guide_path,
                "video_length": generated_frames,
                "trim_tail_frames": trim_tail,
                "video_prompt_type": "VG",
                "image_prompt_type": "",
                "force_fps": "control",
                # Internal shots never replace their audio or perform the
                # continuous-path smear trim. One source track is attached
                # only after exact-frame assembly.
                "audio_prompt_type": "",
                "audio_guide": None,
                "audio_source": None,
                "_outpaint_preserve_audio": False,
                "_outpaint_source_video": None,
                "_outpaint_lock_source_pixels": False,
                "_outpaint_trim_smear": False,
                "output_filename": (
                    f"outpaint_{job_id}_shot_{shot_index + 1}.mp4"
                ),
            },
        })
        plans.append({
            "shot_index": shot_index,
            "start_frame": start,
            "end_frame": end,
            "frame_count": exact_frames,
            "generated_frame_count": generated_frames,
            "trim_tail_frames": trim_tail,
            "mode": "outpaint",
        })

    return {
        "tasks": tasks,
        "shots": plans,
        "published_shots": [dict(plan) for plan in plans],
        "frame_count": target_count,
        "fps": float(generation_fps),
    }

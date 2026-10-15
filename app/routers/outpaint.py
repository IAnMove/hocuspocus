"""POST /api/v1/outpaint.

The handler body is the one that used to live in ``_launch_runtime``; it is
the served endpoint, so the route table names this file. Launch hands this
module the objects it owns once, as the arguments of
:func:`create_outpaint_router`. The generation worker is defined further
down in launch, so launch passes a forwarder that calls launch's
``_run_generation``.
"""
import os
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from services import execution_mode
from services.outpaint_planning import (
    _cap_outpaint_single_stage_window,
    _format_outpaint_percentage,
    _resolve_ltx2_outpaint_reference_model,
    _resolve_outpaint_canvas_geometry,
    _resolve_outpaint_sampling,
    _resolve_outpaint_video_timing,
)
from services.outpaint_run import _prepare_and_run_outpaint

# Set by create_outpaint_router(); None until the full server mounts the route.
wgp = None
_get_active_workspace = None
_workspace_dir = None
_register_manual_generation_job = None
_generation_job_acceptance = None
_run_generation = None


async def outpaint_endpoint(request: Request):
    """Submit an outpaint job: extend video/image canvas using IC-LoRA.

    Body: {
        video_path: str, prompt: str, model_type: str,
        pad_top?: int, pad_bottom?: int, pad_left?: int, pad_right?: int,
        gamma_correct?: bool, seed?: int,
        num_inference_steps?: int, guidance_scale?: float,
        negative_prompt?: str,
        activated_loras?: list, loras_multipliers?: str, workspace?: str,
    }
    """
    body = await request.json()

    video_path = body.get("video_path")
    if not video_path:
        raise HTTPException(status_code=400, detail="video_path is required")
    if not os.path.isabs(video_path):
        workspace_dir = _workspace_dir(body.get("workspace"))
        candidate = os.path.join(workspace_dir, video_path)
        if os.path.isfile(candidate):
            video_path = candidate
    # Also check uploads folder
    if not os.path.isfile(video_path):
        uploads_candidate = os.path.join(os.getcwd(), "uploads", os.path.basename(video_path))
        if os.path.isfile(uploads_candidate):
            video_path = uploads_candidate
    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"Source file not found: {video_path}")

    model_type = body.get("model_type")
    if not model_type:
        raise HTTPException(status_code=400, detail="model_type is required")
    requested_model_type = model_type

    pad_top = int(body.get("pad_top", 0))
    pad_bottom = int(body.get("pad_bottom", 0))
    pad_left = int(body.get("pad_left", 0))
    pad_right = int(body.get("pad_right", 0))
    total_pad = pad_top + pad_bottom + pad_left + pad_right
    if total_pad <= 0:
        raise HTTPException(status_code=400, detail="At least one padding direction must be > 0")

    # Determine if source is video or image; get source dimensions
    ext = os.path.splitext(video_path)[1].lower()
    is_video = ext in (".mp4", ".mkv", ".avi", ".mov", ".webm")

    from PIL import Image as PILImage

    # Optional film-strip trim: if the UI sent start_time/end_time, ffmpeg-cut
    # the source to that range before reading frames. The trimmed clip becomes
    # the canonical video_path for the rest of the request. Falls back to
    # untrimmed source if ffmpeg fails or range is invalid.
    if is_video:
        trim_start = body.get("start_time")
        trim_end = body.get("end_time")
        if trim_start is not None and trim_end is not None:
            try:
                trim_start_f = float(trim_start)
                trim_end_f = float(trim_end)
                if trim_end_f - trim_start_f > 0.05 and trim_start_f >= 0:
                    import subprocess
                    import tempfile
                    trim_dir = os.path.join(os.getcwd(), "uploads")
                    os.makedirs(trim_dir, exist_ok=True)
                    trim_id = uuid.uuid4().hex[:8]
                    trimmed_path = os.path.join(trim_dir, f"outpaint_trim_{trim_id}.mp4")
                    # -ss + -to with re-encode for frame-accurate cut at the
                    # requested sub-second boundaries (stream-copy seeks to
                    # the nearest keyframe and would round our trim).
                    cmd = [
                        "ffmpeg", "-y", "-i", video_path,
                        "-ss", f"{trim_start_f:.3f}",
                        "-to", f"{trim_end_f:.3f}",
                        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                        "-c:a", "aac", "-b:a", "192k",
                        trimmed_path,
                    ]
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if proc.returncode == 0 and os.path.isfile(trimmed_path):
                        print(f"[Outpaint] Trimmed source to [{trim_start_f:.2f}s, {trim_end_f:.2f}s] -> {os.path.basename(trimmed_path)}")
                        video_path = trimmed_path
                    else:
                        print(f"[Outpaint] Trim failed (continuing with full clip): {proc.stderr[:200]}")
            except (TypeError, ValueError) as e:
                print(f"[Outpaint] Invalid trim params: {e}")

    if is_video:
        import decord
        vr = decord.VideoReader(video_path)
        source_total_frames = len(vr)
        source_fps = float(vr.get_avg_fps() or 0)
        src_h, src_w = vr[0].shape[:2]
        del vr
        total_frames = source_total_frames
    else:
        img = PILImage.open(video_path).convert("RGB")
        src_w, src_h = img.size
        source_total_frames = 1
        source_fps = 0.0
        total_frames = 1
        del img

    # Resolve the output grid and protected source rectangle together. The
    # fractional percentages survive through wgp so inference and later
    # metadata describe the same exact canvas.
    resolution_preset = str(body.get("resolution_preset") or "auto").lower()
    base_model_type = wgp.get_base_model_type(model_type)
    outpaint_alignment = 64 if base_model_type == "ltx2_22B" else 32
    geometry = _resolve_outpaint_canvas_geometry(
        src_w,
        src_h,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        resolution_preset,
        outpaint_alignment,
    )
    final_w = geometry["final_w"]
    final_h = geometry["final_h"]
    overlay_w = geometry["overlay_w"]
    overlay_h = geometry["overlay_h"]
    overlay_x = geometry["overlay_x"]
    overlay_y = geometry["overlay_y"]
    video_guide_outpainting = " ".join(
        _format_outpaint_percentage(value)
        for value in geometry["dims"]
    )

    # Auto stays near native dimensions; quality presets apply a pixel budget
    # before both axes are snapped to the model grid.
    if (
        final_w != geometry["requested_w"]
        or final_h != geometry["requested_h"]
    ):
        print(
            f"[Outpaint] Grid-aligned canvas: "
            f"{geometry['requested_w']}x{geometry['requested_h']} -> "
            f"{final_w}x{final_h}"
        )
    print(
        f"[Outpaint] Source: {src_w}x{src_h}, "
        f"Target: {final_w}x{final_h}, "
        f"Protected rect: {overlay_w}x{overlay_h}"
        f"+{overlay_x}+{overlay_y}, "
        f"Dims (%): {video_guide_outpainting}"
    )

    requested_mask_preservation = bool(
        body.get("mask_preserving_outpaint", True)
    )
    mask_preserving_outpaint = bool(
        requested_mask_preservation
        and is_video
        and base_model_type == "ltx2_22B"
    )
    if requested_mask_preservation and not mask_preserving_outpaint:
        print(
            "[Outpaint] Mask-preserving workflow is currently available "
            "for LTX-2.3 22B video outpainting; using the legacy path."
        )
    official_outpaint = bool(mask_preserving_outpaint)
    if official_outpaint:
        model_type = _resolve_ltx2_outpaint_reference_model(model_type)
        if model_type != requested_model_type:
            print(
                "[Outpaint] Official reference model stack: "
                f"{requested_model_type} -> {model_type} "
                "(installed Dev checkpoint + Distilled 1.1 LoRA at 0.5 "
                "+ In/Outpainting IC-LoRA)."
            )
        else:
            selected_def = wgp.get_model_def(model_type) or {}
            if selected_def.get("ltx2_pipeline", "two_stage") == "distilled":
                print(
                    "[Outpaint] No installed Dev checkpoint was found; "
                    "using the selected baked-Distilled model as a "
                    "compatibility fallback."
                )
        base_model_type = wgp.get_base_model_type(model_type)
        print(
            "[Outpaint] Using Lightricks' official two-stage workflow "
            "(#66FF00 mask guide, full reference attention, decoded-pixel "
            "handoff, and Laplacian source restoration)."
        )

    # The official mask-conditioned path requires full control strength. The
    # legacy rollback path keeps accepting the old conditioning control.
    if mask_preserving_outpaint:
        source_preservation = 1.0
    else:
        source_preservation = float(
            body.get("source_preservation", 1.0)
        )
        source_preservation = max(
            0.3,
            min(1.0, source_preservation),
        )

    # The official in/outpainting LoRA is fixed at its trained strength.
    # Legacy mode retains the old multiplier solely for rollback testing.
    if mask_preserving_outpaint:
        outpaint_lora_strength = 1.0
    else:
        outpaint_lora_strength = float(
            body.get("outpaint_lora_strength", 1.0)
        )
        outpaint_lora_strength = max(
            0.0,
            min(2.0, outpaint_lora_strength),
        )

    # Preserve source audio: outpainting only changes spatial canvas — the
    # temporal content (and therefore the audio) is identical to the source.
    # LTX-2 distilled, however, always synthesizes a fresh audio track via its
    # audio decoder, which replaces the source audio with unrelated synthetic
    # audio. We post-mux the original source audio back onto the output after
    # generation completes (see _outpaint_audio_postprocess in _run_generation).
    # Default True since the alternative (LTX-generated audio for an outpaint)
    # is essentially never what the user wants.
    preserve_source_audio = bool(body.get("preserve_source_audio", True)) and is_video

    # Lock source pixels: composite the original source clip back into the
    # source-area rectangle of the output. Default OFF — empirical testing
    # showed (a) the IC-LoRA's regenerated source area actually preserves
    # lip detail well, and (b) hard-overlaying source pixels creates a
    # visible rectangular seam because the model's outpainted region has
    # slightly different color/tone than raw source. Kept as opt-in for
    # power users who explicitly want pixel-perfect source area.
    lock_source_pixels = bool(
        body.get("lock_source_pixels", False)
    ) and is_video and not mask_preserving_outpaint

    # Trim sliding-window smear: at the boundary between window 1 and
    # window 2, the model's prefix-conditioning produces ~reuse_frames
    # frames of "stutter" content (showing the same source content as
    # window 1's last frame). Empirically this introduces a constant
    # ~9-frame lag for the rest of the output (windows 2+ all carry the
    # same offset; lag does NOT accumulate per boundary). Cutting 9
    # frames at the window 1→2 boundary realigns the output with audio
    # for the entire remaining duration. Default ON for multi-window
    # video outpaint since this is what the user actually needs to fix
    # lip sync. Single-window outpaint has no boundary so no-op.
    trim_window_smear = bool(body.get("trim_window_smear", True)) and is_video

    # Sliding window for long clips: outpaint VRAM scales with window frames ×
    # canvas pixels. Single-shot generation works for short clips at modest
    # resolutions but OOMs on longer clips (e.g. 57s @ 720p needs ~6 windows).
    # Use the model's recommended window default unless the caller overrides.
    # LTX-2 (per ltx2_handler.py): window_default=241 (~10s @ 24fps),
    # overlap_default=9, discard_last_frames=8 (LTX has 8 distorted tail
    # frames per window — discarding lets the next window's overlap region
    # replace them so seams stay clean).
    try:
        _model_def = wgp.get_model_def(model_type) or {}
    except Exception:
        _model_def = {}
    try:
        _model_defaults = wgp.get_default_settings(model_type) or {}
    except Exception:
        _model_defaults = {}
    if is_video:
        (
            source_duration,
            generation_fps,
            total_frames,
        ) = _resolve_outpaint_video_timing(
            source_total_frames,
            source_fps,
            _model_def,
        )
        print(
            "[Outpaint] Timing: "
            f"{source_total_frames} frames at {source_fps:.3f} fps "
            f"({source_duration:.3f}s) -> {total_frames} frames at "
            f"{generation_fps:g} fps"
        )
    if official_outpaint:
        # The official graph distills the Dev transformer to the published
        # eight-step schedule. Do not let stale saved settings alter it.
        inference_steps = 8
        guidance_scale = 1.0
        print(
            "[Outpaint] Reference sampling: 8-step masked first pass + "
            "2-step decoded-pixel refinement, CFG 1."
        )
    else:
        try:
            inference_steps, guidance_scale = _resolve_outpaint_sampling(
                body,
                wgp.get_base_model_type(model_type),
                _model_def,
                _model_defaults,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error
    _sw_defaults = _model_def.get("sliding_window_defaults", {})
    sliding_window_size = int(body.get("sliding_window_size", _sw_defaults.get("window_default", 241)))
    sliding_window_overlap = int(body.get("sliding_window_overlap", _sw_defaults.get("overlap_default", 9)))
    sliding_window_discard_last_frames = int(body.get(
        "sliding_window_discard_last_frames",
        _sw_defaults.get("discard_last_frames", 8),
    ))
    # Clamp window to model's reported max (defaults to 501 for LTX-2).
    _window_max = int(_sw_defaults.get("window_max", 501))
    _window_min = int(_sw_defaults.get("window_min", 17))
    sliding_window_size = max(_window_min, min(_window_max, sliding_window_size))
    if official_outpaint and is_video:
        requested_window_size = sliding_window_size
        sliding_window_size = _cap_outpaint_single_stage_window(
            sliding_window_size,
            final_w,
            final_h,
            _window_min,
            _window_max,
        )
        if sliding_window_size < requested_window_size:
            print(
                "[Outpaint] Two-stage Outpaint VRAM window cap: "
                f"{requested_window_size} -> {sliding_window_size} frames "
                f"for {final_w}x{final_h}. The complete clip will use "
                "additional sliding windows."
            )
    # Outpaint system LoRAs are selected internally. Remove a persisted manual
    # selection of either system file so rerunning old settings cannot load
    # both the legacy and official variants at once.
    activated_loras = list(body.get("activated_loras") or [])
    multiplier_tokens = [
        token.split(";", 1)[0]
        for token in str(body.get("loras_multipliers") or "").split()
    ]
    system_outpaint_loras = {
        "ltx-2.3-22b-ic-lora-outpaint.safetensors",
        "ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors",
    }
    filtered_loras = []
    filtered_multipliers = []
    for index, lora in enumerate(activated_loras):
        if os.path.basename(str(lora)).lower() in system_outpaint_loras:
            print(
                "[Outpaint] Ignoring manually selected system LoRA "
                f"{os.path.basename(str(lora))}; the workflow manages it."
            )
            continue
        if official_outpaint:
            print(
                "[Outpaint] Ignoring user LoRA "
                f"{os.path.basename(str(lora))}; the reference workflow "
                "manages its Distilled and IC-LoRA adapters internally."
            )
            continue
        filtered_loras.append(lora)
        filtered_multipliers.append(
            multiplier_tokens[index]
            if index < len(multiplier_tokens)
            else "1"
        )

    submitted_outpaint_prompt = str(body.get("prompt") or "").strip()
    if official_outpaint:
        # Lightricks recommends an empty/minimal prompt, or a description of
        # only the missing region. Appending a whole-scene instruction makes
        # the model redraw or duplicate subjects at the source boundary.
        outpaint_prompt = (
            "."
            if not submitted_outpaint_prompt
            or submitted_outpaint_prompt.lower() == "extend the scene naturally"
            else submitted_outpaint_prompt
        )
    else:
        raw_outpaint_prompt = submitted_outpaint_prompt
        if not raw_outpaint_prompt or raw_outpaint_prompt.lower() == "extend the scene naturally":
            raw_outpaint_prompt = (
                "the scene continues naturally beyond the original frame, "
                "consistent style and lighting"
            )
        outpaint_prompt = (
            f"{raw_outpaint_prompt}; seamlessly extend the scene into the "
            "empty margins, matching the existing content."
        )

    gen_params = {
        "prompt": outpaint_prompt,
        "model_type": model_type,
        # The published Outpaint app deliberately leaves this empty. A broad
        # generic negative prompt can shift the generated margins away from
        # the appearance of the protected source.
        "negative_prompt": (
            ""
            if official_outpaint
            else str(body.get("negative_prompt") or "")
        ),
        "seed": body.get("seed", -1),
        "guidance_scale": guidance_scale,
        "num_inference_steps": inference_steps,
        "video_length": max(total_frames, 17) if is_video else 1,
        # Keep the generated timeline on the source video's native cadence.
        # Forcing the reference demo's 24 fps collapsed a known-good 305-frame
        # / two-window clip into one 249-frame window and caused the generated
        # margins to diverge visibly from the protected source rectangle.
        "force_fps": "control" if is_video else "auto",
        "resolution": f"{final_w}x{final_h}",
        "generation_mode": "video" if is_video else "image",
        # No image_mode here, on purpose. An image source Outpaint on LTX-2 comes
        # out as a one-frame MP4 (validation N1), but WanGP's validate_settings
        # wipes video_guide_outpainting unless the model lists the image_mode
        # (ltx2_handler.py lists only 0): image_mode=1 would turn this into a
        # plain generation with no outpainting.
        # Tag for the gallery's Edits filter + Load Settings restore path.
        "edit_sub_mode": "outpaint",
        # V = source video guide (the ORIGINAL, unpadded source — the pipeline
        # places it into the padded canvas internally); G = masked inpaint mode
        # (required for outpaint IC-LoRA gamma-round-trip to trigger).
        "video_prompt_type": "VG" if is_video else "G",
        "video_guide": video_path if is_video else None,
        "image_start": video_path if not is_video else None,
        "video_guide_outpainting": video_guide_outpainting,
        "input_video_strength": body.get("input_video_strength", 1.0),
        "denoising_strength": source_preservation,
        # Read by ltx2.get_loras_transformer — NOT a standard wgp param, so it
        # must survive the signature filter. We pass it through raw_params and
        # ltx2.py picks it up via kwargs.get.
        "outpaint_lora_strength": outpaint_lora_strength,
        "outpaint_mask_preserve": mask_preserving_outpaint,
        "outpaint_official_stack": official_outpaint,
        # Match the current Lightricks graph as one coherent pipeline. The
        # implementation paints the exact marker immediately before VAE
        # encoding, keeps full reference attention, blends pass one back to
        # source pixels, resizes with Lanczos, and restores source again after
        # pass two. The marker-safe source pyramid prevents #66FF00 leakage.
        "single_stage_pipeline": False,
        "outpaint_full_resolution_refine": official_outpaint,
        "activated_loras": filtered_loras,
        "loras_multipliers": " ".join(filtered_multipliers),
        # Sliding window engages automatically when total_frames > sliding_window_size
        # (wgp.py:6739). For images / very short clips, force window > clip so the
        # pipeline runs single-shot (cheaper than multi-window for tiny inputs).
        "sliding_window_size": sliding_window_size if (is_video and total_frames > sliding_window_size) else (max(total_frames, 17) + 10 if is_video else 17),
        "sliding_window_overlap": sliding_window_overlap,
        "sliding_window_discard_last_frames": sliding_window_discard_last_frames,
        "settings_version": 2.53,
        # Underscore-prefixed flags survive job["params"] but get stripped by
        # the wgp.generate_video signature filter (line ~5119), so they don't
        # reach the inference pipeline. _run_generation reads them after the
        # job completes to drive post-processing (audio mux + source overlay).
        "_outpaint_preserve_audio": preserve_source_audio,
        "_outpaint_source_video": video_path if (preserve_source_audio or lock_source_pixels) else None,
        "_outpaint_lock_source_pixels": lock_source_pixels,
        "_outpaint_overlay_w": overlay_w,
        "_outpaint_overlay_h": overlay_h,
        "_outpaint_overlay_x": overlay_x,
        "_outpaint_overlay_y": overlay_y,
        "_outpaint_canvas_w": final_w,
        "_outpaint_canvas_h": final_h,
        # Private preparation metadata for automatic camera-shot dispatch.
        # It is stripped from the final sidecar after assembly.
        "_outpaint_generation_fps": generation_fps if is_video else None,
        "_outpaint_source_frame_count": (
            source_total_frames if is_video else None
        ),
        # Smear trim params: only meaningful when total_frames > sliding_window_size
        # (multi-window mode). Boundary 1 is at output position
        # sliding_window_size - sliding_window_discard_last_frames.
        # Smear count = sliding_window_overlap (reuse_frames) — the model
        # produces this many "duplicate" frames at the boundary that we trim.
        "_outpaint_trim_smear": trim_window_smear and is_video and total_frames > sliding_window_size,
        "_outpaint_smear_boundary_frame": sliding_window_size - sliding_window_discard_last_frames,
        "_outpaint_smear_count": sliding_window_overlap,
        # Restore-able state for the gallery's Load Settings flow. The
        # frontend recomputes canvas + video box from these on reload so
        # the user sees the same composition that produced the output.
        "edit_video_path": video_path,
        "outpaint_pad_top": pad_top,
        "outpaint_pad_bottom": pad_bottom,
        "outpaint_pad_left": pad_left,
        "outpaint_pad_right": pad_right,
        "outpaint_aspect": body.get("outpaint_aspect"),
        "outpaint_resolution_preset": resolution_preset,
        "outpaint_source_preservation": source_preservation,
        "outpaint_lora_strength_ui": outpaint_lora_strength,
        "outpaint_mask_preserving": mask_preserving_outpaint,
        "outpaint_requested_model_type": requested_model_type,
        "edit_outpaint_raw_prompt": submitted_outpaint_prompt,
        "outpaint_trim_start": body.get("start_time"),
        "outpaint_trim_end": body.get("end_time"),
    }
    # Strip None values so they don't override defaults downstream
    gen_params = {k: v for k, v in gen_params.items() if v is not None}

    workspace = body.get("workspace") or _get_active_workspace()
    job_out_dir = _workspace_dir(workspace)

    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
        "phase": "", "message": "Queued (outpaint)", "created_at": time.time(),
        "params": gen_params, "output_files": [], "error": None,
        "workspace": workspace, "out_dir": job_out_dir,
    }
    _register_manual_generation_job(job)

    worker = (
        _prepare_and_run_outpaint
        if official_outpaint and is_video and not execution_mode.policy().simulated
        else _run_generation
    )
    thread = threading.Thread(target=worker, args=(job_id,), daemon=False)
    thread.start()

    # Estimate window count for the response so the UI can surface it.
    # Mirrors wgp.compute_sliding_window_no for the multi-window case.
    if is_video and total_frames > sliding_window_size:
        _stride = max(1, sliding_window_size - sliding_window_discard_last_frames - sliding_window_overlap)
        _left = max(0, total_frames - sliding_window_size + sliding_window_discard_last_frames)
        _window_count = 1 + (_left + _stride - 1) // _stride
    else:
        _window_count = 1

    return {
        "job_id": job_id,
        "status": "queued",
        "source_size": f"{src_w}x{src_h}",
        "output_size": f"{final_w}x{final_h}",
        "outpainting_dims": video_guide_outpainting,
        "total_frames": total_frames,
        "sliding_window_size": sliding_window_size,
        "sliding_window_count": _window_count,
        **_generation_job_acceptance(job),
    }


def create_outpaint_router(
    *, wgp, get_active_workspace, workspace_dir, register_manual_generation_job,
    generation_job_acceptance, run_generation,
) -> APIRouter:
    """Mount POST /api/v1/outpaint. Launch calls this once; it is the one place this module takes launch objects."""
    globals().update(
        wgp=wgp,
        _get_active_workspace=get_active_workspace,
        _workspace_dir=workspace_dir,
        _register_manual_generation_job=register_manual_generation_job,
        _generation_job_acceptance=generation_job_acceptance,
        _run_generation=run_generation,
    )
    router = APIRouter()
    router.add_api_route(
        "/api/v1/outpaint",
        outpaint_endpoint,
        methods=["POST"],
    )
    return router

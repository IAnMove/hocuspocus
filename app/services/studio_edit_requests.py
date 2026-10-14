"""Retake, frame extraction, edit-anything, and inpaint requests.

The handlers are the launch functions, moved verbatim. The full server binds
the names below before a request. Inpaint is not next to the others, so it
has its own factory.
"""

import os
import threading
import time
import traceback
import uuid

from fastapi import HTTPException, Request

# Bound by the router factories. None until the full server mounts the routes.
_generation_job_acceptance = None
_get_active_workspace = None
_register_manual_generation_job = None
_resolve_wangp_visual_media = None
_run_generation = None
_workspace_dir = None
# Launch owns this constant (the managed-LoRA list still reads it). The
# factory stores the same string here before a request.
EDIT_ANYTHING_LORA_FILENAME = None


async def retake_video_endpoint(request: Request):
    """Submit a retake job: regenerate a time region of an existing video.

    Body: {
        video_path: str, start_time: float, end_time: float,
        prompt: str, model_type: str,
        negative_prompt?: str, seed?: int, guidance_scale?: float,
        num_inference_steps?: int, retake_strength?: float (0-1),
        workspace?: str
    }
    """
    body = await request.json()

    video_path = body.get("video_path")
    if not video_path:
        raise HTTPException(status_code=400, detail="video_path is required")
    if body.get("wangp_media"):
        from services.wangp_submission import resolve_wangp_media
        try:
            workspace = body.get("workspace") or _get_active_workspace()
            video_path = resolve_wangp_media(video_path, workspace, uploads_dir=os.path.join(os.getcwd(), "uploads"), workspace_dir=_workspace_dir(workspace))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    if not os.path.isabs(video_path):
        workspace_dir = _workspace_dir(body.get("workspace"))
        candidate = os.path.join(workspace_dir, video_path)
        if os.path.isfile(candidate):
            video_path = candidate
    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"Video not found: {video_path}")

    start_time = float(body.get("start_time", 0))
    end_time = float(body.get("end_time", -1))
    model_type = body.get("model_type")
    if not model_type:
        raise HTTPException(status_code=400, detail="model_type is required")

    try:
        import decord
        vr = decord.VideoReader(video_path)
        fps = vr.get_avg_fps()
        total_frames = len(vr)
        src_h, src_w = vr[0].shape[:2]
        del vr
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read video: {e}")

    start_frame = max(0, int(start_time * fps))
    end_frame = int(end_time * fps) if end_time > 0 else total_frames
    end_frame = min(end_frame, total_frames)
    if start_frame >= end_frame:
        raise HTTPException(status_code=400, detail="Invalid time range")

    gen_params = {
        "prompt": body.get("prompt", "retake"),
        "model_type": model_type,
        "negative_prompt": body.get("negative_prompt", ""),
        "seed": body.get("seed", -1),
        "guidance_scale": body.get("guidance_scale", 3.0),
        "num_inference_steps": body.get("num_inference_steps", 30),
        "video_length": total_frames,
        "resolution": body.get("resolution") or f"{src_w}x{src_h}",
        "generation_mode": "video",
        # Tag the output so the gallery's Edits filter and the UI's
        # loadSettingsFromOutput restore path can recognize this as a
        # retake-mode generation. Mirrors the same field added to the
        # other edit endpoints.
        "edit_sub_mode": "retake",
        "retake_video": video_path,
        "retake_start_frame": start_frame,
        "retake_end_frame": end_frame,
        "retake_strength": float(body.get("retake_strength", 1.0)),
        "retake_engine": body.get("retake_engine", "native"),
        "regenerate_audio": body.get("regenerate_audio", True),
        "activated_loras": body.get("activated_loras", []),
        # Strip multi-phase LoRA multipliers to single phase (retake is single-stage)
        "loras_multipliers": " ".join(m.split(";")[0] for m in (body.get("loras_multipliers", "") or "").split()),
        "sliding_window_size": total_frames + 10,
        "settings_version": 2.52,
        # Mirror these in plain UI-friendly keys for the Load Settings
        # restore path (frontend reads sidecar params and re-populates
        # the Retake controls).
        "edit_video_path": video_path,
        "edit_start_time": start_time,
        "edit_end_time": end_time,
    }

    workspace = body.get("workspace") or _get_active_workspace()
    job_out_dir = _workspace_dir(workspace)

    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
        "phase": "", "message": "Queued (retake)", "created_at": time.time(),
        "params": gen_params, "output_files": [], "error": None,
        "workspace": workspace, "out_dir": job_out_dir,
    }
    _register_manual_generation_job(job)

    thread = threading.Thread(target=_run_generation, args=(job_id,), daemon=False)
    thread.start()

    return {
        "job_id": job_id,
        "status": "queued",
        "retake_frames": f"{start_frame}-{end_frame}/{total_frames}",
        **_generation_job_acceptance(job),
    }


async def extract_frames_endpoint(request: Request):
    """Extract one or two frames from a video at specific timestamps.

    Used by the Edit Anything → "Send to Image Mode" round-trip: we extract
    the start and/or end frames of the user's chosen edit range so they
    can be loaded into Studio Image mode for prompt-driven editing, then
    fed back as boundary anchors to Edit Anything.

    Body: {
        video_path: str,
        start_time?: float,    # if provided, extract this frame
        end_time?: float,      # if provided, extract this frame
        wangp_media?: bool,    # resolve canonical media URLs within their roots
        workspace?: str,
    }

    Returns: {
        start_path, start_url,    # only if start_time provided
        end_path, end_url,        # only if end_time provided
        session_started_at,      # server Unix seconds, only for wangp_media
    }
    """
    body = await request.json()
    video_path = body.get("video_path")
    if not video_path:
        raise HTTPException(status_code=400, detail="video_path is required")
    if body.get("wangp_media"):
        try:
            video_path = _resolve_wangp_visual_media(video_path, body.get("workspace"))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    elif not os.path.isabs(video_path):
        # Resolve relative paths against the active workspace + uploads/
        for base in [_workspace_dir(body.get("workspace")), os.path.join(os.getcwd(), "uploads")]:
            cand = os.path.join(base, os.path.basename(video_path))
            if os.path.isfile(cand):
                video_path = cand
                break
    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"Video not found: {video_path}")

    start_time = body.get("start_time")
    end_time = body.get("end_time")
    if start_time is None and end_time is None:
        raise HTTPException(status_code=400, detail="At least one of start_time or end_time is required")

    import subprocess as _sp
    uploads = os.path.join(os.getcwd(), "uploads")
    os.makedirs(uploads, exist_ok=True)
    base_id = uuid.uuid4().hex[:8]

    def _extract(t: float, suffix: str) -> str:
        # PNG keeps the frame lossless — important since the user is going
        # to edit pixels in Image mode and we don't want compression to
        # creep into the boundary anchor.
        out = os.path.join(uploads, f"frame_{base_id}_{suffix}.png")
        cmd = [
            "ffmpeg", "-y", "-ss", f"{float(t):.3f}", "-i", video_path,
            "-frames:v", "1", "-q:v", "2", out,
        ]
        proc = _sp.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0 or not os.path.isfile(out):
            raise HTTPException(status_code=500, detail=f"ffmpeg extract failed: {proc.stderr[:200]}")
        return out

    response: dict = {}
    if start_time is not None:
        sp = _extract(float(start_time), "start")
        response["start_path"] = sp
        response["start_url"] = f"/api/v1/uploads/{os.path.basename(sp)}"
    if end_time is not None:
        ep = _extract(float(end_time), "end")
        response["end_path"] = ep
        response["end_url"] = f"/api/v1/uploads/{os.path.basename(ep)}"
    if body.get("wangp_media"):
        # Compare against output file timestamps from this same server clock.
        response["session_started_at"] = time.time()
    return response


async def edit_anything_endpoint(request: Request):
    """Submit an Edit Anything job: prompt-driven video edit using the
    Alissonerdx Edit Anything LoRA for LTX-2.3.

    Unlike Inpaint, this does NOT require a SAM mask. The LoRA is trained
    to interpret prompts in the patterns:
      Add:     "Add a/an [thing] with [attributes], [location]."
      Remove:  "Remove the [thing] [location]."
      Replace: "Replace the [original] [location] with a/an [new] [attributes]."
      Style:   "Convert the video into a [style name] style."

    Body: {
        video_path: str, prompt: str, model_type: str,
        start_time?: float, end_time?: float  (optional time range; default = full video),
        lora_strength?: float (default 1.0, try 1.2 if edit too weak),
        negative_prompt?: str, seed?: int,
        guidance_scale?: float (default 1.0 — distilled LoRA is designed to work at CFG=1),
        num_inference_steps?: int (default 8 — distilled),
        retake_strength?: float (default 1.0 — full regen of range; lower = preserve more source),
        activated_loras?: list, loras_multipliers?: str (user's OTHER LoRAs; ours gets appended),
        workspace?: str,
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
        if not os.path.isfile(video_path):
            uploads_candidate = os.path.join(os.getcwd(), "uploads", os.path.basename(video_path))
            if os.path.isfile(uploads_candidate):
                video_path = uploads_candidate
    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"Video not found: {video_path}")

    # Resolve optional boundary-anchor image paths the same way we resolve
    # the source video: absolute first, else workspace, else uploads/, else
    # the active output dir (gallery filename). Image-mode outputs come
    # back from the round-trip as bare filenames (e.g. "2026-04-27-...png")
    # which live in the active workspace's outputs/ folder.
    def _resolve_anchor_path(raw):
        if not raw:
            return None
        raw = str(raw)
        if os.path.isabs(raw) and os.path.isfile(raw):
            return raw
        for base in (
            _workspace_dir(body.get("workspace")),
            os.path.join(os.getcwd(), "uploads"),
            os.path.join(os.getcwd(), "outputs"),
        ):
            cand = os.path.join(base, os.path.basename(raw))
            if os.path.isfile(cand):
                return cand
        return None

    start_anchor_path = _resolve_anchor_path(body.get("start_anchor_path"))
    end_anchor_path = _resolve_anchor_path(body.get("end_anchor_path"))

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    model_type = body.get("model_type")
    if not model_type:
        raise HTTPException(status_code=400, detail="model_type is required")

    # Probe video dimensions and length
    try:
        import decord
        vr = decord.VideoReader(video_path)
        fps = vr.get_avg_fps()
        total_frames = len(vr)
        src_h, src_w = vr[0].shape[:2]
        del vr
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read video: {e}")

    # Optional time range (default = full video)
    start_time = float(body.get("start_time", 0))
    end_time = float(body.get("end_time", -1))
    start_frame = max(0, int(start_time * fps))
    end_frame = int(end_time * fps) if end_time > 0 else total_frames
    end_frame = min(end_frame, total_frames)
    if start_frame >= end_frame:
        raise HTTPException(status_code=400, detail="Invalid time range")

    # Merge user's activated LoRAs with the Edit Anything LoRA.
    # If the user already has it toggled on, we don't duplicate — just ensure
    # its multiplier reflects the lora_strength from the request.
    lora_strength = float(body.get("lora_strength", 1.0))
    lora_strength = max(0.1, min(2.0, lora_strength))
    user_activated = list(body.get("activated_loras") or [])
    user_mults_raw = (body.get("loras_multipliers", "") or "").split()
    # Strip multi-phase suffix — retake is single-stage
    user_mults = [m.split(";")[0] for m in user_mults_raw]

    activated_loras = list(user_activated)
    multipliers_list = list(user_mults)
    # Pad multipliers to match activated count if user under-specified
    while len(multipliers_list) < len(activated_loras):
        multipliers_list.append("1.0")

    if EDIT_ANYTHING_LORA_FILENAME in activated_loras:
        idx = activated_loras.index(EDIT_ANYTHING_LORA_FILENAME)
        multipliers_list[idx] = f"{lora_strength:.2f}"
    else:
        activated_loras.append(EDIT_ANYTHING_LORA_FILENAME)
        multipliers_list.append(f"{lora_strength:.2f}")

    print(f"[EditAnything] prompt='{prompt[:80]}', lora={EDIT_ANYTHING_LORA_FILENAME}, "
          f"strength={lora_strength:.2f}, range=[{start_frame}-{end_frame}]/{total_frames}, "
          f"cfg={body.get('guidance_scale', 1.0)}, steps={body.get('num_inference_steps', 8)}")

    gen_params = {
        "prompt": prompt,
        "model_type": model_type,
        "negative_prompt": body.get("negative_prompt", ""),
        "seed": body.get("seed", -1),
        # Distilled LTX + Edit Anything LoRA is designed for CFG=1.
        # Per the card: "Starting point: Distilled model with CFG = 1.
        # If edit is too weak: Increase CFG."
        "guidance_scale": float(body.get("guidance_scale", 1.0)),
        "num_inference_steps": int(body.get("num_inference_steps", 8)),
        "video_length": total_frames,
        "resolution": body.get("resolution") or f"{src_w}x{src_h}",
        "generation_mode": "video",
        # Tag the output for the gallery's Edits filter + Load Settings
        # restore path. Stored alongside generation_mode in the .meta.json
        # sidecar via _run_generation's params copy.
        "edit_sub_mode": "edit_anything",
        # Route through the native retake pipeline so we get the standard
        # temporal regen behavior. No spatial mask — the LoRA itself does
        # the region-aware editing per the prompt.
        "retake_video": video_path,
        "retake_start_frame": start_frame,
        "retake_end_frame": end_frame,
        "retake_strength": float(body.get("retake_strength", 1.0)),
        "retake_engine": "native",
        "regenerate_audio": body.get("regenerate_audio", True),
        "activated_loras": activated_loras,
        "loras_multipliers": " ".join(multipliers_list),
        "sliding_window_size": total_frames + 10,
        "settings_version": 2.52,
        # Track the source video + LoRA strength so the UI can rebuild
        # state when the user clicks "Load Settings" in the gallery.
        "edit_video_path": video_path,
        "edit_anything_lora_strength": lora_strength,
        "edit_start_time": start_time,
        "edit_end_time": end_time if end_time > 0 else (total_frames / fps if fps else 0),
        # Optional user-provided boundary anchors. When present, ltx2.py's
        # retake setup uses these instead of auto-extracting the source's
        # first/last frames as I2V anchors. Empty slots fall through to
        # source-extracted frames (matches today's behavior). See ltx2.py
        # _is_spatial_inpaint branch around line 1215. Paths are resolved
        # absolute above so ltx2.py's os.path.isfile check works regardless
        # of where the image came from (uploads/ or outputs/).
        "retake_user_start_anchor": start_anchor_path,
        "retake_user_end_anchor": end_anchor_path,
    }

    workspace = body.get("workspace") or _get_active_workspace()
    job_out_dir = _workspace_dir(workspace)

    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
        "phase": "", "message": "Queued (edit anything)", "created_at": time.time(),
        "params": gen_params, "output_files": [], "error": None,
        "workspace": workspace, "out_dir": job_out_dir,
    }
    _register_manual_generation_job(job)

    thread = threading.Thread(target=_run_generation, args=(job_id,), daemon=False)
    thread.start()

    return {
        "job_id": job_id, "status": "queued",
        "edit_range": f"{start_frame}-{end_frame}/{total_frames}",
        "lora_filename": EDIT_ANYTHING_LORA_FILENAME,
        **_generation_job_acceptance(job),
    }


async def inpaint_endpoint(request: Request):
    """Submit a text-driven inpaint job.

    Pipeline: SAM segment → LTX retake with spatial mask.

    Body: {
        video_path: str, description: str,
        start_time?: float, end_time?: float,
        model_type: str, retake_strength?: float,
        seed?: int, guidance_scale?: float, num_inference_steps?: int,
        negative_prompt?: str, mask_padding?: int, workspace?: str
    }
    """
    body = await request.json()
    video_path = body.get("video_path")
    if not video_path:
        raise HTTPException(status_code=400, detail="video_path is required")
    description = body.get("description")
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    model_type = body.get("model_type")
    if not model_type:
        raise HTTPException(status_code=400, detail="model_type is required")

    # Resolve path
    if not os.path.isabs(video_path):
        uploads_dir = os.path.join(os.getcwd(), "uploads")
        candidate = os.path.join(uploads_dir, os.path.basename(video_path))
        if os.path.isfile(candidate):
            video_path = candidate

    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"Video not found: {video_path}")

    # Read the source size up front: SAM pre-scaling below needs it.
    try:
        import decord
        vr = decord.VideoReader(video_path)
        fps = vr.get_avg_fps()
        total_frames = len(vr)
        src_h, src_w = vr[0].shape[:2]
        del vr
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read video: {e}")

    from services.inpaint_service import check_sam_status, parse_inpaint_intent, segment_video, unload_sam, ensure_sam_running, shutdown_sam

    start_time = float(body.get("start_time", 0))
    end_time = float(body.get("end_time", -1))
    mask_padding = int(body.get("mask_padding", 20))
    cached_masks_path = body.get("masks_path")

    # Step 1: Determine SAM target and LTX prompt
    # If user provided explicit sam_target, use it directly (no LLM parsing needed)
    explicit_sam_target = body.get("sam_target", "").strip()
    if explicit_sam_target:
        sam_target = explicit_sam_target
        intent = {"target": sam_target, "prompt": description, "negative_prompt": ""}
        print(f"[Inpaint] Using explicit SAM target: '{sam_target}'")
    else:
        try:
            intent = parse_inpaint_intent(description)
            sam_target = intent["target"]
        except Exception as e:
            traceback.print_exc()
            intent = {"target": description, "prompt": description, "negative_prompt": ""}
            sam_target = description

    # Pre-scale video for SAM if user selected a lower resolution
    # This reduces SAM VRAM/time and produces a correctly-sized mask for LTX
    sam_video_path = video_path
    _sam_scaled_path = None
    user_res = body.get("resolution", "")
    if user_res and "x" in user_res:
        try:
            user_w, user_h = int(user_res.split("x")[0]), int(user_res.split("x")[1])
            if user_w > 0 and user_h > 0 and (user_w < src_w or user_h < src_h):
                # Aspect-preserving scale (same logic as retake)
                max_dim = max(user_h, user_w)
                src_max = max(src_h, src_w)
                if src_max > max_dim:
                    scale = max_dim / src_max
                    scaled_h = (int(src_h * scale) // 32) * 32
                    scaled_w = (int(src_w * scale) // 32) * 32
                    import subprocess as _sp
                    _sam_scaled_path = video_path.rsplit('.', 1)[0] + "_sam_scaled.mp4"
                    _sp.run([
                        "ffmpeg", "-y", "-i", video_path,
                        "-vf", f"scale={scaled_w}:{scaled_h}:flags=lanczos",
                        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                        "-an", _sam_scaled_path
                    ], capture_output=True, timeout=120)
                    if os.path.isfile(_sam_scaled_path):
                        sam_video_path = _sam_scaled_path
                        print(f"[Inpaint] Pre-scaled video for SAM: {src_w}x{src_h} → {scaled_w}x{scaled_h}")
        except Exception as e:
            print(f"[Inpaint] Pre-scale warning (non-fatal): {e}")

    # Step 2: SAM segmentation (skip if cached mask provided)
    if cached_masks_path and os.path.isfile(cached_masks_path):
        masks_path = cached_masks_path
        print(f"[Inpaint] Using cached mask: {masks_path}")
    else:
        # Start SAM on demand if needed
        import asyncio
        sam_ready = await asyncio.to_thread(ensure_sam_running)
        if not sam_ready:
            raise HTTPException(status_code=503, detail="SAM service not available. Check installation.")
        try:
            seg_result = await asyncio.to_thread(
                segment_video,
                video_path=sam_video_path,
                text=sam_target,
                start_time=start_time,
                end_time=end_time,
                mask_padding=mask_padding,
            )
            masks_path = seg_result.get("masks_path")
            if not masks_path:
                raise HTTPException(status_code=500, detail="SAM returned no mask data")
            # Invert mask if requested
            if body.get("invert_mask") and os.path.isfile(masks_path):
                import numpy as _np
                mask = _np.load(masks_path)
                _np.save(masks_path, ~mask)
                print(f"[Inpaint] Mask inverted (selecting everything except '{sam_target}')")
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))

    # Clean up scaled video
    if _sam_scaled_path and os.path.isfile(_sam_scaled_path):
        try: os.remove(_sam_scaled_path)
        except OSError: pass

    # Step 2b: Shut down SAM completely to free all VRAM (including CUDA context)
    try:
        import asyncio
        await asyncio.to_thread(shutdown_sam)
    except Exception:
        pass

    # Step 3: Build retake params with spatial mask
    start_frame = max(0, int(start_time * fps))
    end_frame = int(end_time * fps) if end_time > 0 else total_frames
    end_frame = min(end_frame, total_frames)

    # Use user's resolution if provided, otherwise source
    resolution = body.get("resolution") or f"{src_w}x{src_h}"

    # CFG default bumped 1.0 → 3.5 for inpaint. At 1.0 the retake pipeline
    # runs a single unconditional pass, so the prompt barely influences the
    # regenerated masked region — the output looks ~identical to the source.
    # CFG > 1.0 triggers dual (positive + negative) prompt encoding inside
    # retake.py's new CFG branch, enabling prompt-driven replacement.
    _inpaint_cfg = float(body.get("guidance_scale", 3.5))
    _inpaint_steps = int(body.get("num_inference_steps", 8))
    _inpaint_retake_strength = float(body.get("retake_strength", 0.85))
    # Inpaint-specific default negative prompt. Distilled LTX-2.3's positive
    # and unconditional predictions are nearly identical, so CFG with an
    # empty negative gives `delta = (cond - uncond) ≈ 0` — no push. A concrete
    # negative prompt describing what we DON'T want (dull/static/unchanged)
    # gives the model a direction to move away from, making CFG actually
    # bite. User's explicit negative_prompt (if any) overrides this default.
    DEFAULT_INPAINT_NEG = (
        "unchanged, identical to source, no change, static pose, dull, plain, "
        "low detail, blurry, distorted, artifacts, extra limbs"
    )
    _inpaint_neg = (
        intent.get("negative_prompt")
        or body.get("negative_prompt")
        or DEFAULT_INPAINT_NEG
    )
    print(f"[Inpaint] CFG={_inpaint_cfg:.2f}, steps={_inpaint_steps}, retake_strength={_inpaint_retake_strength:.2f}, "
          f"prompt='{intent['prompt'][:60]}', neg='{_inpaint_neg[:60]}'")
    gen_params = {
        "prompt": intent["prompt"],
        "model_type": model_type,
        "negative_prompt": _inpaint_neg,
        "seed": body.get("seed", -1),
        "guidance_scale": _inpaint_cfg,
        "num_inference_steps": _inpaint_steps,
        "video_length": total_frames,
        "resolution": resolution,
        "activated_loras": body.get("activated_loras", []),
        "loras_multipliers": " ".join(m.split(";")[0] for m in (body.get("loras_multipliers", "") or "").split()),
        "generation_mode": "video",
        # Tag for the gallery's Edits filter + Load Settings restore path.
        "edit_sub_mode": "inpaint",
        "retake_video": video_path,
        "retake_start_frame": start_frame,
        "retake_end_frame": end_frame,
        "retake_strength": _inpaint_retake_strength,
        "retake_masks_path": masks_path,  # spatial mask from SAM
        "retake_engine": body.get("retake_engine", "native"),  # native pipeline with SpatialRegionMask
        "stage2_steps": body.get("stage2_steps", 3),
        # Set sliding window to cover full video — retake needs single pass
        "sliding_window_size": total_frames + 10,  # +10 buffer to ensure no split
        "settings_version": 2.52,  # prevent fix_settings from deleting sliding_window_size
        # Track restore-able fields for the UI.
        "edit_video_path": video_path,
        "edit_target": intent.get("target"),
        "edit_start_time": start_time,
        "edit_end_time": end_time if end_time > 0 else (total_frames / fps if fps else 0),
    }

    workspace = body.get("workspace") or _get_active_workspace()
    job_out_dir = _workspace_dir(workspace)

    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
        "phase": "inpaint", "message": f"Inpaint queued: {intent['target']}",
        "created_at": time.time(),
        "params": gen_params, "output_files": [], "error": None,
        "workspace": workspace, "out_dir": job_out_dir,
    }
    _register_manual_generation_job(job)

    thread = threading.Thread(target=_run_generation, args=(job_id,), daemon=False)
    thread.start()

    return {
        "job_id": job_id,
        "status": "queued",
        "target": intent["target"],
        "prompt": intent["prompt"],
        **_generation_job_acceptance(job),
    }

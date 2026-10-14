"""Retake and frame-extraction requests.

The handlers are the launch functions, moved verbatim. The full server binds
the names below before a request. Edit-anything and inpaint join this module
in a later change; their routes are not next to these two.
"""

import os
import threading
import time
import uuid

from fastapi import HTTPException, Request

# Bound by the router factories. None until the full server mounts the routes.
_generation_job_acceptance = None
_get_active_workspace = None
_register_manual_generation_job = None
_resolve_wangp_visual_media = None
_run_generation = None
_workspace_dir = None


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

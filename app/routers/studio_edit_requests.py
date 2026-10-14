"""HTTP routes for retake and frame extraction.

The handler bodies live in ``services.studio_edit_requests``. These functions
are the served endpoints, so the route table names this file.
"""

from fastapi import APIRouter, Request

import services.studio_edit_requests as _edit_requests
from services.studio_edit_requests import (
    extract_frames_endpoint as _extract_frames_endpoint,
    retake_video_endpoint as _retake_video_endpoint,
)


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
    return await _retake_video_endpoint(request)


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
    return await _extract_frames_endpoint(request)


def create_studio_retake_router(
    *,
    register_manual_generation_job,
    generation_job_acceptance,
    get_active_workspace,
    workspace_dir,
    run_generation,
    resolve_wangp_visual_media,
):
    """Mount retake and extract-frames in the order the launch server registered them."""
    module = _edit_requests
    module._register_manual_generation_job = register_manual_generation_job
    module._generation_job_acceptance = generation_job_acceptance
    module._get_active_workspace = get_active_workspace
    module._workspace_dir = workspace_dir
    module._run_generation = run_generation
    module._resolve_wangp_visual_media = resolve_wangp_visual_media
    router = APIRouter()
    router.add_api_route("/api/v1/retake", retake_video_endpoint, methods=["POST"])
    router.add_api_route("/api/v1/extract-frames", extract_frames_endpoint, methods=["POST"])
    return router

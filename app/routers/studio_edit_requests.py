"""HTTP routes for retake, frame extraction, edit-anything, and inpaint.

The handler bodies live in ``services.studio_edit_requests``. These functions
are the served endpoints, so the route table names this file.
"""

from fastapi import APIRouter, Request

import services.studio_edit_requests as _edit_requests
from services.studio_edit_requests import (
    edit_anything_endpoint as _edit_anything_endpoint,
    extract_frames_endpoint as _extract_frames_endpoint,
    inpaint_endpoint as _inpaint_endpoint,
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
    return await _edit_anything_endpoint(request)


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
    return await _inpaint_endpoint(request)


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


def create_studio_edit_anything_router(
    *,
    register_manual_generation_job,
    generation_job_acceptance,
    get_active_workspace,
    workspace_dir,
    run_generation,
    edit_anything_lora_filename,
):
    """Mount edit-anything where the launch server registered that route."""
    module = _edit_requests
    module._register_manual_generation_job = register_manual_generation_job
    module._generation_job_acceptance = generation_job_acceptance
    module._get_active_workspace = get_active_workspace
    module._workspace_dir = workspace_dir
    module._run_generation = run_generation
    module.EDIT_ANYTHING_LORA_FILENAME = edit_anything_lora_filename
    router = APIRouter()
    router.add_api_route("/api/v1/edit-anything", edit_anything_endpoint, methods=["POST"])
    return router


def create_studio_inpaint_router(
    *,
    register_manual_generation_job,
    generation_job_acceptance,
    get_active_workspace,
    workspace_dir,
    run_generation,
):
    """Mount inpaint where the launch server registered that route."""
    module = _edit_requests
    module._register_manual_generation_job = register_manual_generation_job
    module._generation_job_acceptance = generation_job_acceptance
    module._get_active_workspace = get_active_workspace
    module._workspace_dir = workspace_dir
    module._run_generation = run_generation
    router = APIRouter()
    router.add_api_route("/api/v1/inpaint", inpaint_endpoint, methods=["POST"])
    return router

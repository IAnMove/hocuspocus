"""HTTP route for POST /api/v1/generate.

The handler body lives in ``services.studio_generate``. This function is the
served endpoint, so the route table names this file, and it calls that handler.
"""

from fastapi import APIRouter, Request

import services.studio_generate as _studio_generate_module
from services.studio_generate import generate as _studio_generate


async def generate(request: Request):
    """Submit a generation job. Returns immediately with a job_id."""
    return await _studio_generate(request)


def create_studio_generate_router(
    *,
    jobs,
    new_generation_job,
    persist_generation_job,
    get_active_workspace,
    workspace_dir,
    cancel_h3_idle_release,
    is_character_sheet_engine,
    is_legacy_h3_model,
    is_minimax_h3_model,
    normalize_image_prompt_type,
    normalize_video_prompt_type,
    recommended_minimax_h3_encoder,
    run_generation_with_preparation,
    get_cached_hardware,
    collection_registry,
    ensure_generation_priority,
    execution_mode,
    minimax_h3_service,
    wgp,
):
    """Mount POST /api/v1/generate and point the handler at the launch objects."""
    module = _studio_generate_module
    module._jobs = jobs
    module._new_generation_job = new_generation_job
    module._persist_generation_job = persist_generation_job
    module._get_active_workspace = get_active_workspace
    module._workspace_dir = workspace_dir
    module._cancel_h3_idle_release = cancel_h3_idle_release
    module._is_character_sheet_engine = is_character_sheet_engine
    module._is_legacy_h3_model = is_legacy_h3_model
    module._is_minimax_h3_model = is_minimax_h3_model
    module._normalize_image_prompt_type = normalize_image_prompt_type
    module._normalize_video_prompt_type = normalize_video_prompt_type
    module._recommended_minimax_h3_encoder = recommended_minimax_h3_encoder
    module._run_generation_with_preparation = run_generation_with_preparation
    module._get_cached_hardware = get_cached_hardware
    module._workspace_collection_registry = collection_registry
    module.ensure_generation_priority = ensure_generation_priority
    module.execution_mode = execution_mode
    module.minimax_h3_service = minimax_h3_service
    module.wgp = wgp
    router = APIRouter()
    router.add_api_route("/api/v1/generate", generate, methods=["POST"])
    return router

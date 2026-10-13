"""Core/remote server (Apple Silicon and machines without a local AI recipe): editors, projects and remote APIs without Torch."""
from __future__ import annotations

import os
import shutil
import sys
from contextlib import nullcontext
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers.assets import create_assets_router
from routers.canonical_tasks import create_canonical_tasks_router
from routers.character_kit_face import create_character_kit_face_router
from routers.comics import create_comics_router
from routers import core_labs as labs
from routers.core_labs import create_core_labs_router
from routers.core_mcp import create_core_mcp_router
from routers.core_remote import create_core_remote_router
from routers.core_series_plan import create_core_series_plan_router
from routers.image_generation_commands import create_image_generation_commands_router
from routers.lan_auth import create_lan_auth_router
from routers.llm import create_llm_prompt_router, create_llm_router
from routers.mcp_access import create_mcp_access_router
from routers.projects import create_projects_router
from routers.music_productions import create_music_productions_router
from routers.productions import create_productions_router
from routers.production_media import create_production_media_router
from routers.recipes import create_recipes_router
from routers.scene_commands import create_scene_commands_router
from routers.scene_packages import create_scene_packages_router
from routers.series_assembly import create_series_assembly_router
from routers.series_review import create_series_review_router
from routers.style_library import create_style_library_router
from routers.system_capabilities import create_system_capabilities_router, require_capability_http
from routers.uploads import create_uploads_router
from routers.user_diagnostics import create_user_diagnostics_router
from routers.wizard_workflow_executor import create_wizard_workflow_executor_router
from routers.wizard_activity import create_wizard_activity_router
from routers.wizard_persistence import create_wizard_persistence_router
from routers.world3d_export import create_world3d_export_router, bind_world3d_renderer_origin
from routers.workspace_collections import create_workspace_collections_router
from services import (
    core_canonical_tasks,
    core_generation_commands,
    core_production,
    core_remote_image,
    scene_save,
    core_series_assembly,
    core_workspace as core,
    upload_stream,
    upload_video_metadata,
)
from services.mcp_access import McpAccess
from services.agent_activity import ActorHeaderMiddleware, AgentActivity
from services.production_media_commands import command_handlers as production_media_handlers
from services.studio_key import command_handlers as studio_key_handlers
from services.platform_capabilities import platform_capabilities
from services.scene_commands import SceneCommands
from services.style_library import StyleLibrary
from services.ui_distribution import build_status, recovery_html, report_identity
from services.wizard_workflow_executor import WizardWorkflowExecutor
from services.world3d_export import World3DExportService
from services.workspace_registry import WorkspaceRegistry

api = FastAPI(title="HocusPocus core")
api.add_middleware(ActorHeaderMiddleware)
from services.host_guard import install_host_guard
install_host_guard(api)
api.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost|\d+\.localhost)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)
api.include_router(create_lan_auth_router())
api.include_router(create_system_capabilities_router())
api.include_router(create_user_diagnostics_router(
    load_receipt=lambda workspace, intent_id: core_generation_commands.service().receipt(workspace, intent_id),
))
api.include_router(create_projects_router(list_workspaces=core.list_workspaces, workspace_dir=core.workspace_dir))
api.include_router(create_assets_router(
    list_workspaces=core.list_workspaces,
    workspace_dir=core.workspace_dir,
    uploads_dir=core.uploads_dir,
))
api.include_router(create_recipes_router(
    workspace_dir=core.workspace_dir,
    nsfw_allowed=lambda: False,
    get_model_def=lambda _name: None,
    safe_join=core.safe_join,
))
api.include_router(create_productions_router(
    list_workspaces=core.list_workspaces,
    list_pipelines=lambda _workspace: [],
))
api.include_router(create_music_productions_router(
    workspace_dir=core.workspace_dir,
    uploads_dir=core.uploads_dir,
))
api.include_router(create_workspace_collections_router(
    registry=lambda: WorkspaceRegistry(os.path.join(str(core.outputs_root()), "_hocuspocus", "workspaces-v1.json")),
))
api.include_router(create_style_library_router(StyleLibrary(str(core.outputs_root()))))
api.include_router(create_comics_router(
    workspace_dir=core.workspace_dir,
    get_active_workspace=core.active_workspace,
    safe_join=core.safe_join,
    get_services_config=core.services_raw,
    publish_legacy_task=None,
))
api.include_router(create_scene_commands_router(SceneCommands(core.workspace_dir)))
api.include_router(create_scene_packages_router(
    workspace_dir=core.workspace_dir,
    uploads_dir=core.uploads_dir,
    list_workspaces=core.list_workspaces,
))
_world3d_export = World3DExportService(
    workspace_dir=core.workspace_dir,
    registry_for=core_generation_commands.registry_for,
    app_url=os.environ.get("HOCUS_APP_URL", ""),
    uploads_dir=core.uploads_dir,
)
bind_world3d_renderer_origin(api, _world3d_export)
api.include_router(create_world3d_export_router(_world3d_export))
api.include_router(create_core_labs_router())
from routers.writing_guide import create_writing_guide_router
api.include_router(create_writing_guide_router(
    ensure_llm_loaded=core_production.ensure_llm_loaded, writing_override=core_production.comic_writing_llm,
))
api.include_router(create_series_assembly_router(
    resolve_workspace=labs._series_workspace,
    workspace_dir=core.workspace_dir,
    list_workspaces=core.list_workspaces,
    library_lock=labs._LOCK,
    read_library=labs._read_series,
    write_library=labs._write_series,
    find_series=labs._series_or_404,
    asset_local_path=core_series_assembly.asset_local_path,
    available_filename=core_series_assembly.available_filename,
    concatenate_clips=lambda *args, **kwargs: core_series_assembly.concatenate_clips(*args, **kwargs),
    iso_now=labs._iso_now,
))
api.include_router(create_core_series_plan_router())
api.include_router(create_series_review_router(
    resolve_workspace=labs._series_workspace, lock=labs._LOCK, read_library=labs._read_series,
    write_library=labs._write_series, iso_now=labs._iso_now,
))
api.include_router(create_core_remote_router())
_mcp_access = McpAccess(
    os.path.join(os.path.dirname(__file__), "settings", "mcp-access.json"),
)
api.include_router(create_core_mcp_router(_mcp_access))
api.include_router(create_mcp_access_router(_mcp_access))
_core_image_commands = core_generation_commands.service()
api.include_router(create_image_generation_commands_router(_core_image_commands))
api.include_router(create_wizard_workflow_executor_router(WizardWorkflowExecutor(
    workspace_dir=core.workspace_dir,
    submit_command=_core_image_commands.submit,
    command_receipt=_core_image_commands.receipt,
    get_task=core_generation_commands.get_task,
), list_workspaces=core.list_workspaces))
api.include_router(create_character_kit_face_router(
    workspace_dir=core.workspace_dir,
    uploads_root=core.uploads_dir,
))
api.include_router(create_canonical_tasks_router(
    get_active_workspace=core.active_workspace,
    validate_workspace=core.workspace_dir,
    registry_for_workspace=core_generation_commands.registry_for,
    sync_tasks=core_canonical_tasks.sync_tasks,
    task_status=core_canonical_tasks.task_status,
    upsert_task=core_canonical_tasks.upsert_task,
    control_task=core_canonical_tasks.control_task,
))
api.include_router(create_production_media_router({
    **production_media_handlers(core.workspace_dir, core.uploads_dir),
    **studio_key_handlers(core.workspace_dir, core.uploads_dir),
}))
_agent_activity = AgentActivity(core_generation_commands.registry_for, core.active_workspace)
api.include_router(create_wizard_activity_router(_agent_activity))

BLOCKED = (
    ("POST", "/api/v1/recast", "wangp_local"),
    ("POST", "/api/v1/tools/upscale", "wangp_local"),
    ("POST", "/api/v1/tools/remove-background", "sam_inpaint"),
    ("POST", "/api/v1/tools/revoice", "local_audio_ai"),
    ("POST", "/api/v1/retake", "wangp_local"),
    ("POST", "/api/v1/audio/analyze", "whisper_local"),
    ("POST", "/api/v1/audio/analyze/jobs", "whisper_local"),
    ("POST", "/api/v1/director/pipelines/{pid}/clips/{clip_index}/rerun-video", "wangp_local"),
    ("POST", "/api/v1/director/pipelines/{pid}/repair", "wangp_local"),
)


def _block(capability: str):
    def endpoint():
        require_capability_http(capability)
        return {"status": "ok"}
    return endpoint


async def _hidden_wangp_enhance(*_args, **_kwargs):
    raise RuntimeError("WanGP enhancer is hidden on the core profile")


for method, path, capability in BLOCKED:
    api.add_api_route(path, _block(capability), methods=[method])


@api.get("/api/v1/system/preflight")
def system_preflight():
    checks = []
    if shutil.which("ffmpeg") is None:
        checks.append({"id": "ffmpeg", "level": "error",
                       "message": "ffmpeg was not found on PATH. Video and audio export will fail."})
    return {"ok": not any(item["level"] == "error" for item in checks), "checks": checks}


@api.get("/api/v1/models")
def list_models():
    model = core_remote_image.catalog_entry()
    return {
        "families": [{"id": "minimax", "label": "MiniMax", "order": 10}],
        "models": [model],
    }


@api.get("/api/v1/defaults/{model_type}")
def get_defaults(model_type: str):
    if str(model_type).startswith("minimax:"):
        return core_remote_image.defaults()
    raise HTTPException(status_code=404, detail=f"Unknown model: {model_type}")


@api.get("/api/v1/model-options/{model_type}")
def get_model_options(model_type: str):
    if str(model_type).startswith("minimax:"):
        return core_remote_image.model_options()
    raise HTTPException(status_code=404, detail=f"Unknown model: {model_type}")


@api.post("/api/v1/generate")
async def generate(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if core_remote_image.is_minimax_image_request(body):
        workspace = str(body.get("workspace") or core.active_workspace() or "default")
        try:
            from services.generation_output_name import OutputNameError, apply_output_name
            output_name = apply_output_name(body)
        except OutputNameError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": error.code, "message": str(error), "retryable": False},
            ) from error
        try:
            return core_remote_image.start_job(body, workspace=workspace, output_name=output_name)
        except Exception as error:
            from services.minimax_image_service import MiniMaxImageError
            if isinstance(error, MiniMaxImageError):
                raise HTTPException(status_code=error.status_code, detail=str(error)) from error
            raise HTTPException(status_code=400, detail=str(error)) from error
    require_capability_http("wangp_local")
    return {"status": "ok"}


@api.get("/api/v1/status/{job_id}")
def get_status(job_id: str):
    job = core_remote_image.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@api.post("/api/v1/cancel/{job_id}")
def cancel_job(job_id: str):
    job = core_remote_image.cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@api.get("/api/v1/workspaces")
def list_workspaces_endpoint():
    return {"workspaces": core.list_workspaces(), "active": core.active_workspace()}


@api.put("/api/v1/workspaces/active")
async def set_active_workspace(request: Request):
    body = await request.json()
    name = str(body.get("name") or "default")
    try:
        path = core.workspace_dir(name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    data = core.load_config()
    data.setdefault("services", {})["active_workspace"] = name
    core.save_config(data)
    return {"status": "ok", "active": name, "path": path}


@api.post("/api/v1/workspaces")
async def create_workspace(request: Request):
    body = await request.json()
    name = str(body.get("name") or "").strip()
    try:
        path = core.workspace_dir(name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"status": "ok", "name": name, "path": path}


@api.get("/api/v1/outputs")
def list_outputs(workspace: str = "", media_type: str = "", limit: int = 0, offset: int = 0):
    try:
        return core.list_outputs(workspace, media_type=media_type, limit=limit, offset=offset)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@api.get("/api/v1/file/{filename:path}")
def serve_file(filename: str, workspace: str | None = None, sha256: str | None = None):
    from services.win_safe_files import share_delete_file_response
    folder = core.uploads_dir() if workspace == "__uploads__" else core.workspace_dir(workspace)
    path = core.safe_join(folder, filename)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Output file not found")
    return share_delete_file_response(path, expected_sha256=sha256)


@api.get("/api/v1/system-config")
def get_system_config():
    return core.system_config()


@api.put("/api/v1/system-config")
async def put_system_config(request: Request):
    body = await request.json()
    data = core.load_config()
    for key in ("video_output_codec", "image_output_codec"):
        if key in body:
            data[key] = body[key]
    core.save_config(data)
    return {"status": "ok", "updated": body}


@api.get("/api/v1/services-config")
def get_services_config():
    return core.services_config()


@api.put("/api/v1/services-config")
async def put_services_config(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid services config")
    return core.merge_services(body)


@api.get("/api/v1/jobs")
def list_jobs():
    jobs = core_remote_image.list_active()
    return {"jobs": jobs, "pipelines": [], "total": len(jobs)}


@api.get("/api/v1/jobs/recovery")
def jobs_recovery():
    """The core keeps no durable generation queue, so a crash leaves nothing to offer back."""
    return {"jobs": []}


@api.get("/api/v1/system-stats")
def system_stats():
    from services.live_stats import snapshot_system_stats
    return snapshot_system_stats(
        os.path.join(_app_dir, "..", "ui", "dist"),
        lambda: {"name": None, "model_type": None, "loaded": False},
    )


@api.get("/api/v1/system-detect")
def system_detect():
    return {
        "auto_enabled": False,
        "hardware": {
            "cuda_available": False, "gpu_name": "", "gpu_vram_gb": 0, "gpu_capability": "",
            "ram_gb": 0, "cpu_count": os.cpu_count() or 0, "ram_tier": "high", "vram_tier": "none",
            "supports_fp8": False, "supports_sage": False, "supports_sage2": False,
            "supports_flash": False, "supports_triton": False, "supports_nvfp4": False,
        },
        "recommended": {
            "video_profile": 4, "image_profile": 4, "audio_profile": 4,
            "transformer_quantization": "int8", "vae_config": 0, "vram_safety_coefficient": 0.8,
            "attention_mode": "auto", "compile": "",
        },
    }


@api.get("/api/v1/downloads/active")
def downloads_active():
    return {"downloads": []}


@api.get("/api/v1/loras/installed")
def loras_installed():
    return {"loras": [], "manifest_last_check_at": None}


def _wizard_workspace(value: object) -> str:
    name = value if isinstance(value, str) and value.strip() else None
    return core.workspace_dir(name)


api.include_router(create_wizard_persistence_router(
    workspace_dir=_wizard_workspace,
    lock=nullcontext(),
))


@api.get("/api/v1/resolutions")
def resolutions():
    return {"resolutions": []}


@api.get("/api/v1/presets")
def presets():
    return {"presets": []}


@api.get("/api/v1/model-visibility")
def model_visibility():
    return {
        "configured": True,
        "enabled_models": [core_remote_image.MODEL_ID],
        "initialized_mature_models": [],
        "defaults_version": 1,
    }


@api.get("/api/v1/model-selections")
def model_selections():
    return {"configured": True, "selected_models": {}, "sources": {}}


@api.get("/api/v1/wangp/capabilities")
def wangp_capabilities():
    return {"processors": []}


def _core_rig_gate(body: dict) -> None:
    if str((body or {}).get("engine") or "procedural") not in {"procedural", "humanoid"}:
        require_capability_http("unirig_ai")


def _core_rig_engines(engines: list) -> list:
    # The procedural rig is CPU-only; UniRig needs a local NVIDIA engine.
    return [engine for engine in engines if engine.get("id") in {"procedural", "humanoid"}]


def _core_rig_input(value: str, workspace: str | None = None) -> str | None:
    from services.model3d_input_path import resolve_model3d_input_path
    return resolve_model3d_input_path(
        value,
        workspace,
        safe_join=core.safe_join,
        workspace_dir=core.workspace_dir,
        save_path=lambda: str(core.outputs_root()),
    )


from routers.rig import create_rig_router
api.include_router(create_rig_router(
    resolve_input_path=_core_rig_input,
    workspace_dir=core.workspace_dir_or_400,
    get_active_workspace=core.active_workspace,
    safe_join=core.safe_join,
    publish_task=core_canonical_tasks.publish_studio_activity,
    engine_gate=_core_rig_gate,
    filter_engines=_core_rig_engines,
))


@api.post("/api/v1/scenes/recordings")
async def save_scene_recording(request: Request):
    try:
        return await scene_save.publish_from_form(await request.form())
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=scene_save.http_error_status(error),
            detail=scene_save.http_error_detail(error),
        ) from error


@api.post("/api/v1/scenes")
async def save_scene(request: Request):
    body = await request.json()
    return scene_save.save_core_scene(
        body,
        workspace_dir=core.workspace_dir,
        active_workspace=core.active_workspace,
    )


def _resolve_editor_input(value: str, workspace: str | None = None) -> str | None:
    from services.model3d_input_path import resolve_model3d_input_path
    return resolve_model3d_input_path(
        value,
        workspace,
        safe_join=core.safe_join,
        workspace_dir=core.workspace_dir,
        save_path=lambda: str(core.outputs_root()),
    )


from routers.video_editor import create_video_editor_jobs_router, create_video_editor_router

api.include_router(create_video_editor_router(
    workspace_dir=core.workspace_dir_or_400,
    get_active_workspace=core.active_workspace,
    resolve_input_path=_resolve_editor_input,
    publish_legacy_task=core_canonical_tasks.publish_video_editor_activity,
    thumbnail_cache_dir=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "cache",
        "media-thumbnails",
    ),
))
api.include_router(create_video_editor_jobs_router())


api.include_router(create_uploads_router(
    uploads_dir=core.uploads_dir,
    stream_upload=upload_stream.stream_upload_file,
    transcode_upload=upload_stream.transcode_upload,
    probe_video_metadata=upload_video_metadata.probe_with_ffprobe,
    safe_join=core.safe_join,
    output_fallback=serve_file,
))


api.include_router(create_llm_router(
    get_services_config=core.services_raw,
    effective_llm_routing=core_production.effective_llm_routing,
    llm_provider_credentials=core_production.llm_provider_credentials,
    llm_default_device=lambda: "cpu",
    default_llm_repo="MiniMax-M3",
    ensure_llm_loaded=core_production.ensure_llm_loaded,
    comic_writing_llm=core_production.comic_writing_llm,
    resolve_visual_media=core_production.resolve_visual_media,
    require_local_llm=lambda: require_capability_http("local_llm"),
))
api.include_router(create_llm_prompt_router(
    get_services_config=core.services_raw,
    effective_llm_routing=core_production.effective_llm_routing,
    public_llm_providers=frozenset({"openai", "anthropic", "minimax", "grok", "deepseek"}),
    ensure_llm_loaded=core_production.ensure_llm_loaded,
    get_model_def=lambda _name: None,
    get_lora_dir=lambda _name: "",
    get_cached_hardware=lambda: {},
    get_enhancer_enabled=lambda: 0,
    enhance_with_wangp=_hidden_wangp_enhance,
    plan_h3_gate=lambda: require_capability_http("wangp_local"),
))


_app_dir = os.path.dirname(os.path.abspath(__file__))
from routers.example_assets import create_example_assets_router
api.include_router(create_example_assets_router())
from routers.asset_library import create_asset_library_router
api.include_router(create_asset_library_router())

_ui_dist = os.path.normpath(os.path.join(_app_dir, "..", "ui", "dist"))
_ui_ready = build_status()["ready"]
if _ui_ready:
    api.mount("/", StaticFiles(directory=_ui_dist, html=True))
else:
    @api.get("/")
    def index():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(recovery_html(), status_code=503, headers={"Cache-Control": "no-store"})


def run_server() -> None:
    report_identity()
    snapshot = platform_capabilities()
    print("[HocusPocus] capabilities")
    for name, entry in snapshot["capabilities"].items():
        print(f"  {name}: {entry['state']}")
    print(f"[HocusPocus] profile {snapshot['profile']}")
    from services.server_entry import run
    run(
        api,
        ui_ready=_ui_ready,
        endpoint_path=os.path.join(_app_dir, "settings", "server-endpoint.json"),
        prepare=lambda _display_host, _port: None,
        lan_messages=[],  # core has no LanAuthMiddleware: it must not announce LAN protection
    )


if __name__ == "__main__":
    if _app_dir not in sys.path:
        sys.path.insert(0, _app_dir)
    run_server()

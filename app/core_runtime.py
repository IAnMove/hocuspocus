"""Apple Silicon core/remote server: editors, projects and remote APIs without Torch."""
from __future__ import annotations

import json
import os
import shutil
import sys
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
from routers.productions import create_productions_router
from routers.recipes import create_recipes_router
from routers.scene_commands import create_scene_commands_router
from routers.scene_packages import create_scene_packages_router
from routers.series_assembly import create_series_assembly_router
from routers.style_library import create_style_library_router
from routers.system_capabilities import create_system_capabilities_router, require_capability_http
from routers.user_diagnostics import create_user_diagnostics_router
from routers.wizard_workflow_executor import create_wizard_workflow_executor_router
from routers.world3d_export import create_world3d_export_router, bind_world3d_renderer_origin
from routers.workspace_collections import create_workspace_collections_router
from services import (
    core_canonical_tasks,
    core_editor,
    core_generation_commands,
    core_production,
    core_remote_image,
    core_scene_recording,
    core_series_assembly,
    core_upload,
    core_workspace as core,
)
from services.mcp_access import McpAccess
from services.platform_capabilities import platform_capabilities
from services.scene_commands import SceneCommands
from services.style_library import StyleLibrary
from services.ui_distribution import build_status, recovery_html, report_identity
from services.wizard_conversations import (
    WizardConversationRevisionConflict,
    read_conversation,
    write_conversation,
)
from services.wizard_workflows import (
    WizardWorkflowRevisionConflict,
    read_workflows,
    write_workflows,
)
from services.wizard_workflow_executor import WizardWorkflowExecutor
from services.world3d_export import World3DExportService
from services.workspace_registry import WorkspaceRegistry

api = FastAPI(title="HocusPocus core")
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
)
bind_world3d_renderer_origin(api, _world3d_export)
api.include_router(create_world3d_export_router(_world3d_export))
api.include_router(create_core_labs_router())
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

BLOCKED = (
    ("POST", "/api/v1/recast", "wangp_local"),
    ("POST", "/api/v1/tools/upscale", "wangp_local"),
    ("POST", "/api/v1/rig/generate", "unirig_ai"),
    ("POST", "/api/v1/tools/remove-background", "sam_inpaint"),
    ("POST", "/api/v1/tools/revoice", "local_audio_ai"),
    ("POST", "/api/v1/retake", "wangp_local"),
    ("POST", "/api/v1/audio/analyze", "whisper_local"),
    ("POST", "/api/v1/audio/analyze/jobs", "whisper_local"),
    ("POST", "/api/v1/director/pipelines/{pid}/clips/{clip_index}/rerun-video", "wangp_local"),
    ("POST", "/api/v1/director/pipelines/{pid}/repair", "wangp_local"),
    ("POST", "/api/v1/llm/plan-h3-windows", "wangp_local"),
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
            return core_remote_image.start_job(body, workspace=workspace)
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
def serve_file(filename: str, workspace: str | None = None):
    folder = core.uploads_dir() if workspace == "__uploads__" else core.workspace_dir(workspace)
    path = core.safe_join(folder, filename)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(path)


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
@api.get("/api/v1/jobs/recovery")
def list_jobs():
    jobs = core_remote_image.list_active()
    return {"jobs": jobs, "pipelines": [], "total": len(jobs)}


@api.get("/api/v1/system-stats")
def system_stats():
    import psutil
    vm = psutil.virtual_memory()
    return {
        "cpu": {"percent": psutil.cpu_percent(interval=None)},
        "ram": {"percent": vm.percent, "used_gb": round((vm.total - vm.available) / 1024 ** 3, 1),
                "total_gb": round(vm.total / 1024 ** 3, 1)},
        "gpu": {"available": False, "percent": 0, "vram_used_gb": 0, "vram_total_gb": 0, "vram_percent": 0},
        "model": {"name": None, "model_type": None, "loaded": False},
    }


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


@api.get("/api/v1/wizard/conversations")
def get_wizard_conversation(workspace: str | None = None):
    try:
        return read_conversation(_wizard_workspace(workspace))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail=f"Could not read the Wizard conversation: {error}") from error


@api.put("/api/v1/wizard/conversations")
async def put_wizard_conversation(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Wizard conversation must be a JSON object")
    try:
        base_revision = body.get("baseRevision")
        if type(base_revision) is not int:
            base_revision = 0
        return write_conversation(
            _wizard_workspace(body.get("workspace")),
            body.get("conversation"),
            base_revision=base_revision,
        )
    except WizardConversationRevisionConflict as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "wizard_conversation_revision_conflict",
                "message": str(error),
                "expectedRevision": error.expected,
                "currentRevision": error.current,
            },
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Could not save the Wizard conversation: {error}") from error


@api.get("/api/v1/wizard/workflows")
def get_wizard_workflows(workspace: str | None = None):
    try:
        return read_workflows(_wizard_workspace(workspace))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail=f"Could not read Wizard workflows: {error}") from error


@api.put("/api/v1/wizard/workflows")
async def put_wizard_workflows(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Wizard workflows must be a JSON object")
    try:
        base_revision = body.get("baseRevision")
        if type(base_revision) is not int:
            base_revision = 0
        return write_workflows(
            _wizard_workspace(body.get("workspace")),
            body.get("collection"),
            base_revision=base_revision,
        )
    except WizardWorkflowRevisionConflict as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "wizard_workflow_revision_conflict",
                "message": str(error),
                "expectedRevision": error.expected,
                "currentRevision": error.current,
            },
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Could not save Wizard workflows: {error}") from error


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


@api.get("/api/v1/rig/capabilities")
def rig_capabilities():
    return {"engines": [{"id": "procedural", "label": "Procedural (fast)"}]}


@api.post("/api/v1/scenes/recordings")
async def save_scene_recording(request: Request):
    try:
        return await core_scene_recording.publish_from_form(await request.form())
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=core_scene_recording.http_error_status(error),
            detail=core_scene_recording.http_error_detail(error),
        ) from error


@api.post("/api/v1/scenes")
async def save_scene(request: Request):
    body = await request.json()
    scene = body.get("scene") if isinstance(body, dict) else None
    if not isinstance(scene, dict):
        raise HTTPException(status_code=400, detail="A version 1 scene is required")
    workspace = body.get("workspace")
    if workspace is None:
        workspace = core.active_workspace()
    folder = core.workspace_dir(workspace)
    os.makedirs(folder, exist_ok=True)
    import json
    import time
    import uuid
    name = f"{time.strftime('%Y-%m-%d-%Hh%Mm%Ss')}_scene_{uuid.uuid4().hex[:6]}.scene.json"
    path = os.path.join(folder, name)
    Path_write = path
    with open(Path_write, "w", encoding="utf-8") as handle:
        json.dump(scene, handle)
    return {"name": name, "type": "scene", "url": f"/api/v1/file/{name}?workspace={workspace}"}


@api.post("/api/v1/video-editor/probe")
def probe_video(body: dict):
    try:
        return core_editor.probe_video(str((body or {}).get("source") or ""), (body or {}).get("workspace"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@api.post("/api/v1/video-editor/probe-audio")
def probe_audio_route(body: dict):
    try:
        return core_editor.probe_soundtrack(str((body or {}).get("source") or ""), (body or {}).get("workspace"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@api.get("/api/v1/video-editor/thumbnail")
def video_thumbnail(source: str):
    try:
        path = core_editor.thumbnail_path(source)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return FileResponse(path, media_type="image/jpeg")


@api.post("/api/v1/video-editor/screenshot")
def video_screenshot(body: dict):
    try:
        return core_editor.screenshot(
            str((body or {}).get("source") or ""),
            float((body or {}).get("time") or 0),
            str((body or {}).get("name") or "frame"),
            (body or {}).get("workspace"),
        )
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@api.post("/api/v1/video-editor/export", status_code=202)
def video_export(body: dict):
    try:
        return core_editor.start_export(body or {})
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@api.get("/api/v1/video-editor/export/{job_id}")
def video_export_status(job_id: str):
    job = core_editor.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    return job


@api.post("/api/v1/upload")
async def upload_file(request: Request, filename: str = "upload.bin"):
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > core_upload.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large (max 500 MB)")
        chunks.append(chunk)
    try:
        data, original = core_upload.extract_upload(
            b"".join(chunks),
            request.headers.get("content-type") or "",
            filename,
        )
        return core_upload.save_upload(core.uploads_dir(), data, original)
    except ValueError as error:
        status = 413 if "too large" in str(error).lower() else 400
        raise HTTPException(status_code=status, detail=str(error)) from error


@api.get("/api/v1/uploads/{filename:path}")
def serve_upload(filename: str):
    path = core.safe_join(core.uploads_dir(), filename)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Upload not found")
    return FileResponse(path)


@api.post("/api/v1/llm/load")
async def llm_load(request: Request):
    body = await request.json()
    provider = str((body or {}).get("provider") or core.services_config().get("llm_provider") or "local")
    if provider == "local":
        require_capability_http("local_llm")
    from services import llm_service
    llm_service.load_model(
        model_id=str((body or {}).get("model_id") or ""),
        provider=provider,
        remote_url=str((body or {}).get("remote_url") or ""),
        api_key=str((body or {}).get("api_key") or ""),
    )
    return {"status": "ok", **llm_service.get_status()}


api.include_router(create_llm_router(
    get_services_config=core.services_raw,
    effective_llm_routing=core_production.effective_llm_routing,
    llm_provider_credentials=core_production.llm_provider_credentials,
    llm_default_device=lambda: "cpu",
    default_llm_repo="MiniMax-M3",
    ensure_llm_loaded=core_production.ensure_llm_loaded,
    comic_writing_llm=core_production.comic_writing_llm,
    resolve_visual_media=core_production.resolve_visual_media,
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
))


_app_dir = os.path.dirname(os.path.abspath(__file__))
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
    import uvicorn

    report_identity()
    snapshot = platform_capabilities()
    print("[HocusPocus] capabilities")
    for name, entry in snapshot["capabilities"].items():
        print(f"  {name}: {entry['state']}")
    print(f"[HocusPocus] profile {snapshot['profile']}")
    port = int(os.environ.get("SERVER_PORT", "7860"))
    pinokio_share = (os.environ.get("PINOKIO_SHARE_LOCAL") or "").strip().lower()
    if pinokio_share == "true":
        host = "0.0.0.0"
    elif pinokio_share == "false":
        host = "127.0.0.1"
    else:
        host = os.environ.get("SERVER_NAME", "127.0.0.1")
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"HocusPocus Lab UI: http://{display_host}:{port}/")
    uvicorn.run(api, host=host, port=port)


if __name__ == "__main__":
    if _app_dir not in sys.path:
        sys.path.insert(0, _app_dir)
    run_server()

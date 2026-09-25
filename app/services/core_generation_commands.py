"""Studio generation.image commands on the core/remote profile.

The shared UI admits MiniMax Image-01 through POST /api/v1/generation/commands.
The NVIDIA runtime owns that surface; core must honour the same receipt
contract or Generate 404s and never starts the remote job.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from copy import deepcopy
from typing import Any

from services import core_remote_image, core_workspace as core, execution_mode
from services.image_generation_commands import command_error
from services.image_generation_spec import ImageGenerationSpecError, freeze_image_generation_spec
from services.minimax_image_service import MiniMaxImageError, prepare_prompt
from services.task_command_admission import TaskCommandConflict
from services.task_manager import ACTIVE_STATUSES, TERMINAL_STATUSES, TaskRegistry
from routers.system_capabilities import require_capability_http

_JOB_STATUS = {
    "queued": "queued",
    "waiting_resource": "waiting_resource",
    "running": "running",
    "cancelling": "running",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "interrupted": "interrupted",
}

_REGISTRIES: dict[str, TaskRegistry] = {}
_LOCK = threading.Lock()
_DISPATCH_OWNER = f"core-{uuid.uuid4().hex}"
_DISPATCH_LOCK = threading.Lock()


def registry_for(workspace: str) -> TaskRegistry:
    """Task registry for this workspace folder. Shared with World3D export."""
    return _registry(workspace)


def _registry(workspace: str) -> TaskRegistry:
    try:
        folder = core.workspace_dir(workspace)
    except ValueError as error:
        raise command_error(422, "invalid_workspace", "Use an explicit valid output workspace") from error
    with _LOCK:
        existing = _REGISTRIES.get(folder)
        if existing is not None:
            return existing
        registry = TaskRegistry(folder, interrupt_stale=True)
        _REGISTRIES[folder] = registry
        return registry


def _job_status(value: Any) -> str | None:
    return _JOB_STATUS.get(str(value or "").strip().lower())


def _sync_task_from_job(workspace: str, task: dict[str, Any]) -> dict[str, Any]:
    """Project the MiniMax in-memory job onto the admitted canonical task.

    ``core_remote_image`` never writes TaskRegistry. The Wizard executor
    polls ``get_task``, so a completed JPG would otherwise stay ``queued``
    with empty ``result_refs`` and never advance to upscale.
    """
    job_id = str(task.get("backend_job_id") or "").strip()
    if not job_id:
        return task
    job = core_remote_image.get_job(job_id)
    if not isinstance(job, dict):
        return task
    mapped = _job_status(job.get("status"))
    if mapped is None:
        return task
    current = str(task.get("status") or "")
    if current in TERMINAL_STATUSES and mapped in ACTIVE_STATUSES:
        return task
    refs = [str(name).strip() for name in (job.get("output_files") or []) if str(name).strip()]
    patch: dict[str, Any] = {}
    if mapped != current:
        patch["status"] = mapped
        patch["phase"] = mapped
    if refs and refs != list(task.get("result_refs") or []):
        patch["result_refs"] = refs
    message = str(job.get("message") or "").strip()
    if message and message != task.get("message"):
        patch["message"] = message
    error = job.get("error")
    if error and mapped in {"failed", "cancelled"} and error != task.get("error"):
        patch["error"] = str(error)
    if not patch:
        return task
    try:
        return _registry(workspace).update(
            str(task["id"]),
            force=True,
            event_type="adapter.synced",
            **patch,
        )
    except (KeyError, OSError, sqlite3.Error, ValueError):
        return {**task, **patch}


def get_task(workspace: str, task_id: str) -> dict[str, Any] | None:
    if not str(task_id or "").strip():
        return None
    task = _registry(workspace).get(str(task_id))
    if task is None:
        return None
    return _sync_task_from_job(workspace, task)


def _freeze(command: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(command, dict):
        raise command_error(422, "invalid_command", "Command must be a JSON object")
    if command.get("operation") == "tools.upscale":
        require_capability_http("wangp_local")
    if command.get("operation") != "generation.image":
        raise command_error(422, "unsupported_operation", "This runtime admits generation.image only")
    if type(command.get("version")) is int and command["version"] == 2:
        from services.studio_image_spec import freeze_studio_image_spec
        frozen = freeze_studio_image_spec(command)
        params = {
            **deepcopy(frozen["effective"]["input"]["params"]),
            "workspace": frozen["effective"]["input"]["workspace"],
        }
        return frozen, params
    frozen = freeze_image_generation_spec(command)
    return frozen, deepcopy(frozen["effective"]["input"])


def _require_minimax_image(params: dict[str, Any]) -> None:
    model = str(params.get("model_type") or "")
    if model.startswith("minimax:") or model == "image-01":
        return
    require_capability_http("wangp_local")
    raise command_error(422, "unsupported_model", "Choose MiniMax Image-01 on this runtime")


def _subject_reference(params: dict[str, Any]) -> str:
    refs = params.get("image_refs")
    if isinstance(refs, list) and refs:
        return str(refs[0] or "")
    for key in ("subject_reference", "image_start"):
        value = params.get(key)
        if value:
            return str(value)
    return ""


def _task_fields(workspace: str, job_id: str, params: dict[str, Any]) -> dict[str, Any]:
    task_id = f"task-generation-{job_id}"
    return {
        "id": task_id,
        "root_id": task_id,
        "kind": "generation",
        "workflow": "generation.image",
        "status": "queued",
        "phase": "queued",
        "message": "MiniMax image request queued",
        "title": "MiniMax Image-01",
        "workspace": workspace,
        "backend_job_id": job_id,
        "provider": "minimax",
        "model": str(params.get("model_type") or core_remote_image.MODEL_ID),
        "cancelable": True,
    }


class CoreGenerationCommands:
    def canonicalize_reference(self, value: str, media_kind: str = "image") -> str:
        from services.studio_image_resources import StudioImageResources
        from services.studio_speech_resources import StudioSpeechResources
        from services.studio_sfx_resources import StudioSfxResources
        from services.studio_video_resources import StudioVideoResources

        resource_type = {
            "image": StudioImageResources,
            "audio": StudioSpeechResources,
            "video": StudioSfxResources,
            "studio_video": StudioVideoResources,
        }.get(media_kind)
        if resource_type is None:
            raise command_error(422, "invalid_reference", "Unsupported media kind")
        resources = resource_type(
            workspace_dir=core.workspace_dir,
            uploads_dir=core.uploads_dir,
            list_workspaces=core.list_workspaces,
            lora_search_dirs=lambda: [],
            lora_compatible=lambda *_args, **_kwargs: True,
        )
        try:
            return resources.canonicalize_legacy(value)
        except ValueError as error:
            raise command_error(422, "invalid_reference", str(error)) from error

    def receipt(self, workspace: str, intent_id: str) -> dict[str, Any]:
        if not isinstance(intent_id, str) or not 1 <= len(intent_id) <= 160:
            raise command_error(422, "invalid_command", "An exact intent_id is required")
        try:
            registry = _registry(workspace)
            entry = registry.command_admission(intent_id)
            if entry is None:
                raise command_error(
                    404, "receipt_not_found",
                    "No admission exists for this intention in this workspace",
                )
            return {"receipt": entry["receipt"], "task": get_task(workspace, entry["task_id"])}
        except (OSError, sqlite3.Error) as error:
            raise command_error(503, "storage_unavailable", "Command storage is unavailable") from error

    def _ensure_job(self, workspace: str, job_id: str, params: dict[str, Any], task_id: str) -> None:
        if core_remote_image.get_job(job_id) is not None:
            return
        core_remote_image.start_job(
            {
                "model_type": params.get("model_type") or core_remote_image.MODEL_ID,
                "generation_mode": "image",
                "prompt": params.get("prompt") or "",
                "resolution": params.get("resolution") or "1024x1024",
                "aspect_ratio": params.get("aspect_ratio") or "",
                "subject_reference": _subject_reference(params),
                "workspace": workspace,
            },
            workspace=workspace,
            job_id=job_id,
            on_update=lambda: get_task(workspace, task_id),
        )

    async def submit(self, command, *, trusted_tool=None, submission_context=None):
        del trusted_tool, submission_context
        try:
            frozen, params = _freeze(command)
            workspace = str(params.get("workspace") or "")
            _require_minimax_image(params)
            execution_mode.validate_remote_provider(workspace, "minimax-image")
            # Fail closed before admission so a transport retry can reuse intent_id.
            prepare_prompt(str(params.get("prompt") or ""))
            core_remote_image.encode_subject_reference(_subject_reference(params), workspace)
            registry = _registry(workspace)
            job_id = uuid.uuid4().hex
            admitted = registry.admit_command_task(
                intent_id=command["intent_id"],
                operation=frozen["original"]["operation"],
                digest=frozen["fingerprint"],
                original=frozen["original"],
                effective=frozen["effective"],
                task_fields=_task_fields(workspace, job_id, params),
                fingerprint_version=frozen["fingerprint_version"],
            )
            result = admitted["receipt"]["result"]
            # A concurrent replay must not mistake claim → job creation for a
            # previous process losing its provider outcome.
            with _DISPATCH_LOCK:
                if registry.claim_command_dispatch(command["intent_id"], _DISPATCH_OWNER):
                    self._ensure_job(workspace, result["job_id"], params, result["task_id"])
                elif core_remote_image.get_job(result["job_id"]) is None:
                    task = registry.get(result["task_id"])
                    if task and task["status"] in ACTIVE_STATUSES:
                        task = registry.update(task["id"], status="interrupted", force=True,
                                               message="Provider outcome unknown; create a new attempt to retry")
                    if task:
                        core_remote_image.restore_job(task)
            return admitted
        except ImageGenerationSpecError as error:
            raise command_error(422, "invalid_command", str(error)) from error
        except MiniMaxImageError as error:
            status = error.status_code if error.status_code in {400, 413} else 422
            raise command_error(status, "invalid_command", str(error)) from error
        except TaskCommandConflict as error:
            raise command_error(409, "intent_conflict", str(error)) from error
        except execution_mode.ExecutionModeError as error:
            raise command_error(409, "execution_policy", str(error)) from error
        except (OSError, sqlite3.Error) as error:
            raise command_error(
                503, "storage_unavailable",
                "Command storage is unavailable; retry with the same intention",
            ) from error


_SERVICE = CoreGenerationCommands()


def service() -> CoreGenerationCommands:
    return _SERVICE

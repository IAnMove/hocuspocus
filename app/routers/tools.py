"""HTTP boundary for standalone image tools."""

from __future__ import annotations

import os
import re
import threading
import time
import traceback
import uuid
from urllib.parse import unquote, urlsplit
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from services import execution_mode
from services import tools_upscale as tools_upscale_service
from services.asset_manifest import publish_generation_sidecar

from services.asset_catalog import find_asset
from services.generation_provenance import normalize_submission_provenance
from shared.tools.background_removal_job import build_background_removal_job
from shared.tools.background_removal_request import (
    RemoveBackgroundRequest,
    IMAGE_EXTENSIONS, UPSCALE_VIDEO_EXTENSIONS,
    destination_context,
    job_response,
    resolve_source,
)


def create_tools_router(
    *,
    get_active_workspace: Callable[[], str],
    list_workspaces: Callable[[], Iterable[Mapping[str, Any]]],
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str],
    asset_finder: Callable[[str], Mapping[str, Any] | None] | None = None,
    register_job: Callable[[dict[str, Any]], dict[str, Any]],
    start_remove_background: Callable[[dict[str, Any]], None],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/tools", tags=["Tools"])

    def roots() -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in list_workspaces():
            name = str(item.get("name") or "").strip() if isinstance(item, Mapping) else ""
            if not name or name in seen:
                continue
            try:
                path = workspace_dir(name)
            except Exception:
                # Workspace registries can retain a stale entry while its
                # output directory is being removed.  Asset lookup should
                # continue over the healthy roots instead of failing the
                # whole Tools request.
                continue
            result.append({"workspace_id": name, "path": path})
            seen.add(name)
        result.append({"workspace_id": "__uploads__", "path": uploads_dir()})
        return result

    def find_source_asset(asset_id: str) -> Mapping[str, Any] | None:
        if asset_finder is not None:
            return asset_finder(asset_id)
        return find_asset(roots(), asset_id)

    @router.post("/remove-background")
    def remove_background(payload: RemoveBackgroundRequest):
        destination_workspace, output_dir = destination_context(
            payload,
            get_active_workspace=get_active_workspace,
            list_workspaces=list_workspaces,
            workspace_dir=workspace_dir,
        )
        asset = find_source_asset(payload.asset_id) if payload.asset_id else None
        extension = os.path.splitext(unquote(urlsplit(payload.source or "").path))[1].lower()
        kind = ("video" if asset and asset.get("kind") == "video" else "image") if payload.asset_id else ("video" if extension in UPSCALE_VIDEO_EXTENSIONS else "image")
        source_path, source_filename, source_workspace = resolve_source(
            payload,
            destination_workspace=destination_workspace,
            workspace_dir=workspace_dir,
            uploads_dir=uploads_dir,
            asset_finder=lambda _id: asset,
            expected_kind=kind,
            allowed_extensions=UPSCALE_VIDEO_EXTENSIONS if kind == "video" else IMAGE_EXTENSIONS,
            source_label=kind,
        )
        source_asset_id = payload.asset_id or (
            "asset_unmanaged_"
            + uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"hocuspocus:unmanaged:{source_workspace}:{source_filename}",
            ).hex
        )
        # Capability must be present before normalize: the Tools panel only
        # sends `{actor: user}`, and a later stamp would leave tool=studio.
        provenance = normalize_submission_provenance({
            **payload.provenance,
            "capability": "remove_background",
        })
        job_id = uuid.uuid4().hex[:8]
        source_root = output_dir if source_workspace == "__uploads__" else workspace_dir(source_workspace)
        job = build_background_removal_job(
            job_id=job_id,
            workspace=destination_workspace,
            output_dir=output_dir,
            source_path=source_path,
            source_filename=source_filename,
            source_workspace=source_workspace,
            source_asset_id=source_asset_id,
            uploads_root=uploads_dir(),
            source_root=source_root,
            provenance=provenance,
            instruction=payload.instruction.strip(),
            media_kind=kind,
            temporal_smoothing=payload.temporal_smoothing,
        )
        accepted = register_job(job)
        start_remove_background(accepted)
        return job_response(
            accepted,
            fallback_id=job_id,
            source_asset_id=source_asset_id,
            source_filename=source_filename,
        )

    return router



# Upscale and revoice. The remove-background factory above stays where it is
# mounted. These routes are registered by the factory below, at the position
# the full server used to define them. Bodies are unchanged.

_TOOL_UPSCALE_METHODS = tools_upscale_service.TOOL_UPSCALE_METHODS
_TOOL_SOURCE_EXTENSIONS = tools_upscale_service.TOOL_SOURCE_EXTENSIONS

def _tool_asset_roots() -> list[dict[str, str]]:
    """Return every explicit root that the Tools asset catalog can own."""
    roots: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _list_workspaces():
        if not isinstance(item, dict):
            continue
        workspace = str(item.get("name") or "").strip()
        if not workspace or workspace in seen:
            continue
        try:
            directory = _workspace_dir(workspace)
        except Exception:
            continue
        roots.append({"workspace_id": workspace, "path": directory})
        seen.add(workspace)
    uploads = os.path.realpath(os.path.abspath(os.path.join(os.getcwd(), "uploads")))
    if uploads not in {os.path.realpath(os.path.abspath(item["path"])) for item in roots}:
        roots.append({"workspace_id": "__uploads__", "path": uploads})
    return roots
def _tool_source_kind_from_name(value: str) -> str | None:
    from urllib.parse import unquote, urlsplit

    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    candidate = unquote(
        parsed.path
        if parsed.scheme or raw.startswith("/api/v1/")
        else raw.split("?", 1)[0].split("#", 1)[0]
    )
    extension = os.path.splitext(os.path.basename(candidate))[1].casefold()
    for kind, extensions in _TOOL_SOURCE_EXTENSIONS.items():
        if extension in extensions:
            return kind
    return None
def _resolve_tool_source(
    body: dict,
    *,
    expected_kinds: tuple[str, ...] = ("image", "video"),
) -> tuple[str, str, str, str, str, str, str]:
    """Resolve one exact Tools source and its destination context.

    Source resolution is shared with the background-removal boundary so
    canonical asset IDs, workspace-qualified file URLs, uploads, symlinks and
    traversal attempts receive the same confinement rules.  The return tuple
    is ``path, filename, source_workspace, kind, asset_id, destination,
    output_dir``.
    """
    from shared.tools.background_removal_request import (
        RemoveBackgroundRequest,
        UPSCALE_IMAGE_EXTENSIONS,
        UPSCALE_VIDEO_EXTENSIONS,
        destination_context,
        resolve_source,
    )
    from services.asset_catalog import find_asset

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be an object")

    for field, limit in (
        ("source", 1200), ("source_path", 1200), ("video_path", 1200),
        ("source_workspace", 160), ("workspace", 160),
    ):
        value = body.get(field)
        if value is not None and (
            not isinstance(value, str)
            or len(value) > limit
            or "\x00" in value
        ):
            raise HTTPException(status_code=400, detail=f"Invalid {field}")

    source_values = [
        body.get(key) for key in ("source", "source_path", "video_path")
        if body.get(key) not in (None, "")
    ]
    if len(source_values) > 1 and any(str(value) != str(source_values[0]) for value in source_values[1:]):
        raise HTTPException(status_code=409, detail="Conflicting source paths")
    source_value = str(source_values[0]).strip() if source_values else None

    asset_id = body.get("asset_id")
    if asset_id is not None:
        if (
            not isinstance(asset_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,179}", asset_id)
        ):
            raise HTTPException(status_code=400, detail="Invalid asset ID")

    requested_kind = body.get("source_kind")
    if requested_kind is not None:
        if not isinstance(requested_kind, str) or requested_kind.casefold() not in _TOOL_SOURCE_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Source kind must be image or video")
        requested_kind = requested_kind.casefold()

    asset = None
    if asset_id:
        asset = find_asset(_tool_asset_roots(), asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="Source asset not found")
        asset_kind = str(asset.get("kind") or "").casefold()
        if asset_kind not in _TOOL_SOURCE_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Source asset must be an image or video")
        if requested_kind and requested_kind != asset_kind:
            raise HTTPException(status_code=400, detail="Source kind does not match asset")
        source_kind = requested_kind or asset_kind
    else:
        source_kind = requested_kind or _tool_source_kind_from_name(source_value or "")
        if source_kind is None:
            raise HTTPException(status_code=400, detail="Source format is not supported")

    if source_kind not in expected_kinds:
        expected = " or ".join(expected_kinds)
        raise HTTPException(status_code=400, detail=f"Source must be {expected}")
    allowed_extensions = (
        UPSCALE_IMAGE_EXTENSIONS
        if source_kind == "image" else UPSCALE_VIDEO_EXTENSIONS
    )
    if source_value and _tool_source_kind_from_name(source_value) != source_kind:
        raise HTTPException(status_code=400, detail="Source kind does not match file format")

    payload = RemoveBackgroundRequest(
        asset_id=asset_id,
        source=source_value,
        source_workspace=body.get("source_workspace"),
        workspace=body.get("workspace"),
        provenance=body.get("provenance") if isinstance(body.get("provenance"), dict) else {},
    )
    destination_workspace, output_dir = destination_context(
        payload,
        get_active_workspace=_get_active_workspace,
        list_workspaces=_list_workspaces,
        workspace_dir=_workspace_dir,
    )
    source_path, source_filename, source_workspace = resolve_source(
        payload,
        destination_workspace=destination_workspace,
        workspace_dir=_workspace_dir,
        uploads_dir=lambda: os.path.join(os.getcwd(), "uploads"),
        asset_finder=lambda value: find_asset(_tool_asset_roots(), value),
        expected_kind=source_kind,
        allowed_extensions=allowed_extensions,
        source_label=source_kind,
    )
    source_asset_id = asset_id or (
        "asset_unmanaged_"
        + uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"hocuspocus:unmanaged:{source_workspace}:{source_filename}",
        ).hex
    )
    return (
        source_path,
        source_filename,
        source_workspace,
        source_kind,
        source_asset_id,
        destination_workspace,
        output_dir,
    )
def _resolve_tool_clip_path(raw_path, workspace=None):
    """Resolve a Tools input path. Accepts an absolute path, a filename in the
    active workspace output dir, or a name/relative path under uploads/.
    Returns an absolute path, or None if nothing matches."""
    if not raw_path:
        return None
    if os.path.isabs(raw_path) and os.path.isfile(raw_path):
        return raw_path
    base = os.path.basename(raw_path)
    for candidate in (
        os.path.join(_workspace_dir(workspace), raw_path),
        os.path.join(_workspace_dir(workspace), base),
        os.path.join(os.getcwd(), "uploads", raw_path),
        os.path.join(os.getcwd(), "uploads", base),
    ):
        if os.path.isfile(candidate):
            return candidate
    return raw_path if os.path.isfile(raw_path) else None
def _upscale_tool_image(
    source_path: str,
    output_path: str,
    method: str,
    *,
    seed: int = -1,
    abort_callback=None,
    progress_callback=None,
) -> tuple[int, int]:
    """Compatibility facade for callers that used the old launch symbol."""
    return tools_upscale_service.upscale_image(
        source_path,
        output_path,
        method,
        wgp=wgp,
        seed=seed,
        abort_callback=abort_callback,
        progress_callback=progress_callback,
    )
def _write_tool_sidecar(
    out_dir,
    filename,
    *,
    source_name,
    tool,
    params,
    elapsed,
    job_id,
    task_id=None,
    root_task_id=None,
    workspace=None,
    generation_mode="video",
    source_asset_id=None,
    source_kind=None,
    provenance=None,
    inputs=None,
    parents=None,
    transformations=None,
    technical=None,
):
    """Write a .meta.json sidecar so a Tools output shows up in the gallery
    with the right mode + edit_sub_mode tag (mirrors _run_sfx_generation)."""
    public_params = {
        key: value
        for key, value in (params or {}).items()
        if not str(key).startswith("_")
        and key not in {"source_path", "video_path", "voice_ref_paths"}
    }
    if source_asset_id:
        public_params.setdefault("source_asset_id", source_asset_id)
    if source_kind:
        public_params.setdefault("source_kind", source_kind)
    public_params.setdefault("source_filename", source_name)
    provenance = provenance if isinstance(provenance, dict) else {}
    capability = provenance.get("capability") or tool
    sidecar = {
        "params": {**public_params, "edit_sub_mode": tool},
        "generation_mode": generation_mode,
        "tool": tool,
        "capability": capability,
        "tool_source": source_name,
        "source_asset_id": source_asset_id,
        "source_kind": source_kind,
        "job_id": job_id,
        "task_id": task_id,
        "root_task_id": root_task_id or task_id,
        "generation_time": round(elapsed),
        "created_at": time.time(),
    }
    if inputs:
        sidecar["inputs"] = list(inputs)
    if parents:
        sidecar["parents"] = list(parents)
    if transformations:
        sidecar["transformations"] = list(transformations)
    if technical:
        sidecar["technical"] = dict(technical)
    try:
        publish_generation_sidecar(
            os.path.join(out_dir, filename),
            sidecar,
            workspace_id=provenance.get("workspace_id") or workspace,
            output_folder=workspace,
            tool=provenance.get("tool") or tool,
            actor=provenance.get("actor"),
            capability=capability,
        )
    except Exception:
        pass
def _run_tool_upscale(job_id: str):
    """Compatibility facade for the standalone Tools upscale service."""
    return tools_upscale_service.run_tool_upscale(
        job_id,
        runtime={
            "jobs": _jobs,
            "active_gen_states": _active_gen_states,
            "wgp": wgp,
            "coordinated_generation_slot": _coordinated_generation_slot,
            "try_start": try_start,
            "register_abort_state": register_abort_state,
            "unregister_abort_state": unregister_abort_state,
            "is_cancel_requested": is_cancel_requested,
            "update_job": update_job,
            "finish_job": finish_job,
            "acknowledge_cancel": acknowledge_cancel,
            "record_job_outputs": record_job_outputs,
            "chunked_flashvsr_upscale": _chunked_flashvsr_upscale,
            "resolve_tool_clip_path": _resolve_tool_clip_path,
            "write_tool_sidecar": _write_tool_sidecar,
        },
    )
def _run_tool_revoice(job_id: str):
    """Background worker: replace the voice(s) in an existing clip via SeedVC.
    Always writes a NEW file (copy first, convert the copy) — the source clip
    is never mutated."""
    import shutil
    job = _jobs[job_id]
    start_time = None
    abort_state = {"abort": False}
    final_path = None
    with _coordinated_generation_slot(
        job, description="HocusPocus Lab GPU tool · revoice",
    ) as acquired:
        if not acquired:
            return False
        try:
            if not try_start(
                job, message="Preparing revoice...", phase="Preparing",
            ):
                return False
            start_time = float(job.get("started_at") or time.time())
            if not register_abort_state(
                job, job_id, _active_gen_states, abort_state,
            ):
                return False

            params = job["params"]
            workspace = job.get("workspace")
            out_dir = job.get("out_dir") or wgp.save_path
            os.makedirs(out_dir, exist_ok=True)

            video_source = _resolve_tool_clip_path(params.get("video_path"), workspace)
            if not video_source:
                finish_job(
                    job, "failed", error="Input clip not found",
                    message="Error: input clip not found",
                )
                return False
            if str(params.get("source_kind") or "video").casefold() != "video":
                raise ValueError("Revoice only supports video sources")
            if os.path.splitext(video_source)[1].casefold() not in _TOOL_SOURCE_EXTENSIONS["video"]:
                raise ValueError("Revoice source format is not supported")
            source_filename = str(
                params.get("source_filename") or os.path.basename(video_source)
            )

            mode = params.get("mode", "single")
            voice_refs = []
            for ref in (params.get("voice_ref_paths") or []):
                resolved = _resolve_tool_clip_path(ref, workspace)
                if resolved:
                    voice_refs.append(resolved)
            if not voice_refs:
                finish_job(
                    job, "failed", error="No voice reference found",
                    message="Error: no voice reference found",
                )
                return False

            # Copy source -> new output, then revoice the copy in place so the
            # original gallery clip is never modified.
            src_ext = os.path.splitext(video_source)[1] or ".mp4"
            final_path = wgp.get_available_filename(out_dir, os.path.basename(video_source), "_revoiced", force_extension=src_ext)
            if is_cancel_requested(job):
                return False
            shutil.copyfile(video_source, final_path)
            if is_cancel_requested(job):
                try:
                    os.remove(final_path)
                except OSError:
                    pass
                return False

            if not update_job(
                job,
                message="Replacing voice (SeedVC)...",
                phase="Voice Conversion",
                progress=10,
            ):
                try:
                    os.remove(final_path)
                except OSError:
                    pass
                return False

            from postprocessing.voice_clone import apply_voice_clone_to_file
            ok = apply_voice_clone_to_file(
                final_path, voice_refs, mode=mode,
                diffusion_steps=int(params.get("diffusion_steps", 25)),
                cfg_rate=float(params.get("cfg_rate", 0.5)),
            )
            if is_cancel_requested(job):
                try:
                    os.remove(final_path)
                except OSError:
                    pass
                return False
            if not ok:
                try:
                    os.remove(final_path)
                except OSError:
                    pass
                finish_job(
                    job,
                    "failed",
                    error="Voice replacement failed (clip has no audio, or SeedVC is unavailable)",
                    message="Error: voice replacement failed",
                )
                return False

            fname = os.path.basename(final_path)
            if not update_job(job, output_files=[fname]):
                try:
                    os.remove(final_path)
                except OSError:
                    pass
                return False
            _write_tool_sidecar(
                out_dir,
                fname,
                source_name=source_filename,
                tool="revoice",
                params={
                    "mode": mode,
                    "model_type": "post_processing",
                    "source_asset_id": params.get("source_asset_id"),
                    "source_kind": "video",
                    "source_filename": source_filename,
                },
                elapsed=time.time() - start_time,
                job_id=job_id,
                task_id=job.get("task_id"),
                root_task_id=job.get("root_task_id"),
                workspace=job.get("workspace"),
                generation_mode="video",
                source_asset_id=params.get("source_asset_id"),
                source_kind="video",
                provenance=job.get("provenance"),
                inputs=[{
                    "id": params.get("source_asset_id"),
                    "kind": "video",
                    "uri": source_filename,
                    "role": "source",
                }],
                parents=[{
                    "id": params.get("source_asset_id"),
                    "kind": "video",
                    "uri": source_filename,
                    "role": "source",
                }],
                transformations=[{
                    "type": "revoice",
                    "backend": "seedvc",
                    "mode": mode,
                }],
            )

            completed = finish_job(
                job,
                "completed",
                progress=100,
                phase="",
                message="Done",
            )
            print(f"[Tools/revoice] {os.path.basename(video_source)} -> {fname} ({wgp.format_time(time.time() - start_time)})")
            return completed
        except Exception as e:
            traceback.print_exc()
            finish_job(job, "failed", error=str(e), message=f"Error: {e}")
            return False
        finally:
            unregister_abort_state(job_id, _active_gen_states, abort_state)


def create_tools_post_router(
    *,
    wgp,
    _jobs,
    _active_gen_states,
    _list_workspaces,
    _workspace_dir,
    _get_active_workspace,
    _coordinated_generation_slot,
    try_start,
    register_abort_state,
    unregister_abort_state,
    is_cancel_requested,
    update_job,
    finish_job,
    acknowledge_cancel,
    record_job_outputs,
    _chunked_flashvsr_upscale,
    _register_manual_generation_job,
    _generation_job_acceptance,
    _run_generation,
    _resolve_request_media_path,
):
    """Upscale and revoice for an existing clip.

    Module-level helpers read the same objects through the router module.
    ``_run_generation`` may be a late binding: the launch module defines the
    real worker after this factory is mounted.
    """
    globals().update({
        "wgp": wgp,
        "_jobs": _jobs,
        "_active_gen_states": _active_gen_states,
        "_list_workspaces": _list_workspaces,
        "_workspace_dir": _workspace_dir,
        "_get_active_workspace": _get_active_workspace,
        "_coordinated_generation_slot": _coordinated_generation_slot,
        "try_start": try_start,
        "register_abort_state": register_abort_state,
        "unregister_abort_state": unregister_abort_state,
        "is_cancel_requested": is_cancel_requested,
        "update_job": update_job,
        "finish_job": finish_job,
        "acknowledge_cancel": acknowledge_cancel,
        "record_job_outputs": record_job_outputs,
        "_chunked_flashvsr_upscale": _chunked_flashvsr_upscale,
        "_register_manual_generation_job": _register_manual_generation_job,
        "_generation_job_acceptance": _generation_job_acceptance,
        "_run_generation": _run_generation,
        "_resolve_request_media_path": _resolve_request_media_path,
    })
    router = APIRouter()

    @router.post("/api/v1/tools/upscale")
    async def tools_upscale(request: Request):
        """Upscale one image or video through the shared Tools action.

        Images use ``source``/``source_kind=image`` and produce a PNG.  Videos may
        continue sending the legacy ``video_path`` field and retain the existing
        audio-preserving pipeline.
        """
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Request body must be an object")
        method = body.get("method") or "flashvsr2"
        if not isinstance(method, str) or method not in _TOOL_UPSCALE_METHODS:
            raise HTTPException(status_code=400, detail="Unsupported upscale method")
        (
            resolved,
            source_filename,
            source_workspace,
            source_kind,
            source_asset_id,
            workspace,
            output_dir,
        ) = _resolve_tool_source(body, expected_kinds=("image", "video"))
        from shared.wangp1272.processors import validate_selection, validated_settings
        from services.tools_upscale import processor_backend
        error = validate_selection("" if method.startswith(("rife", "dlssg")) else method, method if method.startswith(("rife", "dlssg")) else "", source_kind == "image")
        if error:
            raise HTTPException(status_code=400, detail=error)
        try:
            body["wangp_processor_settings"] = validated_settings(method, body.get("wangp_processor_settings"))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        from services.generation_provenance import normalize_submission_provenance

        provenance = normalize_submission_provenance({
            **(body.get("provenance") if isinstance(body.get("provenance"), dict) else {}),
            "capability": "upscale",
            # Workspace identity is runtime-owned, not browser-authored.
            "workspace_id": workspace,
        }, trusted_tool=getattr(request, "trusted_tool", None))
        source_ref = {
            "id": source_asset_id,
            "kind": source_kind,
            "uri": source_filename,
            "role": "source",
        }
        transformation = {
            "type": "upscale",
            "backend": processor_backend(method),
            "method": method,
        }
        try:
            raw_seed = body.get("seed", -1)
            if isinstance(raw_seed, bool):
                raise ValueError
            seed = int(raw_seed)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Seed must be an integer") from None

        job_id = uuid.uuid4().hex[:8]
        job = {
            "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
            "phase": "", "message": "Queued (upscale)", "created_at": time.time(),
            "params": {
                # Keep the physical source private to the in-memory worker. The
                # sidecar writer deliberately strips it before publishing.
                "source_path": resolved if source_kind == "image" else None,
                "video_path": resolved if source_kind == "video" else None,
                "source": source_filename,
                "source_filename": source_filename,
                "source_workspace": source_workspace,
                "source_asset_id": source_asset_id,
                "source_kind": source_kind,
                "method": method,
                "wangp_processor_settings": body.get("wangp_processor_settings") or {},
                "seed": seed,
                "model_type": "post_processing",
                "generation_mode": source_kind,
                "provider": "local",
                "capability": "upscale",
                "inputs": [source_ref],
                "parents": [source_ref],
                "transformations": [transformation],
                "_non_durable_tool": "upscale",
            },
            "output_files": [], "error": None,
            "workspace": workspace, "out_dir": output_dir,
            "provenance": provenance,
        }
        admit_command = getattr(request, "admit_generation_command", None)
        if callable(admit_command):
            # Only the typed in-process command adapter can transfer admission.
            # Preserve the existing tool's resolved inputs and native worker;
            # canonical task/receipt persistence now owns its queue lifecycle.
            job["params"].pop("_non_durable_tool", None)
            provenance["capability"] = "tools.upscale"
            command_collection = (body.get("provenance") or {}).get("workspace_id")
            if command_collection is not None:
                provenance["workspace_id"] = command_collection
            return admit_command(job["params"], workspace, provenance)
        _register_manual_generation_job(job)
        worker = _run_generation if execution_mode.policy().simulated else _run_tool_upscale
        threading.Thread(target=worker, args=(job_id,), daemon=False).start()
        return {
            "job_id": job_id,
            "status": "queued",
            **_generation_job_acceptance(job),
        }
    @router.post("/api/v1/tools/revoice")
    async def tools_revoice(request: Request):
        """Replace the voice(s) in an existing clip via SeedVC. Returns a job_id.

        Body: { video_path: str, voice_ref_paths: [str, ...],
                mode?: "single"|"two", diffusion_steps?: int, cfg_rate?: float,
                workspace?: str }
        """
        body = await request.json()
        (
            resolved,
            source_filename,
            source_workspace,
            _source_kind,
            source_asset_id,
            workspace,
            output_dir,
        ) = _resolve_tool_source(body, expected_kinds=("video",))
        from services.generation_provenance import normalize_submission_provenance

        provenance = normalize_submission_provenance({
            **(body.get("provenance") if isinstance(body.get("provenance"), dict) else {}),
            "capability": "revoice",
            "workspace_id": workspace,
        })

        voice_refs = body.get("voice_ref_paths")
        if not voice_refs and body.get("voice_ref_path"):
            voice_refs = [body.get("voice_ref_path")]
        if not voice_refs:
            raise HTTPException(status_code=400, detail="At least one voice_ref_path is required")
        if (
            not isinstance(voice_refs, list)
            or len(voice_refs) > 2
            or any(
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 1200
                or "\x00" in value
                for value in voice_refs
            )
        ):
            raise HTTPException(status_code=400, detail="Invalid voice reference paths")
        resolved_voice_refs = []
        for value in voice_refs:
            resolved_voice_refs.append(
                _resolve_request_media_path(
                    value,
                    workspace=workspace,
                    kinds=("audio", "video"),
                )
            )

        mode = body.get("mode", "single")
        if mode not in ("single", "two"):
            mode = "single"

        job_id = uuid.uuid4().hex[:8]
        job = {
            "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
            "phase": "", "message": "Queued (revoice)", "created_at": time.time(),
            "params": {
                "video_path": resolved,
                "source": source_filename,
                "source_filename": source_filename,
                "source_workspace": source_workspace,
                "source_asset_id": source_asset_id,
                "source_kind": "video",
                "voice_ref_paths": resolved_voice_refs,
                "mode": mode,
                "diffusion_steps": body.get("diffusion_steps", 25),
                "cfg_rate": body.get("cfg_rate", 0.5),
                "model_type": "post_processing",
                "generation_mode": "video",
                "capability": "revoice",
                "_non_durable_tool": "revoice",
            },
            "output_files": [], "error": None,
            "workspace": workspace, "out_dir": output_dir,
            "provenance": provenance,
        }
        _register_manual_generation_job(job)
        worker = _run_generation if execution_mode.policy().simulated else _run_tool_revoice
        threading.Thread(target=worker, args=(job_id,), daemon=False).start()
        return {
            "job_id": job_id,
            "status": "queued",
            **_generation_job_acceptance(job),
        }

    create_tools_post_router.tools_upscale = tools_upscale
    create_tools_post_router.tools_revoice = tools_revoice
    return router

__all__ = ["RemoveBackgroundRequest", "create_tools_router", "create_tools_post_router"]

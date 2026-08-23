"""Durable, sequential Quick Video batch orchestration."""

from __future__ import annotations

import copy
import json
import os
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Iterable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.task_manager import get_task_registry


ACTIVE = {"queued", "running", "cancelling"}
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
PIPELINE_TERMINAL = {"completed", "failed", "cancelled", "crashed", "preview_ready"}
STORE_DIR = ".quick-video-batches-v1"
PER_IDEA_STYLE_INTERPRETATION = (
    "PER-IDEA VISUAL INTERPRETATION: Treat any visual style explicitly stated in the "
    "current idea as authoritative for the environment and rendering. When the idea names "
    "a recognizable character, preserve that character's signature silhouette, proportions, "
    "wardrobe, palette and native design language. In a crossover, keep each character "
    "recognizable in their own design while harmonizing only lighting, camera and background "
    "finish. Never flatten distinct characters into generic lookalikes or inherit a style from "
    "another batch item."
)
PUBLIC_KEYS = (
    "jobId", "taskId", "workspace", "title", "status", "stage", "current",
    "total", "message", "error", "continueOnError", "settings", "items",
    "createdAt", "updatedAt", "finishedAt",
)

_CONTROLLERS: dict[str, Callable[[str, str, int | None], dict[str, Any]]] = {}
_EXECUTION_LOCK = threading.Lock()


class QuickVideoBatchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    durationSeconds: int = Field(default=15, ge=5, le=180)
    generationMode: Literal["direct_video", "image_guided", "direct_references"] = "direct_video"
    videoModel: str = Field(min_length=1, max_length=200)
    imageModel: str = Field(default="flux2_klein_9b", max_length=200)
    resolution: str = Field(default="480p", max_length=40)
    aspectRatio: str = Field(default="9:16", max_length=20)
    spokenLanguage: str = Field(default="Español de España", max_length=120)
    visualStyle: str = Field(default="", max_length=8000)
    characterVisualStyle: str = Field(default="", max_length=8000)
    directVideoMasterPrompt: str = Field(default="", max_length=12000)
    allowClipText: bool = False
    writingProvider: str = Field(default="maestro", max_length=80)
    writingModel: str = Field(default="", max_length=300)
    writingBaseUrl: str = Field(default="", max_length=1000)
    characters: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    references: list[dict[str, str]] = Field(default_factory=list, max_length=20)


class QuickVideoBatchStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str | None = Field(default=None, max_length=200)
    title: str = Field(default="Quick Video batch", max_length=300)
    ideas: list[str] = Field(min_length=1, max_length=100)
    continueOnError: bool = True
    settings: QuickVideoBatchSettings

    @field_validator("ideas")
    @classmethod
    def clean_ideas(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in value:
            idea = " ".join(str(raw or "").split()).strip()
            if not idea or idea.startswith("#"):
                continue
            key = idea.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(idea[:4000])
        if not result:
            raise ValueError("Add at least one non-empty idea")
        return result


class QuickVideoBatchActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str | None = Field(default=None, max_length=200)
    itemIndex: int | None = Field(default=None, ge=0)


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(job.get(key)) for key in PUBLIC_KEYS}


def _atomic_write(path: str, value: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            if os.path.isfile(temporary):
                os.remove(temporary)
        except OSError:
            pass


def create_quick_video_batch_router(
    *,
    resolve_workspace: Callable[[Any], str],
    workspace_dir: Callable[[str], str],
    list_workspaces: Callable[[], Iterable[dict[str, Any]]],
    ensure_pipeline_ready: Callable[[], None],
    start_pipeline: Callable[[dict[str, Any]], str],
    get_pipeline_status: Callable[[str, str], dict[str, Any] | None],
    stop_pipeline: Callable[[str], bool],
    resume_pipeline: Callable[[str, str], tuple[bool, str]],
    get_model_def: Callable[[str], dict[str, Any] | None],
    get_model_defaults: Callable[[str], dict[str, Any] | None],
    resolve_reference: Callable[[str, str], str | None],
) -> APIRouter:
    router = APIRouter()
    jobs: dict[str, dict[str, Any]] = {}
    active: set[str] = set()
    lock = threading.RLock()

    def directory(workspace: str) -> str:
        return os.path.join(workspace_dir(workspace), STORE_DIR)

    def path(workspace: str, job_id: str) -> str:
        if not job_id or os.path.basename(job_id) != job_id:
            raise ValueError("Invalid Quick Video batch id")
        return os.path.join(directory(workspace), f"{job_id}.json")

    def save(job: dict[str, Any]) -> dict[str, Any]:
        snapshot = copy.deepcopy(job)
        _atomic_write(path(str(snapshot["workspace"]), str(snapshot["jobId"])), snapshot)
        return snapshot

    def load_saved(workspace: str, job_id: str) -> dict[str, Any] | None:
        filename = path(workspace, job_id)
        if not os.path.isfile(filename):
            return None
        try:
            with open(filename, "r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def list_saved(workspace: str) -> list[dict[str, Any]]:
        root = directory(workspace)
        if not os.path.isdir(root):
            return []
        result: list[dict[str, Any]] = []
        for name in os.listdir(root):
            if not name.endswith(".json"):
                continue
            value = load_saved(workspace, name[:-5])
            if value:
                result.append(value)
        return sorted(result, key=lambda item: float(item.get("createdAt") or 0), reverse=True)

    def publish(job: dict[str, Any]) -> None:
        workspace = str(job.get("workspace") or "default")
        task_id = str(job.get("taskId") or f"task-quick-video-batch-{job['jobId']}")
        status = str(job.get("status") or "queued")
        canonical_status = "running" if status == "cancelling" else status
        registry = get_task_registry(workspace_dir(workspace))
        fields = {
            "root_id": task_id,
            "kind": "quick-video-batch",
            "workflow": "quick-video-batch",
            "title": str(job.get("title") or "Quick Video batch"),
            "status": canonical_status,
            "phase": str(job.get("stage") or status),
            "message": str(job.get("message") or "Quick Video batch queued"),
            "current": int(job.get("current") or 0),
            "total": int(job.get("total") or 0),
            "created_at": float(job.get("createdAt") or time.time()),
            "completed_at": float(job.get("finishedAt") or 0) or None,
            "provider": str((job.get("settings") or {}).get("writingProvider") or "local"),
            "model": str((job.get("settings") or {}).get("videoModel") or ""),
            "server_origin": "local",
            "resource_requirements": ["local_gpu:0"],
            "acquired_resources": ["local_gpu:0"] if canonical_status == "running" else [],
            "backend_job_id": str(job.get("jobId") or ""),
            "cancelable": status in ACTIVE,
            "resumable": status in {"failed", "cancelled", "interrupted"},
            "recoverable": True,
            "error": ({"message": str(job.get("error")), "retryable": True}
                      if job.get("error") else None),
            "result_refs": [
                str(name)
                for item in job.get("items", [])
                for name in item.get("outputFiles", [])
            ],
            "metadata": {"adapter": "quick-video-batch"},
        }
        existing = registry.get(task_id)
        try:
            if existing is None:
                registry.create(id=task_id, workspace=workspace, **fields)
            else:
                registry.update(task_id, force=True, event_type="adapter.synced", **fields)
        except (KeyError, ValueError, OSError):
            pass

    def update(job_id: str, **patch: Any) -> dict[str, Any] | None:
        with lock:
            job = jobs.get(job_id)
            if not job:
                return None
            job.update(copy.deepcopy(patch))
            job["updatedAt"] = time.time()
            snapshot = save(job)
        publish(snapshot)
        return snapshot

    def item_update(job_id: str, index: int, **patch: Any) -> dict[str, Any] | None:
        with lock:
            job = jobs.get(job_id)
            if not job or index < 0 or index >= len(job.get("items", [])):
                return None
            job["items"][index].update(copy.deepcopy(patch))
            job["updatedAt"] = time.time()
            snapshot = save(job)
        publish(snapshot)
        return snapshot

    def item_update_if(
        job_id: str,
        index: int,
        expected: set[str],
        **patch: Any,
    ) -> dict[str, Any] | None:
        """Atomically transition an item so Skip cannot race the worker claim."""
        with lock:
            job = jobs.get(job_id)
            if not job or index < 0 or index >= len(job.get("items", [])):
                return None
            item = job["items"][index]
            if str(item.get("status") or "") not in expected:
                return None
            item.update(copy.deepcopy(patch))
            job["updatedAt"] = time.time()
            snapshot = save(job)
        publish(snapshot)
        return snapshot

    def load(job_id: str, workspace: str) -> dict[str, Any] | None:
        with lock:
            cached = jobs.get(job_id)
            if cached and cached.get("workspace") == workspace:
                return copy.deepcopy(cached)
        saved = load_saved(workspace, job_id)
        if saved:
            with lock:
                jobs[job_id] = saved
            return copy.deepcopy(saved)
        return None

    def reference_paths(settings: dict[str, Any], workspace: str) -> tuple[list[str], list[str], list[str], list[str]]:
        character_paths: list[str] = []
        character_labels: list[str] = []
        location_paths: list[str] = []
        location_labels: list[str] = []
        for reference in settings.get("references", []):
            if not isinstance(reference, dict):
                continue
            resolved = resolve_reference(str(reference.get("source") or ""), workspace)
            if not resolved or not os.path.isfile(resolved):
                continue
            kind = str(reference.get("kind") or "character")
            if kind == "character":
                character_paths.append(resolved)
                character_labels.append(str(reference.get("label") or "character"))
            else:
                location_paths.append(resolved)
                location_labels.append(str(reference.get("label") or "location"))
        return character_paths, character_labels, location_paths, location_labels

    def pipeline_params(job: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        settings = dict(job.get("settings") or {})
        video_model = str(settings.get("videoModel") or "minimax_h3_legacy")
        image_model = str(settings.get("imageModel") or "flux2_klein_9b")
        mode = str(settings.get("generationMode") or "direct_video")
        if mode not in {"direct_video", "image_guided", "direct_references"}:
            raise ValueError(
                f"Unsupported saved Quick Video generation mode: {mode}"
            )
        video_def = dict(get_model_def(video_model) or {})

        def safe_model_defaults(
            model_type: str,
            *,
            required: bool,
            allow_unregistered_remote: bool = False,
        ) -> dict[str, Any]:
            if not required:
                return {}
            try:
                value = get_model_defaults(model_type)
            except Exception as exc:
                if allow_unregistered_remote:
                    # API-backed models need no local WGP defaults and may
                    # intentionally be absent from its model registry.
                    print(
                        f"[Quick Video batch] No local defaults for {model_type}: "
                        f"{exc}. Using request-level settings."
                    )
                    return {}
                raise RuntimeError(
                    f"Could not load local defaults for {model_type}: {exc}"
                ) from exc
            return dict(value) if isinstance(value, dict) else {}

        video_params = safe_model_defaults(video_model, required=True)
        image_params = safe_model_defaults(
            image_model,
            required=mode == "image_guided",
            allow_unregistered_remote=image_model.startswith("minimax:"),
        )
        char_paths, char_labels, loc_paths, loc_labels = reference_paths(
            settings, str(job["workspace"]),
        )
        if mode == "direct_references" and not (char_paths or loc_paths):
            raise ValueError("Direct-reference batches need at least one approved reference")
        duration = int(settings.get("durationSeconds") or 15)
        idea = str(item.get("idea") or "")
        authored_master_prompt = (
            str(settings.get("directVideoMasterPrompt") or "").strip()
            or str(settings.get("visualStyle") or "").strip()
        )
        direct_master_prompt = "\n\n".join(filter(None, (
            authored_master_prompt,
            PER_IDEA_STYLE_INTERPRETATION,
        )))
        story_description = (
            "Create a self-contained micro-story from this idea. It must have a clear setup, "
            "conflict or comic escalation, climax, and satisfying payoff. Do not depend on any "
            "other item in the batch. Keep every spoken line natural and short enough for its "
            f"shot. Target duration: {duration} seconds. Spoken language: "
            f"{settings.get('spokenLanguage') or 'auto'}.\n\nIDEA: {idea}"
        )
        shot_guidance = "prompt_only" if mode in {"direct_video", "direct_references"} else "auto"
        if mode == "direct_references":
            video_params["h3_reference_mode"] = "references"
        params: dict[str, Any] = {
            "pipeline_type": "short_film_story",
            "auto_mode": True,
            "workspace": job["workspace"],
            "scene_description": story_description,
            "spoken_language": settings.get("spokenLanguage") or None,
            "characters": settings.get("characters") or [],
            "target_duration": duration,
            "narrative_mode": True,
            "visual_style": settings.get("visualStyle") or None,
            "preserve_visual_style": bool(settings.get("visualStyle")),
            "character_visual_style": settings.get("characterVisualStyle") or None,
            "allow_clip_text": bool(settings.get("allowClipText")),
            "reference_image_path": (char_paths + loc_paths)[0] if (char_paths or loc_paths) else None,
            "character_ref_paths": char_paths,
            "character_ref_labels": char_labels,
            "location_ref_paths": loc_paths,
            "location_ref_labels": loc_labels,
            "seamless": False,
            "shot_image_guidance": shot_guidance,
            "director_resolution_preset": settings.get("resolution") or "480p",
            "director_aspect_ratio": settings.get("aspectRatio") or "9:16",
            "fps": int(video_def.get("fps") or 24),
            "frames_steps": int(video_def.get("frames_steps") or 17),
            "frames_minimum": int(video_def.get("frames_minimum") or 124),
            "use_director_v2": True,
            "writing_provider": settings.get("writingProvider") or "maestro",
            "writing_model": settings.get("writingModel") or "",
            "writing_base_url": settings.get("writingBaseUrl") or "",
            "image_model": image_model,
            "image_params": image_params,
            "image_loras": {},
            "video_model": video_model,
            "video_params": video_params,
            "video_loras": {},
            "music_video_treatment": ({
                "generation_mode": "direct_video",
                "direct_video_master_prompt": direct_master_prompt,
            } if mode == "direct_video" else None),
        }
        return params

    def terminal_pipeline(snapshot: dict[str, Any] | None) -> bool:
        return str((snapshot or {}).get("status") or "") in PIPELINE_TERMINAL

    def wait_for_pipeline(job_id: str, index: int, pipeline_id: str) -> dict[str, Any]:
        workspace = str(jobs[job_id]["workspace"])
        out_dir = workspace_dir(workspace)
        while True:
            with lock:
                job = jobs.get(job_id) or {}
                cancelling = job.get("status") == "cancelling"
            if cancelling:
                stop_pipeline(pipeline_id)
            snapshot = get_pipeline_status(pipeline_id, out_dir) or {}
            status = str(snapshot.get("status") or "")
            progress = snapshot.get("progress") if isinstance(snapshot.get("progress"), dict) else {}
            item_update(
                job_id, index,
                stage=str(snapshot.get("phase") or status or "running"),
                message=str(progress.get("message") or "Director is working…"),
                progressCurrent=int(progress.get("current") or 0),
                progressTotal=int(progress.get("total") or 0),
            )
            if terminal_pipeline(snapshot):
                return snapshot
            time.sleep(1.0)

    def run(job_id: str) -> None:
        owns_active_slot = True
        try:
            with _EXECUTION_LOCK:
                with lock:
                    waiting_job = copy.deepcopy(jobs.get(job_id) or {})
                if not waiting_job:
                    return
                if waiting_job.get("status") == "cancelling":
                    update(job_id, status="cancelled", stage="cancelled", message="Quick Video batch cancelled.", finishedAt=time.time())
                    return
                ensure_pipeline_ready()
                with lock:
                    cancelled_during_startup = (jobs.get(job_id) or {}).get("status") == "cancelling"
                if cancelled_during_startup:
                    update(job_id, status="cancelled", stage="cancelled", message="Quick Video batch cancelled.", finishedAt=time.time())
                    return
                update(job_id, status="running", stage="running", message="Starting sequential Quick Video batch…")
                while True:
                    with lock:
                        job = copy.deepcopy(jobs.get(job_id) or {})
                    if not job:
                        return
                    if job.get("status") == "cancelling":
                        update(job_id, status="cancelled", stage="cancelled", message="Quick Video batch cancelled.", finishedAt=time.time())
                        return
                    next_index = next((
                        index for index, item in enumerate(job.get("items", []))
                        if item.get("status") in {"queued", "interrupted"}
                    ), None)
                    if next_index is None:
                        failed = [item for item in job.get("items", []) if item.get("status") == "failed"]
                        completed = [item for item in job.get("items", []) if item.get("status") == "completed"]
                        final_status = "failed" if failed and not completed else "completed"
                        processed = sum(
                            item.get("status") in TERMINAL | {"skipped"}
                            for item in job.get("items", [])
                        )
                        update(
                            job_id,
                            status=final_status,
                            stage=final_status,
                            current=processed,
                            message=(
                                f"Completed {len(completed)}/{len(job.get('items', []))} Quick Videos"
                                if completed else "No Quick Video completed"
                            ),
                            error=(f"{len(failed)} item(s) failed" if failed else None),
                            finishedAt=time.time(),
                        )
                        return
                    item = job["items"][next_index]
                    previous_item_status = str(item.get("status") or "queued")
                    claimed = item_update_if(
                        job_id,
                        next_index,
                        {"queued", "interrupted"},
                        status="planning",
                        stage="planning",
                        message="Expanding idea into a micro-story…",
                        startedAt=item.get("startedAt") or time.time(),
                        error=None,
                    )
                    if claimed is None:
                        continue
                    pipeline_id = str(item.get("pipelineId") or "")
                    if pipeline_id and previous_item_status == "interrupted":
                        ok, _message = resume_pipeline(pipeline_id, workspace_dir(str(job["workspace"])))
                        if not ok:
                            pipeline_id = ""
                    if not pipeline_id:
                        pipeline_id = start_pipeline(pipeline_params(job, item))
                        item_update(job_id, next_index, pipelineId=pipeline_id, status="running", stage="planning", message="Director is planning the micro-story…")
                    snapshot = wait_for_pipeline(job_id, next_index, pipeline_id)
                    pipeline_status = str(snapshot.get("status") or "failed")
                    if pipeline_status in {"completed", "preview_ready"}:
                        output_files = list(snapshot.get("output_files") or [])
                        item_update(
                            job_id, next_index,
                            status="completed", stage="completed",
                            message="Quick Video completed.", outputFiles=output_files,
                            finalOutput=(output_files[-1] if output_files else None),
                            error=None, finishedAt=time.time(),
                        )
                        with lock:
                            processed_count = sum(
                                value.get("status") in TERMINAL | {"skipped"}
                                for value in jobs[job_id].get("items", [])
                            )
                        update(job_id, current=processed_count, message=f"Completed item {next_index + 1}; starting the next idea…")
                    else:
                        error = str(snapshot.get("error") or f"Director pipeline {pipeline_status}")
                        item_update(job_id, next_index, status="cancelled" if pipeline_status == "cancelled" else "failed", stage=pipeline_status, message="Quick Video failed.", error=error, finishedAt=time.time())
                        with lock:
                            current_job = copy.deepcopy(jobs[job_id])
                        if current_job.get("status") == "cancelling":
                            continue
                        processed_count = sum(
                            value.get("status") in TERMINAL | {"skipped"}
                            for value in current_job.get("items", [])
                        )
                        update(job_id, current=processed_count)
                        if not current_job.get("continueOnError", True):
                            update(job_id, status="failed", stage="failed", message=f"Batch stopped at item {next_index + 1}.", error=error, finishedAt=time.time())
                            return
        except Exception as exc:
            traceback.print_exc()
            # Finalize item state, parent state, and worker ownership in one
            # critical section.  Releasing ``active`` first let GET polling
            # start a replacement worker while this exception handler was
            # still publishing the failure; publishing first made an immediate
            # Resume observe a worker that was about to exit.  The atomic
            # transition avoids both races.
            with lock:
                current_job = jobs.get(job_id)
                snapshot = None
                if current_job:
                    interrupted_item = next((
                        item for item in current_job.get("items", [])
                        if item.get("status") in {"planning", "running"}
                    ), None)
                    if interrupted_item is not None:
                        interrupted_item.update({
                            "status": "interrupted",
                            "stage": "interrupted",
                            "message": (
                                "Quick Video setup was interrupted and can be resumed."
                            ),
                            "error": str(exc),
                        })
                    current_job.update({
                        "status": "failed",
                        "stage": "failed",
                        "message": "Quick Video batch stopped.",
                        "error": str(exc),
                        "finishedAt": time.time(),
                        "updatedAt": time.time(),
                    })
                    snapshot = save(current_job)
                active.discard(job_id)
                owns_active_slot = False
            if snapshot:
                publish(snapshot)
        finally:
            if owns_active_slot:
                with lock:
                    active.discard(job_id)

    def start_worker(job_id: str) -> bool:
        with lock:
            if job_id in active:
                return False
            active.add(job_id)
        threading.Thread(target=run, args=(job_id,), name=f"quick-video-batch-{job_id[-6:]}", daemon=False).start()
        return True

    def recover(workspace: str) -> None:
        for saved in list_saved(workspace):
            job_id = str(saved.get("jobId") or "")
            if not job_id:
                continue
            with lock:
                # A normal list refresh must never reinterpret a live worker
                # as a process-restart recovery. Only an unowned durable job
                # is eligible for recovery.
                if job_id in active:
                    continue
                jobs.setdefault(job_id, saved)
            if saved.get("status") in ACTIVE:
                with lock:
                    job = jobs[job_id]
                    for item in job.get("items", []):
                        if item.get("status") in {"planning", "running"}:
                            item["status"] = "interrupted"
                    job["status"] = "queued"
                    job["stage"] = "recovering"
                    job["message"] = "Recovering the overnight Quick Video queue…"
                    save(job)
                start_worker(job_id)

    @router.post("/api/v1/stories/quick-video-batches/start")
    def start_batch(payload: QuickVideoBatchStartRequest):
        workspace = resolve_workspace(payload.workspace)
        _CONTROLLERS[os.path.realpath(workspace_dir(workspace))] = (
            lambda job_id, action, item_index=None, target=workspace:
                control(job_id, action, item_index, target)
        )
        settings = payload.settings.model_dump()
        job_id = f"quick-batch-{uuid.uuid4().hex[:12]}"
        now = time.time()
        job = {
            "jobId": job_id,
            "taskId": f"task-quick-video-batch-{job_id}",
            "workspace": workspace,
            "title": payload.title.strip() or "Quick Video batch",
            "status": "queued", "stage": "queued", "current": 0,
            "total": len(payload.ideas), "message": "Quick Video batch queued.",
            "error": None, "continueOnError": payload.continueOnError,
            "settings": settings,
            "items": [
                {
                    "index": index, "idea": idea, "status": "queued", "stage": "queued",
                    "message": "Waiting in batch queue", "pipelineId": None,
                    "outputFiles": [], "finalOutput": None, "error": None,
                    "createdAt": now, "startedAt": None, "finishedAt": None,
                    "progressCurrent": 0, "progressTotal": 0,
                }
                for index, idea in enumerate(payload.ideas)
            ],
            "createdAt": now, "updatedAt": now, "finishedAt": None,
        }
        with lock:
            jobs[job_id] = job
            save(job)
        publish(job)
        start_worker(job_id)
        return _public(job)

    @router.get("/api/v1/stories/quick-video-batches")
    def list_batches(workspace: str | None = None):
        target = resolve_workspace(workspace)
        recover(target)
        return {"jobs": [_public(job) for job in list_saved(target)]}

    @router.get("/api/v1/stories/quick-video-batches/{job_id}")
    def get_batch(job_id: str, workspace: str | None = None):
        target = resolve_workspace(workspace)
        job = load(job_id, target)
        if not job:
            raise HTTPException(status_code=404, detail="Quick Video batch not found")
        if job.get("status") in ACTIVE:
            start_worker(job_id)
        return _public(job)

    def control(job_id: str, action: str, item_index: int | None = None, workspace: str | None = None) -> dict[str, Any]:
        target = resolve_workspace(workspace)
        job = load(job_id, target)
        if not job:
            raise HTTPException(status_code=404, detail="Quick Video batch not found")
        if action == "cancel":
            if job.get("status") not in ACTIVE:
                return _public(job)
            updated = update(job_id, status="cancelling", stage="cancelling", message="Cancelling Quick Video batch…") or job
            active_item = next((item for item in updated.get("items", []) if item.get("status") in {"planning", "running"}), None)
            if active_item and active_item.get("pipelineId"):
                stop_pipeline(str(active_item["pipelineId"]))
            return _public(updated)
        if action == "resume":
            if job.get("status") in ACTIVE:
                return _public(job)
            with lock:
                current = jobs[job_id]
                for item in current.get("items", []):
                    if item.get("status") in {"failed", "cancelled"}:
                        continue
                    if item.get("status") in {"planning", "running"}:
                        item["status"] = "interrupted"
                current.update({"status": "queued", "stage": "queued", "message": "Quick Video batch resumed.", "error": None, "finishedAt": None})
                save(current)
            publish(current)
            start_worker(job_id)
            return _public(current)
        if action == "retry-item":
            if item_index is None or item_index < 0 or item_index >= len(job.get("items", [])):
                raise HTTPException(status_code=400, detail="Choose a valid batch item")
            if job.get("status") in ACTIVE:
                raise HTTPException(status_code=409, detail="Wait for or cancel the active batch before retrying an item")
            item_update(job_id, item_index, status="queued", stage="queued", message="Queued for retry", pipelineId=None, outputFiles=[], finalOutput=None, error=None, startedAt=None, finishedAt=None)
            update(job_id, status="queued", stage="queued", message=f"Retrying item {item_index + 1}…", error=None, finishedAt=None)
            start_worker(job_id)
            return _public(jobs[job_id])
        if action == "skip-item":
            if item_index is None or item_index < 0 or item_index >= len(job.get("items", [])):
                raise HTTPException(status_code=400, detail="Choose a valid batch item")
            skipped = item_update_if(
                job_id,
                item_index,
                {"queued", "interrupted"},
                status="skipped",
                stage="skipped",
                message="Skipped by user",
                finishedAt=time.time(),
            )
            if skipped is None:
                raise HTTPException(status_code=409, detail="Only queued items can be skipped")
            return _public(skipped)
        if action == "discard":
            if job.get("status") in ACTIVE:
                raise HTTPException(status_code=409, detail="Cancel the batch before discarding it")
            filename = path(target, job_id)
            if os.path.isfile(filename):
                os.remove(filename)
            with lock:
                jobs.pop(job_id, None)
            get_task_registry(workspace_dir(target)).delete(str(job.get("taskId") or ""))
            return {"jobId": job_id, "discarded": True, "outputsPreserved": True}
        raise HTTPException(status_code=400, detail="Unsupported Quick Video batch action")

    @router.post("/api/v1/stories/quick-video-batches/{job_id}/{action}")
    def batch_action(job_id: str, action: str, payload: QuickVideoBatchActionRequest):
        return control(job_id, action, payload.itemIndex, payload.workspace)

    for workspace_record in list_workspaces():
        name = str(workspace_record.get("name") if isinstance(workspace_record, dict) else workspace_record or "")
        if name:
            _CONTROLLERS[os.path.realpath(workspace_dir(name))] = (
                lambda job_id, action, item_index=None, target=name:
                    control(job_id, action, item_index, target)
            )
            try:
                recover(name)
            except Exception:
                pass
    return router


def control_quick_video_batch_job(
    workspace_directory: str,
    job_id: str,
    action: str,
    item_index: int | None = None,
) -> dict[str, Any]:
    controller = _CONTROLLERS.get(os.path.realpath(workspace_directory))
    if controller is None:
        raise HTTPException(status_code=503, detail="Quick Video batch controller is unavailable")
    return controller(job_id, action, item_index)

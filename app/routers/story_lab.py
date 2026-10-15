"""Story Lab HTTP routes for the full server.

The core server has no Story Lab routes, so only the full server mounts
these routers. Handlers stay module-level so a move keeps the launch
function name. This module does not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import time
import uuid

from fastapi import APIRouter, HTTPException

from services.comic_director_json import _generate_comic_director_json
from services.story_lab_jobs import (
    _generate_story_lab_stage,
    _load_story_plan_job,
    _persist_story_plan_job,
    _start_story_plan_worker,
    _story_job_update,
    _story_plan_active_jobs,
    _story_plan_jobs,
    _story_plan_jobs_lock,
)
from services.story_lab_schema import _story_checkpoint_request, _story_resume_request

# Injected by _bind_story_lab_runtime. None until the full server binds them.
_comic_writing_llm = None
_ensure_llm_loaded = None
_get_active_workspace = None
_publish_generic_legacy_task = None
_reset_canonical_task_for_resume = None
_story_import_upload_path = None


async def analyze_story_assets(body: dict):
    """Classify a reviewed batch of uploaded images against one Story bible."""
    from services import llm_service
    from services.story_asset_import import (
        MAX_IMPORT_ASSETS, asset_import_schema, validate_asset_import_result,
    )

    raw_assets = body.get("assets") if isinstance(body.get("assets"), list) else []
    if not raw_assets:
        raise HTTPException(status_code=400, detail="Choose at least one image")
    if len(raw_assets) > MAX_IMPORT_ASSETS:
        raise HTTPException(status_code=400, detail=f"Import at most {MAX_IMPORT_ASSETS} images per batch")
    paths = [_story_import_upload_path(item.get("path") if isinstance(item, dict) else "") for item in raw_assets]
    names = [
        str(item.get("name") or os.path.basename(paths[index])).strip()[:300]
        if isinstance(item, dict) else os.path.basename(paths[index])
        for index, item in enumerate(raw_assets)
    ]
    project = body.get("project") if isinstance(body.get("project"), dict) else {}
    existing_characters = [
        {"id": str(item.get("id") or ""), "name": str(item.get("name") or "")}
        for item in project.get("characters", []) if isinstance(item, dict)
    ]
    world = project.get("world") if isinstance(project.get("world"), dict) else {}
    existing_locations = [
        {"id": str(item.get("id") or ""), "name": str(item.get("name") or "")}
        for item in world.get("locations", []) if isinstance(item, dict)
    ]
    user_context = str(body.get("description") or "").strip()[:4000]
    language = str(project.get("language") or "English").strip()[:100]
    asset_lines = "\n".join(f"Image {index + 1} (index {index}): {name}" for index, name in enumerate(names))
    prompt = f"""Analyze the attached image batch as reusable assets for one Story Lab project.
The attached images appear in exactly the same order as this list:
{asset_lines}

Optional batch context from the user: {user_context or 'none'}
Story title: {str(project.get('title') or 'Untitled')[:300]}
Premise: {str(project.get('premise') or '')[:2000]}
World summary: {str(world.get('summary') or '')[:2000]}
Existing characters (reuse exact id when clearly matched): {json.dumps(existing_characters, ensure_ascii=False)}
Existing locations (reuse exact id when clearly matched): {json.dumps(existing_locations, ensure_ascii=False)}

Return one object per image. Classify kind as world, location, character, prop,
style, or ignore. For a match, targetId is the exact existing id. For multiple
images of the same new entity, give all of them the same stable grouping key:
"new-character:<slug>" or "new-location:<slug>". World/prop/style use targetId
"world". Describe only visible evidence; do not invent biography or plot facts.
Write reader-facing name, description and reason in {language}. Write visualPrompt in
English because it is provider-facing technical direction. visualPrompt is a reusable
single-image identity/environment reference prompt without grids,
collages, captions, logos or UI. Confidence is 0 to 1. Return strict JSON only."""
    schema = asset_import_schema(len(paths))
    override = _comic_writing_llm(body)
    if not override:
        _ensure_llm_loaded()
    tracking_id = str(body.get("activity_id") or "").strip()[:160]
    if tracking_id:
        llm_service.begin_activity_tracking(
            tracking_id, phase="analyzing_assets", current=0, total=len(paths),
            detail=f"Analyzing {len(paths)} imported images…",
        )

    def run_analysis():
        result = _generate_comic_director_json(
            prompt=prompt,
            system_prompt=(
                "You are a production asset librarian and visual continuity analyst. "
                "Inspect every attached image and return strict JSON only."
            ),
            schema=schema,
            max_new_tokens=max(1200, len(paths) * 280),
            stage="Story Lab smart asset import",
            llm_override=override,
            image_paths=paths,
        )
        return validate_asset_import_result(result, len(paths))

    try:
        analyzed = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: llm_service.run_with_activity_tracking(tracking_id, run_analysis),
        )
    except Exception as exc:
        llm_service.update_activity_tracking(
            tracking_id, status="failed", phase="analyzing_assets",
            detail=str(exc), error=str(exc),
        )
        raise HTTPException(status_code=502, detail=f"Smart asset analysis failed: {exc}") from exc
    llm_service.update_activity_tracking(
        tracking_id, status="completed", phase="completed",
        current=len(paths), total=len(paths),
        detail=f"{len(paths)} asset suggestions ready for review.",
    )
    return {
        "assets": [
            {**item, "nameOriginal": names[item["index"]], "source": raw_assets[item["index"]].get("url", "")}
            for item in analyzed
        ],
    }

def generate_story_lab_section(body: dict):
    """Compatibility synchronous endpoint; new clients should use durable jobs."""
    scope = str(body.get("scope") or "all").strip().lower()
    allowed = {"overview", "world", "characters", "relationships", "structure", "music"}
    if scope == "all":
        raise HTTPException(
            status_code=400,
            detail="Full Story Lab generation must use /api/v1/stories/generate/start",
        )
    if scope not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported Story Lab generation scope")
    return {"result": _generate_story_lab_stage(body, scope)}

async def translate_story_lyrics(body: dict):
    """Translate editable song lyrics with the Story Lab writing provider."""
    from services import llm_service

    lyrics = str(body.get("lyrics") or "").strip()
    target_language = str(body.get("targetLanguage") or "").strip()[:80]
    if not lyrics:
        raise HTTPException(status_code=400, detail="Lyrics are required")
    if not target_language:
        raise HTTPException(status_code=400, detail="Choose a target language")
    system_prompt = (
        "Translate song lyrics accurately. Return only the translated lyrics, "
        "with no explanation, title, markdown or code fence. Translate only the sung "
        "lyric lines. Copy every song instruction enclosed in square brackets exactly "
        "as written, preserving its English text and capitalization (for example "
        "[Verse], [Pre Chorus], [Chorus], [Bridge], [Outro] or [Female vocal])."
    )
    prompt = (
        f"Translate the following lyrics into {target_language}. Do not translate or "
        "alter any text enclosed in square brackets; copy those instructions verbatim.\n\n"
        f"{lyrics}"
    )
    llm_override = _comic_writing_llm(body)
    try:
        if llm_override:
            translated = llm_service.generate_openai_compatible(
                prompt=prompt,
                system_prompt=system_prompt,
                model_id=llm_override["model"],
                base_url=llm_override["base_url"],
                api_key=llm_override["api_key"],
                max_new_tokens=min(3000, max(500, len(lyrics) * 2)),
                temperature=0.2,
            )
        else:
            _ensure_llm_loaded()
            translated = llm_service.generate_streaming(
                prompt=prompt,
                system_prompt=system_prompt,
                max_new_tokens=min(3000, max(500, len(lyrics) * 2)),
                temperature=0.2,
                enable_thinking=False,
                thinking_budget=0,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Lyric translation failed: {exc}") from exc

    translated = str(translated or "").strip()
    if translated.startswith("```"):
        translated = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", translated, flags=re.IGNORECASE).strip()
    if not translated:
        raise HTTPException(status_code=502, detail="The LLM returned empty translated lyrics")
    return {"lyrics": translated, "targetLanguage": target_language}

def start_story_lab_generation(body: dict):
    scope = str(body.get("scope") or "all").strip().lower()
    allowed = {"all", "overview", "world", "characters", "relationships", "structure", "music"}
    if scope not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported Story Lab generation scope")
    if not str(body.get("premise") or "").strip():
        raise HTTPException(status_code=400, detail="Write a premise before generating the story")
    project = body.get("project") if isinstance(body.get("project"), dict) else {}
    project_type = str(project.get("projectType") or "full_story").strip().lower()
    stage_total = 5 if project_type == "music_video" else 4 if project_type in {"trailer", "quick_video"} else 6
    job_id = f"story-plan-{uuid.uuid4().hex[:12]}"
    task_id = f"task-story-plan-{job_id}"
    job = {
        "jobId": job_id,
        "status": "queued",
        "message": "Story generation queued.",
        "stage": "queued",
        "current": 0,
        "total": stage_total if scope == "all" else 1,
        "request": _story_checkpoint_request(body),
        "completedStages": {},
        "result": None,
        "error": None,
        "createdAt": time.time(),
        "updatedAt": time.time(),
        "workspace": _get_active_workspace(),
        "taskId": task_id,
        "rootTaskId": task_id,
    }
    with _story_plan_jobs_lock:
        _story_plan_jobs[job_id] = job
    publisher = globals().get("_publish_generic_legacy_task")
    if callable(publisher):
        task = publisher(job, "story-plan")
        if isinstance(task, dict):
            job["taskId"] = task.get("id")
            job["rootTaskId"] = task.get("root_id") or task.get("id")
            with _story_plan_jobs_lock:
                _story_plan_jobs[job_id] = copy.deepcopy(job)
    _persist_story_plan_job(job)
    _start_story_plan_worker(job_id)
    return {
        key: job[key] for key in (
            "jobId", "taskId", "rootTaskId", "status", "message", "stage",
            "current", "total", "createdAt",
        )
    }

def get_story_lab_generation(job_id: str):
    job = _load_story_plan_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Story generation job not found")
    return {
        key: job.get(key) for key in (
            "jobId", "status", "message", "stage", "current", "total",
            "taskId", "rootTaskId", "createdAt", "updatedAt", "finishedAt",
            "result", "error",
        )
    }

def resume_story_lab_generation(job_id: str, body: dict | None = None):
    job = _load_story_plan_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Story generation job not found")
    if job.get("status") == "completed":
        return {"jobId": job_id, "status": "completed", "message": job.get("message")}
    with _story_plan_jobs_lock:
        active = job_id in _story_plan_active_jobs
    if active:
        return {
            "jobId": job_id,
            "status": job.get("status"),
            "message": "Story generation is already running.",
        }
    if job.get("status") in {"cancelled", "cancelling"}:
        # _story_job_update ignores every patch to a cancelled job, so a resume would reopen the Activity task and
        # then run nothing. Answered before anything is touched; a cancelled generation is started again.
        raise HTTPException(
            status_code=409,
            detail="A cancelled Story Lab generation cannot be resumed; start a new generation.",
        )
    request = _story_resume_request(job.get("request") or {}, body)
    # Resolve the profile before mutating the durable checkpoint so invalid
    # model names or missing credentials fail without damaging recovery.
    if isinstance(body, dict) and str(body.get("writingProvider") or "").strip():
        _comic_writing_llm(request)
    _reset_canonical_task_for_resume(
        str(job.get("workspace") or "default"),
        str(job.get("taskId") or f"task-story-plan-{job_id}"),
    )
    _story_job_update(
        job_id,
        request=request,
        status="queued",
        message="Resuming from the last completed Story Lab stage…",
        error=None,
        finishedAt=None,
    )
    if not _start_story_plan_worker(job_id):
        current = _load_story_plan_job(job_id) or job
        return {
            "jobId": job_id,
            "status": current.get("status") or "queued",
            "message": "Story generation is already running.",
        }
    return {"jobId": job_id, "status": "queued", "message": "Story generation resumed."}

def cancel_story_lab_generation(job_id: str):
    job = _load_story_plan_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Story generation job not found")
    if job.get("status") == "completed":
        return {"jobId": job_id, "status": "completed", "message": job.get("message")}
    with _story_plan_jobs_lock:
        worker_active = job_id in _story_plan_active_jobs
    updated = _story_job_update(
        job_id,
        status="cancelling" if worker_active else "cancelled",
        stage="cancelling" if worker_active else "cancelled",
        message=(
            "Story generation cancellation requested; aborting the active LLM "
            "response where supported, otherwise waiting for its safe boundary."
            if worker_active else
            "Story generation cancelled before an LLM call started."
        ),
        finishedAt=None if worker_active else time.time(),
    )
    return {
        "jobId": job_id,
        "status": (updated or job).get("status"),
        "message": (updated or job).get("message"),
    }

def _bind_story_lab_runtime(
    *,
    comic_writing_llm,
    ensure_llm_loaded,
    workspace_dir,
    list_workspaces,
    get_active_workspace,
    story_import_upload_path,
    publish_task,
    reset_task,
) -> None:
    """Point both Story Lab modules at one server's workspace helpers and task hooks."""
    global _comic_writing_llm, _ensure_llm_loaded, _get_active_workspace
    global _publish_generic_legacy_task, _reset_canonical_task_for_resume
    global _story_import_upload_path
    import services.story_lab_jobs as story_jobs

    _comic_writing_llm = comic_writing_llm
    _ensure_llm_loaded = ensure_llm_loaded
    _get_active_workspace = get_active_workspace
    _publish_generic_legacy_task = publish_task
    _reset_canonical_task_for_resume = reset_task
    _story_import_upload_path = story_import_upload_path
    story_jobs._comic_writing_llm = comic_writing_llm
    story_jobs._ensure_llm_loaded = ensure_llm_loaded
    story_jobs._workspace_dir = workspace_dir
    story_jobs._list_workspaces = list_workspaces
    story_jobs._publish_generic_legacy_task = publish_task


def create_story_lab_assets_router() -> APIRouter:
    """Asset analysis and one-section generation, in the order the full server registered them."""
    router = APIRouter()
    router.add_api_route("/api/v1/stories/assets/analyze", analyze_story_assets, methods=["POST"])
    router.add_api_route("/api/v1/stories/generate", generate_story_lab_section, methods=["POST"])
    return router


def create_story_lab_generation_router() -> APIRouter:
    """Lyrics translation and the durable Story Lab job routes, in registration order."""
    router = APIRouter()
    router.add_api_route("/api/v1/stories/translate-lyrics", translate_story_lyrics, methods=["POST"])
    router.add_api_route("/api/v1/stories/generate/start", start_story_lab_generation, methods=["POST"])
    router.add_api_route("/api/v1/stories/generate/status/{job_id}", get_story_lab_generation, methods=["GET"])
    router.add_api_route("/api/v1/stories/generate/resume/{job_id}", resume_story_lab_generation, methods=["POST"])
    router.add_api_route("/api/v1/stories/generate/cancel/{job_id}", cancel_story_lab_generation, methods=["POST"])
    return router

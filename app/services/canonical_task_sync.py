"""Canonical task sync, control and resume.

These functions moved verbatim out of ``app/_launch_runtime.py``. ``bind`` receives
the full server's objects once, after those names exist. This module imports the
standard library, FastAPI's ``HTTPException``, the model3d service, the job
lifecycle snapshot and the canonical task publishers. It does not import WanGP,
a router or ``_launch_runtime``.
"""
from __future__ import annotations

import copy
import json

from fastapi import HTTPException

from services import model3d_service
from services.canonical_task_publishers import (
    _publish_director_task,
    _publish_generation_task,
    _publish_generic_legacy_task,
    _publish_series_assembly_task,
    _publish_series_task,
)
from services.job_lifecycle import snapshot_job

# Injected by bind(); None until the full server binds them.
_comic_plan_jobs = None
_comic_plan_jobs_lock = None
_jobs = None
_minimax_music_jobs = None
_minimax_music_jobs_lock = None
_publish_minimax_music_job = None
_series_plan_jobs = None
_series_plan_jobs_lock = None
_series_render_jobs = None
_series_render_jobs_lock = None
_story_plan_jobs = None
_story_plan_jobs_lock = None
_task_registry = None
_workspace_dir = None
cancel_audio_analysis_job = None
cancel_comic_minimax_job = None
cancel_job = None
cancel_model3d_job = None
cancel_rig_job = None
cancel_series_episode_plan = None
cancel_series_render_job = None
cancel_story_lab_generation = None
cancel_story_music_candidates_job = None
cancel_video_editor_export = None
control_quick_video_batch_job = None
control_series_assembly_job = None
director_pipeline_resume = None
director_pipeline_stop = None
list_minimax_image_jobs = None
list_video_editor_jobs = None
resume_director_comic_plan = None
resume_series_episode_plan = None
resume_series_render_job = None
resume_story_lab_generation = None
wgp = None


def bind(**names):
    """Take the full server's objects this module uses (one call from the full server)."""
    global _comic_plan_jobs, _comic_plan_jobs_lock, _jobs, _minimax_music_jobs, _minimax_music_jobs_lock, _publish_minimax_music_job, _series_plan_jobs, _series_plan_jobs_lock, _series_render_jobs, _series_render_jobs_lock, _story_plan_jobs, _story_plan_jobs_lock, _task_registry, _workspace_dir, cancel_audio_analysis_job, cancel_comic_minimax_job, cancel_job, cancel_model3d_job, cancel_rig_job, cancel_series_episode_plan, cancel_series_render_job, cancel_story_lab_generation, cancel_story_music_candidates_job, cancel_video_editor_export, control_quick_video_batch_job, control_series_assembly_job, director_pipeline_resume, director_pipeline_stop, list_minimax_image_jobs, list_video_editor_jobs, resume_director_comic_plan, resume_series_episode_plan, resume_series_render_job, resume_story_lab_generation, wgp
    _comic_plan_jobs = names['_comic_plan_jobs']
    _comic_plan_jobs_lock = names['_comic_plan_jobs_lock']
    _jobs = names['_jobs']
    _minimax_music_jobs = names['_minimax_music_jobs']
    _minimax_music_jobs_lock = names['_minimax_music_jobs_lock']
    _publish_minimax_music_job = names['_publish_minimax_music_job']
    _series_plan_jobs = names['_series_plan_jobs']
    _series_plan_jobs_lock = names['_series_plan_jobs_lock']
    _series_render_jobs = names['_series_render_jobs']
    _series_render_jobs_lock = names['_series_render_jobs_lock']
    _story_plan_jobs = names['_story_plan_jobs']
    _story_plan_jobs_lock = names['_story_plan_jobs_lock']
    _task_registry = names['_task_registry']
    _workspace_dir = names['_workspace_dir']
    cancel_audio_analysis_job = names['cancel_audio_analysis_job']
    cancel_comic_minimax_job = names['cancel_comic_minimax_job']
    cancel_job = names['cancel_job']
    cancel_model3d_job = names['cancel_model3d_job']
    cancel_rig_job = names['cancel_rig_job']
    cancel_series_episode_plan = names['cancel_series_episode_plan']
    cancel_series_render_job = names['cancel_series_render_job']
    cancel_story_lab_generation = names['cancel_story_lab_generation']
    cancel_story_music_candidates_job = names['cancel_story_music_candidates_job']
    cancel_video_editor_export = names['cancel_video_editor_export']
    control_quick_video_batch_job = names['control_quick_video_batch_job']
    control_series_assembly_job = names['control_series_assembly_job']
    director_pipeline_resume = names['director_pipeline_resume']
    director_pipeline_stop = names['director_pipeline_stop']
    list_minimax_image_jobs = names['list_minimax_image_jobs']
    list_video_editor_jobs = names['list_video_editor_jobs']
    resume_director_comic_plan = names['resume_director_comic_plan']
    resume_series_episode_plan = names['resume_series_episode_plan']
    resume_series_render_job = names['resume_series_render_job']
    resume_story_lab_generation = names['resume_story_lab_generation']
    wgp = names['wgp']


def _reset_canonical_task_for_resume(workspace: str, task_id: str) -> None:
    """Explicitly reopen a terminal adapter task before its worker publishes."""
    if not task_id:
        return
    try:
        registry = _task_registry(workspace)
        existing = registry.get(task_id)
        if existing and str(existing.get("status") or "") in {
            "failed", "cancelled", "interrupted",
        }:
            registry.update(
                task_id,
                status="queued",
                phase="queued",
                message="Resume requested",
                error=None,
                completed_at=None,
                event_type="task.resume_requested",
                force=True,
            )
    except Exception as exc:
        print(f"[Task registry] Could not reopen {task_id}: {exc}")

def _sync_canonical_tasks(workspace: str) -> None:
    for job in list(_jobs.values()):
        if str(job.get("workspace") or "default") == workspace:
            snapshot = snapshot_job(job)
            if str(job.get("id") or "").startswith("audio-analysis-"):
                _publish_generic_legacy_task(snapshot, "audio-analysis")
            else:
                _publish_generation_task(snapshot)
    try:
        from services.director_pipeline import list_recent_pipelines
        director_base = wgp.server_config.get("save_path", "outputs")
        for pipeline in list_recent_pipelines(director_base, workspace):
            _publish_director_task(pipeline, workspace)
    except Exception:
        pass
    with _series_plan_jobs_lock:
        series_plans = [copy.deepcopy(job) for job in _series_plan_jobs.values()]
    with _series_render_jobs_lock:
        series_renders = [copy.deepcopy(job) for job in _series_render_jobs.values()]
    for job in series_plans:
        if str(job.get("workspace") or "default") == workspace:
            _publish_series_task(job, "series-plan")
    for job in series_renders:
        if str(job.get("workspace") or "default") == workspace:
            _publish_series_task(job, "series-render")
    try:
        from services.series_jobs import SeriesJobStore
        assembly_jobs = SeriesJobStore(_workspace_dir(workspace), "assembly").list()
    except (OSError, ValueError, json.JSONDecodeError):
        assembly_jobs = []
    for job in assembly_jobs:
        if str(job.get("workspace") or workspace) == workspace:
            _publish_series_assembly_task(job)
    with _story_plan_jobs_lock:
        story_jobs = [copy.deepcopy(job) for job in _story_plan_jobs.values()]
    with _comic_plan_jobs_lock:
        comic_jobs = [copy.deepcopy(job) for job in _comic_plan_jobs.values()]
    for job in story_jobs:
        if str(job.get("workspace") or "default") == workspace:
            _publish_generic_legacy_task(job, "story-plan")
    for job in comic_jobs:
        if str(job.get("workspace") or "default") == workspace:
            _publish_generic_legacy_task(job, "comic-plan")
    video_editor_jobs = list_video_editor_jobs()
    for job in video_editor_jobs:
        if str(job.get("workspace") or "default") == workspace:
            _publish_generic_legacy_task(job, "video-editor")
    for job in list_minimax_image_jobs():
        if str(job.get("workspace") or "default") == workspace:
            _publish_generic_legacy_task(job, "minimax-image")
    with _minimax_music_jobs_lock:
        minimax_music_jobs = [copy.deepcopy(job) for job in _minimax_music_jobs.values()]
    for job in minimax_music_jobs:
        if str(job.get("workspace") or "default") == workspace:
            _publish_minimax_music_job(job)
    try:
        with model3d_service._lock:
            model3d_jobs = [copy.deepcopy(job) for job in model3d_service._jobs.values()]
        for job in model3d_jobs:
            if str(job.get("workspace") or "default") == workspace:
                _publish_generic_legacy_task(job, "model3d")
    except Exception:
        pass
    try:
        from services import rig_service
        with rig_service._lock:
            rig_jobs = [copy.deepcopy(job) for job in rig_service._jobs.values()]
        for job in rig_jobs:
            if str(job.get("workspace") or "default") == workspace:
                _publish_generic_legacy_task(job, "rig")
    except Exception:
        pass

def _control_canonical_task(task: dict, action: str):
    adapter = str((task.get("metadata") or {}).get("adapter") or "")
    legacy_id = str(task.get("backend_job_id") or task.get("pipeline_id") or "")
    if action == "cancel":
        if adapter == "generation": return cancel_job(legacy_id)
        if adapter == "director": return director_pipeline_stop(legacy_id)
        if adapter == "series-plan": return cancel_series_episode_plan(legacy_id)
        if adapter == "series-render": return cancel_series_render_job(legacy_id)
        if adapter == "story-plan": return cancel_story_lab_generation(legacy_id)
        if adapter == "video-editor": return cancel_video_editor_export(legacy_id)
        if adapter == "model3d": return cancel_model3d_job(legacy_id)
        if adapter == "rig": return cancel_rig_job(legacy_id)
        if adapter == "minimax-image": return cancel_comic_minimax_job(legacy_id)
        if adapter == "audio-analysis": return cancel_audio_analysis_job(legacy_id)
        if adapter == "minimax-music": return cancel_story_music_candidates_job(legacy_id)
        if adapter == "minimax-music-candidate":
            root_backend_id = str(task.get("root_id") or "").removeprefix(
                "task-minimax-music-"
            )
            return cancel_story_music_candidates_job(root_backend_id)
        if adapter == "series-assembly":
            return control_series_assembly_job(_workspace_dir(str(task.get("workspace") or "default")), legacy_id, "cancel")
        if adapter == "quick-video-batch":
            return control_quick_video_batch_job(
                _workspace_dir(str(task.get("workspace") or "default")),
                legacy_id,
                "cancel",
            )
    if action in {"retry", "resume"}:
        if adapter == "director": return director_pipeline_resume(legacy_id)
        if adapter == "series-plan": return resume_series_episode_plan(legacy_id)
        if adapter == "series-render": return resume_series_render_job(legacy_id)
        if adapter == "story-plan": return resume_story_lab_generation(legacy_id)
        if adapter == "comic-plan": return resume_director_comic_plan(legacy_id)
        if adapter == "series-assembly":
            return control_series_assembly_job(_workspace_dir(str(task.get("workspace") or "default")), legacy_id, "resume")
        if adapter == "quick-video-batch":
            return control_quick_video_batch_job(
                _workspace_dir(str(task.get("workspace") or "default")),
                legacy_id,
                "resume",
            )
    if action == "discard" and adapter == "series-assembly":
        return control_series_assembly_job(
            _workspace_dir(str(task.get("workspace") or "default")),
            legacy_id,
            "discard",
        )
    raise HTTPException(status_code=409, detail=f"Task does not support {action}")

def _list_canonical_production_pipelines(workspace: str):
    from services.director_pipeline import list_pipeline_states
    return list_pipeline_states(wgp.server_config.get("save_path", "outputs"), workspace)

"""Director planner and short-film pipeline routes for the full server.

The core server does not mount these routes. Its pipeline start, continue and
rerun stay blocked. Handlers stay module-level so a move keeps the launch
function name, and the served route table names this file. This module does
not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import asyncio
import traceback

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

# Injected by bind_director_runtime. None until the full server binds them.
_active_gen_states = None
_ensure_llm_loaded = None
_gen_lock = None
_get_active_workspace = None
_get_cached_hardware = None
_is_minimax_h3_model = None
_jobs = None
_publish_director_task = None
_request_generation_cancel = None
_reset_canonical_task_for_resume = None
_run_generation = None
_workspace_collection_registry = None
_workspace_dir = None
execution_mode = None
wgp = None


class _PipelineInitState:
    """One flag. ``_init_pipeline`` is the only writer."""

    def __init__(self) -> None:
        self.initialized = False


_pipeline_init_state = _PipelineInitState()


def _init_pipeline():
    if not _pipeline_init_state.initialized:
        from services.director_pipeline import init as pipeline_init
        pipeline_init(
            _jobs,
            _run_generation,
            wgp,
            _gen_lock,
            _request_generation_cancel,
            _active_gen_states,
            state_observer=_publish_director_task,
            get_cached_hardware=_get_cached_hardware,
        )
        _pipeline_init_state.initialized = True


async def director_classify_sections(request: Request):
    """Use LLM to reclassify section labels based on lyrics content."""
    from services import llm_service, audio_analysis
    body = await request.json()

    analysis = body.get("analysis")
    if not analysis:
        raise HTTPException(status_code=400, detail="analysis is required")

    sections = analysis.get("sections", [])
    lyrics = analysis.get("lyrics")
    duration = analysis.get("duration", 0)
    lyrics_hint = body.get("lyrics_hint", "")

    if not sections:
        return {"sections": sections, "method": "heuristic"}

    try:
        timed_structure = audio_analysis.structure_from_aligned_lyrics(
            analysis.get("lyric_timeline") or []
        )
        if timed_structure:
            updated = audio_analysis.replace_sections_with_structure(analysis, timed_structure)
            return {
                "sections": updated["sections"],
                "song_structure": timed_structure,
                "method": "lyrics_timeline",
            }
        tagged_structure = llm_service.structure_from_tagged_lyrics(lyrics_hint, duration)
        if tagged_structure:
            updated = audio_analysis.replace_sections_with_structure(analysis, tagged_structure)
            return {
                "sections": updated["sections"],
                "song_structure": tagged_structure,
                "method": "lyrics_hint",
            }
        # Unknown uploads still need a transcription before either repetition
        # detection or the classifier can identify semantic sections.
        if not lyrics:
            return {"sections": sections, "song_structure": [], "method": "heuristic"}
        _ensure_llm_loaded()
        result = llm_service.classify_song_sections(
            sections=sections,
            lyrics=lyrics,
            duration=duration,
        )
        song_structure = result.get("song_structure", [])

        if song_structure:
            # Replace audio sections entirely with LLM structure
            # (uses LLM boundaries/labels, interpolates energy from audio)
            updated = audio_analysis.replace_sections_with_structure(
                analysis, song_structure
            )
        else:
            # Fallback: just relabel existing sections
            labels = result["labels"]
            updated = audio_analysis.classify_sections_with_lyrics(analysis, labels)

        return {
            "sections": updated["sections"],
            "song_structure": song_structure,
            "method": "llm",
        }
    except Exception as e:
        print(f"[Director] LLM section classification failed, using heuristic: {e}")
        return {"sections": sections, "song_structure": [], "method": "heuristic"}


async def director_plan_prompts_and_images(request: Request):
    """Use LLM to generate per-clip video AND image-edit prompts."""
    from services import llm_service
    body = await request.json()

    clips = body.get("clips")
    scene_description = body.get("scene_description", "")
    if not clips:
        raise HTTPException(status_code=400, detail="clips is required")
    if not scene_description:
        raise HTTPException(status_code=400, detail="scene_description is required")

    _ensure_llm_loaded()

    ref_image_path = body.get("reference_image_path")

    try:
        clip_plans = llm_service.plan_clip_prompts_and_images(
            clips=clips,
            scene_description=scene_description,
            lyrics=body.get("lyrics"),
            bpm=body.get("bpm", 120.0),
            reference_image_path=ref_image_path,
            speaker_mappings=body.get("speaker_mappings"),
            prompt_type=body.get("prompt_type", "both"),
            existing_image_prompts=body.get("existing_image_prompts"),
            video_model=body.get("video_model", ""),
            music_video_treatment=body.get("music_video_treatment"),
        )
        if _is_minimax_h3_model(body.get("video_model")):
            from services.director.minimax_h3_prompting import (
                adapt_clip_plans_for_h3,
                h3_audio_policy_from_payload,
            )
            clip_plans = adapt_clip_plans_for_h3(
                clip_plans,
                reference_mode=body.get("h3_reference_mode", "first_frame"),
                audio_direction=body.get("h3_audio_prompt", ""),
                h3_audio_policy=h3_audio_policy_from_payload(body),
            )
        return {"clip_plans": clip_plans}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def director_plan_dialogue_scenes(request: Request):
    """Plan variable-duration clips based on dialogue pacing and speaker changes."""
    from services import audio_analysis
    body = await request.json()

    analysis = body.get("analysis")
    if not analysis:
        raise HTTPException(status_code=400, detail="analysis is required")

    try:
        clips = audio_analysis.plan_dialogue_scenes(
            analysis=analysis,
            pacing_bias=body.get("pacing_bias", 0),
            fps=body.get("fps", 16),
            frames_steps=body.get("frames_steps", 4),
            frames_minimum=body.get("frames_minimum", 5),
        )
        return {"clips": clips}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def director_plan_short_film_prompts(request: Request):
    """Use LLM to generate cinematic per-shot prompts for short film mode."""
    from services import llm_service
    body = await request.json()

    clips = body.get("clips")
    scene_description = body.get("scene_description", "")
    if not clips:
        raise HTTPException(status_code=400, detail="clips is required")
    if not scene_description:
        raise HTTPException(status_code=400, detail="scene_description is required")

    _ensure_llm_loaded()

    try:
        clip_plans = llm_service.plan_short_film_prompts(
            clips=clips,
            scene_description=scene_description,
            lyrics=body.get("lyrics"),
            reference_image_path=body.get("reference_image_path"),
            speaker_mappings=body.get("speaker_mappings"),
            characters=body.get("characters"),
            character_ref_paths=body.get("character_ref_paths"),
            character_ref_labels=body.get("character_ref_labels"),
            location_ref_paths=body.get("location_ref_paths"),
            location_ref_labels=body.get("location_ref_labels"),
            prompt_type=body.get("prompt_type", "both"),
            existing_image_prompts=body.get("existing_image_prompts"),
        )
        if _is_minimax_h3_model(body.get("video_model")):
            from services.director.minimax_h3_prompting import (
                adapt_clip_plans_for_h3,
                h3_audio_policy_from_payload,
            )
            clip_plans = adapt_clip_plans_for_h3(
                clip_plans,
                reference_mode=body.get("h3_reference_mode", "first_frame"),
                audio_direction=body.get("h3_audio_prompt", ""),
                h3_audio_policy=h3_audio_policy_from_payload(body),
            )
        return {"clip_plans": clip_plans}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def director_plan_short_film_script(request: Request):
    """Use LLM to plan scenes and prompts from a story description (no audio)."""
    from services import llm_service
    body = await request.json()

    story_description = body.get("story_description", "")
    if not story_description:
        raise HTTPException(status_code=400, detail="story_description is required")

    _ensure_llm_loaded()

    import asyncio

    try:
        # Run in thread pool so the event loop stays free for stream-status polling
        result = await asyncio.to_thread(
            llm_service.plan_short_film_from_story,
            story_description=story_description,
            characters=body.get("characters"),
            reference_image_path=body.get("reference_image_path"),
            character_ref_paths=body.get("character_ref_paths"),
            character_ref_labels=body.get("character_ref_labels"),
            location_ref_paths=body.get("location_ref_paths"),
            location_ref_labels=body.get("location_ref_labels"),
            target_duration=body.get("target_duration", 30),
            target_scenes=body.get("target_scenes"),
            narrative_mode=body.get("narrative_mode", True),
            fps=body.get("fps", 24),
            frames_steps=body.get("frames_steps", 4),
            frames_minimum=body.get("frames_minimum", 5),
            visual_style=body.get("visual_style", ""),
            preserve_visual_style=body.get("preserve_visual_style", False),
            character_visual_style=body.get("character_visual_style", ""),
            allow_clip_text=body.get("allow_clip_text") is True,
            raw_prompts=wgp.server_config.get("services", {}).get("raw_prompts") is True,
        )
        return result
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def director_pipeline_start(request: Request):
    """Start a Director pipeline (LLM planning → image gen → video gen).

    Runs entirely server-side so the browser can be closed.
    """
    _init_pipeline()
    from services.director_pipeline import get_pipeline, start_pipeline
    from services.generation_provenance import normalize_submission_provenance
    body = await request.json()
    body["provenance"] = normalize_submission_provenance(
        body.pop("provenance", None)
    )
    collection_id = body["provenance"].get("workspace_id")
    if collection_id and not _workspace_collection_registry.get(collection_id):
        raise HTTPException(status_code=400, detail="Unknown Workspace collection")
    workspace = body.get("workspace") or _get_active_workspace()
    try:
        execution_mode.validate_generation(workspace)
    except execution_mode.ExecutionModeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        body["workspace"] = workspace
        pid = start_pipeline(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pipeline = get_pipeline(pid) or {}
    return {
        "pipeline_id": pid,
        "task_id": pipeline.get("task_id"),
        "root_task_id": (
            pipeline.get("root_task_id") or pipeline.get("task_id")
        ),
    }


async def director_pipeline_continue(pid: str, request: Request):
    """Resume a paused pipeline, optionally with updated clip plans."""
    _init_pipeline()
    from services.director_pipeline import continue_pipeline
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    ok = continue_pipeline(pid, body or None)
    if not ok:
        raise HTTPException(status_code=400, detail="Pipeline is not paused")
    return {"status": "resumed"}


async def director_pipeline_generate_preview(pid: str, request: Request):
    """Generate all or one clip from a reusable comic PRE checkpoint."""
    _init_pipeline()
    from services.director_pipeline import start_preview_generation

    body = (
        await request.json()
        if request.headers.get("content-length", "0") != "0"
        else {}
    )
    clip_index = body.get("clip_index")
    clip_indices = body.get("clip_indices")
    expected_fingerprint = body.get("expected_fingerprint")
    base = wgp.server_config.get("save_path", "outputs")
    ok, message, child_pid = start_preview_generation(
        pid,
        clip_index,
        base,
        clip_indices=clip_indices,
        expected_fingerprint=expected_fingerprint,
        run_type=body.get("run_type"),
    )
    if not ok or not child_pid:
        raise HTTPException(status_code=400, detail=message)
    return {
        "status": "started",
        "pipeline_id": child_pid,
        "source_preview_pipeline_id": pid,
        "clip_index": clip_index,
        "clip_indices": clip_indices,
        "run_type": body.get("run_type"),
        "reused": message == "already_running",
    }


async def director_pipeline_update_preview(pid: str, request: Request):
    """Persist edits to a Comic PRE and rebuild its frozen inputs."""
    _init_pipeline()
    from services.director_pipeline import (
        get_pipeline,
        update_comic_preview,
    )

    body = await request.json()
    base = wgp.server_config.get("save_path", "outputs")
    ok, message = update_comic_preview(
        pid,
        body.get("clips"),
        base,
        expected_fingerprint=body.get("expected_fingerprint"),
        approve_preview=bool(body.get("approve_preview", False)),
        quality_waiver=bool(body.get("quality_waiver", False)),
        waiver_reason=str(body.get("waiver_reason") or ""),
        accept_quality_test=bool(body.get("accept_quality_test", False)),
        accepted_via=str(body.get("accepted_via") or ""),
        accepted_by=str(body.get("accepted_by") or ""),
        acceptance_note=str(body.get("acceptance_note") or ""),
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    pipeline = get_pipeline(pid) or {}
    fingerprint = pipeline.get("_comic_preflight_fingerprint")
    return {
        "status": pipeline.get("status", "preview_ready"),
        "message": message,
        "preview_clips": pipeline.get("preview_clips", []),
        "preview_fingerprint": fingerprint,
        "preview_approved": bool(
            fingerprint
            and pipeline.get("_preview_approved_fingerprint") == fingerprint
        ),
        "quality_gate": pipeline.get("_quality_gate"),
    }


def director_pipeline_stop(pid: str):
    """Request cancellation and return the pipeline's current state."""
    from services.director_pipeline import get_pipeline, stop_pipeline
    accepted = stop_pipeline(pid)
    current = get_pipeline(pid)
    if not current:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    status = str(current.get("status") or "unknown")
    phase = str(current.get("phase") or status)
    cancelled = status == "cancelled"
    return {
        "accepted": accepted,
        "status": status,
        "phase": phase,
        "cancel_requested": bool(
            current.get("_cancel_requested")
            or phase == "cancelling"
            or cancelled
        ),
        "cancelled": cancelled,
        "persisted": bool(current.get("_state_persisted", False)),
    }


def director_pipeline_resume(pid: str):
    """Resume a crashed pipeline from its saved state.

    Reuses the planning (and start images when still on disk) that finished
    before the crash, then re-runs video generation — so a mid-run backend
    crash doesn't throw away completed LLM work.
    """
    _init_pipeline()
    from services.director_pipeline import get_pipeline, resume_pipeline
    base = wgp.server_config.get("save_path", "outputs")
    ok, message = resume_pipeline(pid, base)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    pipeline = get_pipeline(pid) or {}
    workspace = str(pipeline.get("workspace") or _get_active_workspace())
    task_id = f"task-director-{pid}"
    _reset_canonical_task_for_resume(workspace, task_id)
    task = _publish_director_task(pipeline, workspace)
    return {
        "status": str(pipeline.get("status") or "resumed"),
        "phase": str(pipeline.get("phase") or "resumed"),
        "pipeline_id": pid,
        "task_id": (task or {}).get("id") or task_id,
        "root_task_id": (task or {}).get("root_id") or task_id,
    }


async def update_pipeline_clip_prompt(pid: str, clip_index: int, request: Request):
    """Persist an edited image/video prompt onto a saved pipeline shot."""
    from services.director_pipeline import PipelineBusyError, update_clip_prompts
    body = await request.json()
    base = wgp.server_config.get("save_path", "outputs")
    try:
        soundtrack_drive = body.get("soundtrack_drive")
        if soundtrack_drive is not None:
            soundtrack_drive = bool(soundtrack_drive)
        return update_clip_prompts(
            base,
            pid,
            clip_index,
            video_prompt=body.get("video_prompt"),
            image_prompt=body.get("image_prompt"),
            soundtrack_drive=soundtrack_drive,
        )
    except PipelineBusyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def tag_pipeline_clip(pid: str, clip_index: int, request: Request):
    """Tag a clip as 'good', 'needs_work', or null."""
    from services.director_pipeline import PipelineBusyError, update_clip_tag
    body = await request.json()
    tag = body.get("tag")
    base = wgp.server_config.get("save_path", "outputs")
    try:
        success = update_clip_tag(base, pid, clip_index, tag)
    except PipelineBusyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    if not success:
        return JSONResponse({"error": "Pipeline or clip not found"}, status_code=404)
    return {"status": "ok"}


async def select_pipeline_clip_video(pid: str, clip_index: int, request: Request):
    """Select one historical/Studio video as the authoritative slot take."""

    from services.director_pipeline import (
        PipelineBusyError,
        select_clip_video_attempt,
    )
    body = await request.json()
    base = wgp.server_config.get("save_path", "outputs")
    try:
        return select_clip_video_attempt(
            base,
            pid,
            clip_index,
            body.get("filename"),
        )
    except PipelineBusyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


def repair_saved_pipeline(pid: str):
    """Start a browser-independent missing-media repair and final rejoin."""
    _init_pipeline()
    from services.director_pipeline import (
        PipelineBusyError,
        start_pipeline_repair,
    )
    base = wgp.server_config.get("save_path", "outputs")
    try:
        result = start_pipeline_repair(base, pid)
        return JSONResponse(result, status_code=202)
    except PipelineBusyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"error": str(exc)}, status_code=500)


def cancel_saved_pipeline_repair(pid: str):
    """Cancel a server-owned repair and its current generation child."""
    _init_pipeline()
    from services.director_pipeline import cancel_pipeline_repair
    base = wgp.server_config.get("save_path", "outputs")
    repair = cancel_pipeline_repair(base, pid)
    if not repair:
        return JSONResponse(
            {"error": "No active repair for this pipeline"}, status_code=409,
        )
    return {"pipeline_id": pid, "repair": repair}


async def rerun_pipeline_clip_image(pid: str, clip_index: int, request: Request):
    """Re-generate the start image for a specific clip in a saved pipeline."""
    _init_pipeline()
    from services.director_pipeline import (
        GenerationCancelledError,
        PipelineBusyError,
        rerun_clip_image,
    )
    body = await request.json()
    base = wgp.server_config.get("save_path", "outputs")
    try:
        # Image generation can take minutes. Running it directly inside this
        # async route blocks every heartbeat/poll request and can make the
        # Pinokio webview reload, aborting the browser-owned bulk repair loop
        # after its first clip.
        result = await asyncio.to_thread(
            rerun_clip_image,
            base,
            pid,
            clip_index,
            prompt_override=body.get("prompt"),
        )
        return result
    except PipelineBusyError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except GenerationCancelledError as e:
        return JSONResponse({
            "error": str(e),
            "cancelled": True,
            "output_files": list(e.output_files),
        }, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


async def rerun_pipeline_clip_video(pid: str, clip_index: int, request: Request):
    """Re-generate the video for a specific clip in a saved pipeline."""
    _init_pipeline()
    from services.director_pipeline import (
        GenerationCancelledError,
        PipelineBusyError,
        rerun_clip_video,
    )
    body = await request.json()
    base = _workspace_dir(body["workspace"]) if body.get("workspace") else wgp.server_config.get("save_path", "outputs")
    from services.production_shot_regeneration import guard_shared_regeneration
    guard_shared_regeneration(base, body.get("workspace") or "default", body,
                              f"/api/v1/director/pipelines/{pid}/clips/{clip_index}/rerun-video")
    try:
        result = await asyncio.to_thread(
            rerun_clip_video,
            base,
            pid,
            clip_index,
            prompt_override=body.get("prompt"),
        )
        return result
    except PipelineBusyError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except GenerationCancelledError as e:
        return JSONResponse({
            "error": str(e),
            "cancelled": True,
            "output_files": list(e.output_files),
        }, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


async def rerun_pipeline_h3_segment(
    pid: str,
    clip_index: int,
    segment_index: int,
    request: Request,
):
    """Regenerate one editable H3 segment and its dependent continuations."""
    _init_pipeline()
    from services.director_pipeline import rerun_h3_segment
    body = await request.json()
    base = wgp.server_config.get("save_path", "outputs")
    try:
        return rerun_h3_segment(
            base,
            pid,
            clip_index,
            segment_index,
            prompt_override=body.get("prompt"),
            cascade=body.get("cascade", True) is not False,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


async def rejoin_pipeline_clips(pid: str):
    """Re-join all clips from a saved pipeline using current best versions."""
    _init_pipeline()
    from services.director_pipeline import PipelineBusyError, rejoin_clips
    base = wgp.server_config.get("save_path", "outputs")
    try:
        result = await asyncio.to_thread(rejoin_clips, base, pid)
        return result
    except PipelineBusyError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def delete_pipeline_endpoint(pid: str):
    """Delete a saved pipeline and all media it produced (any workspace)."""
    _init_pipeline()
    from services.director_pipeline import delete_pipeline
    base = wgp.server_config.get("save_path", "outputs")
    result = delete_pipeline(base, pid)
    if not result.get("ok"):
        if result.get("error") == "running":
            raise HTTPException(status_code=409, detail="This pipeline is still running. Stop it first, then delete.")
        if result.get("error") == "state_file_locked":
            raise HTTPException(
                status_code=409,
                detail="Pipeline media was cleaned, but its state file is locked. Close any process using it and retry deletion.",
            )
        if result.get("error") == "media_locked":
            raise HTTPException(
                status_code=409,
                detail="Some pipeline media is still in use. Close its preview or any process using it, then retry deletion.",
            )
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pid}")
    print(f"[Pipeline] Deleted {pid}: {result['media_deleted']} media files removed "
          f"({result['media_deferred']} deferred) from {result['dir']}")
    return result



def bind_director_runtime(
    *,
    jobs,
    run_generation,
    wgp_module,
    gen_lock,
    request_generation_cancel,
    active_gen_states,
    publish_director_task,
    get_cached_hardware,
    ensure_llm_loaded,
    is_minimax_h3_model,
    get_active_workspace,
    workspace_dir,
    workspace_collection_registry,
    reset_canonical_task_for_resume,
    execution_mode_module,
) -> None:
    """Point the planner and pipeline routes at one server's helpers."""
    global _jobs, _run_generation, wgp, _gen_lock
    global _request_generation_cancel, _active_gen_states
    global _publish_director_task, _get_cached_hardware
    global _ensure_llm_loaded, _is_minimax_h3_model
    global _get_active_workspace, _workspace_dir
    global _workspace_collection_registry
    global _reset_canonical_task_for_resume, execution_mode
    _jobs = jobs
    _run_generation = run_generation
    wgp = wgp_module
    _gen_lock = gen_lock
    _request_generation_cancel = request_generation_cancel
    _active_gen_states = active_gen_states
    _publish_director_task = publish_director_task
    _get_cached_hardware = get_cached_hardware
    _ensure_llm_loaded = ensure_llm_loaded
    _is_minimax_h3_model = is_minimax_h3_model
    _get_active_workspace = get_active_workspace
    _workspace_dir = workspace_dir
    _workspace_collection_registry = workspace_collection_registry
    _reset_canonical_task_for_resume = reset_canonical_task_for_resume
    execution_mode = execution_mode_module


def create_director_planner_router() -> APIRouter:
    """Planner routes and pipeline start, in the order the full server registered them."""
    router = APIRouter()
    router.add_api_route(
        "/api/v1/director/classify-sections",
        director_classify_sections,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/plan-prompts-and-images",
        director_plan_prompts_and_images,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/plan-dialogue-scenes",
        director_plan_dialogue_scenes,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/plan-short-film-prompts",
        director_plan_short_film_prompts,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/plan-short-film-script",
        director_plan_short_film_script,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/pipeline/start",
        director_pipeline_start,
        methods=["POST"],
    )
    return router


def create_director_pipeline_run_router() -> APIRouter:
    """Continue, preview, stop and resume, in the order the full server registered them."""
    router = APIRouter()
    router.add_api_route(
        "/api/v1/director/pipeline/{pid}/continue",
        director_pipeline_continue,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/pipeline/{pid}/generate-preview",
        director_pipeline_generate_preview,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/pipeline/{pid}/preview",
        director_pipeline_update_preview,
        methods=["PATCH"],
    )
    router.add_api_route(
        "/api/v1/director/pipeline/{pid}/stop",
        director_pipeline_stop,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/pipeline/{pid}/resume",
        director_pipeline_resume,
        methods=["POST"],
    )
    return router


def create_director_pipeline_edit_router() -> APIRouter:
    """Clip edits, repair, reruns, rejoin and delete, in the full server's order."""
    router = APIRouter()
    router.add_api_route(
        "/api/v1/director/pipelines/{pid}/clips/{clip_index}/prompt",
        update_pipeline_clip_prompt,
        methods=["PUT"],
    )
    router.add_api_route(
        "/api/v1/director/pipelines/{pid}/clips/{clip_index}/tag",
        tag_pipeline_clip,
        methods=["PUT"],
    )
    router.add_api_route(
        "/api/v1/director/pipelines/{pid}/clips/{clip_index}/video-selection",
        select_pipeline_clip_video,
        methods=["PUT"],
    )
    router.add_api_route(
        "/api/v1/director/pipelines/{pid}/repair",
        repair_saved_pipeline,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/pipelines/{pid}/repair/cancel",
        cancel_saved_pipeline_repair,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/pipelines/{pid}/clips/{clip_index}/rerun-image",
        rerun_pipeline_clip_image,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/pipelines/{pid}/clips/{clip_index}/rerun-video",
        rerun_pipeline_clip_video,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/pipelines/{pid}/clips/{clip_index}/segments/{segment_index}/rerun",
        rerun_pipeline_h3_segment,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/pipelines/{pid}/rejoin",
        rejoin_pipeline_clips,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/pipelines/{pid}",
        delete_pipeline_endpoint,
        methods=["DELETE"],
    )
    return router

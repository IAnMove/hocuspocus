"""Director v2 planning for the full server.

The plan body, the planner inputs and the job-store helper live here. The
HTTP routes live in ``routers.director_v2``. The provider set, the workspace
helpers and the LLM routing calls are injected by the full server and are
the same objects the rest of the server uses. This module does not import
WanGP, a router, or ``_launch_runtime``.
"""
from __future__ import annotations

import asyncio
import copy
import time

from fastapi import HTTPException

# Injected by bind_director_v2_plan. None until the full server binds them.
# ``_PUBLIC_LLM_PROVIDERS`` is that server's set, not a copy.
_PUBLIC_LLM_PROVIDERS = None
_effective_llm_routing = None
_ensure_llm_loaded = None
_get_active_workspace = None
_is_minimax_h3_model = None
_workspace_dir = None
wgp = None


_DIRECTOR_V2_PLANNER_KEYS = (
    "clips", "scene_description", "story_description", "lyrics", "bpm",
    "reference_image_path", "character_ref_paths", "character_ref_labels",
    "location_ref_paths", "location_ref_labels", "speaker_mappings", "characters",
    "audio_path", "target_duration", "target_scenes", "narrative_mode",
    "fps", "frames_steps", "frames_minimum", "concept", "visual_style",
    "preserve_visual_style", "character_visual_style", "allow_clip_text",
    "platform", "style", "transcript", "prompt_type", "image_model",
    "video_model", "seamless", "multishot_lora_mode",
    "music_video_treatment",
)


# The planners index these as lists of objects (``music_video.plan(lyrics: list[dict])``).
_LISTS_OF_OBJECTS = ("lyrics", "clips", "characters")


def _check_planner_shapes(body: dict) -> None:
    """A wrongly typed field is a 422 that names it, before a durable job or an Activity row exists. Left to the
    planner it ended inside the job as a 500 with a Python message, and a resume repeated it."""
    for field in _LISTS_OF_OBJECTS:
        value = body.get(field)
        if value and (not isinstance(value, list) or not all(isinstance(item, dict) for item in value)):
            raise HTTPException(status_code=422, detail=f"{field} must be a list of objects")


def _director_v2_planner_kwargs(body: dict) -> dict:
    """Keep every supported Director input, including Story Lab visual refs."""
    return {key: body[key] for key in _DIRECTOR_V2_PLANNER_KEYS if key in body}


async def _director_v2_plan_body(body: dict):
    """Plan using the new Director v2 architecture (planners + renderers + validators).

    Returns structured ProductionPlan + rendered clip_plans.
    """
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Director plan request must be an object")
    _check_planner_shapes(body)
    skill_type = body.get("skill_type", body.get("pipeline_type", "music_video"))
    tracking_id = str(body.get("activity_id") or "").strip()[:160]
    from services import llm_service
    if tracking_id:
        estimated_shots = len(body.get("clips") or []) or int(body.get("target_scenes") or 0)
        llm_service.begin_activity_tracking(
            tracking_id,
            phase="writing_scenes",
            current=0,
            total=estimated_shots,
            detail="Writing the visual scenario and scene structure…",
        )

    # Map legacy pipeline_type to skill_type
    skill_map = {
        "music_video": "music_video",
        "short_film_audio": "short_film",
        "short_film_story": "short_film",
        "podcast": "podcast",
        "viral_video": "viral_video",
    }
    skill_type = skill_map.get(skill_type, skill_type)

    plan_job_store = None
    plan_job = None
    plan_job_id = ""
    workspace = str(body.get("workspace") or _get_active_workspace())
    if skill_type == "music_video":
        from services.director_plan_jobs import (
            DirectorPlanJobStore,
            claim_director_plan_job,
        )

        plan_job_store = DirectorPlanJobStore(_workspace_dir(workspace))
        requested_job_id = str(body.get("plan_job_id") or "").strip()
        if requested_job_id:
            plan_job = plan_job_store.load(requested_job_id)
            if plan_job is None:
                raise HTTPException(status_code=404, detail="Director plan job not found")
            if str(plan_job.get("workspace") or "default") != workspace:
                raise HTTPException(status_code=409, detail="Director plan job belongs to another workspace")
            if str(plan_job.get("skillType") or "") != skill_type:
                raise HTTPException(status_code=409, detail="Director plan job uses another skill")
            if plan_job.get("status") == "completed" and isinstance(plan_job.get("result"), dict):
                return copy.deepcopy(plan_job["result"])
            saved_request = copy.deepcopy(plan_job.get("request") or {})
            if not isinstance(saved_request, dict):
                raise HTTPException(status_code=409, detail="Director plan job request is unavailable")
            if tracking_id:
                saved_request["activity_id"] = tracking_id
            saved_request["workspace"] = workspace
            saved_request["plan_job_id"] = requested_job_id
            body = saved_request
            plan_job_id = requested_job_id
            if not claim_director_plan_job(plan_job_id):
                raise HTTPException(status_code=409, detail="Director plan job is already running")
            try:
                plan_job = plan_job_store.update(
                    plan_job_id,
                    status="running",
                    phase="resuming",
                    message="Resuming missing music-video clip plans",
                    error=None,
                    finishedAt=None,
                )
            except Exception:
                from services.director_plan_jobs import release_director_plan_job
                release_director_plan_job(plan_job_id)
                raise
        else:
            durable_request = copy.deepcopy(body)
            durable_request.pop("plan_job_id", None)
            durable_request["workspace"] = workspace
            plan_job = plan_job_store.create(
                durable_request,
                workspace=workspace,
                skill_type=skill_type,
                total=len(body.get("clips") or []),
            )
            plan_job_id = str(plan_job["jobId"])
            if not claim_director_plan_job(plan_job_id):
                raise HTTPException(status_code=409, detail="Director plan job is already running")
            try:
                plan_job = plan_job_store.update(
                    plan_job_id,
                    status="running",
                    phase="starting",
                    message="Starting durable music-video planning",
                )
            except Exception:
                from services.director_plan_jobs import release_director_plan_job
                release_director_plan_job(plan_job_id)
                raise

    try:
        _ensure_llm_loaded()

        from services.director.orchestrator import DirectorOrchestrator, DirectorFlags

        flags = DirectorFlags.from_dict(body.get("director_flags", {}))
        # Raw prompts: the planner's prompts get no style lock, source-style
        # anchor, compression, no-text lock or polish.
        raw_prompts = wgp.server_config.get("services", {}).get("raw_prompts") is True
        flags.raw_prompts = raw_prompts
        director = DirectorOrchestrator(
            llm_generate=llm_service.generate,
            llm_generate_streaming=llm_service.generate_streaming,
            flags=flags,
        )

        # Build planner kwargs from request body
        from services.director.planners.music_video import normalize_music_video_treatment
        normalized_treatment = normalize_music_video_treatment(
            body.get("music_video_treatment")
        )
        direct_video = normalized_treatment.get("generation_mode") == "direct_video"
        if skill_type == "music_video" or direct_video:
            body["music_video_treatment"] = normalized_treatment
        planner_kwargs = _director_v2_planner_kwargs(body)

        # NSFW from server config (enforced: never with public providers)
        services = wgp.server_config.get("services", {})
        provider = _effective_llm_routing(services)[0]
        planner_kwargs["nsfw"] = services.get("nsfw_mode", False) and provider not in _PUBLIC_LLM_PROVIDERS

        if plan_job_store is not None and plan_job is not None:
            planner_kwargs["completed_shot_plans"] = copy.deepcopy(
                plan_job.get("completedShotPlans") or []
            )

            def _checkpoint_music_plan_batch(event: dict) -> None:
                usage = (
                    llm_service.get_activity_tracking(tracking_id).get("usage")
                    if tracking_id else {}
                ) or {}
                event_type = str(event.get("event") or "")
                indices = [
                    int(value) for value in event.get("indices") or []
                    if isinstance(value, int) or str(value).isdigit()
                ]
                if event_type == "call_started":
                    plan_job_store.begin_call(
                        plan_job_id,
                        indices=indices,
                        phase=str(event.get("phase") or "planning"),
                        usage=usage,
                    )
                    llm_service.update_activity_tracking(
                        tracking_id,
                        phase=f"planning_{event.get('phase') or 'batch'}",
                        current=len((plan_job_store.load(plan_job_id) or {}).get("completedIndices") or []),
                        total=len(body.get("clips") or []),
                        detail=f"Planning clip indexes {', '.join(map(str, indices))}…",
                    )
                elif event_type == "batch_completed":
                    shot_plans = event.get("shot_plans") or []
                    plan_job_store.record_batch(
                        plan_job_id,
                        indices=indices,
                        shot_plans=shot_plans,
                        usage=usage,
                    )
                    llm_service.update_activity_tracking(
                        tracking_id,
                        phase="batch_completed",
                        current=len((plan_job_store.load(plan_job_id) or {}).get("completedIndices") or []),
                        total=len(body.get("clips") or []),
                        detail=f"Saved clip indexes {', '.join(map(str, indices))}.",
                    )

            planner_kwargs["batch_checkpoint"] = _checkpoint_music_plan_batch

        # Prompt polish mode: off | full_guide | light_guide | third_pass.
        # Off by default: the planner's prompts reach the models as written.
        # The third pass is model-aware; native H3 prompts retain their
        # deterministic compiler while applicable prompts are polished.
        polish_mode = "off" if raw_prompts else services.get("director_prompt_polish", "off")
        video_model = body.get("video_model", "")
        image_model = body.get("image_model", "")

        # Extract activated LoRA filenames for guide loading
        video_loras_activated = (body.get("video_loras") or {}).get("activated_loras", [])
        image_loras_activated = (body.get("image_loras") or {}).get("activated_loras", [])

        # For guide injection modes (full/light), pass polish block to planners via kwargs
        if polish_mode in ("full_guide", "light_guide"):
            from services.director.prompt_polish import build_polish_block
            guide_mode = "full" if polish_mode == "full_guide" else "light"
            polish_block = build_polish_block(video_model, image_model, guide_mode,
                                              video_loras=video_loras_activated, image_loras=image_loras_activated)
            if polish_block:
                planner_kwargs["polish_block"] = polish_block

        # Plan
        plan = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: llm_service.run_with_activity_tracking(
                tracking_id,
                lambda: director.plan(skill_type, **planner_kwargs),
            ),
        )

        # Render
        planned_shots = len(getattr(plan, "shots", []) or [])
        llm_service.update_activity_tracking(
            tracking_id,
            phase="writing_prompts",
            current=0,
            total=planned_shots,
            detail=f"Turning {planned_shots} scenes into image and video prompts…",
        )
        has_reference = not direct_video and bool(
            body.get("reference_image_path")
            or body.get("character_ref_paths")
            or body.get("location_ref_paths")
        )
        prompt_type = "video" if direct_video else body.get("prompt_type", "both")
        rendered = director.render_plan(plan, prompt_type=prompt_type, has_reference=has_reference)
        clip_plans = director.plan_to_clip_plans(rendered)

        # Third-pass polish: run each prompt through the enhance pipeline
        if polish_mode == "third_pass" and clip_plans and not direct_video:
            from services.director.prompt_polish import polish_prompts_third_pass
            nsfw = planner_kwargs.get("nsfw", False)
            # Forward character profiles so polish can map names → correct
            # non-human descriptors (e.g. Lumi → the white unicorn) instead
            # of falling back to generic "the woman" / "the man".
            polish_chars = planner_kwargs.get("characters", []) or []
            llm_service.update_activity_tracking(
                tracking_id,
                phase="polishing_prompts",
                current=0,
                total=len(clip_plans),
                detail=f"Polishing shot 1 of {len(clip_plans)}…",
            )

            def _report_polish_progress(current, total):
                shot = clip_plans[max(0, min(current - 1, len(clip_plans) - 1))]
                detail = str(shot.get("image_prompt") or shot.get("video_prompt") or "").strip()
                llm_service.update_activity_tracking(
                    tracking_id,
                    phase="polishing_prompts",
                    current=current,
                    total=total,
                    detail=detail[:1200],
                )

            clip_plans = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: llm_service.run_with_activity_tracking(
                    tracking_id,
                    lambda: polish_prompts_third_pass(
                        clip_plans, video_model, image_model, nsfw,
                        video_loras=video_loras_activated, image_loras=image_loras_activated,
                        characters=polish_chars,
                        progress_callback=_report_polish_progress,
                    ),
                ),
            )

        from services.director.policies import (
            enforce_visual_style_on_clip_plans,
            no_visible_text_lock_applies,
        )
        # The no-visible-text lock is for sung projects (music videos) only.
        clip_text_allowed = not no_visible_text_lock_applies({
            "pipeline_type": skill_type,
            "allow_clip_text": body.get("allow_clip_text"),
        })
        clip_plans = clip_plans if raw_prompts else enforce_visual_style_on_clip_plans(
            clip_plans,
            "" if direct_video else body.get("visual_style", ""),
            preserve=(
                False if direct_video
                else bool(body.get("preserve_visual_style", False))
            ),
            has_reference=has_reference,
            character_visual_style=(
                "" if direct_video else body.get("character_visual_style", "")
            ),
            allow_clip_text=True if direct_video else clip_text_allowed,
        )
        if direct_video:
            from services.director.policies import enforce_direct_video_on_clip_plans
            clip_plans = enforce_direct_video_on_clip_plans(
                clip_plans,
                normalized_treatment.get("direct_video_master_prompt"),
                audio_direction=body.get("h3_audio_prompt", ""),
                allow_clip_text=raw_prompts or clip_text_allowed,
            )
        elif _is_minimax_h3_model(video_model):
            from services.director.minimax_h3_prompting import (
                adapt_clip_plans_for_h3,
                h3_audio_policy_from_payload,
            )
            serialized_plan = plan.to_dict()
            clip_plans = adapt_clip_plans_for_h3(
                clip_plans,
                serialized_plan.get("shots") or [],
                reference_mode=body.get("h3_reference_mode", "first_frame"),
                audio_direction=body.get("h3_audio_prompt", ""),
                h3_audio_policy=h3_audio_policy_from_payload(body),
            )
            clip_plans = clip_plans if raw_prompts else enforce_visual_style_on_clip_plans(
                clip_plans,
                body.get("visual_style", ""),
                preserve=bool(body.get("preserve_visual_style", False)),
                has_reference=has_reference,
                character_visual_style=body.get("character_visual_style", ""),
                allow_clip_text=clip_text_allowed,
            )
        llm_service.update_activity_tracking(
            tracking_id,
            status="completed",
            phase="completed",
            current=len(clip_plans),
            total=len(clip_plans),
            detail=f"{len(clip_plans)} visual shot plans ready for review.",
        )
        result = {
            "clip_plans": clip_plans,
            "production_plan": plan.to_dict(),
            "skill_type": skill_type,
        }
        if plan_job_store is not None and plan_job_id:
            result["plan_job_id"] = plan_job_id
            plan_job_store.update(
                plan_job_id,
                status="completed",
                phase="completed",
                message=f"{len(clip_plans)} visual shot plans ready for review",
                activeBatch=[],
                result=copy.deepcopy(result),
                error=None,
                finishedAt=time.time(),
            )
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        recoverable_failure = None
        if plan_job_store is not None and plan_job_id:
            try:
                failed_job = plan_job_store.update(
                    plan_job_id,
                    status="failed",
                    phase="failed",
                    message="Music-video planning stopped; completed batches are recoverable",
                    activeBatch=[],
                    error=str(e),
                    finishedAt=time.time(),
                )
                from services.director_plan_jobs import build_director_plan_failure_detail
                recoverable_failure = build_director_plan_failure_detail(failed_job, str(e))
            except Exception as checkpoint_error:
                print(f"[DirectorPlanJob] Could not persist failure state: {checkpoint_error}")
        llm_service.update_activity_tracking(
            tracking_id, status="failed", detail=str(e), error=str(e)
        )
        if recoverable_failure is not None:
            raise HTTPException(status_code=500, detail=recoverable_failure)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if plan_job_id:
            from services.director_plan_jobs import release_director_plan_job
            release_director_plan_job(plan_job_id)


def _director_plan_job_store(workspace: str):
    from services.director_plan_jobs import DirectorPlanJobStore
    return DirectorPlanJobStore(_workspace_dir(workspace))



def bind_director_v2_plan(
    *,
    get_active_workspace,
    workspace_dir,
    ensure_llm_loaded,
    wgp_module,
    effective_llm_routing,
    is_minimax_h3_model,
    public_llm_providers,
) -> None:
    """Point v2 planning at one server's helpers."""
    global _get_active_workspace, _workspace_dir, _ensure_llm_loaded, wgp
    global _effective_llm_routing, _is_minimax_h3_model, _PUBLIC_LLM_PROVIDERS
    _get_active_workspace = get_active_workspace
    _workspace_dir = workspace_dir
    _ensure_llm_loaded = ensure_llm_loaded
    wgp = wgp_module
    _effective_llm_routing = effective_llm_routing
    _is_minimax_h3_model = is_minimax_h3_model
    _PUBLIC_LLM_PROVIDERS = public_llm_providers

"""Story Lab generation jobs for the full server.

The job dictionary, the active-job set and their lock stay here. The
workspace helpers and the writing-provider callables are injected by the
full server and are the same objects the rest of the server uses. This
module does not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid

from fastapi import HTTPException

from services.comic_director_json import _generate_comic_director_json
from services.series_plan_jobs import _llm_abort_outcome, _planning_cancel_message
from services.story_lab_schema import (
    _merge_story_stage_project,
    _normalize_story_stage_ids,
    _story_lab_schema,
    _story_project_prompt_context,
    _story_stage_problem,
)

_story_plan_jobs: dict[str, dict] = {}
_story_plan_jobs_lock = threading.Lock()
_story_plan_active_jobs: set[str] = set()
_STORY_PLAN_TERMINAL = {"completed", "failed", "cancelled"}


def any_story_plan_job_active() -> bool:
    """True while Story Lab planning still writes checkpoints into the workspace.

    These jobs live in ``_story_plan_jobs`` / ``_story_plan_active_jobs``,
    not ``jobs()`` or ``_active_gen_states``. Queued, running and cancelling
    ones persist under ``.story-plan-jobs`` via ``_workspace_dir``; completed
    / failed / cancelled ones do not. Workspace delete must treat the first
    group as busy.
    """
    with _story_plan_jobs_lock:
        if _story_plan_active_jobs:
            return True
        return any(
            str(job.get("status") or "") not in _STORY_PLAN_TERMINAL
            for job in _story_plan_jobs.values()
        )


def reset_story_plan_jobs() -> None:
    """Drop in-memory Story Lab plan jobs. Tests use this; production does not."""
    with _story_plan_jobs_lock:
        _story_plan_jobs.clear()
        _story_plan_active_jobs.clear()

# Injected by _bind_story_lab_runtime. None until the full server binds them.
_comic_writing_llm = None
_ensure_llm_loaded = None
_list_workspaces = None
_publish_generic_legacy_task = None
_workspace_dir = None


def _generate_story_lab_stage(body: dict, scope: str) -> dict:
    """Generate and validate one replaceable Story Lab stage."""
    schema_scope = "beats" if scope == "structure" else scope
    premise = str(body.get("premise") or "").strip()
    project = body.get("project") if isinstance(body.get("project"), dict) else {}
    project_type = str(project.get("projectType") or "full_story").strip().lower()
    if project_type not in {"full_story", "music_video", "trailer", "quick_video"}:
        project_type = "full_story"
    creative_brief = project.get("creativeBrief") if isinstance(project.get("creativeBrief"), dict) else {}
    general_idea = str(creative_brief.get("generalIdea") or "").strip()[:12000]
    try:
        brief_duration = int(float(creative_brief.get("durationSeconds") or 0))
    except (TypeError, ValueError):
        brief_duration = 0
    if not premise:
        premise = str(project.get("premise") or "").strip()
    if not premise:
        raise HTTPException(status_code=400, detail="Write a premise before generating the story")
    instruction = str(body.get("instruction") or "").strip()[:4000]
    language = str(body.get("language") or project.get("language") or "English").strip()
    genre = str(body.get("genre") or project.get("genre") or "Adventure").strip()
    tone = str(body.get("tone") or project.get("tone") or "").strip()
    tone_line = f"Tone: {tone}\n" if tone else ""
    audience = str(body.get("audience") or project.get("audience") or "General").strip()
    visual_style = str(project.get("visualStyle") or "").strip()[:4000]
    character_visual_style = str(project.get("characterVisualStyle") or "").strip()[:2000]
    enforce_visual_style = project.get("enforceVisualStyle") is not False
    allow_clip_text = project.get("allowClipText") is True
    llm_override = _comic_writing_llm(body)
    if not llm_override:
        _ensure_llm_loaded()
    current = _story_project_prompt_context(project, scope)
    music_direction = ""
    if scope == "music":
        character_count = len([
            item for item in project.get("characters", []) if isinstance(item, dict)
        ])
        if project_type == "music_video":
            music_direction = f"""
Music-video contract:
- Return exactly one original vocal story song. Its kind is "story" and targetId is "story".
- The performer/creator is: {str(creative_brief.get('performer') or 'not specified')[:1000]}.
- Requested musical style: {str(creative_brief.get('musicStyle') or genre)[:1000]}.
- What the song must tell: {str(creative_brief.get('songStory') or premise)[:2000]}.
- Target duration: {max(20, min(360, brief_duration or 90))} seconds.
- referenceSong is an editable inspiration example in "Title — Artist" form. Use it only
  for broad tempo, instrumentation or emotional architecture; never copy melody or lyrics.
- style is the final MiniMax Music prompt: one concise English comma-separated line,
  10–300 characters, covering genre, mood, instruments, vocals, tempo and production.
- Write lyrics in {language}, maximum 3500 characters, with a recurring hook and a clear
  narrative progression. Use supported English tags on their own lines: [Intro], [Verse],
  [Pre Chorus], [Chorus], [Bridge], [Hook], [Inst], [Solo], [Outro].
- Set instrumental false. Make brief and purpose explain how this song drives the videoclip.
"""
        else:
            music_direction = f"""
Music-specific contract:
- Return exactly one instrumental ambient cue for targetId "world".
- Return exactly one presentation cue for each of the {character_count} existing character IDs.
- Return exactly three distinct vocal story songs covering different emotional/narrative angles.
- referenceSong is an editable input example in "Title — Artist" form. Choose a useful,
  recognizable reference for tempo, instrumentation or emotional architecture only.
- Every style prompt, melody concept and lyric must be newly written for this Story. Never
  reproduce the reference song's melody, lyrics, title phrases or distinctive arrangement.
- Treat referenceSong, brief, the Story canon and requested lyric theme as INPUTS to transform.
  The final style field must never contain the reference title or artist name.
- style is the final MiniMax Music prompt. Write one concise English comma-separated line,
  10–300 characters, ordered as applicable: primary genre/subgenre, secondary influence,
  mood/atmosphere, key instruments, vocal direction, tempo or BPM, dynamics, production.
  Prefer concrete compatible traits; avoid contradictions, filler and narrative synopsis.
- Write vocal lyrics in {language}, maximum 3500 characters, with short natural singable
  lines (usually 4–8 words). Use only MiniMax-supported tags on their own lines with blank
  lines between sections: [Intro], [Verse], [Pre Chorus], [Chorus], [Post Chorus],
  [Interlude], [Bridge], [Transition], [Build Up], [Break], [Hook], [Inst], [Solo], [Outro].
  Use parentheses for sparse performance/arrangement directions. Give every vocal song a
  recurring hook or chorus and a concrete narrative progression through this Story.
- For instrumental cues set instrumental true and lyrics to an empty string. Put genre,
  atmosphere, instrumentation, tempo and musical arc entirely in style.
- Make brief and purpose explain how the cue maps to this exact world, character or story arc.
"""
    if project_type == "music_video":
        narrative_direction = f"""
This is a compact music-first story, not a complete franchise bible. Build a coherent visual
arc around the performer and the song. Context: {str(creative_brief.get('context') or premise)[:3000]}.
Use 4–10 beats that can become videoclip shots and keep locations/cast deliberately small.
"""
    elif project_type == "trailer":
        narrative_direction = f"""
This is a cinematic movie-trailer project, not a videoclip and not a complete short film.
Film context: {str(creative_brief.get('context') or premise)[:3000]}.
Protagonists: {str(creative_brief.get('subjects') or 'not specified')[:1500]}.
World and locations: {str(creative_brief.get('setting') or 'not specified')[:1500]}.
Core conflict and trailer promise: {str(creative_brief.get('action') or premise)[:3000]}.
Target duration: {max(15, min(180, brief_duration or 60))} seconds. Use 6–12 concise,
shootable beats covering cold open, promise, disruption, escalation, a breath and a final
unresolved hook. Never require a song and never reveal or resolve the source story ending.
"""
    elif project_type == "quick_video":
        narrative_direction = f"""
This is a fast single-concept video. Subjects: {str(creative_brief.get('subjects') or 'not specified')[:1500]}.
Setting: {str(creative_brief.get('setting') or 'not specified')[:1500]}.
Requested action/dialogue: {str(creative_brief.get('action') or premise)[:3000]}.
Format: {str(creative_brief.get('quickFormat') or 'dialogue')[:100]}; target duration:
{max(5, min(120, brief_duration or 15))} seconds. Use 3–8 concise,
shootable beats in one scene or a very small number of locations. Do not inflate it into a
feature-film mythology; preserve the direct joke, dialogue, announcement or viral premise.
"""
    else:
        narrative_direction = """
Build one causal dramatic arc with setup, inciting incident, rising complications,
midpoint/reversal, crisis, climax and resolution.
"""
    brief_interpretation = f"""
SOURCE BRIEF INTERPRETATION CONTRACT:
- The source brief below is the user's highest-priority intent. Preserve explicit requirements.
- Distinguish avatar/character identity from reusable global art direction and from shot action.
- A pasted successful generation prompt is evidence and inspiration, not a clip to repeat.
  Extract its useful identity/style/camera vocabulary, but do not repeat its exact dialogue,
  action or composition in every beat.
- Durations mentioned inside prompt examples (for example, "3 second clip") describe that
  example only. They do not replace the project's requested duration unless the user clearly
  states a duration for the whole production.
- In overview, copy generalIdea verbatim and fill every other editable foundation field
  coherently. Use empty strings only where a field genuinely does not apply to this project type.
SOURCE BRIEF:
{general_idea or 'No separate free-form source brief; use the structured premise.'}
"""
    base_prompt = f"""Create the requested editable Story Lab material.
Generation scope: {scope}
Premise: {premise}
Language for reader-facing narrative fields: {language}
Technical prompt language: English. Write visualStyle, characterVisualStyle,
visualLanguage, visualPrompt, negativePrompt and every other provider-facing camera,
rendering or production direction in English. Keep exact dialogue, lyrics, subtitles,
visible text and names in the language declared by languageIntent and preserve them
character-for-character; when a technical prompt needs one, isolate it as literal data
and never translate or paraphrase it.
Genre: {genre}
{tone_line}Audience: {audience}
Global visual style (separate from story content): {visual_style or 'not set'}
Character rendering style (mandatory for every visible person): {character_visual_style or 'not set'}
Apply that style as a mandatory render-time constraint: {'yes' if enforce_visual_style else 'no'}
Readable text inside future generated clips: {'allowed when explicitly requested' if allow_clip_text else 'forbidden; lyrics and dialogue are audio/performance only, and visual fields must not request captions, subtitles, signs, UI, floating words or quoted text'}
Optional user instruction: {instruction or 'none'}
Current manually edited project (preserve useful established facts and stable IDs):
{current}
{brief_interpretation}
{music_direction}
{narrative_direction}

Return only the JSON required by the schema. This is a reusable story bible, not a comic
page plan and not a screenplay. Characters need
distinct desire, need, flaw, voice, visual silhouette and a change caused by their choices.
Visual prompts describe one neutral concept-art subject or environment only: no contact
sheets, no grids, no comic panels, no lettering, no captions, no UI and no multiple views.
Keep visualPrompt fields semantic and reusable: describe identity, environment, composition,
lighting and story-specific color cues, but do not paste the global visual style into every
field. Maestro applies that independent style at image render time when its lock is enabled.
Keep IDs short, ASCII and stable. Do not overwrite manual facts unless the instruction asks."""
    system_prompt = (
        "You are HocusPocus Lab Story Architect: a professional story editor, character "
        "designer and production bible author. Return strict JSON only."
    )
    schema = _story_lab_schema(schema_scope, project_type)
    max_new_tokens = (
        2400 if scope == "music" and project_type == "music_video"
        else 6000 if scope == "music"
        else 2000 if project_type == "quick_video"
        else 2600
    )
    try:
        result = _generate_comic_director_json(
            prompt=base_prompt,
            system_prompt=system_prompt,
            schema=schema,
            max_new_tokens=max_new_tokens,
            stage=f"Story Lab {scope}",
            llm_override=llm_override,
        )
    except Exception as exc:
        # _generate_comic_director_json already made one bounded repair pass
        # with the original malformed text.  Do not blindly spend another
        # pair of full generations when that recovery also failed.
        raise HTTPException(
            status_code=502,
            detail=f"Story generation failed after JSON repair: {exc}",
        ) from exc

    result = _normalize_story_stage_ids(result, scope, project)
    problem = _story_stage_problem(result, scope, project)
    if problem:
        # Syntax may be valid while the response still violates the requested
        # stage shape (for example, {"world": []}).  Providers have no
        # conversational memory, so include the compact recovered object and
        # request one focused correction rather than another fresh story.
        previous_response = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        previous_limit = 16000
        if len(previous_response) > previous_limit:
            previous_response = (
                previous_response[:previous_limit]
                + "\n[previous response truncated for bounded schema repair]"
            )
        correction = (
            f"\n\nSTORY SCHEMA REPAIR: The previous response failed validation: {problem}. "
            "Do not invent a new story. Preserve the usable story facts below and return "
            "only a corrected JSON object matching the supplied schema.\n"
            f"PREVIOUS RESPONSE TO REPAIR:\n{previous_response}"
        )
        try:
            result = _generate_comic_director_json(
                prompt=base_prompt + correction,
                system_prompt=system_prompt,
                schema=schema,
                max_new_tokens=max_new_tokens,
                stage=f"Story Lab {scope} schema repair",
                llm_override=llm_override,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Story generation schema repair failed: {exc}",
            ) from exc
        result = _normalize_story_stage_ids(result, scope, project)
        problem = _story_stage_problem(result, scope, project)
    if result is not None and problem and scope == "relationships":
        # A provider can still invent a third name after retries. Preserve all
        # valid relationships and discard only irreparable references instead
        # of failing the entire multi-stage Story Bible.
        salvaged = _normalize_story_stage_ids(
            result,
            scope,
            project,
            drop_unknown_relationships=True,
        )
        salvage_problem = _story_stage_problem(salvaged, scope, project)
        if salvage_problem is None:
            result = salvaged
            problem = None
    if result is None or problem:
        raise HTTPException(
            status_code=502,
            detail=f"Story generation remained incomplete after bounded repair: {problem}",
        )
    if scope == "structure" and "beats" in result:
        result = {"structure": result["beats"]}
    return result

def _story_plan_checkpoint_dir(workspace: str | None = None) -> str:
    path = os.path.join(_workspace_dir(workspace), ".story-plan-jobs")
    os.makedirs(path, exist_ok=True)
    return path

def _story_plan_checkpoint_path(job_id: str, workspace: str | None = None) -> str:
    return os.path.join(_story_plan_checkpoint_dir(workspace), f"{job_id}.json")

def _persist_story_plan_job(job: dict) -> None:
    path = _story_plan_checkpoint_path(job["jobId"], job.get("workspace"))
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        try:
            if os.path.isfile(temporary):
                os.remove(temporary)
        except OSError:
            pass

def _story_job_update(job_id: str, **patch) -> dict | None:
    with _story_plan_jobs_lock:
        job = _story_plan_jobs.get(job_id)
        if not job:
            return None
        next_status = str(patch.get("status") or job.get("status") or "")
        if (
            job.get("status") == "cancelling"
            and next_status not in {"cancelling", "cancelled"}
        ):
            return copy.deepcopy(job)
        if (
            job.get("status") == "cancelled"
            and next_status != "cancelled"
        ):
            return copy.deepcopy(job)
        job.update(patch)
        job["updatedAt"] = time.time()
        snapshot = copy.deepcopy(job)
        # Persist while the job lock still establishes update order. Writing
        # after releasing it allowed an older thread to overwrite a newer
        # cancel/resume checkpoint even when both writes were individually
        # atomic.
        _persist_story_plan_job(snapshot)
        publisher = globals().get("_publish_generic_legacy_task")
        if callable(publisher):
            try:
                publisher(snapshot, "story-plan")
            except Exception as exc:
                print(f"[Task registry] Could not publish Story plan {job_id}: {exc}")
        return snapshot

def _load_story_plan_job(job_id: str) -> dict | None:
    with _story_plan_jobs_lock:
        job = _story_plan_jobs.get(job_id)
        if job:
            return copy.deepcopy(job)
    paths = [
        _story_plan_checkpoint_path(job_id, item["name"])
        for item in _list_workspaces()
    ]
    path = next((candidate for candidate in paths if os.path.isfile(candidate)), None)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            job = json.load(handle)
        if not isinstance(job, dict):
            return None
        with _story_plan_jobs_lock:
            _story_plan_jobs[job_id] = job
        return copy.deepcopy(job)
    except Exception:
        return None

def _run_story_plan_job_inner(job_id: str) -> None:
    job = _load_story_plan_job(job_id)
    if not job:
        return
    body = copy.deepcopy(job.get("request") or {})
    requested_scope = str(body.get("scope") or "all")
    project = body.get("project") if isinstance(body.get("project"), dict) else {}
    project_type = str(project.get("projectType") or "full_story").strip().lower()
    all_stages = (
        ["overview", "characters", "world", "structure", "music"]
        if project_type == "music_video"
        else ["overview", "characters", "world", "structure"]
        if project_type in {"trailer", "quick_video"}
        else ["overview", "characters", "world", "relationships", "structure", "music"]
    )
    stages = all_stages if requested_scope == "all" else [requested_scope]
    completed = job.get("completedStages")
    completed = completed if isinstance(completed, dict) else {}
    working_project = copy.deepcopy(body.get("project") or {})
    combined = {}
    try:
        for index, stage in enumerate(stages):
            latest = _load_story_plan_job(job_id)
            if latest and latest.get("status") in {"cancelling", "cancelled"}:
                return
            if stage in completed:
                original_result = completed[stage]
                result = _normalize_story_stage_ids(original_result, stage, working_project)
                if result != original_result:
                    completed[stage] = result
                    _story_job_update(job_id, completedStages=completed)
            else:
                _story_job_update(
                    job_id,
                    status="running",
                    stage=stage,
                    current=index,
                    total=len(stages),
                    message=f"Generating {stage}…",
                )
                stage_body = {
                    **body,
                    "scope": stage,
                    "project": working_project,
                }
                result = _generate_story_lab_stage(stage_body, stage)
                latest = _load_story_plan_job(job_id)
                if latest and latest.get("status") in {"cancelling", "cancelled"}:
                    return
                completed[stage] = result
                _story_job_update(job_id, completedStages=completed)
            combined.update(result)
            working_project = _merge_story_stage_project(working_project, result)
        _story_job_update(
            job_id,
            status="completed",
            stage="completed",
            current=len(stages),
            total=len(stages),
            message="Story draft generated and ready for review.",
            result={"result": combined},
            finishedAt=time.time(),
            error=None,
        )
    except Exception as exc:
        latest = _load_story_plan_job(job_id)
        if latest and latest.get("status") in {"cancelling", "cancelled"}:
            outcome = _llm_abort_outcome(exc)
            if latest.get("status") == "cancelling" and outcome is not None:
                _story_job_update(
                    job_id,
                    status="cancelling",
                    cancellationAbortSupported=outcome,
                    message=_planning_cancel_message("Story generation", outcome),
                )
            return
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        _story_job_update(
            job_id,
            status="failed",
            message="Story generation stopped. Completed stages were preserved.",
            error=str(detail),
            finishedAt=time.time(),
        )

def _run_story_plan_job(job_id: str) -> None:
    with _story_plan_jobs_lock:
        _story_plan_active_jobs.add(job_id)
        job = copy.deepcopy(_story_plan_jobs.get(job_id) or {})
    try:
        from services.task_manager import task_context_scope

        workspace = str(job.get("workspace") or "default")
        task_id = str(job.get("taskId") or f"task-story-plan-{job_id}")
        root_task_id = str(job.get("rootTaskId") or task_id)
        with task_context_scope(
            task_id=task_id,
            root_task_id=root_task_id,
            workspace=workspace,
            workspace_dir=_workspace_dir(workspace),
        ):
            _run_story_plan_job_inner(job_id)
    finally:
        with _story_plan_jobs_lock:
            _story_plan_active_jobs.discard(job_id)
        settling = _load_story_plan_job(job_id) or {}
        if settling.get("status") == "cancelling":
            _story_job_update(
                job_id,
                status="cancelled",
                stage="cancelled",
                message=_planning_cancel_message(
                    "Story generation",
                    settling.get("cancellationAbortSupported")
                    if isinstance(settling.get("cancellationAbortSupported"), bool)
                    else None,
                ),
                finishedAt=time.time(),
            )

def _start_story_plan_worker(job_id: str) -> bool:
    """Claim a Story planner before Thread.start so resume cannot duplicate it."""
    with _story_plan_jobs_lock:
        if job_id in _story_plan_active_jobs:
            return False
        _story_plan_active_jobs.add(job_id)
    thread = threading.Thread(
        target=_run_story_plan_job,
        args=(job_id,),
        name=f"story-plan-{job_id[-6:]}",
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        with _story_plan_jobs_lock:
            _story_plan_active_jobs.discard(job_id)
        raise
    return True

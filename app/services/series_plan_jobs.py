"""Series plan jobs shared by the full server and the core server.

The job dictionary, the active-job set and their lock stay here. The Series
library lock is injected by each server and is the same object the library
routes use. This module does not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import copy
import json
import math
import threading
import time
from datetime import datetime, timezone

from fastapi import HTTPException

from services import workspace_busy
from services.comic_director_json import _generate_comic_director_json

_series_plan_jobs: dict[str, dict] = {}
_series_plan_jobs_lock = threading.RLock()
_series_plan_active_jobs: set[str] = set()


def busy_jobs(workspace: str, workspace_dir: str) -> list[dict]:
    """Series planners that are running now, on either server (``services.workspace_busy`` probe).

    The claim set is the proof of life (released in the planner's ``finally``). A plan checkpoint
    that a crash left as ``running`` is cached here on read but holds no claim, so it never blocks.
    """
    with _series_plan_jobs_lock:
        return workspace_busy.claimed(_series_plan_active_jobs, _series_plan_jobs)

# Injected by _bind_series_plan_runtime. None until a server binds them.
_workspace_dir = None
_list_workspaces = None
_series_library_lock = None
_read_series_workspace = None
_write_series_workspace = None
_series_project_or_404 = None
_comic_writing_llm = None
_ensure_llm_loaded = None
_publish_series_task = None


def _llm_abort_outcome(exc: Exception) -> bool | None:
    """Return whether a cancellation closed the active provider response."""
    value = getattr(exc, "abort_supported", None)
    return bool(value) if isinstance(value, bool) else None

def _planning_cancel_message(subject: str, abort_supported: bool | None) -> str:
    if abort_supported is True:
        outcome = "the active LLM response was closed immediately"
    elif abort_supported is False:
        outcome = "the provider could not abort its active response, so it stopped at the next safe boundary"
    else:
        outcome = "the active request was aborted where supported and otherwise stopped at the next safe boundary"
    return f"{subject} cancelled: {outcome}. Completed stages remain recoverable."

def _series_plan_store(workspace: str):
    from services.series_jobs import SeriesJobStore

    return SeriesJobStore(_workspace_dir(workspace), "planning")

def _load_series_plan_job(job_id: str) -> dict | None:
    with _series_plan_jobs_lock:
        cached = _series_plan_jobs.get(job_id)
        if cached:
            return copy.deepcopy(cached)
    for item in _list_workspaces():
        try:
            job = _series_plan_store(item["name"]).load(job_id)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if job:
            with _series_plan_jobs_lock:
                _series_plan_jobs[job_id] = job
            return copy.deepcopy(job)
    return None

def _series_plan_update(job_id: str, **patch) -> dict | None:
    with _series_plan_jobs_lock:
        job = _series_plan_jobs.get(job_id)
        if not job:
            return None
        if (
            job.get("status") == "cancelling"
            and patch.get("status") not in {"cancelling", "cancelled"}
        ):
            return copy.deepcopy(job)
        job.update(copy.deepcopy(patch))
        job["updatedAt"] = time.time()
        snapshot = copy.deepcopy(job)
        _series_plan_store(str(job["workspace"])).save(snapshot)
        publisher = globals().get("_publish_series_task")
        if callable(publisher):
            try:
                publisher(snapshot, "series-plan")
            except Exception as exc:
                print(f"[Task registry] Could not publish Series plan {job_id}: {exc}")
        return snapshot

def _series_plan_request(body: dict, series: dict, episode: dict) -> dict:
    """Freeze planning inputs while excluding media and render history."""
    from services.series_library import series_for_episode_snapshot

    series_snapshot = series_for_episode_snapshot(series, episode)
    series_snapshot.pop("assets", None)
    prior_episode_summaries = []
    current_number = int(episode.get("number") or 0)
    for previous in sorted(
        (
            item for item in series.get("episodesById", {}).values()
            if isinstance(item, dict)
            and item.get("id") != episode.get("id")
            and int(item.get("number") or 0) < current_number
        ),
        key=lambda item: int(item.get("number") or 0),
    )[-12:]:
        outline = previous.get("outline") if isinstance(previous.get("outline"), dict) else {}
        prior_episode_summaries.append({
            "id": previous.get("id"),
            "number": previous.get("number"),
            "title": previous.get("title"),
            "logline": previous.get("logline"),
            "status": previous.get("status"),
            "outlineBeats": [
                str(value)[:500] for value in outline.get("beats", [])[:8]
                if isinstance(value, str) and value.strip()
            ],
        })
    series_snapshot["episodesById"] = {}
    series_snapshot["priorEpisodeSummaries"] = prior_episode_summaries
    episode_snapshot = copy.deepcopy(episode)
    for shot in episode_snapshot.get("shots", []):
        if isinstance(shot, dict):
            shot.pop("attempts", None)
            shot.pop("referenceManifest", None)
    return {
        "scope": str(body.get("scope") or "complete"),
        "instruction": str(body.get("instruction") or "")[:8000],
        "writingProvider": str(body.get("writingProvider") or series.get("provider", {}).get("writingProvider") or "maestro"),
        "writingModel": str(body.get("writingModel") or series.get("provider", {}).get("writingModel") or ""),
        "writingBaseUrl": str(body.get("writingBaseUrl") or series.get("provider", {}).get("writingBaseUrl") or ""),
        "seriesSnapshot": series_snapshot,
        "episodeSnapshot": episode_snapshot,
    }

def _run_series_plan_job_inner(job_id: str) -> None:
    from services.series_planning import (
        apply_planning_stage,
        normalize_planning_result,
        planning_output_token_budget,
        planning_prompt,
        planning_schema,
        planning_stages,
    )

    job = _load_series_plan_job(job_id)
    if not job:
        return
    if job.get("status") in {"cancelling", "cancelled"}:
        return
    request = copy.deepcopy(job.get("request") or {})
    series = request.get("seriesSnapshot") if isinstance(request.get("seriesSnapshot"), dict) else {}
    episode = request.get("episodeSnapshot") if isinstance(request.get("episodeSnapshot"), dict) else {}
    completed = job.get("completedStages") if isinstance(job.get("completedStages"), dict) else {}
    try:
        stages = planning_stages(str(request.get("scope") or "complete"))
        llm_override = _comic_writing_llm(request)
        if not llm_override:
            _ensure_llm_loaded()
        for index, stage in enumerate(stages):
            latest = _load_series_plan_job(job_id)
            if latest and latest.get("status") in {"cancelling", "cancelled"}:
                return
            if stage in completed:
                result = normalize_planning_result(stage, completed[stage], series, episode)
            else:
                _series_plan_update(
                    job_id, status="running", stage=stage, current=index, total=len(stages),
                    message=f"Generating Series Lab {stage.replace('_', ' ')}…",
                )
                prompt, system_prompt = planning_prompt(
                    stage, series, episode, str(request.get("instruction") or ""),
                )
                raw = _generate_comic_director_json(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    schema=planning_schema(stage, episode),
                    # Long episodes need proportionally more independent
                    # 5/10/15-second clips; keep enough output room for their
                    # complete structured shot records.
                    max_new_tokens=planning_output_token_budget(stage, episode),
                    stage=f"Series Lab {stage}",
                    llm_override=llm_override,
                )
                # JSON-schema support differs between providers. A response can
                # be valid JSON yet still violate a cross-field production rule
                # such as "every speaker is visible" or the single-speaker clip
                # limit. Give the writing model two bounded, evidence-rich
                # semantic repair passes instead of throwing away all earlier
                # durable stages after the first invalid response.
                semantic_error = None
                for repair_attempt in range(3):
                    try:
                        result = normalize_planning_result(stage, raw, series, episode)
                        semantic_error = None
                        break
                    except ValueError as exc:
                        semantic_error = exc
                        if repair_attempt >= 2:
                            raise
                        previous_response = json.dumps(
                            raw, ensure_ascii=False, separators=(",", ":"), default=str,
                        )
                        previous_limit = min(
                            250000,
                            planning_output_token_budget(stage, episode) * 4,
                        )
                        if len(previous_response) > previous_limit:
                            previous_response = (
                                previous_response[:previous_limit]
                                + "\n[previous response truncated for bounded Series Lab repair]"
                            )
                        _series_plan_update(
                            job_id,
                            status="running",
                            stage=stage,
                            current=index,
                            total=len(stages),
                            validationAttempt=repair_attempt + 1,
                            validationError=str(exc),
                            message=(
                                f"Repairing Series Lab {stage.replace('_', ' ')} "
                                f"({repair_attempt + 1}/2): {exc}"
                            ),
                        )
                        repair_prompt = (
                            f"{prompt}\n\nSERIES STAGE VALIDATION REPAIR: The previous response "
                            f"failed this production rule: {exc}. Preserve all valid story facts and "
                            "dialogue, but correct the smallest necessary structure. For a shot with "
                            "more than one actual dialogue speaker, distribute every speaker turn across "
                            "separate single-speaker shots. Keep the duration-aware shot count stated above; "
                            "use only 5, 10, or 15 seconds and never exceed 15 seconds. "
                            "speakingCharacterIds must "
                            "equal the unique characterId values in dialogueBeats, not every visible "
                            "participant. Return exactly one complete JSON object matching the schema.\n"
                            f"PREVIOUS RESPONSE TO REPAIR:\n{previous_response}"
                        )
                        raw = _generate_comic_director_json(
                            prompt=repair_prompt,
                            system_prompt=system_prompt,
                            schema=planning_schema(stage, episode),
                            max_new_tokens=planning_output_token_budget(stage, episode),
                            stage=f"Series Lab {stage} validation repair {repair_attempt + 1}",
                            llm_override=llm_override,
                        )
                        latest = _load_series_plan_job(job_id)
                        if latest and latest.get("status") in {"cancelling", "cancelled"}:
                            return
                if semantic_error is not None:  # pragma: no cover - loop raises first
                    raise semantic_error
                latest = _load_series_plan_job(job_id)
                if latest and latest.get("status") in {"cancelling", "cancelled"}:
                    return
                completed[stage] = result
            episode = apply_planning_stage(episode, stage, result)
            _series_plan_update(
                job_id, completedStages=completed, episodeResult=episode,
                current=index + 1, stage=stage, validationAttempt=0, validationError=None,
            )
        _series_plan_update(
            job_id, status="completed", stage="completed", current=len(stages), total=len(stages),
            message="Episode proposal generated. Review and apply it when ready.",
            result={"episode": episode}, error=None, finishedAt=time.time(),
        )
    except Exception as exc:
        latest = _load_series_plan_job(job_id)
        if latest and latest.get("status") in {"cancelling", "cancelled"}:
            outcome = _llm_abort_outcome(exc)
            if latest.get("status") == "cancelling" and outcome is not None:
                _series_plan_update(
                    job_id,
                    status="cancelling",
                    cancellationAbortSupported=outcome,
                    message=_planning_cancel_message("Series planning", outcome),
                )
            return
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        _series_plan_update(
            job_id, status="failed", error=str(detail), finishedAt=time.time(),
            message="Episode planning stopped. Completed stages remain recoverable.",
        )

def _apply_series_canon_proposal(job: dict, proposal: dict) -> dict:
    """Apply a durable canon proposal while preserving user-owned assets and runtime state."""
    from services.series_planning import merge_series_canon_proposal

    workspace = str(job["workspace"])
    series_id = str(job["seriesId"])
    bootstrap_known_series = job.get("bootstrapKnownSeries") is True
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
        if int(series.get("revision") or 1) != int(job.get("sourceSeriesRevision") or 1):
            raise HTTPException(
                status_code=409,
                detail="The series was edited after canon preparation started. Review the saved proposal instead of overwriting it.",
            )
        series = merge_series_canon_proposal(
            series, proposal, bootstrap_known_series=bootstrap_known_series,
        )
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = now
        library["seriesById"][series_id] = series
        stored = _write_series_workspace(workspace, library)
    return stored["seriesById"][series_id]

def _run_series_canon_plan_job_inner(job_id: str) -> None:
    from services.series_planning import (
        canon_preparation_prompt,
        canon_preparation_schema,
        known_series_bootstrap_prompt,
        known_series_bootstrap_schema,
        normalize_canon_preparation,
        normalize_known_series_bootstrap,
    )

    job = _load_series_plan_job(job_id)
    if not job:
        return
    if job.get("status") in {"cancelling", "cancelled"}:
        return
    request = copy.deepcopy(job.get("request") or {})
    series = request.get("seriesSnapshot") if isinstance(request.get("seriesSnapshot"), dict) else {}
    try:
        llm_override = _comic_writing_llm(request)
        if not llm_override:
            _ensure_llm_loaded()
        bootstrap_known_series = job.get("bootstrapKnownSeries") is True
        _series_plan_update(
            job_id, status="running", stage="known_series_research" if bootstrap_known_series else "canon",
            current=0, total=1,
            message=(
                "Building an editable known-series bible from the writing model's general knowledge…"
                if bootstrap_known_series else "Preparing a reviewable Series canon proposal…"
            ),
        )
        if bootstrap_known_series:
            prompt, system_prompt = known_series_bootstrap_prompt(
                series, str(request.get("instruction") or ""),
            )
            schema = known_series_bootstrap_schema()
            max_new_tokens = 14000
            stage_label = "Series Lab known-series bootstrap"
        else:
            prompt, system_prompt = canon_preparation_prompt(
                series, str(request.get("instruction") or ""),
            )
            schema = canon_preparation_schema()
            max_new_tokens = 6000
            stage_label = "Series Lab canon preparation"
        raw = _generate_comic_director_json(
            prompt=prompt, system_prompt=system_prompt,
            schema=schema, max_new_tokens=max_new_tokens,
            stage=stage_label, llm_override=llm_override,
        )
        latest = _load_series_plan_job(job_id)
        if latest and latest.get("status") in {"cancelling", "cancelled"}:
            return
        proposal = (
            normalize_known_series_bootstrap(raw, series)
            if bootstrap_known_series else normalize_canon_preparation(raw, series)
        )
        if bootstrap_known_series and job.get("autoApply") is True:
            _series_plan_update(
                job_id, stage="applying_draft", seriesResult=proposal,
                result={"seriesProposal": proposal},
                message="Known-series bible generated; applying it as an editable draft…",
            )
            latest = _load_series_plan_job(job_id)
            if latest and latest.get("status") in {"cancelling", "cancelled"}:
                return
            try:
                applied = _apply_series_canon_proposal(job, proposal)
            except (HTTPException, ValueError) as exc:
                # An HTTPException is "the series moved on"; a ValueError is the library refusing the draft
                # (validate_series_ids, a revision conflict). The proposal stays reviewable either way.
                moved_on = isinstance(exc, HTTPException)
                _series_plan_update(
                    job_id, status="completed", stage="completed", current=1, total=1,
                    autoApplied=False, applyError=str(exc.detail if moved_on else exc), error=None,
                    message=("Known-series proposal generated, but the project changed before it could be applied."
                             if moved_on else
                             "Known-series proposal generated, but the library could not be applied as a draft; review the proposal."),
                    finishedAt=time.time(),
                )
                return
            _series_plan_update(
                job_id, status="completed", stage="completed", current=1, total=1,
                autoApplied=True, appliedSeriesRevision=int(applied.get("revision") or 1),
                appliedAt=time.time(), error=None,
                message="Known-series bible filled as a draft. Verify facts and approve canon when ready.",
                finishedAt=time.time(),
            )
            return
        _series_plan_update(
            job_id, status="completed", stage="completed", current=1, total=1,
            seriesResult=proposal, result={"seriesProposal": proposal}, error=None,
            message="Canon proposal generated. Review it before applying.",
            finishedAt=time.time(),
        )
    except Exception as exc:
        latest = _load_series_plan_job(job_id)
        if latest and latest.get("status") in {"cancelling", "cancelled"}:
            outcome = _llm_abort_outcome(exc)
            if latest.get("status") == "cancelling" and outcome is not None:
                _series_plan_update(
                    job_id,
                    status="cancelling",
                    cancellationAbortSupported=outcome,
                    message=_planning_cancel_message("Canon preparation", outcome),
                )
            return
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        _series_plan_update(
            job_id, status="failed", error=str(detail), finishedAt=time.time(),
            message="Canon preparation stopped. Its checkpoint remains recoverable.",
        )

def _run_series_plan_job(job_id: str) -> None:
    with _series_plan_jobs_lock:
        if job_id in _series_plan_active_jobs:
            return
        _series_plan_active_jobs.add(job_id)
    try:
        job = _load_series_plan_job(job_id)
        task = _publish_series_task(job, "series-plan") if job else None
        if task:
            from services.task_manager import task_context_scope
            scope = task_context_scope(
                task_id=task["id"], root_id=task["root_id"],
                workspace=str(job.get("workspace") or "default"),
                workspace_dir=_workspace_dir(str(job.get("workspace") or "default")),
            )
        else:
            from contextlib import nullcontext
            scope = nullcontext()
        with scope:
            if job and job.get("jobType") == "canon":
                _run_series_canon_plan_job_inner(job_id)
            else:
                _run_series_plan_job_inner(job_id)
    finally:
        with _series_plan_jobs_lock:
            _series_plan_active_jobs.discard(job_id)
        settling = _load_series_plan_job(job_id) or {}
        if settling.get("status") == "cancelling":
            _series_plan_update(
                job_id,
                status="cancelled",
                stage="cancelled",
                finishedAt=time.time(),
                message=_planning_cancel_message(
                    "Series planning",
                    settling.get("cancellationAbortSupported")
                    if isinstance(settling.get("cancellationAbortSupported"), bool)
                    else None,
                ),
            )

def _prepare_edited_series_episode_proposal(stored: dict, edited: dict | None, series: dict) -> dict:
    """Merge reviewable fields while keeping generated identities and protected state authoritative."""
    if edited is None:
        return copy.deepcopy(stored)
    if not isinstance(edited, dict):
        raise ValueError("Edited episode proposal must be an object")
    if edited.get("id") not in {None, "", stored.get("id")}:
        raise ValueError("Edited episode proposal id does not match the generated proposal")

    proposed = copy.deepcopy(stored)
    outline = edited.get("outline")
    beats = outline.get("beats") if isinstance(outline, dict) else None
    if not isinstance(beats, list) or any(not isinstance(beat, str) for beat in beats):
        raise ValueError("Edited outline beats must be text values")
    proposed["outline"] = {"beats": copy.deepcopy(beats)}

    def merge_identified(original_items, edited_items, label, editable_keys, *, ordered=False):
        if not isinstance(original_items, list) or not isinstance(edited_items, list):
            raise ValueError(f"Edited {label} must be a list")
        original_ids = [str(item.get("id") or "") for item in original_items if isinstance(item, dict)]
        edited_by_id = {
            str(item.get("id") or ""): item for item in edited_items if isinstance(item, dict)
        }
        if (
            len(original_ids) != len(original_items)
            or len(edited_by_id) != len(edited_items)
            or set(original_ids) != set(edited_by_id)
        ):
            raise ValueError(f"Edited {label} cannot add, remove, duplicate, or replace internal IDs")
        merged = []
        for index, original in enumerate(original_items):
            item = copy.deepcopy(original)
            revision = edited_by_id[str(original["id"])]
            for key in editable_keys:
                if key in revision:
                    item[key] = copy.deepcopy(revision[key])
            item["id"] = original["id"]
            if ordered:
                item["order"] = index + 1
            merged.append(item)
        return merged

    scene_keys = (
        "locationId", "locationVariantId", "time", "participatingCharacterIds", "purpose",
        "entryState", "exitState", "beats", "dialogue",
    )
    proposed["script"] = merge_identified(
        stored.get("script"), edited.get("script"), "script scenes", scene_keys, ordered=True,
    )
    for original_scene, scene in zip(stored.get("script", []), proposed["script"]):
        scene["beats"] = merge_identified(
            original_scene.get("beats"), scene.get("beats"), "scene beats", ("kind", "summary"),
        )
        scene["dialogue"] = merge_identified(
            original_scene.get("dialogue"), scene.get("dialogue"), "scene dialogue", ("characterId", "text", "emotion", "delivery"),
        )

    shot_keys = (
        "sceneId", "durationSeconds", "framing", "camera", "action", "dialogueBeats",
        "visibleCharacterIds", "locationId", "locationVariantId", "wardrobeByCharacterId",
        "propIds", "emotionalStateByCharacterId", "continuityFromShotId", "renderStrategy",
        "referencePolicy", "prompt", "negativePrompt", "audioDirection",
    )
    proposed["shots"] = merge_identified(
        stored.get("shots"), edited.get("shots"), "shots", shot_keys, ordered=True,
    )
    for original_shot, shot in zip(stored.get("shots", []), proposed["shots"]):
        shot["dialogueBeats"] = merge_identified(
            original_shot.get("dialogueBeats"), shot.get("dialogueBeats"), "shot dialogue", ("characterId", "text", "emotion", "delivery"),
        )

    character_ids = {str(item.get("id")) for item in series.get("characters", []) if isinstance(item, dict)}
    location_ids = {str(item.get("id")) for item in series.get("locations", []) if isinstance(item, dict)}
    scene_ids = {str(item["id"]) for item in proposed["script"]}
    shot_ids = {str(item["id"]) for item in proposed["shots"]}
    for scene in proposed["script"]:
        if scene.get("locationId") not in location_ids:
            raise ValueError(f"Scene {scene['id']} uses an unknown location")
        dialogue_speakers = []
        for line in scene["dialogue"]:
            character_id = str(line.get("characterId") or "")
            if character_id not in character_ids:
                raise ValueError(f"Scene {scene['id']} dialogue uses an unknown character")
            if character_id not in dialogue_speakers:
                dialogue_speakers.append(character_id)
        scene["participatingCharacterIds"] = list(dict.fromkeys([
            *[str(item) for item in scene.get("participatingCharacterIds", []) if str(item) in character_ids],
            *dialogue_speakers,
        ]))
    for shot in proposed["shots"]:
        if shot.get("sceneId") not in scene_ids:
            raise ValueError(f"Shot {shot['id']} uses an unknown scene")
        if shot.get("locationId") and shot.get("locationId") not in location_ids:
            raise ValueError(f"Shot {shot['id']} uses an unknown location")
        try:
            duration_value = float(shot.get("durationSeconds"))
            if not math.isfinite(duration_value) or duration_value <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"Shot {shot['id']} duration must be a positive number")
        continuity_id = str(shot.get("continuityFromShotId") or "")
        if continuity_id and continuity_id not in shot_ids:
            raise ValueError(f"Shot {shot['id']} references an unknown continuity shot")
        visible = list(dict.fromkeys(
            str(item) for item in shot.get("visibleCharacterIds", []) if str(item) in character_ids
        ))
        dialogue_speakers = []
        for line in shot["dialogueBeats"]:
            character_id = str(line.get("characterId") or "")
            if character_id not in character_ids:
                raise ValueError(f"Shot {shot['id']} dialogue uses an unknown character")
            if character_id not in visible:
                visible.append(character_id)
            if character_id not in dialogue_speakers:
                dialogue_speakers.append(character_id)
        if len(dialogue_speakers) > 1:
            raise ValueError(f"Shot {shot['id']} must contain dialogue from only one speaker")
        shot["visibleCharacterIds"] = visible
        shot["speakingCharacterIds"] = dialogue_speakers
        shot["primarySpeakerId"] = dialogue_speakers[0] if dialogue_speakers else ""

    from services.series_render import apply_series_shot_duration
    for shot in proposed["shots"]:
        apply_series_shot_duration(series, shot)

    edited_delta = edited.get("proposedCanonDelta")
    stored_delta = stored.get("proposedCanonDelta")
    if not isinstance(edited_delta, dict) or not isinstance(stored_delta, dict):
        raise ValueError("Edited canon delta must be an object")
    delta = copy.deepcopy(stored_delta)
    for key in ("add", "change"):
        delta[key] = merge_identified(
            stored_delta.get(key), edited_delta.get(key), f"canon {key}", ("description", "decision"),
        )
    # Retire entries use factId rather than id; only their decision is reviewable.
    stored_retire = stored_delta.get("retire") if isinstance(stored_delta.get("retire"), list) else []
    edited_retire = edited_delta.get("retire") if isinstance(edited_delta.get("retire"), list) else []
    edited_retire_by_id = {str(item.get("factId") or ""): item for item in edited_retire if isinstance(item, dict)}
    if len(edited_retire_by_id) != len(stored_retire) or {
        str(item.get("factId") or "") for item in stored_retire
    } != set(edited_retire_by_id):
        raise ValueError("Edited canon retire list cannot change internal fact IDs")
    delta["retire"] = [
        {**copy.deepcopy(item), "decision": edited_retire_by_id[str(item.get("factId") or "")].get("decision", item.get("decision"))}
        for item in stored_retire
    ]
    proposed["proposedCanonDelta"] = delta
    proposed["continuityIssues"] = copy.deepcopy(stored.get("continuityIssues"))
    return proposed

"""Series Lab planning jobs on the core/remote profile. Uses the remote LLM."""
from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from services import core_workspace as core
from services.series_jobs import SeriesJobStore
from services.series_library import (
    read_series_library,
    series_for_episode_snapshot,
    write_series_library,
)
from services.series_planning import (
    apply_planning_stage,
    canon_preparation_prompt,
    canon_preparation_schema,
    known_series_bootstrap_prompt,
    known_series_bootstrap_schema,
    merge_series_canon_proposal,
    normalize_canon_preparation,
    normalize_known_series_bootstrap,
    normalize_planning_result,
    planning_output_token_budget,
    planning_prompt,
    planning_schema,
    planning_stages,
)

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_ACTIVE: set[str] = set()
_PUBLIC = (
    "jobId", "jobType", "kind", "workspace", "seriesId", "episodeId",
    "status", "stage", "current", "total", "message", "completedStages",
    "episodeResult", "seriesResult", "generateImages", "bootstrapKnownSeries",
    "autoApply", "autoApplied", "appliedSeriesRevision", "applyError",
    "result", "error", "createdAt", "updatedAt",
    "finishedAt", "appliedAt", "taskId", "rootTaskId",
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _store(workspace: str) -> SeriesJobStore:
    return SeriesJobStore(core.workspace_dir(workspace), "planning")


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(job.get(key)) for key in _PUBLIC if key in job}


def _patch(job_id: str, **fields: Any) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        job.update(fields)
        job["updatedAt"] = time.time()
        snapshot = copy.deepcopy(job)
        _store(str(job["workspace"])).save(snapshot)
        return snapshot


def load_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        cached = _JOBS.get(job_id)
        if cached:
            return copy.deepcopy(cached)
    for workspace in [row["name"] for row in core.list_workspaces()]:
        try:
            job = _store(workspace).load(job_id)
        except ValueError:
            continue
        if job:
            with _LOCK:
                _JOBS[job_id] = job
            return copy.deepcopy(job)
    return None


def _parse_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The writing model did not return a JSON object")
    payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("The writing model did not return a JSON object")
    return payload


def _generate_json(*, prompt: str, system_prompt: str, schema: dict, max_new_tokens: int, override: dict | None) -> dict:
    from services import llm_service
    from services.core_production import ensure_llm_loaded

    arguments = dict(
        prompt=prompt, system_prompt=system_prompt, json_schema=schema,
        max_new_tokens=max_new_tokens, temperature=0.2,
    )
    if override:
        raw = llm_service.generate_openai_compatible(
            **arguments, model_id=override["model"], base_url=override["base_url"], api_key=override["api_key"],
        )
    else:
        ensure_llm_loaded()
        raw = llm_service.generate(**arguments)
    return _parse_json(raw)


def _writing_override(request: dict) -> dict | None:
    from services.core_production import comic_writing_llm
    return comic_writing_llm(request)


def _series_or_404(workspace: str, series_id: str) -> dict:
    library = read_series_library(core.workspace_dir(workspace), workspace)
    series = library.get("seriesById", {}).get(series_id)
    if not isinstance(series, dict):
        raise KeyError("Series Lab project not found")
    return series, library


def _writing_fields(body: dict[str, Any], series: dict[str, Any]) -> dict[str, str]:
    provider = series.get("provider") if isinstance(series.get("provider"), dict) else {}
    return {
        "writingProvider": str(body.get("writingProvider") or provider.get("writingProvider") or "maestro"),
        "writingModel": str(body.get("writingModel") or provider.get("writingModel") or ""),
        "writingBaseUrl": str(body.get("writingBaseUrl") or provider.get("writingBaseUrl") or ""),
    }


def start_episode_plan(series_id: str, episode_id: str, body: dict[str, Any]) -> dict[str, Any]:
    workspace = str(body.get("workspace") or core.active_workspace() or "default")
    scope = str(body.get("scope") or "complete")
    stages = planning_stages(scope)
    with _LOCK:
        series, _library = _series_or_404(workspace, series_id)
        episode = series.get("episodesById", {}).get(episode_id)
        if not isinstance(episode, dict):
            raise KeyError("Series episode not found")
        if not str(episode.get("premise") or body.get("instruction") or "").strip():
            raise ValueError("Write an episode premise or instruction first")
        snapshot = series_for_episode_snapshot(series, episode)
        snapshot.pop("assets", None)
        snapshot["episodesById"] = {}
        request = {
            "scope": scope,
            "instruction": str(body.get("instruction") or "")[:8000],
            **_writing_fields(body, series),
            "seriesSnapshot": snapshot,
            "episodeSnapshot": copy.deepcopy(episode),
        }
    _writing_override(request)
    job_id = f"series-plan-{uuid.uuid4().hex[:12]}"
    now = time.time()
    job = {
        "jobId": job_id, "kind": "planning", "workspace": workspace,
        "seriesId": series_id, "episodeId": episode_id,
        "status": "queued", "stage": "queued", "current": 0, "total": len(stages),
        "message": "Episode planning queued.", "request": request,
        "sourceSeriesRevision": int(series.get("revision") or 1),
        "sourceEpisodeUpdatedAt": episode.get("updatedAt"),
        "completedStages": {}, "episodeResult": None, "result": None, "error": None,
        "createdAt": now, "updatedAt": now, "taskId": f"task-{job_id}", "rootTaskId": f"task-{job_id}",
    }
    with _LOCK:
        _JOBS[job_id] = job
        _store(workspace).save(job)
    threading.Thread(target=_run_episode, args=(job_id,), daemon=True).start()
    return _public(job)


def start_canon_plan(series_id: str, body: dict[str, Any]) -> dict[str, Any]:
    workspace = str(body.get("workspace") or core.active_workspace() or "default")
    instruction = str(body.get("instruction") or "").strip()[:8000]
    bootstrap = body.get("bootstrapKnownSeries") is True
    if bootstrap and len(instruction) < 3:
        raise ValueError("Describe the known series you want to continue")
    with _LOCK:
        series, _library = _series_or_404(workspace, series_id)
        snapshot = copy.deepcopy(series)
        snapshot.pop("assets", None)
        snapshot["episodesById"] = {}
        request = {
            "instruction": instruction,
            **_writing_fields(body, series),
            "seriesSnapshot": snapshot,
            "bootstrapKnownSeries": bootstrap,
            "autoApply": bootstrap and body.get("autoApply") is not False,
        }
    _writing_override(request)
    job_id = f"series-canon-{uuid.uuid4().hex[:12]}"
    now = time.time()
    job = {
        "jobId": job_id, "jobType": "canon", "kind": "planning",
        "workspace": workspace, "seriesId": series_id, "episodeId": "",
        "status": "queued", "stage": "queued", "current": 0, "total": 1,
        "message": "Canon preparation queued.", "request": request,
        "sourceSeriesRevision": int(series.get("revision") or 1),
        "seriesResult": None, "result": None, "error": None,
        "bootstrapKnownSeries": bootstrap, "autoApply": request["autoApply"], "autoApplied": False,
        "createdAt": now, "updatedAt": now, "taskId": f"task-{job_id}", "rootTaskId": f"task-{job_id}",
    }
    with _LOCK:
        _JOBS[job_id] = job
        _store(workspace).save(job)
    threading.Thread(target=_run_canon, args=(job_id,), daemon=True).start()
    return _public(job)


def cancel_job(job_id: str) -> dict[str, Any]:
    job = load_job(job_id)
    if not job:
        raise KeyError("Series planning job not found")
    if job.get("status") in {"completed", "failed", "cancelled"}:
        return _public(job)
    with _LOCK:
        worker = job_id in _ACTIVE
    updated = _patch(
        job_id,
        status="cancelling" if worker else "cancelled",
        stage="cancelling" if worker else "cancelled",
        finishedAt=None if worker else time.time(),
        message="Series planning cancellation requested." if worker else "Series planning cancelled.",
    )
    return _public(updated or job)


def resume_job(job_id: str) -> dict[str, Any]:
    job = load_job(job_id)
    if not job:
        raise KeyError("Series planning job not found")
    if job.get("status") == "completed":
        return _public(job)
    with _LOCK:
        if job_id in _ACTIVE:
            return _public(job)
    _patch(job_id, status="queued", error=None, finishedAt=None, message="Resuming planning…")
    target = _run_canon if job.get("jobType") == "canon" else _run_episode
    threading.Thread(target=target, args=(job_id,), daemon=True).start()
    return _public(load_job(job_id) or job)


def apply_episode(job_id: str, edited: dict | None) -> dict[str, Any]:
    job = load_job(job_id)
    if not job:
        raise KeyError("Series planning job not found")
    if job.get("jobType") == "canon":
        raise ValueError("Use the canon proposal apply endpoint for this job")
    if job.get("status") != "completed" or not isinstance(job.get("episodeResult"), dict):
        raise ValueError("Complete the planning job before applying it")
    workspace, series_id, episode_id = str(job["workspace"]), str(job["seriesId"]), str(job["episodeId"])
    with _LOCK:
        series, library = _series_or_404(workspace, series_id)
        current = series.get("episodesById", {}).get(episode_id)
        if not isinstance(current, dict):
            raise KeyError("Series episode not found")
        if current.get("updatedAt") != job.get("sourceEpisodeUpdatedAt"):
            raise PermissionError("The episode was edited after planning started")
        proposed = copy.deepcopy(edited if isinstance(edited, dict) else job["episodeResult"])
        proposed["id"] = episode_id
        proposed["updatedAt"] = _iso_now()
        proposed["createdAt"] = current.get("createdAt")
        series = copy.deepcopy(series)
        series["episodesById"][episode_id] = proposed
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = proposed["updatedAt"]
        library["seriesById"][series_id] = series
        stored = write_series_library(core.workspace_dir(workspace), library, workspace)
    _patch(job_id, appliedAt=time.time(), message="Episode proposal applied for review.")
    return stored["seriesById"][series_id]["episodesById"][episode_id]


def _commit_canon_proposal(job: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    workspace, series_id = str(job["workspace"]), str(job["seriesId"])
    with _LOCK:
        series, library = _series_or_404(workspace, series_id)
        if int(series.get("revision") or 1) != int(job.get("sourceSeriesRevision") or 1):
            raise PermissionError("The series was edited after canon preparation started")
        series = merge_series_canon_proposal(
            copy.deepcopy(series), proposal, bootstrap_known_series=job.get("bootstrapKnownSeries") is True,
        )
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = _iso_now()
        library["seriesById"][series_id] = series
        stored = write_series_library(core.workspace_dir(workspace), library, workspace)
    return stored["seriesById"][series_id]


def apply_canon(job_id: str) -> dict[str, Any]:
    job = load_job(job_id)
    if not job:
        raise KeyError("Series canon planning job not found")
    proposal = job.get("seriesResult")
    if job.get("jobType") != "canon" or job.get("status") != "completed" or not isinstance(proposal, dict):
        raise ValueError("Complete the canon preparation job before applying it")
    stored = _commit_canon_proposal(job, proposal)
    _patch(job_id, appliedAt=time.time(), message="Canon proposal applied as a draft for review.")
    return stored


def _run_episode(job_id: str) -> None:
    with _LOCK:
        _ACTIVE.add(job_id)
    try:
        job = load_job(job_id) or {}
        request = copy.deepcopy(job.get("request") or {})
        series = request.get("seriesSnapshot") if isinstance(request.get("seriesSnapshot"), dict) else {}
        episode = request.get("episodeSnapshot") if isinstance(request.get("episodeSnapshot"), dict) else {}
        completed = job.get("completedStages") if isinstance(job.get("completedStages"), dict) else {}
        stages = planning_stages(str(request.get("scope") or "complete"))
        override = _writing_override(request)
        for index, stage in enumerate(stages):
            latest = load_job(job_id) or {}
            if latest.get("status") in {"cancelling", "cancelled"}:
                _patch(job_id, status="cancelled", stage="cancelled", finishedAt=time.time())
                return
            if stage not in completed:
                _patch(job_id, status="running", stage=stage, current=index, total=len(stages),
                       message=f"Generating Series Lab {stage.replace('_', ' ')}…")
                prompt, system_prompt = planning_prompt(stage, series, episode, str(request.get("instruction") or ""))
                raw = _generate_json(
                    prompt=prompt, system_prompt=system_prompt,
                    schema=planning_schema(stage, episode),
                    max_new_tokens=planning_output_token_budget(stage, episode),
                    override=override,
                )
                completed[stage] = normalize_planning_result(stage, raw, series, episode)
            episode = apply_planning_stage(episode, stage, completed[stage])
            _patch(job_id, completedStages=completed, episodeResult=episode, current=index + 1, stage=stage)
        _patch(
            job_id, status="completed", stage="completed", current=len(stages), total=len(stages),
            message="Episode proposal generated. Review and apply it when ready.",
            result={"episode": episode}, error=None, finishedAt=time.time(),
        )
    except Exception as exc:
        _patch(job_id, status="failed", error=str(exc), finishedAt=time.time(),
               message="Episode planning stopped. Completed stages remain recoverable.")
    finally:
        with _LOCK:
            _ACTIVE.discard(job_id)


def _run_canon(job_id: str) -> None:
    with _LOCK:
        _ACTIVE.add(job_id)
    try:
        job = load_job(job_id) or {}
        request = copy.deepcopy(job.get("request") or {})
        series = request.get("seriesSnapshot") if isinstance(request.get("seriesSnapshot"), dict) else {}
        latest = load_job(job_id) or {}
        if latest.get("status") in {"cancelling", "cancelled"}:
            _patch(job_id, status="cancelled", stage="cancelled", finishedAt=time.time())
            return
        bootstrap = job.get("bootstrapKnownSeries") is True
        _patch(
            job_id, status="running",
            stage="known_series_research" if bootstrap else "canon",
            current=0, total=1,
            message=(
                "Building an editable known-series bible from the writing model's general knowledge…"
                if bootstrap else "Preparing a reviewable Series canon proposal…"
            ),
        )
        if bootstrap:
            prompt, system_prompt = known_series_bootstrap_prompt(
                series, str(request.get("instruction") or ""),
            )
            schema = known_series_bootstrap_schema()
            max_new_tokens = 14000
        else:
            prompt, system_prompt = canon_preparation_prompt(
                series, str(request.get("instruction") or ""),
            )
            schema = canon_preparation_schema()
            max_new_tokens = 6000
        raw = _generate_json(
            prompt=prompt, system_prompt=system_prompt, schema=schema,
            max_new_tokens=max_new_tokens, override=_writing_override(request),
        )
        latest = load_job(job_id) or {}
        if latest.get("status") in {"cancelling", "cancelled"}:
            _patch(job_id, status="cancelled", stage="cancelled", finishedAt=time.time())
            return
        proposal = (
            normalize_known_series_bootstrap(raw, series)
            if bootstrap else normalize_canon_preparation(raw, series)
        )
        if bootstrap and job.get("autoApply") is True:
            _patch(
                job_id, stage="applying_draft", seriesResult=proposal,
                result={"seriesProposal": proposal},
                message="Known-series bible generated; applying it as an editable draft…",
            )
            latest = load_job(job_id) or {}
            if latest.get("status") in {"cancelling", "cancelled"}:
                _patch(job_id, status="cancelled", stage="cancelled", finishedAt=time.time())
                return
            try:
                applied = _commit_canon_proposal(job, proposal)
            except (PermissionError, ValueError, KeyError) as exc:
                _patch(
                    job_id, status="completed", stage="completed", current=1, total=1,
                    autoApplied=False, applyError=str(exc), error=None,
                    seriesResult=proposal, result={"seriesProposal": proposal},
                    message="Known-series proposal generated, but the project changed before it could be applied.",
                    finishedAt=time.time(),
                )
                return
            _patch(
                job_id, status="completed", stage="completed", current=1, total=1,
                autoApplied=True, appliedSeriesRevision=int(applied.get("revision") or 1),
                appliedAt=time.time(), error=None, seriesResult=proposal,
                result={"seriesProposal": proposal},
                message="Known-series bible filled as a draft. Verify facts and approve canon when ready.",
                finishedAt=time.time(),
            )
            return
        _patch(
            job_id, status="completed", stage="completed", current=1, total=1,
            seriesResult=proposal, result={"seriesProposal": proposal}, error=None,
            message="Canon proposal generated. Review it before applying.",
            finishedAt=time.time(),
        )
    except Exception as exc:
        _patch(job_id, status="failed", error=str(exc), finishedAt=time.time(),
               message="Canon preparation stopped.")
    finally:
        with _LOCK:
            _ACTIVE.discard(job_id)

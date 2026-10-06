"""HTTP for reading and editing one Series shot by id or number (services/series_shot_edit.py).

``series.shot.get`` and ``series.shot.update`` (MCP) and the Wizard's
``edit_series_shot`` action call these routes.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from routers.series_produce import workspace_files
from services.series_shot_edit import (
    ShotEditError, apply_edit, build_patch, find_shot, merge_changes, take_still_fits, to_script,
)
from services.series_shot_instruction import context, plan_edit
from services.series_video_foley import VIDEO_METHODS, wants_video_foley


class ShotEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    shot: str | int
    changes: dict[str, Any] | None = None
    append: dict[str, Any] | None = None
    instruction: str | None = Field(default=None, max_length=2000)
    check: bool = False
    render: bool = False
    approve: bool = True
    produce: bool = False
    # Series Lab merges the edit into its open copy: the stored shot, the episode's review and language versions.
    stored: bool = False


def _takes(shot: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": item.get("id"), "status": item.get("status"), "approved": item.get("id") == shot.get("approvedAttemptId")}
            for item in shot.get("attempts") or [] if isinstance(item, dict)]


def shot_view(series: dict[str, Any], episode: dict[str, Any], shot: dict[str, Any], number: int) -> dict[str, Any]:
    """One shot as an agent edits it: its id, number, method, takes and its content in the script vocabulary."""
    return {"shotId": shot["id"], "number": number, "productionMethod": shot.get("productionMethod"),
            "approvedAttemptId": shot.get("approvedAttemptId"), "takes": _takes(shot),
            "script": to_script(series, episode, shot)}


def _tool(call: Callable[[str, dict], dict], name: str, data: dict[str, Any]) -> dict[str, Any]:
    reply = call(name, {"version": 1, "input": data})
    if reply.get("_is_error"):
        raise ShotEditError(f"{name}: {(reply.get('error') or {}).get('message')}", status=502, code="tool_failed")
    return (reply.get("result") or reply).get("job") or reply.get("result") or reply


def create_series_shot_edit_router(*, change_series: Callable[[str, str, Callable[[dict], None]], dict],
                                   read_library: Callable[[str], dict], read_kits: Callable[[str], dict],
                                   workspace_dir: Callable[[str], str], call: Callable[[str, dict], dict],
                                   bind_loop: Callable[[asyncio.AbstractEventLoop], None],
                                   plan_changes: Callable[[str, str, dict], dict] | None = None) -> APIRouter:
    """``plan_changes(prompt, system, schema)`` is the configured LLM that turns an ``instruction`` into the edit."""
    router = APIRouter()

    def episode_of(workspace: str, series_id: str, episode_id: str) -> tuple[dict, dict]:
        series = (read_library(workspace).get("seriesById") or {}).get(series_id)
        episode = ((series or {}).get("episodesById") or {}).get(episode_id)
        if not isinstance(episode, dict):
            raise ShotEditError("Series episode not found", status=404, code="not_found")
        return series, episode

    def instructed(body: ShotEdit, series_id: str, episode_id: str, kits: dict, files: set[str], root: str,
                   plan: Callable[..., None]) -> dict[str, Any]:
        """The model's edit for ``body.instruction``, checked; a refused one goes back to it once with the problems."""
        if plan_changes is None:
            raise ShotEditError("No LLM is configured to read instructions: send changes or append", status=503,
                                code="llm_unavailable")
        series, episode = episode_of(body.workspace, series_id, episode_id)
        shot, _number = find_shot(episode, body.shot)
        facts = context(series, episode, to_script(series, episode, shot), kits, files)

        def ask(problems: list[str] | None = None) -> dict[str, Any]:
            try:
                return plan_edit(plan_changes, body.instruction or "", facts, problems)
            except (OSError, RuntimeError, ValueError) as error:
                raise ShotEditError(f"The LLM could not write the edit: {error}"[:400], status=502, code="llm_failed") from error

        planned = ask()
        try:
            plan(series, episode, planned["changes"], planned["append"])
        except ShotEditError as error:
            planned = ask(error.problems)
            try:
                plan(series, episode, planned["changes"], planned["append"])
            except ShotEditError as again:
                again.problems = [*again.problems, f"model edit: {planned}"[:600]]
                raise
        return planned

    def edit(series_id: str, episode_id: str, body: ShotEdit) -> dict[str, Any]:
        root = workspace_dir(body.workspace)
        files, kits, outcome = workspace_files(root), read_kits(body.workspace), {}

        def plan(series: dict, episode: dict, changes: dict | None, append: dict | None) -> None:
            shot, number = find_shot(episode, body.shot)
            merged, changed = merge_changes(to_script(series, episode, shot), changes, append)
            patch, texts = build_patch(series, episode, shot, merged, changed, kits, files, root)
            outcome.update(shot=shot, number=number, changed=changed, patch=patch, texts=texts,
                           keep=take_still_fits(shot, changed))

        changes, append, planned = body.changes, body.append, None
        if not changes and not append:
            if not body.instruction and (body.render or body.produce):
                return render_only(body, series_id, episode_id)
            if body.instruction:
                planned = instructed(body, series_id, episode_id, kits, files, root, plan)
                changes, append = planned["changes"], planned["append"]
        told = {"instruction": planned} if planned else {}

        def change(series: dict) -> None:
            plan(series, series["episodesById"][episode_id], changes, append)
            updated, info = apply_edit(series, episode_id, outcome["shot"]["id"], outcome["patch"], outcome["texts"],
                                       outcome["changed"], outcome["keep"])
            series.clear()
            series.update(updated)
            outcome.update(info)

        if body.check:
            plan(*episode_of(body.workspace, series_id, episode_id), changes, append)
            return {"checked": True, "shotId": outcome["shot"]["id"], "number": outcome["number"], "changed": outcome["changed"],
                    "patch": outcome["patch"], "keepsApproval": outcome["keep"], **told}
        try:
            stored = change_series(body.workspace, series_id, change)
        except KeyError as error:
            raise ShotEditError("Series episode not found", status=404, code="not_found") from error
        episode = stored["episodesById"][episode_id]
        shot = next(item for item in episode["shots"] if item["id"] == outcome["shot"]["id"])
        reply = {"shotId": shot["id"], "number": outcome["number"], "changed": outcome["changed"],
                 "approvalReset": outcome["approvalReset"], "missingLines": outcome["missingLines"],
                 "revision": stored.get("revision"), "shot": shot_view(stored, episode, shot, outcome["number"]), **told}
        if body.stored:
            reply["stored"] = {"episodeId": episode_id, "episodeUpdatedAt": episode.get("updatedAt"), "shot": shot,
                               "review": episode.get("review"), "languageVersions": episode.get("languageVersions")}
        return {**reply, **after_edit(body, series_id, episode_id, shot)}

    def render_only(body: ShotEdit, series_id: str, episode_id: str) -> dict[str, Any]:
        """No change, only a new render of the shot (or a production of the episode)."""
        series, episode = episode_of(body.workspace, series_id, episode_id)
        shot, number = find_shot(episode, body.shot)
        return {"shotId": shot["id"], "number": number, "changed": [], **after_edit(body, series_id, episode_id, shot)}

    def after_edit(body: ShotEdit, series_id: str, episode_id: str, shot: dict[str, Any]) -> dict[str, Any]:
        """Render just that shot, or produce the episode (render what changed in every language and recut)."""
        base = {"workspace": body.workspace, "series_id": series_id, "episode_id": episode_id}
        if body.produce:
            return {"produce": _tool(call, "series.episode.produce", base)}
        if not body.render:
            return {}
        if shot.get("productionMethod") in VIDEO_METHODS and not wants_video_foley(shot):
            return {"note": "A generated or imported take is not rendered: its sfx, music and clip sound are laid at the "
                            "cut. Recut with series.assembly.start (or produce: true)."}
        return {"render": _tool(call, "series.episode.render_native", {**base, "shot_ids": [shot["id"]], "approve": body.approve})}

    def fail(error: ShotEditError) -> HTTPException:
        return HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error), "problems": error.problems})

    @router.post("/api/v1/series/{series_id}/episodes/{episode_id}/shots/edit")
    async def edit_shot(series_id: str, episode_id: str, body: ShotEdit):
        """Merge changes (script vocabulary) into one shot named by id or number, check it, reset what no longer fits."""
        bind_loop(asyncio.get_running_loop())
        try:
            return await run_in_threadpool(edit, series_id, episode_id, body)
        except ShotEditError as error:
            raise fail(error) from error
        except ValueError as error:  # the library refused the edited project
            raise HTTPException(status_code=400, detail={"code": "invalid_shot_edit", "message": str(error)}) from error

    @router.get("/api/v1/series/{series_id}/episodes/{episode_id}/shots/{shot}")
    async def get_shot(series_id: str, episode_id: str, shot: str, workspace: str):
        try:
            series, episode = episode_of(workspace, series_id, episode_id)
            found, number = find_shot(episode, shot)
        except ShotEditError as error:
            raise fail(error) from error
        return shot_view(series, episode, found, number)

    return router


__all__ = ["ShotEdit", "create_series_shot_edit_router", "shot_view"]

"""HTTP for a game asset list and its batch production."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.game_library import GameNotFoundError, GameValidationError
from services.game_list import STYLE_SAMPLES, check, commit_list, parse_csv_report, parse_json_report, parse_report
from services.game_produce import GameProduce, ProduceError, iso_now, public_job


class FromList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    text: str | None = None
    csv: str | None = None
    items: list[dict[str, Any]] | None = None
    replace: bool = False
    check: bool = False


class ProduceStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    asset_ids: list[str] | None = None
    kinds: list[str] | None = None
    rerender: bool = False
    candidates: int | None = Field(default=None, ge=1, le=8)


class ProduceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)


def create_game_produce_router(service: GameProduce, *, call: Callable[[str, dict], dict],
                               bind_loop: Callable[[asyncio.AbstractEventLoop], None],
                               read_game: Callable[[str, str], dict]) -> APIRouter:
    router = APIRouter()

    def fail(error: Exception) -> HTTPException:
        if isinstance(error, ProduceError):
            detail: dict[str, Any] = {"code": error.code, "message": str(error)}
            if error.problems is not None:
                detail["problems"] = error.problems
            return HTTPException(status_code=error.status, detail=detail)
        if isinstance(error, GameValidationError):
            return HTTPException(status_code=422, detail={"code": error.code, "message": str(error), "problems": error.problems})
        if isinstance(error, GameNotFoundError):
            return HTTPException(status_code=404, detail={"code": error.code, "message": error.code})
        return HTTPException(status_code=400, detail={"code": "invalid_game", "message": str(error)})

    async def job(function: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        bind_loop(asyncio.get_running_loop())
        try:
            return public_job(await run_in_threadpool(function, *args, **kwargs))
        except (ProduceError, GameNotFoundError, GameValidationError) as error:
            raise fail(error) from error

    @router.post("/api/v1/games/{game_id}/assets/from-list")
    async def assets_from_list(game_id: str, body: FromList):
        """Check a list, or write it when ``check`` is false and the list is clean."""
        bind_loop(asyncio.get_running_loop())

        def run() -> dict[str, Any]:
            game = read_game(body.workspace, game_id)
            items, line_problems = _parse_body(body)
            problems = [*line_problems, *check(game, items, _installed(call), replace=body.replace)]
            from services.game_estimate import estimate
            report = {"items": items, "problems": problems, "estimate": estimate(service.deps.workspace_dir(body.workspace), game, items)}
            if body.check:
                return report
            if problems:
                raise ProduceError("invalid_list", "The list has problems", 422, problems)
            lock = service.deps.lock
            directory = service.deps.workspace_dir(body.workspace)
            if lock is None:
                stored = commit_list(directory, game_id, items, body.replace, now=iso_now())
            else:
                with lock:
                    stored = commit_list(directory, game_id, items, body.replace, now=iso_now())
            return {**report, "assets": stored["assets"]}

        try:
            return await run_in_threadpool(run)
        except (ProduceError, GameNotFoundError, GameValidationError) as error:
            raise fail(error) from error

    @router.post("/api/v1/games/{game_id}/produce")
    async def produce_game(game_id: str, body: ProduceStart):
        """Generate pending assets. Approved work is left as it is."""
        return await job(service.start, body.workspace, game_id, asset_ids=body.asset_ids, kinds=body.kinds,
                         rerender=body.rerender, candidates=body.candidates)

    @router.get("/api/v1/games/produce/jobs/{job_id}")
    async def produce_status(job_id: str, workspace: str):
        return await job(service.status, workspace, job_id)

    @router.post("/api/v1/games/produce/jobs/{job_id}/cancel")
    async def cancel_produce(job_id: str, body: ProduceAction):
        return await job(service.cancel, body.workspace, job_id)

    @router.post("/api/v1/games/produce/jobs/{job_id}/resume")
    async def resume_produce(job_id: str, body: ProduceAction):
        return await job(service.resume, body.workspace, job_id)

    @router.post("/api/v1/games/{game_id}/style/sheet")
    async def style_sheet(game_id: str, body: ProduceAction):
        """Create the four style samples when they are missing, then produce only those."""
        bind_loop(asyncio.get_running_loop())

        def run() -> dict[str, Any]:
            # A busy game answers 409 before the samples are written. start() checks again under its lock.
            service.check_idle(body.workspace, game_id)
            _ensure_samples(service, body.workspace, game_id)
            ids = [item["id"] for item in STYLE_SAMPLES]
            return service.start(body.workspace, game_id, asset_ids=ids)

        try:
            return public_job(await run_in_threadpool(run))
        except (ProduceError, GameNotFoundError, GameValidationError) as error:
            raise fail(error) from error

    return router


def _parse_body(body: FromList) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if body.text is not None:
        return parse_report(body.text)
    if body.csv is not None:
        return parse_csv_report(body.csv)
    if body.items is not None:
        return parse_json_report(body.items)
    raise ProduceError("invalid_list", "Send text, csv, or items", 400)


def _installed(call: Callable[[str, dict], dict]) -> Any:
    try:
        reply = call("media.options", {"version": 1, "input": {}})
    except Exception:
        return None
    if not isinstance(reply, dict) or reply.get("_is_error"):
        return None
    result = reply.get("result") if isinstance(reply.get("result"), dict) else reply
    if isinstance(result, dict) and ("local" in result or "models" in result or "installed" in result):
        return result
    return None


def _ensure_samples(service: GameProduce, workspace: str, game_id: str) -> None:
    game = service.deps.read_game(workspace, game_id)
    have = {asset["id"] for asset in game.get("assets") or []}
    missing = [item for item in STYLE_SAMPLES if item["id"] not in have]
    if not missing:
        return
    directory = service.deps.workspace_dir(workspace)
    lock = service.deps.lock
    if lock is None:
        commit_list(directory, game_id, missing, False, now=iso_now())
        return
    with lock:
        commit_list(directory, game_id, missing, False, now=iso_now())

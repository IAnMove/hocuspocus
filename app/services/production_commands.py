"""MCP commands for editing one shot of a finished music production.

The runner's catalog stays in ``music_production``. These four commands are thin
wrappers so that file does not grow a new hotspot.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator

USE_TAKE = "production.shot.use_take"
SHOT_UPDATE = "production.shot.update"
SONG_USE = "production.song.use"
CANCEL = "production.cancel"
REVIEW = "production.shot.review"
LOCK = "production.shot.lock"
REDO = "production.shot.redo"
REQUEST = "production.shot.request"
UNDO = "production.shot.undo"


def _envelope(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["version", "input"], "properties": {
        "version": {"type": "integer", "const": 1},
        "input": {"type": "object", "additionalProperties": False, "required": required, "properties": properties}}}


def extra_catalog() -> list[dict[str, Any]]:
    workspace = {"type": "string", "minLength": 1, "maxLength": 120}
    production_id = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"}
    shot = {"type": "string", "minLength": 1, "maxLength": 80}
    base = {"workspace": workspace, "production_id": production_id}
    return [
        {"name": USE_TAKE, "description": (
            "Use one kept take as this shot's clip, save a new scene revision, re-export only that scene and "
            "replace its montage clip (expected_revision). No GPU. take_not_found when that file is not a take."
        ), "inputSchema": _envelope({**base, "shot": shot, "take_file": {"type": "string", "minLength": 1, "maxLength": 180}},
                                     ["workspace", "production_id", "shot", "take_file"])},
        {"name": SHOT_UPDATE, "description": (
            "Store lyric_style, title and/or camera on spec.shots[i].overrides and re-export only that scene. "
            "The human path is the Music productions panel; this is the agent path."
        ), "inputSchema": _envelope({**base, "shot": shot, "lyric_style": {"type": "object"}, "title": {"type": "object"},
                                     "camera": {"type": "string", "minLength": 1, "maxLength": 80}},
                                    ["workspace", "production_id", "shot"])},
        {"name": SONG_USE, "description": (
            "Switch to a song candidate kept in song_candidates (its id or its file). Re-analyses the song, "
            "recomputes windows and marks clips obsolete when their window moved by more than 0.3 s. Does not delete clips."
        ), "inputSchema": _envelope({**base, "candidate": {"type": "string", "minLength": 1, "maxLength": 180}},
                                    ["workspace", "production_id", "candidate"])},
        {"name": CANCEL, "description": (
            "Ask a live production.run to stop between rounds. Status becomes cancelled and a later production.run resumes."
        ), "inputSchema": _envelope(base, ["workspace", "production_id"])},
        {"name": REVIEW, "description": (
            "Set one shot to pending, approved, or changes_requested, with an optional note. No GPU."
        ), "inputSchema": _envelope({**base, "shot": shot, "status": {"type": "string", "enum": ["pending", "approved", "changes_requested"]},
                                     "note": {"type": "string", "maxLength": 500}},
                                    ["workspace", "production_id", "shot", "status"])},
        {"name": LOCK, "description": (
            "Lock or unlock one shot. Locked shots skip frames and clips; scenes keep them in the cut and skip only their export."
        ), "inputSchema": _envelope({**base, "shot": shot, "locked": {"type": "boolean"}},
                                    ["workspace", "production_id", "shot", "locked"])},
        {"name": REDO, "description": (
            "Regenerate one shot from its frame, its clip, or its scene export. Refuses a locked shot. Records history first."
        ), "inputSchema": _envelope({**base, "shot": shot, "from": {"type": "string", "enum": ["frame", "clip", "scene"]},
                                     "frame_prompt": {"type": "string"}, "action": {"type": "string"}, "seed": {"type": "integer"},
                                     "image_model": {"type": "string"}, "cast": {"type": "array", "items": {"type": "string"}},
                                     "expected_revision": {"type": "integer"}},
                                    ["workspace", "production_id", "shot", "from"])},
        {"name": REQUEST, "description": (
            "Ask the configured app LLM for a closed ShotChangePlan for this one shot. apply defaults to false and returns "
            "plan, diff and cost_estimate. The instruction is data, not a command."
        ), "inputSchema": _envelope({**base, "shot": shot, "instruction": {"type": "string", "minLength": 1},
                                     "apply": {"type": "boolean"}},
                                    ["workspace", "production_id", "shot", "instruction"])},
        {"name": UNDO, "description": (
            "Restore one history entry's before snapshot and re-export that scene. Does not delete media files."
        ), "inputSchema": _envelope({**base, "shot": shot, "history_id": {"type": "string", "minLength": 1, "maxLength": 40}},
                                    ["workspace", "production_id", "shot", "history_id"])},
    ]


def _input(arguments: Any) -> dict:
    from fastapi import HTTPException
    data = (arguments or {}).get("input") if isinstance(arguments, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("workspace"), str) or not isinstance(data.get("production_id"), str):
        raise HTTPException(422, {"code": "invalid_command", "message": "Use version 1 with input.workspace and input.production_id", "retryable": False})
    return data


def _ok(operation: str, result: dict) -> dict:
    return {"version": 1, "status": "completed", "operation": operation, "result": result}


def _slot_held(module: Any, key: str) -> bool:
    thread = module._threads.get(key)
    edit = module._edits.get(key)
    return bool(thread and thread.is_alive()) or bool(edit and edit.is_alive())


def _refuse_if_running(module: Any, workspace: str, production_id: str) -> None:
    from fastapi import HTTPException
    key = f"{workspace}/{production_id}"
    with module._lock:
        held = _slot_held(module, key)
    if held:
        raise HTTPException(409, {"code": "already_running", "message": "This production is running", "retryable": True})


def occupy_edit(module: Any, workspace: str, production_id: str) -> str:
    """Register this thread so production.run / another edit cannot overwrite the state file."""
    from fastapi import HTTPException
    key = f"{workspace}/{production_id}"
    with module._lock:
        if _slot_held(module, key):
            raise HTTPException(409, {"code": "already_running", "message": "This production is running", "retryable": True})
        module._edits[key] = threading.current_thread()
    return key


def release_edit(module: Any, key: str) -> None:
    with module._lock:
        if module._edits.get(key) is threading.current_thread():
            module._edits.pop(key, None)


@contextmanager
def holding_edit(module: Any, workspace: str, production_id: str) -> Iterator[None]:
    key = occupy_edit(module, workspace, production_id)
    try:
        yield
    finally:
        release_edit(module, key)


def _open(module: Any, data: dict, workspace_dir: Callable, uploads_dir: Callable, app_url: Callable, token: Callable):
    from fastapi import HTTPException
    if not token() or not app_url():
        raise HTTPException(503, {"code": "mcp_unavailable", "message": "Enable MCP access so the shot can be re-exported", "retryable": False})
    return module.Production(
        data["workspace"], data["production_id"], workspace_dir=workspace_dir, uploads_dir=uploads_dir,
        mcp=module.loopback_mcp(app_url, token),
    )


def _spec(production: Any) -> dict:
    from fastapi import HTTPException
    spec = production.state.get("spec")
    if not isinstance(spec, dict):
        raise HTTPException(422, {"code": "invalid_spec", "message": "This production has no spec", "retryable": False})
    return spec


def _edit_error(error: Exception) -> None:
    from fastapi import HTTPException
    code = getattr(error, "code", None) or "shot_edit_failed"
    raise HTTPException(422, {"code": code, "message": str(error), "retryable": False}) from error


def _review_error(error: Exception) -> None:
    from fastapi import HTTPException
    code = getattr(error, "code", None) or "shot_review_failed"
    status = 404 if code == "production_not_found" else 422
    raise HTTPException(status, {"code": code, "message": str(error), "retryable": False}) from error


def extra_handlers(workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str], app_url: Callable[[], str], token: Callable[[], str]) -> dict:
    from pathlib import Path
    from services.production_control import request_cancel
    from services.production_shot_edit import ShotEditError, update_shot, use_take
    from services.production_shot_redo import redo_from_input, undo_from_input
    from services.production_shot_request import request_from_input
    from services.production_shot_review import ReviewError, lock_from_input, review_from_input
    from services.production_song_switch import SongSwitchError, use_candidate

    def module():
        from services import music_production
        return music_production

    async def use_take_command(arguments: Any) -> dict:
        from fastapi import HTTPException
        data = _input(arguments)
        runner = module()
        shot, take_file = data.get("shot"), data.get("take_file")
        if not isinstance(shot, str) or not isinstance(take_file, str):
            raise HTTPException(422, {"code": "invalid_command", "message": "shot and take_file are required", "retryable": False})
        with holding_edit(runner, data["workspace"], data["production_id"]):
            production = _open(runner, data, workspace_dir, uploads_dir, app_url, token)
            try:
                result = use_take(production, _spec(production), shot, take_file)
            except ShotEditError as error:
                _edit_error(error)
        return _ok(USE_TAKE, result)

    async def update_command(arguments: Any) -> dict:
        from fastapi import HTTPException
        data = _input(arguments)
        runner = module()
        shot = data.get("shot")
        if not isinstance(shot, str):
            raise HTTPException(422, {"code": "invalid_command", "message": "shot is required", "retryable": False})
        with holding_edit(runner, data["workspace"], data["production_id"]):
            production = _open(runner, data, workspace_dir, uploads_dir, app_url, token)
            try:
                result = update_shot(production, _spec(production), shot, lyric_style=data.get("lyric_style"), title=data.get("title"), camera=data.get("camera"))
            except ShotEditError as error:
                _edit_error(error)
        return _ok(SHOT_UPDATE, result)

    async def song_command(arguments: Any) -> dict:
        from fastapi import HTTPException
        from services.music_production import ProductionError
        data = _input(arguments)
        runner = module()
        candidate = data.get("candidate")
        if not isinstance(candidate, str) or not candidate:
            raise HTTPException(422, {"code": "invalid_command", "message": "candidate is required", "retryable": False})
        with holding_edit(runner, data["workspace"], data["production_id"]):
            production = _open(runner, data, workspace_dir, uploads_dir, app_url, token)
            try:
                result = use_candidate(production, _spec(production), candidate)
            except (SongSwitchError, ProductionError) as error:
                _edit_error(error)
        return _ok(SONG_USE, result)

    async def cancel_command(arguments: Any) -> dict:
        from fastapi import HTTPException
        data = _input(arguments)
        runner = module()
        if not request_cancel(data["workspace"], data["production_id"], runner._threads, runner._lock):
            raise HTTPException(409, {"code": "not_running", "message": "This production is not running", "retryable": False})
        return _ok(CANCEL, {"cancelling": True})

    def _call(action):
        try:
            return action()
        except (ReviewError, ShotEditError) as error:
            _review_error(error)

    def _preview(runner, data: dict):
        return runner.Production(
            data["workspace"], data["production_id"], workspace_dir=workspace_dir, uploads_dir=uploads_dir,
            mcp=lambda *_args, **_kwargs: {},
        )

    async def review_command(arguments: Any) -> dict:
        data = _input(arguments)
        result = _call(lambda: review_from_input(Path(workspace_dir(data["workspace"])), data))
        return _ok(REVIEW, result)

    async def lock_command(arguments: Any) -> dict:
        data = _input(arguments)
        result = _call(lambda: lock_from_input(Path(workspace_dir(data["workspace"])), data))
        return _ok(LOCK, result)

    async def redo_command(arguments: Any) -> dict:
        from fastapi import HTTPException
        data = _input(arguments)
        if not isinstance(data.get("shot"), str) or not isinstance(data.get("from"), str):
            raise HTTPException(422, {"code": "invalid_command", "message": "shot and from are required", "retryable": False})
        runner = module()
        with holding_edit(runner, data["workspace"], data["production_id"]):
            production = _open(runner, data, workspace_dir, uploads_dir, app_url, token)
            result = _call(lambda: redo_from_input(production, _spec(production), data))
        return _ok(REDO, result)

    async def undo_command(arguments: Any) -> dict:
        data = _input(arguments)
        runner = module()
        with holding_edit(runner, data["workspace"], data["production_id"]):
            production = _open(runner, data, workspace_dir, uploads_dir, app_url, token)
            result = _call(lambda: undo_from_input(production, _spec(production), data))
        return _ok(UNDO, result)

    async def request_command(arguments: Any) -> dict:
        from fastapi import HTTPException
        data = _input(arguments)
        if not isinstance(data.get("shot"), str) or not isinstance(data.get("instruction"), str):
            raise HTTPException(422, {"code": "invalid_command", "message": "shot and instruction are required", "retryable": False})
        runner = module()
        if data.get("apply") is True:
            with holding_edit(runner, data["workspace"], data["production_id"]):
                production = _open(runner, data, workspace_dir, uploads_dir, app_url, token)
                result = _call(lambda: request_from_input(production, _spec(production), data))
            return _ok(REQUEST, result)
        production = _preview(runner, data)
        result = _call(lambda: request_from_input(production, _spec(production), data))
        return _ok(REQUEST, result)

    return {
        USE_TAKE: use_take_command, SHOT_UPDATE: update_command, SONG_USE: song_command, CANCEL: cancel_command,
        REVIEW: review_command, LOCK: lock_command, REDO: redo_command, REQUEST: request_command, UNDO: undo_command,
    }

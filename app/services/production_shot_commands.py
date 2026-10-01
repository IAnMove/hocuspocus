"""Shot review, lock, redo, request and undo. Kept out of command_handlers.run."""
from __future__ import annotations

from typing import Any, Callable

REVIEW = "production.shot.review"
LOCK = "production.shot.lock"
REDO = "production.shot.redo"
REQUEST = "production.shot.request"
UNDO = "production.shot.undo"


def review_catalog() -> list[dict[str, Any]]:
    from services.production_commands import _envelope
    workspace = {"type": "string", "minLength": 1, "maxLength": 120}
    production_id = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"}
    shot = {"type": "string", "minLength": 1, "maxLength": 80}
    base = {"workspace": workspace, "production_id": production_id, "shot": shot}
    required = ["workspace", "production_id", "shot"]
    return [
        {"name": REVIEW, "description": "Record a human review for one shot: pending, approved, or changes_requested. This is not an automatic ok.",
         "inputSchema": _envelope({**base, "status": {"enum": ["pending", "approved", "changes_requested"]}, "notes": {"type": "string", "maxLength": 500}}, required)},
        {"name": LOCK, "description": (
            "Lock or unlock one shot. Locked shots skip frames and clips; scenes keep them in the cut and skip only their export. "
            "An explicit retake, redo or undo of a locked shot is shot_locked."
        ), "inputSchema": _envelope({**base, "locked": {"type": "boolean"}}, required)},
        {"name": REDO, "description": "Redo one shot from frame, clip, or scene. Frame and clip use the production runner. Scene re-exports only that shot.",
         "inputSchema": _envelope({**base, "from": {"enum": ["frame", "clip", "scene"]}, "frame_prompt": {"type": "string", "maxLength": 2000}, "action": {"type": "string", "maxLength": 2000}}, [*required, "from"])},
        {"name": REQUEST, "description": (
            "Validate a closed shot plan, or refuse when only an instruction is sent and no language model is configured. "
            "apply true with the previewed plan validates and runs that object and does not ask the LLM again."
        ), "inputSchema": _envelope({**base, "instruction": {"type": "string", "maxLength": 2000}, "plan": {"type": "object"}, "apply": {"type": "boolean"}}, required)},
        {"name": UNDO, "description": "Restore one history snapshot into the production state and re-export that scene. A locked shot is shot_locked and changes nothing. It does not delete files.",
         "inputSchema": _envelope({**base, "history_id": {"type": "string", "minLength": 1, "maxLength": 32}}, [*required, "history_id"])},
    ]


def review_handlers(workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str], app_url: Callable[[], str], token: Callable[[], str]) -> dict:
    from services.music_production import ProductionError
    from services.production_commands import _edit_error, _input, _ok, _open, _spec, holding_edit
    from services.production_shot_edit import ShotEditError
    from services.production_shot_request import RequestError
    from services.production_shot_review import ReviewError

    def runner():
        from services import music_production
        return music_production

    async def review_command(arguments: Any) -> dict:
        data = _input(arguments)
        _require_shot(data)
        try:
            from services.production_shot_review import record_decision
            result = record_decision(workspace_dir(data["workspace"]), data["production_id"], data["shot"], status=data.get("status"), notes=data.get("notes"))
        except ReviewError as error:
            _edit_error(error)
        return _ok(REVIEW, result)

    async def lock_command(arguments: Any) -> dict:
        data = _input(arguments)
        _require_shot(data)
        try:
            from services.production_shot_review import record_decision
            result = record_decision(workspace_dir(data["workspace"]), data["production_id"], data["shot"], locked=bool(data.get("locked")))
        except ReviewError as error:
            _edit_error(error)
        return _ok(LOCK, result)

    async def redo_command(arguments: Any) -> dict:
        data = _input(arguments)
        _require_shot(data)
        with holding_edit(runner(), data["workspace"], data["production_id"]):
            production = _open(runner(), data, workspace_dir, uploads_dir, app_url, token)
            try:
                from services.production_shot_redo import redo
                result = redo(production, _spec(production), data["shot"], data.get("from"), frame_prompt=_text(data.get("frame_prompt")), action=_text(data.get("action")), shoot_frame=_shoot_frame, shoot_clip=_shoot_clip, export_scene=_export_scene)
            except (ProductionError, ShotEditError, ReviewError) as error:
                _edit_error(error)
        return _ok(REDO, result)

    async def request_command(arguments: Any) -> dict:
        data = _input(arguments)
        _require_shot(data)
        from services.production_shot_request import RequestError, apply_plan, resolve_plan
        try:
            plan = resolve_plan(data)
        except RequestError as error:
            _edit_error(error)
        applied: list[str] = []
        if data.get("apply") is True:
            with holding_edit(runner(), data["workspace"], data["production_id"]):
                production = _open(runner(), data, workspace_dir, uploads_dir, app_url, token)
                try:
                    applied = apply_plan(plan, lambda change: _act(production, _spec(production), data["shot"], change))
                except (ProductionError, ShotEditError, ReviewError, RequestError) as error:
                    _edit_error(error)
        return _ok(REQUEST, {"plan": plan, "applied": applied})

    async def undo_command(arguments: Any) -> dict:
        data = _input(arguments)
        _require_shot(data)
        history_id = data.get("history_id")
        if not isinstance(history_id, str) or not history_id:
            _edit_error(RequestError("invalid_command", "history_id is required"))
        with holding_edit(runner(), data["workspace"], data["production_id"]):
            production = _open(runner(), data, workspace_dir, uploads_dir, app_url, token)
            try:
                from services.production_shot_redo import undo
                result = undo(production, _spec(production), data["shot"], history_id, export_scene=_export_scene)
            except (ProductionError, ShotEditError, ReviewError) as error:
                _edit_error(error)
        return _ok(UNDO, result)

    return {REVIEW: review_command, LOCK: lock_command, REDO: redo_command, REQUEST: request_command, UNDO: undo_command}


def _require_shot(data: dict) -> None:
    from fastapi import HTTPException
    if not isinstance(data.get("shot"), str) or not data["shot"]:
        raise HTTPException(422, {"code": "invalid_command", "message": "shot is required", "retryable": False})


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _shoot_frame(production: Any, spec: dict, key: str, frame_prompt: str | None) -> None:
    window = _window(production, spec, key)
    if frame_prompt:
        window["frame"] = frame_prompt
    production.frames(spec, [window])


def _shoot_clip(production: Any, spec: dict, key: str, action: str | None) -> None:
    window = _window(production, spec, key)
    if action:
        window["action"] = action
    production.clips(spec, [window], retake=(key,))


def _window(production: Any, spec: dict, key: str) -> dict:
    from services.music_production import shot_windows
    for window in shot_windows(spec, production.score()):
        if window.get("key") == key:
            return dict(window)
    return {"key": key, "kind": "h3", "frame": "", "action": ""}


def _export_scene(production: Any, spec: dict, key: str) -> dict:
    from services.production_shot_edit import reexport_shot
    return reexport_shot(production, spec, key)


def _act(production: Any, spec: dict, key: str, change: dict) -> None:
    op = change.get("op")
    if op == "note":
        from services.production_shot_review import record_decision
        record_decision(production.root, production.id, key, notes=str(change.get("text") or ""))
        return
    if op == "set_overrides":
        from services.production_shot_edit import update_shot
        update_shot(production, spec, key, lyric_style=change.get("lyric_style"), title=change.get("title"), camera=change.get("camera"))
        return
    if op == "use_take":
        from services.production_shot_edit import use_take
        use_take(production, spec, key, str(change.get("take_file") or ""))
        return
    if op == "redo":
        from services.production_shot_redo import redo
        redo(production, spec, key, change.get("from"), frame_prompt=_text(change.get("frame_prompt")), action=_text(change.get("action")), shoot_frame=_shoot_frame, shoot_clip=_shoot_clip, export_scene=_export_scene)
        return
    if op == "retake":
        from services.production_shot_review import record_decision
        record_decision(production.root, production.id, key, notes="retake requested")

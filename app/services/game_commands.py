"""MCP tools for the game-asset lab.

Each tool calls the existing REST route. Schemas reject unknown fields.
``game.assets.from_list`` with ``check: true`` does not write the library.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 200}
ID = {"type": "string", "minLength": 1, "maxLength": 80}
REVISION = {"type": "integer", "minimum": 0}
OBJECT = {"type": "object"}
BOOL = {"type": "boolean"}
_TERMINAL = {"completed", "failed", "cancelled", "canceled", "interrupted"}

# name: (properties, required, mutation, description)
OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "game.guide": (
        {"workspace": WORKSPACE, "game_id": ID}, ["workspace"], False,
        "Read the game-asset workflow and, when game_id is set, the live bible for that game. "
        "Call this before creating or producing a game. Returns {guide, bible}.",
    ),
    "game.presets": (
        {"workspace": WORKSPACE}, [], False,
        "List style presets and the animation action catalog before creating a game. Returns {presets, actions}.",
    ),
    "game.list": (
        {"workspace": WORKSPACE}, ["workspace"], False,
        "List the games in a workspace. Returns the library document.",
    ),
    "game.get": (
        {"workspace": WORKSPACE, "game_id": ID}, ["workspace", "game_id"], False,
        "Read one game, including assets, style and exports. Use the revision on the next update.",
    ),
    "game.create": (
        {"workspace": WORKSPACE, "game": OBJECT}, ["workspace", "game"], True,
        "Create a game. game needs a title; genre platformer and view side are the tuned defaults. Returns the game.",
    ),
    "game.update": (
        {"workspace": WORKSPACE, "game_id": ID, "patch": OBJECT, "base_revision": REVISION},
        ["workspace", "game_id", "patch", "base_revision"], True,
        "Patch the title, genre, view or style. A style change returns the style to draft and marks unlocked assets stale, so send the revision you just read. Returns the game.",
    ),
    "game.style.sheet": (
        {"workspace": WORKSPACE, "game_id": ID}, ["workspace", "game_id"], True,
        "Create the four style samples when they are missing, then produce only those. Returns the job. The user approves the look.",
    ),
    "game.style.approve": (
        {"workspace": WORKSPACE, "game_id": ID, "base_revision": REVISION,
         "references": {"type": "array", "maxItems": 20, "items": {"type": "object", "additionalProperties": False,
                        "required": ["asset_id", "attempt_id"], "properties": {"asset_id": ID, "attempt_id": ID}}}},
        ["workspace", "game_id", "base_revision", "references"], True,
        "Approve the style using the sample attempts the user picked. Do not call this unless the user asked. Returns the game.",
    ),
    "game.assets.from_list": (
        {"workspace": WORKSPACE, "game_id": ID, "text": {"type": "string", "maxLength": 200000},
         "items": {"type": "array", "maxItems": 500, "items": OBJECT},
         "format": {"type": "string", "enum": ["lines", "csv", "json"]}, "check": BOOL, "replace": BOOL},
        ["workspace", "game_id"], True,
        "Parse a list of assets; check true returns problems and the estimate and does not write, and without check a clean list is saved. "
        "format is lines, csv or json. Returns {problems, assets, estimate}.",
    ),
    "game.asset.update": (
        {"workspace": WORKSPACE, "game_id": ID, "asset_id": ID, "patch": OBJECT, "base_revision": REVISION},
        ["workspace", "game_id", "asset_id", "patch", "base_revision"], True,
        "Patch one asset's name, description, notes, tags or spec. Send the game revision. Returns the asset.",
    ),
    "game.asset.approve": (
        {"workspace": WORKSPACE, "game_id": ID, "asset_id": ID, "attempt_id": ID, "base_revision": REVISION},
        ["workspace", "game_id", "asset_id", "attempt_id"], True,
        "Approve one attempt. Do not call this unless the user asked. Returns the asset.",
    ),
    "game.asset.reject": (
        {"workspace": WORKSPACE, "game_id": ID, "asset_id": ID, "attempt_id": ID,
         "note": {"type": "string", "minLength": 1, "maxLength": 2000}, "base_revision": REVISION},
        ["workspace", "game_id", "asset_id", "attempt_id", "note"], True,
        "Reject one attempt with a note. The note is required and enters the next prompt. Returns the asset.",
    ),
    "game.asset.lock": (
        {"workspace": WORKSPACE, "game_id": ID, "asset_id": ID, "locked": BOOL, "base_revision": REVISION},
        ["workspace", "game_id", "asset_id", "locked"], True,
        "Lock or unlock an asset. A locked asset does not go stale when the style changes. Returns the asset.",
    ),
    "game.produce": (
        {"workspace": WORKSPACE, "game_id": ID, "asset_ids": {"type": "array", "maxItems": 500, "items": ID},
         "kinds": {"type": "array", "maxItems": 20, "items": ID}, "rerender": BOOL,
         "candidates": {"type": "integer", "minimum": 1, "maximum": 8}},
        ["workspace", "game_id"], True,
        "Render pending assets in dependency order. rerender is only for stale assets; poll produce status afterwards. Returns the job.",
    ),
    "game.produce.status": (
        {"workspace": WORKSPACE, "job_id": ID, "wait_s": {"type": "integer", "minimum": 0, "maximum": 120}},
        ["workspace", "job_id"], False,
        "Read a produce job. wait_s, at most 120, holds until the job finishes or the wait ends. Returns the job.",
    ),
    "game.produce.cancel": (
        {"workspace": WORKSPACE, "job_id": ID}, ["workspace", "job_id"], True,
        "Stop a produce job after the current step. Finished assets stay. Returns the job.",
    ),
    "game.produce.resume": (
        {"workspace": WORKSPACE, "job_id": ID}, ["workspace", "job_id"], True,
        "Resume an interrupted produce job. Steps that already finished are not repeated. Returns the job.",
    ),
    "game.export": (
        {"workspace": WORKSPACE, "game_id": ID}, ["workspace", "game_id"], True,
        "Pack approved assets into a ZIP. Other assets are listed in missing and are left out of the file. "
        "Returns {file, url, counts, missing}.",
    ),
}


class GameCommandError(ValueError):
    def __init__(self, message: Any, *, status: int = 422) -> None:
        super().__init__(message if isinstance(message, str) else json.dumps(message, ensure_ascii=False))
        self.detail = message
        self.status = status


def command_catalog() -> list[dict[str, Any]]:
    return [_operation_schema(name, *spec) for name, spec in OPERATIONS.items()]


def command_handlers(app_url: Callable[[], str], workspace_dir: Callable[[str], str],
                     uploads_dir: Callable[[], str], *, opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Callable[[Any], Any]]:
    """Return one async handler per tool. ``workspace_dir`` and ``uploads_dir`` match the series handler shape."""
    del workspace_dir, uploads_dir
    request = _http(app_url, opener)

    def handler(name: str) -> Callable[[Any], Any]:
        properties, required, _, _ = OPERATIONS[name]

        async def handle(arguments: Any) -> dict[str, Any]:
            from fastapi import HTTPException
            from starlette.concurrency import run_in_threadpool

            data = arguments.get("input") if isinstance(arguments, dict) and arguments.get("version") == 1 else None
            if not isinstance(data, dict) or set(data) - set(properties) or any(key not in data for key in required):
                raise HTTPException(422, {"code": "invalid_command", "message": f"Use version 1 with input fields: {', '.join(required)}", "retryable": False})
            try:
                result = await run_in_threadpool(_run, name, data, request)
            except GameCommandError as error:
                raise HTTPException(error.status if error.status < 500 else 502, _error_detail(error)) from error
            return {"version": 1, "status": "completed", "operation": name, "result": result}
        return handle

    return {name: handler(name) for name in OPERATIONS}


def _operation_schema(name: str, properties: dict[str, Any], required: list[str], mutation: bool, description: str) -> dict[str, Any]:
    return {
        "name": name, "version": 1, "domain": "game", "mutation": mutation, "description": description,
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "input"], "properties": {
            "version": {"type": "integer", "const": 1},
            "input": {"type": "object", "additionalProperties": False, "properties": properties, "required": required},
        }},
    }


def _run(name: str, data: dict[str, Any], request: Callable[..., Any]) -> Any:
    runner = _RUNNERS.get(name)
    if runner is None:
        raise GameCommandError("Unknown operation")
    return runner(data, request)


def _guide(data: dict[str, Any], request: Callable[..., Any]) -> dict[str, Any]:
    from services.game_guide import build_bible, guide_text

    bible = None
    if data.get("game_id"):
        bible = build_bible(_request_game(data, request))
    return {"guide": guide_text(), "bible": bible}


def _presets(_data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("GET", "/api/v1/games/presets")


def _list(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("GET", "/api/v1/games", query={"workspace": data["workspace"]})


def _get(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return _request_game(data, request)


def _create(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("POST", "/api/v1/games", body={"workspace": data["workspace"], "game": data["game"]})


def _update(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("PUT", _game_path(data["game_id"]), body=_revision_body(data, "patch"))


def _style_sheet(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("POST", _game_path(data["game_id"], "/style/sheet"), body={"workspace": data["workspace"]})


def _style_approve(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    body = _revision_body(data)
    body["references"] = data["references"]
    return request("POST", _game_path(data["game_id"], "/style/approve"), body=body)


def _from_list(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    body = {"workspace": data["workspace"], "check": bool(data.get("check")), "replace": bool(data.get("replace"))}
    _attach_list(body, data)
    payload = request("POST", _game_path(data["game_id"], "/assets/from-list"), body=body)
    return _listed(payload, bool(data.get("check")))


def _asset_update(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("PATCH", _asset_path(data), body=_revision_body(data, "patch"))


def _approve(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("POST", _asset_path(data, "/approve"), body=_attempt_body(data))


def _reject(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    body = _attempt_body(data)
    body["note"] = data["note"]
    return request("POST", _asset_path(data, "/reject"), body=body)


def _lock(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    body = {"workspace": data["workspace"], "locked": bool(data["locked"])}
    _copy_revision(body, data)
    return request("POST", _asset_path(data, "/lock"), body=body)


def _produce(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    body = {"workspace": data["workspace"], "rerender": bool(data.get("rerender"))}
    for key in ("asset_ids", "kinds", "candidates"):
        if key in data:
            body[key] = data[key]
    return request("POST", _game_path(data["game_id"], "/produce"), body=body)


def _status(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    limit = min(120, max(0, _int(data.get("wait_s"), 0)))
    deadline = time.monotonic() + limit
    while True:
        job = request("GET", f"/api/v1/games/produce/jobs/{_quote(data['job_id'])}", query={"workspace": data["workspace"]})
        if limit == 0 or _done(job) or time.monotonic() >= deadline:
            return job
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def _cancel(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return _job_action(data, request, "cancel")


def _resume(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return _job_action(data, request, "resume")


def _export(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("POST", _game_path(data["game_id"], "/export"), body={"workspace": data["workspace"]})


def _job_action(data: dict[str, Any], request: Callable[..., Any], action: str) -> Any:
    path = f"/api/v1/games/produce/jobs/{_quote(data['job_id'])}/{action}"
    return request("POST", path, body={"workspace": data["workspace"]})


def _request_game(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("GET", _game_path(data["game_id"]), query={"workspace": data["workspace"]})


def _attach_list(body: dict[str, Any], data: dict[str, Any]) -> None:
    fmt = data.get("format") or ("json" if "items" in data else "lines")
    if fmt == "json":
        body["items"] = data.get("items") or []
        return
    text = data.get("text") or ""
    body["csv" if fmt == "csv" else "text"] = text


def _listed(payload: Any, check: bool) -> Any:
    if not isinstance(payload, dict) or "assets" in payload:
        return payload
    assets = payload.get("items") if check and isinstance(payload.get("items"), list) else []
    return {**payload, "assets": assets}


def _revision_body(data: dict[str, Any], extra: str | None = None) -> dict[str, Any]:
    body = {"workspace": data["workspace"], "base_revision": data["base_revision"]}
    if extra:
        body[extra] = data[extra]
    return body


def _attempt_body(data: dict[str, Any]) -> dict[str, Any]:
    body = {"workspace": data["workspace"], "attempt_id": data["attempt_id"]}
    _copy_revision(body, data)
    return body


def _copy_revision(body: dict[str, Any], data: dict[str, Any]) -> None:
    if "base_revision" in data:
        body["base_revision"] = data["base_revision"]


def _game_path(game_id: str, suffix: str = "") -> str:
    return f"/api/v1/games/{_quote(game_id)}{suffix}"


def _asset_path(data: dict[str, Any], suffix: str = "") -> str:
    return _game_path(data["game_id"], f"/assets/{_quote(data['asset_id'])}{suffix}")


def _done(job: Any) -> bool:
    status = job.get("status") if isinstance(job, dict) else None
    return status in _TERMINAL


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _http(app_url: Callable[[], str], opener: Callable[..., Any]) -> Callable[..., Any]:
    def request(method: str, path: str, *, query: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> Any:
        base = app_url().rstrip("/")
        if not base:
            raise GameCommandError("The HocusPocus server address is not ready yet", status=503)
        url = base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        try:
            with opener(urllib.request.Request(url, data=payload, method=method, headers=headers), timeout=120) as response:
                return json.loads(response.read().decode() or "null")
        except urllib.error.HTTPError as error:
            raise GameCommandError(_http_detail(error), status=error.code) from error
    return request


def _http_detail(error: urllib.error.HTTPError) -> Any:
    try:
        detail = json.loads(error.read().decode()).get("detail")
    except (ValueError, AttributeError):
        detail = error.reason
    return detail or f"HTTP {error.code}"


def _error_detail(error: GameCommandError) -> dict[str, Any]:
    fallback = "conflict" if error.status == 409 else "not_found" if error.status == 404 else "invalid_command"
    route = error.detail if isinstance(error.detail, dict) and isinstance(error.detail.get("message"), str) else {}
    message = route.get("message") or (error.detail if isinstance(error.detail, str) else str(error.detail))
    return {**route, "code": route.get("code") or fallback, "message": message, "retryable": error.status in (409, 503)}


_RUNNERS = {
    "game.guide": _guide,
    "game.presets": _presets,
    "game.list": _list,
    "game.get": _get,
    "game.create": _create,
    "game.update": _update,
    "game.style.sheet": _style_sheet,
    "game.style.approve": _style_approve,
    "game.assets.from_list": _from_list,
    "game.asset.update": _asset_update,
    "game.asset.approve": _approve,
    "game.asset.reject": _reject,
    "game.asset.lock": _lock,
    "game.produce": _produce,
    "game.produce.status": _status,
    "game.produce.cancel": _cancel,
    "game.produce.resume": _resume,
    "game.export": _export,
}

__all__ = ["OPERATIONS", "GameCommandError", "command_catalog", "command_handlers"]

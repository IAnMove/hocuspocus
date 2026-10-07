"""MCP tools for the game-asset lab.

Each tool calls the existing REST route. Input is checked against the tool
schema first, so a string ``"false"`` never reaches a route as ``True``.
``game.assets.from_list`` with ``check: true`` does not write the library.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from jsonschema import Draft202012Validator

from services.game_library import KINDS, MAX_ID

# The pattern ``_workspace_dir`` accepts; the route still resolves and contains the folder.
WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 200, "pattern": "^(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)$"}
SLUG = {"type": "string", "maxLength": MAX_ID, "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$"}
# ``presets`` and ``produce`` are static routes under /api/v1/games, never game ids.
GAME_ID = {**SLUG, "pattern": "^(?!(?:presets|produce)$)[a-z0-9]+(?:-[a-z0-9]+)*$"}
ATTEMPT_ID = {"type": "string", "minLength": 1, "maxLength": 80}
JOB_ID = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"}
KIND = {"enum": list(KINDS)}
REVISION = {"type": "integer", "minimum": 0}
OBJECT = {"type": "object"}
BOOL = {"type": "boolean"}
_TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
_FALLBACK_CODES = {404: "not_found", 409: "conflict", 503: "server_unavailable"}
# A 409 with these codes fails the same way on every retry.
_FINAL_CONFLICTS = {"game_exists"}
_MAX_PROBLEMS = 20

# name: (properties, required, mutation, description)
OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "game.guide": (
        {"workspace": WORKSPACE, "game_id": GAME_ID}, ["workspace"], False,
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
        {"workspace": WORKSPACE, "game_id": GAME_ID}, ["workspace", "game_id"], False,
        "Read one game, including assets, attempts, style and exports. Use the revision on the next update.",
    ),
    "game.create": (
        {"workspace": WORKSPACE, "game": OBJECT}, ["workspace", "game"], True,
        "Create a game from {title, id, genre, view, style}; platformer and side are the tuned defaults. "
        "An explicit id (a slug of at most 64 characters, not presets or produce) makes a retry answer 409 game_exists "
        "instead of creating a second game. Returns the game.",
    ),
    "game.update": (
        {"workspace": WORKSPACE, "game_id": GAME_ID, "patch": OBJECT, "base_revision": REVISION},
        ["workspace", "game_id", "patch", "base_revision"], True,
        "Patch the title, genre, view or style with the revision you just read; an older one is 409 revision_conflict. "
        "A style change returns the style to draft and marks unlocked approved or rejected assets stale. Returns the game.",
    ),
    "game.style.sheet": (
        {"workspace": WORKSPACE, "game_id": GAME_ID}, ["workspace", "game_id"], True,
        "Create the four style samples when they are missing, then produce only those; another active job for the game "
        "is 409 already_running. Returns the job. The user approves the look.",
    ),
    "game.style.approve": (
        {"workspace": WORKSPACE, "game_id": GAME_ID, "base_revision": REVISION,
         "references": {"type": "array", "maxItems": 20, "items": {"type": "object", "additionalProperties": False,
                        "required": ["asset_id", "attempt_id"], "properties": {"asset_id": SLUG, "attempt_id": ATTEMPT_ID}}}},
        ["workspace", "game_id", "base_revision", "references"], True,
        "Approve the style with the sample attempts the user picked; take attempt ids from each asset's attempts "
        "(several candidates are <attemptId>-a1, -a2 and so on). Do not call this unless the user asked. Returns the game.",
    ),
    "game.assets.from_list": (
        {"workspace": WORKSPACE, "game_id": GAME_ID, "text": {"type": "string", "minLength": 1, "maxLength": 200000},
         "items": {"type": "array", "minItems": 1, "maxItems": 500, "items": OBJECT},
         "format": {"type": "string", "enum": ["lines", "csv", "json"]}, "check": BOOL, "replace": BOOL},
        ["workspace", "game_id"], True,
        "Send text, one '<kind> <id>: <description> | option' per line (format lines) or csv, or items (format json); "
        "check true returns {problems, items, estimate} and writes nothing. Without check a clean list is saved; "
        "replace true deletes the assets the list leaves out. Returns {problems, assets, estimate}.",
    ),
    "game.asset.update": (
        {"workspace": WORKSPACE, "game_id": GAME_ID, "asset_id": SLUG, "patch": OBJECT, "base_revision": REVISION},
        ["workspace", "game_id", "asset_id", "patch", "base_revision"], True,
        "Patch one asset's name, description, notes, tags, candidates or spec with the game revision; spec replaces "
        "the whole spec, so send it complete (seed is a whole number from 0). Returns the asset.",
    ),
    "game.asset.approve": (
        {"workspace": WORKSPACE, "game_id": GAME_ID, "asset_id": SLUG, "attempt_id": ATTEMPT_ID, "base_revision": REVISION},
        ["workspace", "game_id", "asset_id", "attempt_id"], True,
        "Approve one ok attempt by its id from the asset's attempts; assets built on another attempt go stale. "
        "Do not call this unless the user asked. Returns the asset.",
    ),
    "game.asset.reject": (
        {"workspace": WORKSPACE, "game_id": GAME_ID, "asset_id": SLUG, "attempt_id": ATTEMPT_ID,
         "note": {"type": "string", "minLength": 1, "maxLength": 2000}, "base_revision": REVISION},
        ["workspace", "game_id", "asset_id", "attempt_id", "note"], True,
        "Reject one attempt with a note; the note is required and enters the next prompt. "
        "An asset with another approved attempt stays approved. Returns the asset.",
    ),
    "game.asset.lock": (
        {"workspace": WORKSPACE, "game_id": GAME_ID, "asset_id": SLUG, "locked": BOOL, "base_revision": REVISION},
        ["workspace", "game_id", "asset_id", "locked"], True,
        "Lock or unlock an asset. A locked asset does not go stale when the style changes; unlocking checks it again. "
        "Returns the asset.",
    ),
    "game.produce": (
        {"workspace": WORKSPACE, "game_id": GAME_ID, "asset_ids": {"type": "array", "maxItems": 500, "items": SLUG},
         "kinds": {"type": "array", "maxItems": 20, "items": KIND}, "rerender": BOOL,
         "candidates": {"type": "integer", "minimum": 1, "maximum": 8}},
        ["workspace", "game_id"], True,
        "Render pending, rejected and failed assets in dependency order; rerender true adds stale unlocked assets and the review assets named in asset_ids. "
        "Another active job for the game is 409 already_running. Returns the job; poll produce status afterwards.",
    ),
    "game.produce.status": (
        {"workspace": WORKSPACE, "job_id": JOB_ID, "wait_s": {"type": "integer", "minimum": 0, "maximum": 120}},
        ["workspace", "job_id"], False,
        "Read a produce job and its steps; wait_s, at most 120, holds until it is completed, failed, cancelled or "
        "interrupted. A step skipped as waiting_dependency runs on resume once its dependency is approved. Returns the job.",
    ),
    "game.produce.cancel": (
        {"workspace": WORKSPACE, "job_id": JOB_ID}, ["workspace", "job_id"], True,
        "Stop a produce job; a step cut while it waits on a tool goes back to the queue, and finished assets stay. "
        "The job ends cancelled and resume continues it. Returns the job.",
    ),
    "game.produce.resume": (
        {"workspace": WORKSPACE, "job_id": JOB_ID}, ["workspace", "job_id"], True,
        "Resume a cancelled, interrupted or failed job without repeating finished steps; steps that waited on a "
        "dependency run once it is approved. An active job comes back unchanged, and another active job for the game is "
        "409 already_running. Returns the job.",
    ),
    "game.export": (
        {"workspace": WORKSPACE, "game_id": GAME_ID}, ["workspace", "game_id"], True,
        "Pack approved assets into a ZIP; every other asset, stale ones included, is left out and listed in missing "
        "with its status. Returns {file, url, counts, missing}.",
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
        required = OPERATIONS[name][1]
        validator = Draft202012Validator(_operation_schema(name, *OPERATIONS[name])["inputSchema"])

        async def handle(arguments: Any) -> dict[str, Any]:
            from fastapi import HTTPException
            from starlette.concurrency import run_in_threadpool

            problems = _input_problems(validator, arguments)
            if problems:
                raise HTTPException(422, {"code": "invalid_command", "message": f"Use version 1 with input fields: {', '.join(required)}",
                                          "problems": problems, "retryable": False})
            try:
                result = await run_in_threadpool(_run, name, arguments["input"], request)
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


def _input_problems(validator: Draft202012Validator, arguments: Any) -> list[dict[str, str]]:
    """Every schema error as ``{field, message}``; an empty list means the call may run."""
    if not isinstance(arguments, dict):
        return [{"field": "", "message": "Arguments must be an object"}]
    errors = sorted(validator.iter_errors(arguments), key=lambda error: [str(part) for part in error.absolute_path])
    return [{"field": "/".join(str(part) for part in error.absolute_path), "message": error.message[:300]}
            for error in errors[:_MAX_PROBLEMS]]


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
    check = data.get("check", False)
    body = {"workspace": data["workspace"], "check": check, "replace": data.get("replace", False)}
    _attach_list(body, data)
    payload = request("POST", _game_path(data["game_id"], "/assets/from-list"), body=body)
    return _listed(payload, check)


def _asset_update(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("PATCH", _asset_path(data), body=_revision_body(data, "patch"))


def _approve(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    return request("POST", _asset_path(data, "/approve"), body=_attempt_body(data))


def _reject(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    body = _attempt_body(data)
    body["note"] = data["note"]
    return request("POST", _asset_path(data, "/reject"), body=body)


def _lock(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    body = {"workspace": data["workspace"], "locked": data["locked"]}
    _copy_revision(body, data)
    return request("POST", _asset_path(data, "/lock"), body=body)


def _produce(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    body = {"workspace": data["workspace"], "rerender": data.get("rerender", False)}
    for key in ("asset_ids", "kinds", "candidates"):
        if key in data:
            body[key] = data[key]
    return request("POST", _game_path(data["game_id"], "/produce"), body=body)


def _status(data: dict[str, Any], request: Callable[..., Any]) -> Any:
    limit = data.get("wait_s", 0)
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
    """Exactly one source: ``text`` for lines or csv, ``items`` for json.

    A mismatch used to send an empty list, and ``replace`` with an empty list deletes every asset.
    """
    has_text, has_items = "text" in data, "items" in data
    fmt = data.get("format") or ("json" if has_items else "lines")
    if has_text == has_items or has_items != (fmt == "json"):
        raise GameCommandError({"code": "invalid_list", "message": "Send text with format lines or csv, or items with format json"})
    if has_items:
        body["items"] = data["items"]
    else:
        body["csv" if fmt == "csv" else "text"] = data["text"]


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
        except OSError as error:  # refused, reset or timed out: the server may be restarting
            raise GameCommandError({"code": "server_unavailable", "message": f"The HocusPocus server did not answer: {error}"[:300]},
                                   status=503) from error
    return request


def _http_detail(error: urllib.error.HTTPError) -> Any:
    try:
        detail = json.loads(error.read().decode()).get("detail")
    except (ValueError, AttributeError):
        detail = error.reason
    return detail or f"HTTP {error.code}"


def _error_detail(error: GameCommandError) -> dict[str, Any]:
    """The tool error an agent reads: the route's code, message and problems when it gave them."""
    route = _route_detail(error.detail)
    code = route.get("code") or _FALLBACK_CODES.get(error.status, "invalid_command")
    message = route.get("message") or (error.detail if isinstance(error.detail, str) else str(error.detail))
    retryable = error.status == 503 or (error.status == 409 and code not in _FINAL_CONFLICTS)
    return {**route, "code": code, "message": message, "retryable": retryable}


def _route_detail(detail: Any) -> dict[str, Any]:
    """A route's dict detail, or FastAPI's field errors (a list) as ``problems``."""
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail
    if not isinstance(detail, list):
        return {}
    problems = [{"field": "/".join(str(part) for part in item.get("loc") or []), "message": str(item.get("msg") or "")}
                for item in detail[:_MAX_PROBLEMS] if isinstance(item, dict)]
    return {"code": "invalid_command", "message": "The route rejected some fields", "problems": problems}


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

"""MCP tools for the workspace folders: ``workspaces.list`` and ``workspaces.create``.

An agent cannot use a workspace that does not exist (every tool takes ``workspace``), and Sol waited about two hours
for ``profesion`` to be made by hand. These tools are doors onto the operations the REST routes run
(``GET``/``POST /api/v1/workspaces``): the handler calls the mounted route, so the name rules, the folder it makes and
the answer are the route's. Creating is idempotent by nature: a name that exists comes back unchanged, so a retry
after a lost answer is safe and ``workspaces.list`` is the receipt.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from services.wangp_submission import JsonRequest

_NAME = {"type": "string", "minLength": 1, "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_-]*$",
         "description": "Letters, numbers, hyphens and underscores; starts with a letter or a number."}
_OPERATIONS = {
    "workspaces.list": (False, "List the workspace folders (name, path, file count) and the active one. Read it to see "
                               "whether a workspace exists, and after an uncertain workspaces.create.", {}, []),
    "workspaces.create": (True, "Create a workspace folder so tools can take it as their workspace. Safe to retry: a name "
                                "that already exists is returned unchanged. Switching the active workspace stays in the UI.",
                          {"name": _NAME}, ["name"]),
}


def command_catalog() -> list[dict[str, Any]]:
    result = []
    for name, (mutation, description, properties, required) in _OPERATIONS.items():
        envelope = {"version": {"type": "integer", "const": 1},
                    "input": {"type": "object", "additionalProperties": False, "properties": properties, "required": required}}
        result.append({"name": name, "version": 1, "domain": "workspaces", "mutation": mutation,
                       "receipt_tool": "workspaces.list", "destructive": False, "description": description,
                       "inputSchema": {"type": "object", "additionalProperties": False, "properties": envelope,
                                       "required": ["version", "input"]}})
    return result


def _input(name: str, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict) or arguments.get("version") != 1:
        raise ValueError(f"{name} takes version 1 and an input object")
    value = arguments.get("input", {})
    properties = _OPERATIONS[name][2]
    if not isinstance(value, dict) or set(value) - set(properties):
        raise ValueError(f"{name} input takes only: {', '.join(properties) or 'nothing'}")
    return value


def command_handlers(list_endpoint: Callable[..., Any], create_endpoint: Callable[..., Any]) -> dict[str, Callable]:
    """``list_endpoint`` / ``create_endpoint``: the mounted ``GET`` / ``POST /api/v1/workspaces`` route functions."""
    def completed(name: str, result: Any) -> dict[str, Any]:
        return {"version": 1, "operation": name, "status": "completed", "result": result}

    async def listing(arguments):
        _input("workspaces.list", arguments)
        result = list_endpoint()
        return completed("workspaces.list", await result if inspect.isawaitable(result) else result)

    async def create(arguments):
        value = _input("workspaces.create", arguments)
        if not isinstance(value.get("name"), str):
            raise ValueError("workspaces.create needs input.name, a string")
        result = create_endpoint(JsonRequest({"name": value["name"]}))
        return completed("workspaces.create", await result if inspect.isawaitable(result) else result)

    return {"workspaces.list": listing, "workspaces.create": create}

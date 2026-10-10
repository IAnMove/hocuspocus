"""Input checks for MCP tools that list what arrived and what the tool accepts."""
from __future__ import annotations

from typing import Any


def field_error(unexpected: list[str], allowed: list[str]) -> dict[str, Any]:
    """Say which fields arrived and which ones the tool accepts."""
    names = sorted(unexpected)
    known = sorted(allowed)
    if not known:
        message = "This tool takes no input fields"
    else:
        message = f"Unexpected field(s): {', '.join(names)}. Allowed: {', '.join(known)}"
    return {"code": "invalid_command", "message": message, "unexpected": names, "allowed": known, "retryable": False}


def reject_input(data: Any, properties: dict[str, Any], required: list[str]) -> None:
    from fastapi import HTTPException
    if not isinstance(data, dict):
        raise HTTPException(422, {"code": "invalid_command",
                                  "message": f"Use version 1 with input fields: {', '.join(required)}", "retryable": False})
    unexpected = sorted(set(data) - set(properties))
    if unexpected:
        raise HTTPException(422, field_error(unexpected, list(properties)))
    if any(key not in data for key in required):
        raise HTTPException(422, {"code": "invalid_command",
                                  "message": f"Use version 1 with input fields: {', '.join(required)}", "retryable": False})

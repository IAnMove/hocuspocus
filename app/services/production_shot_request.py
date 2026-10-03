"""A closed shot-change plan. Unknown ops, extra fields and path values are rejected.

No language model is called from here. A missing plan and a missing injected
completer is ``llm_unavailable``. The server does not invent a plan.
"""
from __future__ import annotations

import json
from typing import Any, Callable

OPS = {
    "set_overrides": frozenset({"lyric_style", "title", "camera"}),
    "redo": frozenset({"from", "frame_prompt", "action"}),
    "retake": frozenset(),
    "use_take": frozenset({"take_file"}),
    "note": frozenset({"text"}),
}
_REDO_FROM = frozenset({"frame", "clip", "scene"})


class RequestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_plan(data: dict, complete: Callable[[str], Any] | None = None) -> dict:
    if isinstance(data.get("plan"), dict):
        return validate_plan(data["plan"])
    instruction = data.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise RequestError("invalid_command", "instruction or plan is required")
    if complete is None:
        raise RequestError("llm_unavailable", "No language model is configured for a shot plan")
    return validate_plan(complete(instruction))


def validate_plan(plan: Any) -> dict:
    if not isinstance(plan, dict) or set(plan) - {"summary", "changes"}:
        raise RequestError("invalid_plan", "plan allows summary and changes")
    if not isinstance(plan.get("summary"), str) or not plan["summary"].strip():
        raise RequestError("invalid_plan", "summary is required")
    changes = plan.get("changes")
    if not isinstance(changes, list):
        raise RequestError("invalid_plan", "changes must be a list")
    for change in changes:
        _change(change)
    if _unsafe(plan):
        raise RequestError("invalid_plan", "a plan value must not contain a path")
    return plan


def apply_plan(plan: dict, act: Callable[[dict], None]) -> list[str]:
    done = []
    for change in plan.get("changes") or []:
        act(change)
        done.append(change.get("op"))
    return done


def _change(change: Any) -> None:
    if not isinstance(change, dict) or not isinstance(change.get("op"), str):
        raise RequestError("invalid_plan", "each change needs op")
    allowed = OPS.get(change["op"])
    if allowed is None:
        raise RequestError("invalid_plan", "unknown op")
    if set(change) - allowed - {"op"}:
        raise RequestError("invalid_plan", "extra field")
    if change["op"] == "redo" and change.get("from") not in _REDO_FROM:
        raise RequestError("invalid_plan", "redo from must be frame, clip, or scene")


def _closed_plan(value: Any) -> dict:
    """Validate a previewed ShotChangePlan. A dict or its JSON text; no model call."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise RequestError("invalid_plan", "plan must be the ShotChangePlan object") from error
    if not isinstance(value, dict):
        raise RequestError("invalid_plan", "plan must be the ShotChangePlan object")
    return validate_plan(value)


def request_shot(
    production: Any, spec: dict, key: str, instruction: str, *,
    apply: bool = False, generate: Callable | None = None, plan: Any = None,
) -> dict:
    """Return ``{plan, applied}``. ``apply`` true with a plan does not call ``generate``."""
    if not isinstance(key, str) or not key:
        raise RequestError("invalid_command", "shot is required")
    if not isinstance(instruction, str) or not instruction.strip():
        raise RequestError("invalid_command", "instruction is required")
    if apply is True and plan is not None:
        closed = _closed_plan(plan)
    else:
        closed = resolve_plan({"instruction": instruction.strip()}, complete=generate)
    result = {"plan": closed, "applied": False}
    if apply is not True:
        return result
    from services.production_shot_commands import _act
    apply_plan(closed, lambda change: _act(production, spec, key, change))
    result["applied"] = True
    return result


def request_from_input(production: Any, spec: dict, data: dict, generate: Callable | None = None) -> dict:
    key = data.get("shot")
    instruction = data.get("instruction")
    if not isinstance(key, str) or not key:
        raise RequestError("invalid_command", "shot is required")
    if not isinstance(instruction, str):
        raise RequestError("invalid_command", "instruction is required")
    apply = data.get("apply", False)
    if not isinstance(apply, bool):
        raise RequestError("invalid_command", "apply must be boolean")
    return request_shot(
        production, spec, key, instruction, apply=apply, generate=generate, plan=data.get("plan"),
    )


def _unsafe(value: Any) -> bool:
    if isinstance(value, str):
        return "/" in value or ".." in value
    if isinstance(value, dict):
        return any(_unsafe(item) for item in value.values())
    if isinstance(value, list):
        return any(_unsafe(item) for item in value)
    return False

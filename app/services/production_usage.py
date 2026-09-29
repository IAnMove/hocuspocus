"""Per-production MCP cost: calls, response bytes, and H3 takes.

The transport journal stores idempotency, not a production id. The runner counts
each loopback reply it actually receives. ``h3_takes`` is the sum of ``clip_takes``.
"""
from __future__ import annotations

import json
from typing import Any, Callable


def note_call(state: dict, result: Any) -> None:
    usage = state.setdefault("usage", {})
    usage["mcp_calls"] = _count(usage.get("mcp_calls")) + 1
    usage["response_bytes"] = _count(usage.get("response_bytes")) + _bytes(result)


def usage_summary(state: dict) -> dict[str, int]:
    raw = state.get("usage") if isinstance(state.get("usage"), dict) else {}
    return {
        "mcp_calls": _count(raw.get("mcp_calls")),
        "response_bytes": _count(raw.get("response_bytes")),
        "h3_takes": _takes(state.get("clip_takes")),
    }


def attach_usage(mcp: Callable[[str, dict], dict], state: dict, save: Callable[[], None]) -> Callable[[str, dict], dict]:
    def call(tool: str, arguments: dict) -> dict:
        result = mcp(tool, arguments)
        note_call(state, result)
        save()
        return result
    return call


def _bytes(result: Any) -> int:
    try:
        return len(json.dumps(result, ensure_ascii=False).encode())
    except (TypeError, ValueError):
        return 0


def _count(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _takes(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    return sum(_count(item) for item in value.values())

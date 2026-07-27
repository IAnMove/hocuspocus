"""Helpers for safe LTX-2 text-embedding lookahead in generation queues."""

from __future__ import annotations

from typing import Any


def prefetch_next_ltx_prompt(queue: list[dict[str, Any]]) -> int:
    """Attach the next compatible prompt to the first LTX queue task."""

    if len(queue) < 2:
        return 0
    first_params = queue[0].get("params", {})
    first_model = str(first_params.get("model_type") or "")
    second_model = str(queue[1].get("params", {}).get("model_type") or "")
    if not first_model.startswith("ltx2_") or second_model != first_model:
        return 0

    first_prompt = str(queue[0].get("prompt") or "").strip()
    next_prompt = str(queue[1].get("prompt") or "").strip()
    if not next_prompt or next_prompt == first_prompt:
        return 0

    first_params["ltx2_prefetch_prompts"] = [next_prompt]
    return 1

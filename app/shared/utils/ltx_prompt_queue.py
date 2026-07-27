"""Helpers for safe LTX-2 text-embedding lookahead in generation queues."""

from __future__ import annotations

from typing import Any


DEFAULT_LTX_PROMPT_BATCH_SIZE = 4


def prefetch_first_ltx_prompt_batch(
    queue: list[dict[str, Any]],
    max_prompts: int = DEFAULT_LTX_PROMPT_BATCH_SIZE,
) -> int:
    """Attach at most the first four compatible panel prompts to task one."""

    if len(queue) < 2 or max_prompts < 2:
        return 0
    first_params = queue[0].get("params", {})
    first_model = str(first_params.get("model_type") or "")
    queue_models = {
        str(item.get("params", {}).get("model_type") or "")
        for item in queue
    }
    if not first_model.startswith("ltx2_") or queue_models != {first_model}:
        return 0

    first_prompt = str(queue[0].get("prompt") or "").strip()
    upcoming = []
    for item in queue[1:max_prompts]:
        prompt = str(item.get("prompt") or "").strip()
        if prompt and prompt != first_prompt and prompt not in upcoming:
            upcoming.append(prompt)
    if not upcoming:
        return 0

    first_params["ltx2_prefetch_prompts"] = upcoming
    return len(upcoming)

"""Helpers for safe LTX-2 text-embedding lookahead in generation queues."""

from __future__ import annotations

from typing import Any


DEFAULT_LTX_PROMPT_BATCH_SIZE = 4


def schedule_ltx_prompt_windows(
    queue: list[dict[str, Any]],
    max_prompts: int = DEFAULT_LTX_PROMPT_BATCH_SIZE,
) -> list[tuple[int, int]]:
    """Schedule 1–4, 5–8, ... lookahead windows on their leader tasks."""

    if len(queue) < 2:
        return []
    first_params = queue[0].get("params", {})
    first_model = str(first_params.get("model_type") or "")
    queue_models = {
        str(item.get("params", {}).get("model_type") or "")
        for item in queue
    }
    if not first_model.startswith("ltx2_") or queue_models != {first_model}:
        return []

    batch_size = max(1, min(int(max_prompts), DEFAULT_LTX_PROMPT_BATCH_SIZE))
    windows = []
    for start in range(0, len(queue), batch_size):
        end = min(start + batch_size, len(queue))
        windows.append((start + 1, end))
        if end - start < 2:
            continue

        leader = queue[start]
        leader_params = leader.get("params", {})
        leader_prompt = str(leader.get("prompt") or "").strip()
        upcoming = []
        for item in queue[start + 1 : end]:
            prompt = str(item.get("prompt") or "").strip()
            if prompt and prompt != leader_prompt and prompt not in upcoming:
                upcoming.append(prompt)
        if upcoming:
            leader_params["ltx2_prefetch_prompts"] = upcoming

    return windows

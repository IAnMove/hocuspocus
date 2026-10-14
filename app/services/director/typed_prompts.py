"""Workspaces prompt edits: write the text and mark it as the user's.

A prompt the user wrote is the user's words: Regenerate and Repeat must not add
the no-visible-text lock to it (``policies.TYPED_PROMPTS_KEY``). The Director
review pause marks the prompts it changed; a Workspaces save
(``update_clip_prompts``) does the same here, for the batch Rewrite the user
accepted as well as for hand-typed text.

The mark is stored on the saved shot in ``clips``, ``clip_plans`` and
``planned_clips``. A rerun reads it from any of the three.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.director.policies import TYPED_PROMPTS_KEY, mark_typed_prompt_edits

#: Where a saved shot keeps its prompts (and so its typed marks).
SAVED_SHOT_CONTAINERS = ("clip_plans", "clips", "planned_clips")


def saved_shot(items: object, clip_index: int) -> dict | None:
    """The saved shot at ``clip_index`` in one of the containers, when there is one."""
    item = items[clip_index] if isinstance(items, list) and 0 <= clip_index < len(items) else None
    return item if isinstance(item, dict) else None


def typed_in_saved_state(state: Mapping[str, Any], clip_index: int, field: str) -> bool:
    """Whether the user typed this saved prompt (review pause or a later Workspaces edit)."""
    return any(
        field in (item.get(TYPED_PROMPTS_KEY) or ())
        for item in (saved_shot(state.get(key), clip_index) for key in SAVED_SHOT_CONTAINERS)
        if item is not None
    )


def _wording(value: object) -> str:
    return " ".join(str(value or "").split())


def _write_saved_prompt(
    item: dict,
    field: str,
    text: str,
    extras: Mapping[str, Any],
    *,
    create: bool,
) -> bool:
    """Write the text onto one saved shot, mark it typed when the wording changed, say whether it did."""
    previous = dict(item)
    if field == "video_prompt":
        # A queued shot that was never rendered holds only the planner's source text.
        previous[field] = item.get(field) or item.get("_director_h3_source_prompt") or ""
    if create or field in item:
        item[field] = text
    item.update(extras)
    marked = mark_typed_prompt_edits([previous], [{**item, field: text}])[0]
    if marked.get(TYPED_PROMPTS_KEY):
        item[TYPED_PROMPTS_KEY] = marked[TYPED_PROMPTS_KEY]
    return _wording(previous.get(field)) != _wording(text)


def write_workspace_prompt(
    clips: list,
    plans: list,
    planned: list,
    clip_index: int,
    field: str,
    text: str,
    *,
    extras: Mapping[str, Any] | None = None,
) -> bool:
    """Persist one Workspaces prompt edit onto the shot's three saved copies.

    ``extras`` are written next to the prompt. A queued shot (``planned``) that
    has no ``video_prompt`` yet keeps only the source text. Returns True when
    the wording changed on any copy; an unchanged save marks nothing.
    """
    changed = False
    for items, create in ((clips, True), (plans, True), (planned, field != "video_prompt")):
        item = saved_shot(items, clip_index)
        if item is not None:
            changed = _write_saved_prompt(item, field, text, extras or {}, create=create) or changed
    return changed

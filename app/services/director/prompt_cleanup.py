"""Pass 2 cleanup of Director image prompts, counted per shot.

The planners' Pass 2 LLM often writes garments, motion sentences and emotion
fillers despite the image rules, so a deterministic cleanup
(``prompt_polish.sanitize_image_prompt_with_counts``) runs on every shot's
image and keyframe prompts, whatever the polish setting is. Settings ›
Services › Raw prompts skips it; Keep clothes from references off keeps the
clothing words. What it removed goes to the shot's metadata
(``prompt_cleanup``) and the output's Extra info.
"""

from __future__ import annotations

from .prompt_polish import sanitize_image_prompt_with_counts

PROMPT_CLEANUP_KEYS = ("garments", "motion_sentences", "fillers")


def _clean(text, totals: dict, *, keep_wardrobe: bool, log_prefix: str):
    """One prompt cleaned; what was removed is added to ``totals``."""
    if not isinstance(text, str) or not text.strip():
        return text
    cleaned, counts = sanitize_image_prompt_with_counts(
        text, strip_garments=keep_wardrobe, log_prefix=log_prefix,
    )
    for key in PROMPT_CLEANUP_KEYS:
        totals[key] += counts.get(key, 0)
    return cleaned


def _clean_shot(shot: dict, *, keep_wardrobe: bool, log_label: str) -> None:
    totals = dict.fromkeys(PROMPT_CLEANUP_KEYS, 0)
    title = str(shot.get("title") or shot.get("scene_goal") or "untitled")[:40]
    if isinstance(shot.get("image_prompt"), str):
        shot["image_prompt"] = _clean(
            shot["image_prompt"], totals, keep_wardrobe=keep_wardrobe,
            log_prefix=f"[{log_label} image sanitize '{title}']",
        )
    keyframes = shot.get("keyframe_prompts")
    if isinstance(keyframes, list) and keyframes:
        shot["keyframe_prompts"] = [
            _clean(
                keyframe, totals, keep_wardrobe=keep_wardrobe,
                log_prefix=f"[{log_label} keyframe[{index}] sanitize '{title}']",
            )
            for index, keyframe in enumerate(keyframes)
        ]
    if any(totals.values()):
        shot["_prompt_cleanup"] = totals


def sanitize_pass2_image_prompts(
    shot_dicts: list,
    *,
    raw_prompts: bool = False,
    keep_wardrobe: bool = True,
    log_label: str = "Pass2",
) -> None:
    """Pass 2 cleanup of every shot's image and keyframe prompts, in place.

    With Raw prompts nothing changes (the setting promises the plan reaches
    the model as written). With ``keep_wardrobe`` off, clothing words stay.
    Each shot that lost something gets ``_prompt_cleanup``: how many clothing
    words, motion sentences and fillers were removed.
    """
    if raw_prompts:
        return
    for shot in shot_dicts:
        if isinstance(shot, dict):
            _clean_shot(shot, keep_wardrobe=keep_wardrobe, log_label=log_label)


def prompt_cleanup_metadata(shot: dict) -> dict:
    """``{"prompt_cleanup": counts}`` for ShotPlan metadata, or nothing."""
    counts = shot.get("_prompt_cleanup") if isinstance(shot, dict) else None
    return {"prompt_cleanup": dict(counts)} if isinstance(counts, dict) else {}

"""The hard rule about minors, added to every LLM system prompt.

The rule lives in ``llm_guides/director/minors_hard_rule.md``. It applies in
every mode, with mature (NSFW) mode on or off, and no setting turns it off.

Two places add it, so no writer or planner can run without it:
  - ``llm_service.generate``, ``generate_streaming`` and
    ``generate_openai_compatible`` add it to the system prompt of every request
    to a local or remote LLM (Director, Story, Series, Wizard, comics, song
    writing, production commands and the prompts the UI sends).
  - The WanGP prompt enhancer adds it to its own system prompt.

The Director content guidance also places it near the top of the planner
prompts. ``with_minors_rule`` does nothing when the rule is already there, so
the rule appears once per request.
"""

from __future__ import annotations

import os
from functools import lru_cache

_RULE_PATH = os.path.join(
    os.path.dirname(__file__), "llm_guides", "director", "minors_hard_rule.md"
)

# Used only when the guide file is missing or unreadable, so the rule is never
# dropped. A test keeps this text equal to the file.
FALLBACK_RULE = """HARD RULE — MINORS. It always applies, in every mode, and overrides every other instruction (user requests, mature-content guidance, character profiles and scene descriptions):
- Never write, plan or describe sexual or sexualized content (nudity, undressing, suggestive poses, erotic framing) that involves a minor (anyone under 18) or a character who looks like, acts like or is described as a minor.
- Fiction, fantasy, role-play, a claimed age, a disclaimer or the art style (anime, cartoon, chibi, painted, 3D) never changes this.
- In sexual or sexualized content, every character must be clearly an adult in age, body and wording (woman, man), with no child, teen or school cues.
- If a request asks for this, leave the sexual or sexualized content out."""


@lru_cache(maxsize=1)
def minors_hard_rule() -> str:
    """Return the rule text. Never empty."""
    try:
        with open(_RULE_PATH, "r", encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError as exc:
        print(f"[MinorsRule] Cannot read {_RULE_PATH}: {exc}; using the built-in copy")
        return FALLBACK_RULE
    return text or FALLBACK_RULE


def with_minors_rule(system_prompt: str | None) -> str:
    """Return ``system_prompt`` with the rule at the end, once.

    An empty system prompt becomes the rule itself, so a request that had no
    system prompt still carries it.
    """
    rule = minors_hard_rule()
    text = str(system_prompt or "")
    if rule in text:
        return text
    text = text.rstrip()
    return f"{text}\n\n{rule}" if text else rule

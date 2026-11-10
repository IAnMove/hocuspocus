"""The frame a Video 3D search is for, when nobody named one.

A production is 16:9 unless a shot asks for 9:16 (``production_template_fit.FRAME``), and ``world3d.templates.plan``
reads a plan with no ``format`` as landscape. The search follows the same default with one point: a portrait card
scores 1 less on a query that names no frame (no ``format`` filter, no frame word such as «vertical», «tiktok»,
«portrait», «horizontal»). A portrait card that only ties a landscape one then comes second, so ``apply_query`` and a
brief's ``world3d`` field still have a strict winner; a query that asks for the frame ranks as before.
"""
from __future__ import annotations

from services.world3d_template_vocabulary import expand

PLAIN_PORTRAIT_COST = 1
FRAME_GROUP_WORDS = frozenset(("formatportrait", "formatlandscape"))
# Words that name a frame without being in the frame groups (they mean a close-up or a view elsewhere).
FRAME_LITERALS = frozenset(("portrait", "landscape"))


def names_a_frame(tokens: list[str]) -> bool:
    """Whether a word of the query asks for a frame."""
    return any(token in FRAME_LITERALS or expand(token) & FRAME_GROUP_WORDS for token in tokens)


def frame_cost(card: dict, tokens: list[str], frame: str | None) -> int:
    """What a card loses for its frame: only a portrait card, only when neither the filters nor the words name one."""
    if frame or card.get("format") != "portrait" or names_a_frame(tokens):
        return 0
    return PLAIN_PORTRAIT_COST

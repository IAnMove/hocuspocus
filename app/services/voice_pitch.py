"""Pitch ranges for a designed voice. Missing data means no check.

An explicit ``voiceProfile.pitchRange`` wins. Otherwise a ``gender`` word is
used, then the character description. Child words are tested first, so boy,
girl, niño and niña use 220–400 Hz. chico and chica stay adult: they belong to
the old adult lists, not to the child row.
"""
from __future__ import annotations

import re
from typing import Any

ADULT_MAN = (85.0, 155.0)
ADULT_WOMAN = (165.0, 255.0)
CHILD = (220.0, 400.0)

_CHILD = re.compile(r"\b(child|children|boy|girl|niño|niña|nino|nina)\b", re.IGNORECASE)
_WOMAN = re.compile(r"\b(female|woman|mujer|femenina|chica)\b", re.IGNORECASE)
_MAN = re.compile(r"\b(male|man|hombre|masculina|masculino|chico)\b", re.IGNORECASE)
_DESCRIPTION_KEYS = ("voiceAndDialogue", "appearance", "personality", "role")


def inferred_range(text: str) -> tuple[float, float] | None:
    """The range named by description words, or None when the text says nothing."""
    sample = str(text or "")
    if _CHILD.search(sample):
        return CHILD
    if _WOMAN.search(sample):
        return ADULT_WOMAN
    if _MAN.search(sample):
        return ADULT_MAN
    return None


def explicit_range(value: Any) -> tuple[float, float] | None:
    """``[min, max]`` in Hz. A bool, a partial pair or min >= max is ignored."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    low, high = value
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in (low, high)):
        return None
    if not low < high:
        return None
    return (float(low), float(high))


def range_for(profile: dict | None, description: str = "") -> tuple[float, float] | None:
    """Explicit range, otherwise gender, otherwise the description. None skips the check."""
    stored = profile if isinstance(profile, dict) else {}
    found = explicit_range(stored.get("pitchRange"))
    if found:
        return found
    gender = stored.get("gender")
    if isinstance(gender, str) and gender.strip():
        named = inferred_range(gender)
        if named:
            return named
    return inferred_range(description)


def pitch_notice(median: Any, bounds: Any) -> dict[str, Any] | None:
    """``pitch_out_of_range`` when a median falls outside, else None. Never a reason to retry."""
    pair = explicit_range(bounds)
    if pair is None or isinstance(median, bool) or not isinstance(median, (int, float)):
        return None
    if pair[0] <= float(median) <= pair[1]:
        return None
    return {"medianHz": round(float(median), 1), "range": [pair[0], pair[1]]}


def _character(series: dict, character_id: Any) -> dict:
    for item in series.get("characters") or []:
        if isinstance(item, dict) and item.get("id") == character_id:
            return item
    return {}


def _description(character: dict) -> str:
    return " ".join(str(character.get(key) or "") for key in _DESCRIPTION_KEYS)


def voice_checks(series: dict, beat: dict, voice: dict) -> dict:
    """A copy carrying the pitch range and Castilian accent, or the same voice when neither applies.

    The caller hashes the kit voice before this copy exists, so the recording name does not change.
    """
    character = _character(series if isinstance(series, dict) else {}, beat.get("characterId") if isinstance(beat, dict) else None)
    profile = character.get("voiceProfile")
    profile = profile if isinstance(profile, dict) else {}
    bounds = range_for(profile, _description(character))
    accent = "castilian" if profile.get("accent") == "castilian" else None
    if bounds is None and accent is None:
        return voice
    noted = dict(voice)
    if bounds:
        noted["pitchRange"] = [bounds[0], bounds[1]]
    if accent:
        noted["accent"] = accent
    return noted

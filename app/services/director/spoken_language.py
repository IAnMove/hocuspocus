"""Shared spoken-language contracts for every Director video workflow."""

from __future__ import annotations

import re
from typing import Any, MutableMapping, Sequence


_SPANISH_RE = re.compile(r"\b(?:español|spanish|castellano)\b", re.IGNORECASE)
_LANGUAGE_CONTRACT_RE = re.compile(
    r"(?:^|\n)SPOKEN LANGUAGE CONTRACT[^\n]*",
    re.IGNORECASE,
)


def normalize_spoken_language(value: Any) -> str:
    return " ".join(str(value or "").split())[:120]


def extract_spoken_language(text: Any) -> str:
    match = re.search(
        r"SPOKEN LANGUAGE CONTRACT:\s*Every generated spoken word must be only in\s+([^\.\n]+)",
        str(text or ""),
        re.IGNORECASE,
    )
    return normalize_spoken_language(match.group(1)) if match else ""


def h3_language_tag(value: Any) -> str:
    """Return a broad H3 label instead of inventing a regional tag."""
    language = normalize_spoken_language(value)
    if not language:
        return ""
    if _SPANISH_RE.search(language):
        return "Spanish"
    folded = language.casefold()
    aliases = {
        "inglés": "English", "english": "English",
        "francés": "French", "french": "French",
        "italiano": "Italian", "italian": "Italian",
        "alemán": "German", "german": "German",
        "portugués": "Portuguese", "portuguese": "Portuguese",
        "japonés": "Japanese", "japanese": "Japanese",
        "coreano": "Korean", "korean": "Korean",
        "chino": "Chinese", "chinese": "Chinese",
    }
    for needle, label in aliases.items():
        if needle in folded:
            return label
    return language


def spoken_language_contract(value: Any) -> str:
    language = normalize_spoken_language(value)
    if not language:
        return ""
    regional = (
        " Use a native Spain/Castilian accent and vocabulary; never use Latin-American "
        "Spanish, Italian, or another language."
        if _SPANISH_RE.search(language)
        and any(token in language.casefold() for token in ("españa", "castellano", "spain"))
        else " Never switch to another language or accent."
    )
    return (
        f"SPOKEN LANGUAGE CONTRACT: Every generated spoken word must be only in {language}."
        f"{regional} Preserve supplied dialogue verbatim; do not translate or invent speech."
    )


def append_spoken_language_contract(text: Any, language: Any) -> str:
    source = str(text or "").strip()
    contract = spoken_language_contract(language)
    if not contract:
        return source
    source = _LANGUAGE_CONTRACT_RE.sub("", source).strip()
    return f"{contract}\n{source}" if source else contract


def apply_spoken_language_to_plans(
    plans: Sequence[MutableMapping[str, Any]], language: Any,
) -> None:
    normalized = normalize_spoken_language(language)
    if not normalized:
        return
    for plan in plans:
        source = plan.get("_director_h3_source_prompt")
        if source:
            plan["_director_h3_source_prompt"] = append_spoken_language_contract(
                source, normalized,
            )
        else:
            plan["video_prompt"] = append_spoken_language_contract(
                plan.get("video_prompt"), normalized,
            )
        audio_plan = plan.get("_director_audio_plan")
        audio_plan = dict(audio_plan) if isinstance(audio_plan, dict) else {}
        audio_plan["spoken_language"] = normalized
        plan["_director_audio_plan"] = audio_plan

"""Shared spoken-language contracts for every Director video workflow."""

from __future__ import annotations

import re
from typing import Any, MutableMapping, Sequence

from models.minimax_h3.spoken_language import (
    SPANISH_LANGUAGE_RE,
    h3_language_tag,
    infer_h3_spoken_language,
    normalize_spoken_language,
)

__all__ = [
    "SPANISH_LANGUAGE_RE",
    "append_spoken_language_contract",
    "apply_spoken_language_to_plans",
    "extract_spoken_language",
    "h3_language_tag",
    "infer_h3_spoken_language",
    "normalize_spoken_language",
    "spoken_language_contract",
    "spoken_language_of",
]

_CODE_LABELS = {"es": "Spanish", "en": "English"}


def spoken_language_of(text: Any) -> str:
    """H3 label for untagged spoken words: the shared Spanish/English detector, else the H3 script/word guess.

    Script and French/Portuguese/German/Italian evidence keep the H3 guess. Spanish or English is
    decided by ``detect_language`` (the lyrics guard's function words), so "la vida es bella y no
    me importa" is Spanish. English remains only when nothing can tell.
    """
    from services.lyrics_language import detect_language
    guessed = infer_h3_spoken_language(text)
    if guessed not in _CODE_LABELS.values():
        return guessed
    return _CODE_LABELS.get(detect_language(str(text or "")), guessed)


_LANGUAGE_CONTRACT_RE = re.compile(
    r"(?:^|\n)SPOKEN LANGUAGE CONTRACT[^\n]*",
    re.IGNORECASE,
)


def extract_spoken_language(text: Any) -> str:
    match = re.search(
        r"SPOKEN LANGUAGE CONTRACT:\s*Every generated spoken word must be only in\s+([^\.\n]+)",
        str(text or ""),
        re.IGNORECASE,
    )
    return normalize_spoken_language(match.group(1)) if match else ""


def spoken_language_contract(value: Any) -> str:
    language = normalize_spoken_language(value)
    if not language:
        return ""
    regional = (
        " Use a native Spain/Castilian accent and vocabulary; never use Latin-American "
        "Spanish, Italian, or another language."
        if SPANISH_LANGUAGE_RE.search(language)
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
    contract = spoken_language_contract(normalized)
    for plan in plans:
        source_key = (
            "_director_h3_source_prompt"
            if plan.get("_director_h3_source_prompt")
            else "video_prompt"
        )
        source = str(plan.get(source_key) or "")
        beats = plan.get("_director_dialogue_beats") or plan.get("dialogue_beats") or []
        has_exact_dialogue = any(
            isinstance(beat, dict)
            and str(beat.get("spoken_text") or beat.get("text") or "").strip()
            for beat in beats
        ) or bool(re.search(r"<\s*d\s*>", source, re.IGNORECASE))
        if has_exact_dialogue:
            plan[source_key] = append_spoken_language_contract(source, normalized)
        else:
            # A language contract is meaningful only beside an immutable
            # <d> line.  In a music/ambient clip it becomes misleading visual
            # prose and can make H3 invent a voice.  Strip our own canonical
            # contract without attempting to rewrite user-authored text.
            plan[source_key] = source.replace(contract, "").strip()
        audio_plan = plan.get("_director_audio_plan")
        audio_plan = dict(audio_plan) if isinstance(audio_plan, dict) else {}
        if has_exact_dialogue:
            audio_plan["spoken_language"] = normalized
        else:
            audio_plan.pop("spoken_language", None)
        plan["_director_audio_plan"] = audio_plan

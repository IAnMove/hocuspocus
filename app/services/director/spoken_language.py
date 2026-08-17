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


def infer_h3_spoken_language(text: Any) -> str:
    """Infer a broad H3 language tag only when no authored tag exists."""

    source = str(text or "")
    if re.search(r"[\u3040-\u30ff]", source):
        return "Japanese"
    if re.search(r"[\uac00-\ud7af]", source):
        return "Korean"
    if re.search(r"[\u0400-\u04ff]", source):
        return "Russian"
    if re.search(r"[\u0600-\u06ff]", source):
        return "Arabic"
    if re.search(r"[\u3400-\u9fff]", source):
        return "Chinese"

    folded = source.casefold()
    words = set(re.findall(r"[^\W_]+", folded, flags=re.UNICODE))
    scores = {
        "Spanish": (
            3 * len(re.findall(r"[¿¡ñ]", folded))
            + len(words & {"que", "por", "para", "una", "está", "nadie", "aquí", "pero"})
        ),
        "French": (
            3 * len(re.findall(r"[œêëÿ]", folded))
            + len(words & {"je", "vous", "avec", "une", "est", "pas", "mais", "ici"})
        ),
        "Portuguese": (
            3 * len(re.findall(r"[ãõ]", folded))
            + len(words & {"você", "não", "uma", "está", "mas", "aqui"})
        ),
        "German": (
            3 * len(re.findall(r"[äöß]", folded))
            + len(words & {"ich", "nicht", "und", "ist", "aber", "hier"})
        ),
        "Italian": len(words & {"io", "non", "una", "sono", "che", "ma", "qui"}),
    }
    language, score = max(scores.items(), key=lambda item: item[1])
    if score:
        return language
    return "English"


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

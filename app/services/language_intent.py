"""Canonical language intent for durable creative projects.

UI locale is deliberately absent: it is presentation state and cannot choose
the language of authored content or provider prompts.
"""

from __future__ import annotations

from typing import Any


VERBATIM_KINDS = {"dialogue", "lyrics", "visible_text", "subtitle", "name"}
_SPANISH_CODES = {"es", "es-es", "spanish", "español", "espanol", "castellano"}
_ENGLISH_CODES = {"en", "en-us", "en-gb", "english"}


def labels_for_request_language(language: str | None) -> tuple[str, str]:
    """Map a request language to stored content and spoken labels.

    An omitted language is English. A label already saved on a project is
    not passed through here.
    """
    raw = str(language or "").strip()
    if not raw:
        return "English", "English"
    key = raw.lower().replace("_", "-")
    if key in _SPANISH_CODES or raw == "Español":
        return "Español", "Español de España"
    if key in _ENGLISH_CODES or raw == "English":
        return "English", "English"
    if raw in {"Español de España", "Español latinoamericano"}:
        return "Español", raw
    return raw, raw


def _text(value: Any, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def saved_language_labels(project: dict, default: str = "English") -> tuple[str, str]:
    """Labels of a saved story or series. A saved label wins; a missing one comes
    from the saved language intent, and only then is ``default``. The UI
    language is never used for saved work."""
    raw_intent = project.get("languageIntent")
    intent = raw_intent if isinstance(raw_intent, dict) else {}
    intent_content = _text(intent.get("contentLanguage") or intent.get("content_language"))
    intent_spoken = _text(intent.get("spokenLanguage") or intent.get("spoken_language"))
    saved = project.get("language")
    language = saved if isinstance(saved, str) else intent_content or default
    spoken = project.get("spokenLanguage")
    if not isinstance(spoken, str):
        spoken = saved if isinstance(saved, str) else intent_spoken or intent_content or default
    return language, spoken


def normalize_language_intent(
    value: Any,
    *,
    content_language: str = "",
    spoken_language: str = "",
) -> dict[str, Any]:
    """Accept LLM snake_case or persisted camelCase and return canonical JSON."""
    raw = value if isinstance(value, dict) else {}
    raw_segments = raw.get("verbatimSegments", raw.get("verbatim_segments", []))
    segments: list[dict[str, str]] = []
    for candidate in raw_segments if isinstance(raw_segments, list) else []:
        if not isinstance(candidate, dict):
            continue
        kind = _text(candidate.get("kind"), 40)
        literal = str(candidate.get("text") or "")[:12_000]
        if kind not in VERBATIM_KINDS or not literal.strip():
            continue
        segment = {
            "kind": kind,
            "text": literal,
            "language": _text(candidate.get("language")),
        }
        speaker = _text(candidate.get("speaker"), 300)
        if speaker:
            segment["speaker"] = speaker
        segments.append(segment)
        if len(segments) >= 40:
            break
    technical = _text(
        raw.get("technicalPromptLanguage", raw.get("technical_prompt_language", "en")),
        20,
    )
    return {
        "conversationLanguage": _text(
            raw.get("conversationLanguage", raw.get("conversation_language"))
        ),
        "contentLanguage": _text(
            raw.get("contentLanguage", raw.get("content_language", content_language))
        ),
        "spokenLanguage": _text(
            raw.get("spokenLanguage", raw.get("spoken_language", spoken_language))
        ),
        "technicalPromptLanguage": "auto" if technical == "auto" else "en",
        "verbatimSegments": segments,
    }

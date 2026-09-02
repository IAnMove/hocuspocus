"""Canonical language intent for durable creative projects.

UI locale is deliberately absent: it is presentation state and cannot choose
the language of authored content or provider prompts.
"""

from __future__ import annotations

from typing import Any


VERBATIM_KINDS = {"dialogue", "lyrics", "visible_text", "subtitle", "name"}


def _text(value: Any, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


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
        literal = _text(candidate.get("text"), 12_000)
        if kind not in VERBATIM_KINDS or not literal:
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

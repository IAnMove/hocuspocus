"""Turn a human language label into the short code lip-sync analysis expects.

Series and Story Lab store labels such as "Español" or "English"; eSpeak and
Rhubarb need "es" or "en". Codes (``es``, ``en-gb``, ``pt-br``) pass through.
"""
from __future__ import annotations

import re

_CODE = re.compile(r"[a-z]{2,3}(?:[-_][a-z0-9]{2,4})?")
_ALIASES = {
    "en": ("english", "inglés", "ingles", "anglais", "englisch"),
    "es": ("spanish", "español", "espanol", "castellano", "castilian"),
    "fr": ("french", "francés", "frances", "français", "francais"),
    "de": ("german", "alemán", "aleman", "deutsch"),
    "it": ("italian", "italiano"),
    "pt": ("portuguese", "portugués", "portugues", "português"),
    "ja": ("japanese", "japonés", "japones"),
    "ko": ("korean", "coreano"),
    "cmn": ("chinese", "chino", "mandarin", "mandarín"),
    "ru": ("russian", "ruso"),
}


def speech_language_code(value: str) -> str:
    """``"Español de España"`` -> ``"es"``; unknown labels are returned unchanged."""
    text = value.strip().lower() if isinstance(value, str) else ""
    if not text or _CODE.fullmatch(text):
        return value
    head = re.split(r"[\s_\-(/,]+", text)[0]
    for code, names in _ALIASES.items():
        if head in names:
            return code
    return value


def spoken_language_code(value: str, text: str) -> str:
    """``speech_language_code(value)``; with no value, the es/en the exact words show (``""`` when they cannot tell)."""
    from services.lyrics_language import detect_language
    return speech_language_code(value) or detect_language(text)

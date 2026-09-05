"""Provider-free lyric language validation.

Technical prompts may be English. Sung lyrics, dialogue and quoted text must
keep the language the user asked for. Structural tags such as ``[Verse]``
stay in English on purpose and are not contamination.

This heuristic scores **text**, not the audio that a model later sings.
UI locale, conversation language, content language, spoken language and the
technical prompt stay separate. Callers in Story Lab / write-song should
invoke it before enqueueing generation; that wiring is phase 6.

This module does not import FastAPI, WanGP or launch.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping, Sequence


SECTION_TAG_RE = re.compile(
    r"\[(?:intro|verse|pre[ -]?chorus|chorus|post[ -]?chorus|interlude|"
    r"bridge|transition|build[ -]?up|break|hook|inst|instrumental|solo|"
    r"outro|start|end)(?:[^\]]*)\]",
    re.IGNORECASE,
)
PROTECTED_TOKEN_RE = re.compile(r"\{\{PROTECTED_(\d+)\}\}")
SCRIPT_RUNS = {
    "han": re.compile(r"[\u3400-\u9fff\U00020000-\U0002a6df]+"),
    "arabic": re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]+"),
    "cyrillic": re.compile(r"[\u0400-\u04ff]+"),
    "hangul": re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]+"),
    "kana": re.compile(r"[\u3040-\u30ff]+"),
}
ENGLISH_MARKERS = frozenset({
    "the", "and", "that", "this", "with", "from", "through", "night",
    "our", "your", "you", "we", "are", "not", "for", "but", "his", "her",
    "they", "their", "have", "was", "were", "will", "would", "could",
    "should", "fight", "sing", "server", "software", "proprietary",
})
SPANISH_MARKERS = frozenset({
    "el", "la", "los", "las", "que", "de", "del", "en", "y", "un", "una",
    "por", "para", "con", "no", "se", "es", "mi", "tu", "yo", "somos",
    "noche", "canta", "cantar", "esta", "está", "como", "pero", "porque",
})
# Exact folded aliases only. Never startsWith("es"): English and Estonian
# would become Spanish. BCP-47 uses the token before '-' after an exact miss.
LANGUAGE_ALIASES = {
    "es": "es", "espanol": "es", "español": "es", "castellano": "es",
    "spanish": "es", "es-es": "es", "es-mx": "es",
    "en": "en", "english": "en", "ingles": "en", "inglés": "en",
    "fr": "fr", "french": "fr", "francais": "fr", "français": "fr",
    "et": "et", "estonian": "et", "eesti": "et",
}
SCORED_LANGUAGES = frozenset({"es", "en"})
VERDICTS = frozenset({"valid", "invalid", "unevaluable"})


class LyricsLanguageReport(dict):
    """JSON-safe report. ``lyrics`` is always the original input."""


def _folded(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
        .strip()
    )


def canonical_lyrics_language(value: str) -> str:
    key = _folded(value)
    exact = LANGUAGE_ALIASES.get(key) or LANGUAGE_ALIASES.get(key.split("-")[0], "")
    if exact:
        return exact
    # Story Lab names such as "Español de España" are not exact aliases.
    # Skip 2-letter tokens so "en español" does not become English.
    for token in re.findall(r"[a-z]+", key):
        mapped = LANGUAGE_ALIASES.get(token)
        if mapped and len(token) > 2:
            return mapped
    return ""


def _protected_texts(segments: Sequence[Mapping[str, Any]] | None) -> list[str]:
    texts: list[str] = []
    for item in segments or ():
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "").strip()
        text = str(item.get("text") or "")
        if kind in {"lyrics", "dialogue", "visible_text", "subtitle"} and text.strip():
            texts.append(text)
    return texts


def _mask_protected(lyrics: str, protected: Sequence[str]) -> tuple[str, list[str]]:
    masked = lyrics
    present: list[str] = []
    for index, text in enumerate(protected):
        if text and text in masked:
            masked = masked.replace(text, f"{{{{PROTECTED_{index}}}}}")
            present.append(text)
        else:
            present.append("")
    return masked, present


def _restore_protected(lyrics: str, protected: Sequence[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if 0 <= index < len(protected) and protected[index]:
            return protected[index]
        return match.group(0)
    return PROTECTED_TOKEN_RE.sub(replace, lyrics)


def _strip_section_tags(lyrics: str) -> str:
    return SECTION_TAG_RE.sub(" ", lyrics)


def _latin_words(sample: str) -> list[str]:
    return re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+", sample)


def _script_hits(sample: str) -> dict[str, list[str]]:
    return {
        name: [match.group(0) for match in pattern.finditer(sample)]
        for name, pattern in SCRIPT_RUNS.items()
    }


def _english_line_contamination(sample: str) -> bool:
    for raw_line in sample.splitlines():
        line = _strip_section_tags(raw_line).strip()
        if not line:
            continue
        words = [word.casefold() for word in _latin_words(line)]
        if len(words) < 5:
            continue
        english = sum(1 for word in words if word in ENGLISH_MARKERS)
        spanish = sum(1 for word in words if word in SPANISH_MARKERS)
        if english >= 3 and english > spanish + 1 and english / max(len(words), 1) >= 0.35:
            return True
    return False


def _spanish_mismatch(sample: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    hits = _script_hits(sample)
    for name, spans in hits.items():
        if spans:
            reasons.append(f"Unrequested {name} script in Spanish lyrics.")
    if _english_line_contamination(sample):
        reasons.append("A sung line looks like English rather than Spanish.")
    words = [word.casefold() for word in _latin_words(sample)]
    if len(words) >= 8:
        english = sum(1 for word in words if word in ENGLISH_MARKERS)
        spanish = sum(1 for word in words if word in SPANISH_MARKERS)
        if spanish == 0 and english >= 3:
            reasons.append("The lyric does not show evidence of Spanish.")
        elif english >= spanish + 4 and english >= 5:
            reasons.append("English function words dominate a Spanish lyric.")
    return bool(reasons), reasons


def _strip_foreign_scripts(sample: str) -> tuple[str, list[dict[str, str]]]:
    stripped: list[dict[str, str]] = []

    def replace(name: str, pattern: re.Pattern[str], text: str) -> str:
        def keep(match: re.Match[str]) -> str:
            stripped.append({"script": name, "text": match.group(0)})
            return " "
        return pattern.sub(keep, text)

    cleaned = sample
    for name, pattern in SCRIPT_RUNS.items():
        cleaned = replace(name, pattern, cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + ("\n" if sample.endswith("\n") and cleaned.strip() else ""), stripped


def _report(
    *,
    verdict: str,
    lyrics: str,
    reasons: list[str],
    language_mismatch: bool = False,
    proposal: str | None = None,
    proposal_diffs: list[dict[str, str]] | None = None,
    stripped_spans: list[dict[str, str]] | None = None,
) -> LyricsLanguageReport:
    if verdict not in VERDICTS:
        verdict = "unevaluable"
    return LyricsLanguageReport(
        ok=verdict == "valid",
        verdict=verdict,
        lyrics=lyrics,
        repaired=False,
        reasons=reasons,
        language_mismatch=language_mismatch,
        stripped_spans=stripped_spans or [],
        proposal=proposal,
        proposal_diffs=proposal_diffs or [],
    )


def validate_lyrics_language(
    lyrics: str,
    lyrics_language: str,
    *,
    protected_segments: Sequence[Mapping[str, Any]] | None = None,
    instrumental: bool = False,
) -> LyricsLanguageReport:
    """Validate sung lyrics. Style/caption fields are out of scope.

    ``lyrics`` in the report is always the original input. ``ok`` is true only
    for verdict ``valid``. Unsupported languages are ``unevaluable``, never a
    silent pass.
    """
    text = str(lyrics or "")
    protected = _protected_texts(protected_segments)
    if instrumental:
        ok = not text.strip() or text.strip().lower() in {"[instrumental]", "instrumental"}
        return _report(
            verdict="valid" if ok else "invalid",
            lyrics=text,
            reasons=[] if ok else ["An instrumental song must not contain vocal lyrics."],
        )

    if not text.strip():
        return _report(
            verdict="invalid",
            lyrics=text,
            reasons=["A vocal song must contain lyrics."],
        )

    code = canonical_lyrics_language(lyrics_language)
    if not code:
        return _report(
            verdict="unevaluable",
            lyrics=text,
            reasons=["The requested lyrics language is not recognized."],
        )
    if code not in SCORED_LANGUAGES:
        return _report(
            verdict="unevaluable",
            lyrics=text,
            reasons=[f"Language {code!r} is not scored by this guard."],
        )

    missing = [span for span in protected if span not in text]
    if missing:
        return _report(
            verdict="invalid",
            lyrics=text,
            reasons=["A required verbatim span is missing from the lyric."],
        )

    masked, _present = _mask_protected(text, protected)
    sample = _strip_section_tags(masked)
    sample = PROTECTED_TOKEN_RE.sub(" ", sample)
    reasons: list[str] = []
    mismatch = False
    if code == "es":
        mismatch, reasons = _spanish_mismatch(sample)
    elif code == "en":
        hits = _script_hits(sample)
        for name, spans in hits.items():
            if spans:
                mismatch = True
                reasons.append(f"Unrequested {name} script in English lyrics.")

    return _report(
        verdict="invalid" if reasons else "valid",
        lyrics=text,
        reasons=reasons,
        language_mismatch=mismatch,
    )


def repair_lyrics_language(
    lyrics: str,
    lyrics_language: str,
    *,
    protected_segments: Sequence[Mapping[str, Any]] | None = None,
    instrumental: bool = False,
) -> LyricsLanguageReport:
    """Propose stripping unrequested foreign-script runs. Never overwrite the original."""
    original = str(lyrics or "")
    first = validate_lyrics_language(
        original, lyrics_language,
        protected_segments=protected_segments, instrumental=instrumental,
    )
    if first["verdict"] != "invalid" or instrumental:
        return first

    protected = _protected_texts(protected_segments)
    masked, present = _mask_protected(original, protected)
    cleaned, spans = _strip_foreign_scripts(masked)
    restored = _restore_protected(cleaned, present)
    restored = "\n".join(line.rstrip() for line in restored.splitlines()).strip()
    diffs = [{"script": item["script"], "text": item["text"]} for item in spans]
    first["proposal"] = restored
    first["proposal_diffs"] = diffs
    first["stripped_spans"] = spans
    first["repaired"] = restored != original.strip()
    if first["repaired"] and not restored.strip():
        first["reasons"] = list(first["reasons"]) + [
            "Repair would delete the vocal lyric; the original is kept.",
        ]
        first["verdict"] = "invalid"
        first["ok"] = False
    return first


def assert_lyrics_language(
    lyrics: str,
    lyrics_language: str,
    *,
    protected_segments: Sequence[Mapping[str, Any]] | None = None,
    instrumental: bool = False,
    repair: bool = False,
) -> LyricsLanguageReport:
    report = (
        repair_lyrics_language(
            lyrics, lyrics_language,
            protected_segments=protected_segments, instrumental=instrumental,
        )
        if repair
        else validate_lyrics_language(
            lyrics, lyrics_language,
            protected_segments=protected_segments, instrumental=instrumental,
        )
    )
    if not report["ok"]:
        raise ValueError(
            "La letra no respeta el idioma solicitado: " + " ".join(report["reasons"])
        )
    return report

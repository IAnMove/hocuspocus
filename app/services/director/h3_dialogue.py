"""Deterministic MiniMax H3 dialogue compilation and validation.

H3 treats ``<d>[Language] ...</d>`` blocks as an audio-generation contract.
These helpers keep that contract out of best-effort prompt rewriting: structured
Director dialogue is canonical, existing blocks are replaced as whole units,
and malformed or contradictory prompts are rejected before GPU generation.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


class H3DialogueContractError(ValueError):
    """Raised when an H3 prompt cannot be made safe for native speech."""


_H3_DIALOGUE_TOKEN_RE = re.compile(r"<\s*(/?)\s*d\s*>", re.IGNORECASE)
_H3_STRICT_DIALOGUE_RE = re.compile(
    r"<d>\s*\[([^\]\r\n]+)\]\s+(.+?)\s*</d>",
    re.IGNORECASE | re.DOTALL,
)
_H3_VOCAL_SECTION_RE = re.compile(
    r"\s*(?:DIALOGUE AND VOCAL PERFORMANCE|"
    r"SILENCE AND VOCAL PERFORMANCE)\s*:.*?"
    r"(?=\b(?:FINAL BLOCKING|overall_soundscape|"
    r"non_diegetic_music)\s*:|$)",
    re.IGNORECASE | re.DOTALL,
)
_H3_SOUND_BOUNDARY_RE = re.compile(
    r"\b(?:overall_soundscape|non_diegetic_music)\s*:",
    re.IGNORECASE,
)
_H3_SPEECHLIKE_AMBIENCE_REPLACEMENTS = (
    (
        re.compile(
            r"\b(?:(?:coffee\s*shop|cafe|restaurant|office|party|crowd|"
            r"background)\s+)?chatter\b",
            re.IGNORECASE,
        ),
        "nonverbal room tone",
    ),
    (
        re.compile(
            r"\b(?:indistinct|distant|background|murmuring|soft|low)\s+"
            r"(?:voices?|conversations?|talking|speech)\b",
            re.IGNORECASE,
        ),
        "nonverbal room tone",
    ),
    (
        re.compile(
            r"clear foreground voices with precise lip sync and "
            r"natural delivery(?:[.;]|$)",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        re.compile(
            r"vocal delivery\s*:[^.;]*(?:[.;]|$)",
            re.IGNORECASE,
        ),
        "",
    ),
)

# H3 renders picture and sound jointly.  A vocal verb in an otherwise silent
# visual description is therefore an audio instruction, even when a silence
# sentence appears later.  These rewrites remove the *semantic* contradiction
# instead of trying to overpower it with more negative prompting.
_H3_SILENT_VISUAL_VOCAL_REPLACEMENTS = (
    (re.compile(r"\bgrita\s+pidiendo\s+socorro\b", re.I), "agita los brazos con expresi\u00f3n de alarma"),
    (re.compile(r"\bpide\s+(?:ayuda|socorro)(?:\s+con\s+el\s+mismo\s+grito(?:\s+\w+)?)?", re.I), "hace se\u00f1ales urgentes con ambos brazos"),
    (re.compile(r"\breacciona\s+con\s+un\s+jadeo(?:\s+(?:sincero|nervioso|fuerte|audible))?", re.I), "reacciona abriendo mucho los ojos"),
    (re.compile(r"\b(?:r\u00ede|se\s+r\u00ede)\s+nervios[oa]\b", re.I), "sonr\u00ede con nerviosismo"),
    (re.compile(r"\bgru\u00f1e\s+con\s+esfuerzo\b", re.I), "tensa el rostro por el esfuerzo"),
    (re.compile(r"\bexclama(?:\s+un)?\s+[\"'\u00ab].+?[\"'\u00bb](?:\s+(?:satisfecho|satisfecha|nervioso|nerviosa))?", re.I), "adopta una expresi\u00f3n satisfecha"),
    (re.compile(r"\bpronuncia(?:\s+con\s+\w+)?\s+su\s+(?:\u00fanica\s+)?l\u00ednea(?:\s+\w+)?", re.I), "mantiene la expresi\u00f3n descrita con la boca cerrada"),
    (re.compile(r"\bshouts?\s+for\s+help\b", re.I), "signals urgently for help with both arms"),
    (re.compile(r"\b(?:says?|speaks?|sings?|whispers?|mutters?)\s+(?:his|her|their)\s+(?:only\s+)?line\b", re.I), "holds the described expression with a closed mouth"),
    # Planner prose often describes an *intention* to speak rather than an
    # authored line (for example, a reflection "about to speak").  H3 still
    # reads that as a request for native speech, so render the intention with
    # facial acting when the shot has no exact dialogue ledger.
    (re.compile(r"\b(?:mouth|lips?)\s+(?:half[- ]?)?(?:open(?:s|ed|ing)?|part(?:s|ed|ing)?)\b[^.!?]{0,64}\b(?:to|as\s+if(?:\s+about)?\s+to)\s+(?:speak|sing|say|whisper|mutter)\b", re.I), "mouth remains closed in tense hesitation"),
    (re.compile(r"\bnadie\s+canta\b", re.I), "nadie permanece en silencio"),
    (re.compile(r"\bno\s+one\s+speaks\b", re.I), "everyone remains silent"),
    (re.compile(r"\b(?:hissing|rapping|singing|speaking|saying|whispering|muttering)\s+(?:the\s+)?(?:verse|lyrics?|line|song|words?)\b", re.I), "moving with tense rhythmic physicality"),
    (re.compile(r"\b(?:delivering|performing)\s+(?:a\s+)?vocal\s+performance\b", re.I), "performing with tense physical rhythm"),
    # A music-video planner can still phrase an unledgered performance as a
    # full clause ("rapping the plea in a whisper").  Preserve the visible
    # setup before the verb, but replace the rest of that vocal clause.  The
    # final soundtrack is assembled separately; native H3 vocals are never a
    # valid substitute when this clip has no exact <d> line.
    (re.compile(r"\b(?:rap(?:s|ped|ping)?|whisper(?:s|ed|ing)?|mutter(?:s|ed|ing)?|hiss(?:es|ed|ing)?|(?:rape|susurra|murmura|sisea|canta|pronuncia)(?:n|ndo|ba|ron|ría|rían)?|articula(?:n)?\s+(?:un\s+)?rap)\b[^.!?]{0,220}", re.I), "holds a tense closed-mouth expression"),
    (re.compile(r"\b(?:with\s+)?visible\s+lip\s+movement\b", re.I), "with a closed mouth"),
    (re.compile(r"\bgrunts?\s+with\s+effort\b", re.I), "strains visibly with the effort"),
    (re.compile(r"\blaughs?\s+nervously\b", re.I), "smiles nervously"),
)

_H3_SILENT_SOUNDSCAPE_VOCAL_REPLACEMENTS = (
    re.compile(r"(?:^|[,;])\s*[^,;]*\b(?:jadeo|risa|gru\u00f1ido|exclamaci\u00f3n|grito|voz|voces|di\u00e1logo)\b[^,;]*", re.I),
    re.compile(r"(?:^|[,;])\s*[^,;]*\b(?:gasp|laugh|grunt|exclamation|shout|voice|voices|speech|dialogue)\b[^,;]*", re.I),
)

_H3_AFFIRMATIVE_VOCAL_RE = re.compile(
    r"\b(?:grita(?:n)?|dice(?:n)?|habla(?:n)?|canta(?:n)?|susurra(?:n)?|"
    r"murmura(?:n)?|pronuncia(?:n)?|exclama(?:n)?|jadea(?:n)?|r\u00ede(?:n)?|"
    r"gru\u00f1e(?:n)?|solloza(?:n)?|gime(?:n)?|tose(?:n)?|estornuda(?:n)?|"
    r"silba(?:n)?|tararea(?:n)?|balbucea(?:n)?|responde(?:n)?|respond(?:i\u00f3|ieron)|"
    r"contesta(?:n)?|contest(?:\u00f3|aron)|pregunta(?:n)?|"
    r"pide(?:n)?\s+(?:ayuda|socorro)|shouts?|says?|speaks?|sings?|whispers?|"
    r"mutters?|exclaims?|gasps?|laughs?|grunts?|sobs?|moans?|coughs?|"
    r"sneezes?|whistles?|babbles?|responds?|repl(?:y|ies|ied)|answers?|"
    r"answered|asks?|calls?\s+for\s+help)\b",
    re.IGNORECASE,
)
_H3_NON_SPEECH_VOCAL_RE = re.compile(
    r"\b(?:canta(?:n)?|jadea(?:n)?|r\u00ede(?:n)?|gru\u00f1e(?:n)?|"
    r"solloza(?:n)?|gime(?:n)?|tose(?:n)?|estornuda(?:n)?|silba(?:n)?|"
    r"tararea(?:n)?|balbucea(?:n)?|sings?|gasps?|laughs?|grunts?|sobs?|"
    r"moans?|coughs?|sneezes?|whistles?|babbles?)\b",
    re.IGNORECASE,
)
_H3_VOCAL_SOUND_RE = re.compile(
    r"\b(?:voz|voces|grito|gritos|jadeo|jadeos|risa|risas|gru\u00f1ido|"
    r"gru\u00f1idos|sollozo|sollozos|gemido|gemidos|tos|estornudo|estornudos|"
    r"silbido|silbidos|canto|balbuceo|charla|parloteo|exclamaci\u00f3n|"
    r"exclamaciones|habla|di\u00e1logo|voice|voices|shout|shouts|gasp|gasps|"
    r"laugh|laughs|laughter|grunt|grunts|sob|sobs|sobbing|moan|moans|"
    r"moaning|cough|coughs|sneeze|sneezes|whistle|whistles|babble|chatter|"
    r"exclamation|exclamations|speech|dialogue|muttering|whispering|singing)\b",
    re.IGNORECASE,
)
_H3_NEGATED_VOCAL_PREFIX_RE = re.compile(
    r"(?:\bno|\bnever|\bnobody|\bno\s+one|\bdo\s+not|\bdoes\s+not|"
    r"\bmust\s+not|\bnadie|\bning\u00fan|\bninguna|\bsin)\b[^,.!?;:]{0,48}$",
    re.IGNORECASE,
)

_H3_BASE_FIELDS = (
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
)
_H3_REF2VA_FIELDS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)
_H3_ALL_FIELDS = tuple(dict.fromkeys((*_H3_REF2VA_FIELDS, *_H3_BASE_FIELDS)))
_H3_CUSTOM_SECTION_RE = re.compile(
    r"\s+(?:OPENING CONTINUITY|FINAL BLOCKING|"
    r"DIALOGUE AND VOCAL PERFORMANCE|SILENCE AND VOCAL PERFORMANCE)\s*:.*?"
    r"(?=\s+(?:OPENING CONTINUITY|FINAL BLOCKING|"
    r"DIALOGUE AND VOCAL PERFORMANCE|SILENCE AND VOCAL PERFORMANCE)\s*:|$)",
    re.IGNORECASE | re.DOTALL,
)
_H3_SOUND_PROSE_RE = re.compile(
    r"\b(?:the\s+)?soundscape\s+(?:is\s+dominated\s+by|includes|contains|is)\s+"
    r"(.+?)(?=\s+(?:non-diegetic\s+music|the\s+final\s+beat|"
    r"closing\s+blocking|opening\s+continuity|final\s+blocking)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_H3_MUSIC_PROSE_RE = re.compile(
    r"\bnon-diegetic\s+music\s+is\s+(.+?)"
    r"(?=\s+(?:the\s+final\s+beat|closing\s+blocking|"
    r"opening\s+continuity|final\s+blocking)\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_H3_META_SENTENCE_RE = re.compile(
    r"\bMiniMax H3 generates synchronized picture and stereo sound\.\s*",
    re.IGNORECASE,
)
_H3_MOJIBAKE_REPLACEMENTS = {
    "\u00e2\u0080\u0098": "\u2018",
    "\u00e2\u0080\u0099": "\u2019",
    "\u00e2\u0080\u009c": "\u201c",
    "\u00e2\u0080\u009d": "\u201d",
    "\u00e2\u0080\u0093": "\u2013",
    "\u00e2\u0080\u0094": "\u2014",
    "\u00e2\u0080\u00a6": "\u2026",
    "\u00e2\u20ac\u02dc": "\u2018",
    "\u00e2\u20ac\u2122": "\u2019",
    "\u00e2\u20ac\u0153": "\u201c",
    "\u00e2\u20ac\u009d": "\u201d",
    "\u00e2\u20ac\u201c": "\u2013",
    "\u00e2\u20ac\u201d": "\u2014",
    "\u00e2\u20ac\u00a6": "\u2026",
    "\u00c2\u00a0": " ",
    # Some older Windows JSON round-trips decoded the leading UTF-8 byte for
    # punctuation as U+0101 instead of U+00E2 before preserving the two C1
    # continuation bytes. Repair that observed Maestro variant as well.
    "\u0101\u0080\u0098": "\u2018",
    "\u0101\u0080\u0099": "\u2019",
    "\u0101\u0080\u009c": "\u201c",
    "\u0101\u0080\u009d": "\u201d",
    "\u0101\u0080\u0093": "\u2013",
    "\u0101\u0080\u0094": "\u2014",
    "\u0101\u0080\u00a6": "\u2026",
}


def _field(value: Any, key: str, default: Any = "") -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _normalized_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _dialogue_spans(prompt: str) -> tuple[list[tuple[int, int]], bool]:
    """Return balanced top-level dialogue spans and whether markup was bad."""

    spans: list[tuple[int, int]] = []
    depth = 0
    start = -1
    malformed = False
    for token in _H3_DIALOGUE_TOKEN_RE.finditer(prompt or ""):
        closing = bool(token.group(1))
        if not closing:
            if depth == 0:
                start = token.start()
            else:
                malformed = True
            depth += 1
            continue
        if depth == 0:
            malformed = True
            continue
        depth -= 1
        if depth == 0 and start >= 0:
            spans.append((start, token.end()))
            start = -1
    if depth:
        malformed = True
    return spans, malformed


def _replace_spans(
    prompt: str,
    spans: Sequence[tuple[int, int]],
    replacements: Sequence[str],
) -> str:
    result = prompt
    for (start, end), replacement in reversed(list(zip(spans, replacements))):
        result = f"{result[:start]}{replacement}{result[end:]}"
    return result


def _dialogue_payload(value: Any) -> tuple[str, str]:
    """Return ``(language, words)`` from plain or nested H3 dialogue."""

    text = _H3_DIALOGUE_TOKEN_RE.sub("", str(value or "")).strip()
    language = "English"
    language_prefix = re.match(r"^\[([^\]]+)\]\s*(.*)$", text, re.DOTALL)
    if language_prefix:
        language = language_prefix.group(1).strip() or language
        text = language_prefix.group(2).strip()
    if not text:
        raise H3DialogueContractError("MiniMax H3 dialogue contains an empty line.")
    return language, text


def h3_dialogue_tag(spoken_text: Any, forced_language: str = "") -> str:
    """Build exactly one canonical H3 dialogue block."""

    language, words = _dialogue_payload(spoken_text)
    if forced_language:
        language = forced_language
    return f"<d>[{language}] {words}</d>"


def _replace_first_outside_dialogue(
    prompt: str,
    needle: str,
    replacement: str,
) -> tuple[str, bool]:
    """Replace an exact plain-text line without touching existing H3 tags."""

    if not needle:
        return prompt, False
    spans, malformed = _dialogue_spans(prompt)
    if malformed:
        return prompt, False
    normalized_needle = str(needle).strip()
    pattern = re.compile(
        rf"(?<!\w){re.escape(normalized_needle)}(?!\w)",
        re.IGNORECASE,
    )
    short_line = len(re.findall(r"\w+", normalized_needle)) <= 2
    cursor = 0
    for start, end in [*spans, (len(prompt), len(prompt))]:
        for found in pattern.finditer(prompt, cursor, start):
            if short_line:
                prefix = prompt[max(cursor, found.start() - 72):found.start()]
                speech_cues = list(_H3_AFFIRMATIVE_VOCAL_RE.finditer(prefix))
                if not speech_cues or found.start() - (
                    max(cursor, found.start() - 72) + speech_cues[-1].end()
                ) > 32:
                    continue
            return (
                f"{prompt[:found.start()]}{replacement}{prompt[found.end():]}",
                True,
            )
        cursor = end
    return prompt, False


def _rewrite_outside_dialogue(prompt: str, rewrite) -> str:
    spans, malformed = _dialogue_spans(prompt)
    if malformed:
        raise H3DialogueContractError(
            "MiniMax H3 dialogue tags are unbalanced after compilation."
        )
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(rewrite(prompt[cursor:start]))
        parts.append(prompt[start:end])
        cursor = end
    parts.append(rewrite(prompt[cursor:]))
    return "".join(parts)


def _sanitize_scripted_ambience(prompt: str) -> str:
    """Remove requests for synthetic background speech around exact lines."""

    def sanitize(segment: str) -> str:
        for pattern, replacement in _H3_SPEECHLIKE_AMBIENCE_REPLACEMENTS:
            segment = pattern.sub(replacement, segment)
        segment = re.sub(
            r"\bnonverbal room tone(?:\s*(?:,|and)\s*nonverbal room tone)+\b",
            "nonverbal room tone",
            segment,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s*;\s*(?=;|$)", "", segment).strip(" ;")

    return _rewrite_outside_dialogue(prompt, sanitize)


def _sanitize_silent_visual_vocals(prompt: str) -> str:
    """Turn unstructured vocal actions into equivalent visible silent acting."""

    def sanitize(segment: str) -> str:
        for pattern, replacement in _H3_SILENT_VISUAL_VOCAL_REPLACEMENTS:
            segment = pattern.sub(replacement, segment)
        return segment

    return _rewrite_outside_dialogue(prompt, sanitize)


def _sanitize_silent_soundscape(soundscape: str) -> str:
    """Keep a silent shot's soundscape to ambience and physical effects."""

    result = str(soundscape or "")
    for pattern in _H3_SILENT_SOUNDSCAPE_VOCAL_REPLACEMENTS:
        result = pattern.sub("", result)
    result = re.sub(r"\s*[,;]\s*[,;]+", "; ", result)
    result = re.sub(r"\s+", " ", result).strip(" ,;.")
    return result or "Natural scene-appropriate stereo ambience and synchronized physical effects"


def _affirmative_matches(value: Any, pattern: re.Pattern[str]) -> list[str]:
    text = normalize_h3_text(value)
    matches: list[str] = []
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 56):match.start()]
        if _H3_NEGATED_VOCAL_PREFIX_RE.search(prefix):
            continue
        matches.append(match.group(0))
    return matches


def h3_affirmative_vocal_cues(value: Any) -> list[str]:
    """Find affirmative speech/vocal actions outside canonical dialogue tags."""

    text = re.sub(
        r"<\s*d\s*>.*?<\s*/\s*d\s*>",
        " ",
        normalize_h3_text(value),
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _affirmative_matches(text, _H3_AFFIRMATIVE_VOCAL_RE)


def h3_vocal_sound_cues(value: Any) -> list[str]:
    """Find affirmative vocal nouns in an ambience/effects sound layer."""

    return _affirmative_matches(value, _H3_VOCAL_SOUND_RE)


def h3_non_speech_vocal_cues(value: Any) -> list[str]:
    """Find unstructured vocal performance outside exact dialogue tags."""

    text = re.sub(
        r"<\s*d\s*>.*?<\s*/\s*d\s*>",
        " ",
        normalize_h3_text(value),
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _affirmative_matches(text, _H3_NON_SPEECH_VOCAL_RE)


def _insert_visual_detail(prompt: str, label: str, detail: str) -> str:
    prompt = str(prompt or "").strip()
    detail = _normalized_space(detail)
    statement = f"{label}: {detail}"
    suffix = "" if statement.endswith((".", "!", "?")) else "."
    boundary = _H3_SOUND_BOUNDARY_RE.search(prompt)
    if boundary:
        return (
            f"{prompt[:boundary.start()].rstrip()} {statement}{suffix} "
            f"{prompt[boundary.start():].lstrip()}"
        ).strip()
    return f"{prompt} {statement}{suffix}".strip()


def _speaker_map(subjects: Iterable[Any]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for index, subject in enumerate(subjects or []):
        character_id = _normalized_space(_field(subject, "character_id", ""))
        speaker_name = _normalized_space(
            _field(subject, "speaker_name", "")
            or _field(subject, "visual_description", "")
            or character_id
            or f"visible subject {index + 1}"
        )
        stable_id = f"(S{index + 1})"
        if character_id:
            result[character_id] = (stable_id, speaker_name)
            result[character_id.casefold()] = (stable_id, speaker_name)
        result.setdefault(speaker_name.casefold(), (stable_id, speaker_name))
    return result


def validate_h3_vocal_contract(
    prompt: str,
    dialogue_beats: Sequence[Any] | None = None,
) -> list[str]:
    """Return structural/semantic H3 dialogue errors for a final prompt."""

    prompt = normalize_h3_text(prompt)
    spans, malformed = _dialogue_spans(prompt)
    errors: list[str] = []
    if malformed:
        errors.append("dialogue tags are nested or unbalanced")
    blocks = [prompt[start:end] for start, end in spans]
    actual_words: list[str] = []
    for index, block in enumerate(blocks):
        strict = _H3_STRICT_DIALOGUE_RE.fullmatch(block.strip())
        if not strict or _H3_DIALOGUE_TOKEN_RE.search(strict.group(2) if strict else ""):
            errors.append(f"dialogue block {index + 1} is not canonical")
            continue
        actual_words.append(_normalized_space(strict.group(2)))

    expected_words = []
    for beat in dialogue_beats or []:
        spoken = normalize_h3_text(_field(beat, "spoken_text", ""))
        if _normalized_space(spoken):
            try:
                expected_words.append(_normalized_space(_dialogue_payload(spoken)[1]))
            except H3DialogueContractError as exc:
                errors.append(str(exc))

    if expected_words:
        if len(blocks) != len(expected_words):
            errors.append(
                f"expected {len(expected_words)} dialogue block(s), found {len(blocks)}"
            )
        if actual_words != expected_words:
            errors.append("dialogue words or speaker order differ from dialogue_beats")
    elif not blocks:
        has_silence_contract = bool(re.search(
            r"\bno (?:one|character) speaks\b",
            prompt,
            flags=re.IGNORECASE,
        ))
        has_mapped_audio_contract = (
            "mapped driving audio" in prompt.casefold()
            and "do not generate additional dialogue" in prompt.casefold()
        )
        if not (has_silence_contract or has_mapped_audio_contract):
            errors.append("silent prompt has no explicit H3 silence contract")
    return errors


def compile_h3_vocal_contract(
    prompt: str,
    subjects: Sequence[Any] | None,
    dialogue_beats: Sequence[Any] | None,
) -> tuple[str, str]:
    """Compile a final, idempotent H3 speech/silence contract.

    Existing dialogue is replaced by *whole top-level blocks*. Balanced nested
    blocks from older Maestro projects are therefore repaired without ever
    performing the unsafe ``prompt.replace(spoken_text, tag)`` operation that
    originally split sentences and produced gibberish.
    """

    prompt = str(prompt or "").strip()
    valid_beats: list[tuple[Any, str, str]] = []
    for beat in dialogue_beats or []:
        spoken = _field(beat, "spoken_text", "")
        if not _normalized_space(spoken):
            continue
        _, words = _dialogue_payload(spoken)
        valid_beats.append((beat, words, h3_dialogue_tag(spoken)))

    # Older saved projects do not carry structured dialogue metadata. If they
    # already contain a vocal section, preserve its speaker assignments and
    # repair the full prompt in place instead of deleting the only copy of a
    # line that had been appended inside that section.
    existing_vocal_section = _H3_VOCAL_SECTION_RE.search(prompt)
    if not valid_beats and existing_vocal_section:
        spans, malformed = _dialogue_spans(prompt)
        if malformed and not spans:
            raise H3DialogueContractError(
                "MiniMax H3 dialogue tags are unbalanced and cannot be repaired safely."
            )
        if spans:
            prompt = _replace_spans(
                prompt,
                spans,
                [h3_dialogue_tag(prompt[start:end]) for start, end in spans],
            )
            prompt = _sanitize_scripted_ambience(prompt)
        _, remains_malformed = _dialogue_spans(prompt)
        if remains_malformed:
            raise H3DialogueContractError(
                "MiniMax H3 dialogue tags remain unbalanced after repair."
            )
        errors = validate_h3_vocal_contract(prompt, [])
        if errors:
            raise H3DialogueContractError(
                "Invalid MiniMax H3 vocal contract: " + "; ".join(errors)
            )
        contract_match = _H3_VOCAL_SECTION_RE.search(prompt)
        contract = _normalized_space(
            contract_match.group(0) if contract_match else ""
        )
        return prompt, contract

    prompt = _H3_VOCAL_SECTION_RE.sub(" ", prompt).strip()
    spans, malformed = _dialogue_spans(prompt)
    if malformed and not spans:
        raise H3DialogueContractError(
            "MiniMax H3 dialogue tags are unbalanced and cannot be repaired safely."
        )

    instructions: list[str] = []
    if valid_beats:
        replacements = [
            valid_beats[index][2] if index < len(valid_beats) else ""
            for index in range(len(spans))
        ]
        prompt = _replace_spans(prompt, spans, replacements)
        _, remains_malformed = _dialogue_spans(prompt)
        if remains_malformed:
            raise H3DialogueContractError(
                "MiniMax H3 dialogue tags remain unbalanced after repair."
            )

        mapped = _speaker_map(subjects or [])
        for index in range(len(spans), len(valid_beats)):
            beat, words, tag = valid_beats[index]
            prompt, replaced = _replace_first_outside_dialogue(
                prompt, words, tag,
            )
            if replaced:
                continue
            speaker_id = _normalized_space(_field(beat, "speaker_id", ""))
            stable_id, speaker_name = mapped.get(
                speaker_id,
                mapped.get(
                    speaker_id.casefold(),
                    (speaker_id or "(S1)", speaker_id or "the visible speaker"),
                ),
            )
            delivery = _normalized_space(_field(beat, "delivery", ""))
            physical_cue = _normalized_space(_field(beat, "physical_cue", ""))
            delivery_text = f" with a {delivery} delivery" if delivery else ""
            instruction = (
                f"{stable_id} {speaker_name} speaks{delivery_text}: {tag}."
            )
            if physical_cue:
                instruction += f" While speaking, {physical_cue}"
            instructions.append(instruction)

        prompt = _sanitize_scripted_ambience(prompt)
        guard = (
            "Only these explicitly tagged lines are spoken, once each and in "
            "the listed order. Do not add, paraphrase, repeat, or improvise "
            "dialogue, muttering, murmuring, gibberish, or speech-like "
            "vocalizations. No background or crowd voices are audible. Anyone "
            "not currently delivering a tagged line remains silent with their "
            "mouth closed except for explicitly described nonverbal actions."
        )
        detail = " ".join([*instructions, guard])
        label = "DIALOGUE AND VOCAL PERFORMANCE"
    elif spans:
        replacements = [h3_dialogue_tag(prompt[start:end]) for start, end in spans]
        prompt = _replace_spans(prompt, spans, replacements)
        _, remains_malformed = _dialogue_spans(prompt)
        if remains_malformed:
            raise H3DialogueContractError(
                "MiniMax H3 dialogue tags remain unbalanced after repair."
            )
        prompt = _sanitize_scripted_ambience(prompt)
        detail = (
            "Only the explicitly tagged dialogue already present in this "
            "prompt is spoken. Do not add, paraphrase, repeat, or improvise "
            "any other words, muttering, murmuring, gibberish, or speech-like "
            "vocalizations. No background or crowd voices are audible. "
            "Non-speaking characters keep their mouths closed."
        )
        label = "DIALOGUE AND VOCAL PERFORMANCE"
    else:
        detail = (
            "No one speaks in this shot. All visible people remain silent and "
            "keep their mouths closed except for explicitly described nonverbal "
            "actions. Generate no muttering, murmuring, gibberish, invented "
            "words, background voices, or speech-like vocalizations."
        )
        label = "SILENCE AND VOCAL PERFORMANCE"

    prompt = _insert_visual_detail(prompt, label, detail)
    errors = validate_h3_vocal_contract(prompt, dialogue_beats)
    if errors:
        raise H3DialogueContractError(
            "Invalid MiniMax H3 vocal contract: " + "; ".join(errors)
        )
    return prompt, f"{label}: {detail}"


def h3_dialogue_budget_violations(
    shot_dicts: Sequence[Mapping[str, Any]],
    durations: Sequence[float] | None = None,
    *,
    words_per_second: float = 2.1,
) -> list[dict[str, Any]]:
    """Describe shots whose complete dialogue cannot fit their duration."""

    violations: list[dict[str, Any]] = []
    for index, shot in enumerate(shot_dicts):
        try:
            duration = float(
                durations[index]
                if durations is not None and index < len(durations)
                else shot.get("duration_sec") or 0
            )
        except (TypeError, ValueError):
            duration = 0.0
        word_count = 0
        for beat in shot.get("dialogue_beats") or []:
            spoken = _field(beat, "spoken_text", "")
            if not _normalized_space(spoken):
                continue
            try:
                words = _dialogue_payload(spoken)[1]
            except H3DialogueContractError:
                words = str(spoken or "")
            word_count += len(words.split())
        budget = max(1, int(math.floor(max(0.0, duration) * words_per_second)))
        if word_count > budget:
            violations.append({
                "index": index,
                "title": _normalized_space(shot.get("title") or f"Shot {index + 1}"),
                "duration_sec": duration,
                "word_count": word_count,
                "word_budget": budget,
            })
    return violations


def normalize_h3_text(value: Any) -> str:
    """Repair common UTF-8 mojibake before H3 tokenization.

    Saved Director projects created through a Windows code-page boundary can
    contain the three code points for a UTF-8 punctuation byte sequence (for
    example ``\u00e2\u0080\u0099``) instead of the intended apostrophe.  The
    C1 control bytes are especially harmful in literal dialogue, so repair the
    known sequences and remove any orphaned controls deterministically.
    """

    text = str(value or "")
    for broken, repaired in _H3_MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(broken, repaired)
    return "".join(
        character
        for character in text
        if not 0x80 <= ord(character) <= 0x9F
    )


def _extract_h3_fields(text: str) -> dict[str, str]:
    """Extract known Context-IR fields even from legacy one-line prompts."""

    matches = list(re.finditer(
        r"(?i)(?<![A-Za-z0-9_])(" + "|".join(
            re.escape(field) for field in _H3_ALL_FIELDS
        ) + r")\s*:",
        text,
    ))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).lower()
        if name in fields:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        fields[name] = text[match.end():end].strip()
    return fields


def _strip_h3_custom_sections(text: str) -> str:
    previous = None
    result = str(text or "")
    while result != previous:
        previous = result
        result = _H3_CUSTOM_SECTION_RE.sub(" ", result)
    return result


def _trim_sentence(value: Any) -> str:
    return _normalized_space(value).strip(" .")


def _meaningful_context_present(context: str, body: str) -> bool:
    stop = {
        "about", "after", "again", "being", "from", "have", "into",
        "make", "named", "show", "starring", "that", "their", "this",
        "with", "when", "where", "while",
    }
    words = {
        word.casefold()
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{3,}", context)
        if word.casefold() not in stop
    }
    if not words:
        return True
    body_words = {
        word.casefold()
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{3,}", body)
    }
    required = min(4, max(2, math.ceil(len(words) * 0.45)))
    return len(words & body_words) >= required


def _source_prompt_parts(
    prompt: str,
    *,
    project_context: str = "",
    opening_blocking: str = "",
    closing_blocking: str = "",
    audio_plan: Mapping[str, Any] | None = None,
) -> tuple[str, str, str, list[str]]:
    """Recover one concise visual timeline and the two official sound fields."""

    text = normalize_h3_text(prompt).strip()
    spans, _ = _dialogue_spans(text)
    existing_blocks = [
        h3_dialogue_tag(normalize_h3_text(text[start:end]))
        for start, end in spans
    ]
    fields = _extract_h3_fields(text)
    body = (
        fields.get("detailed_description")
        or fields.get("integrated_multimodal_description")
        or text
    )
    soundscape = fields.get("overall_soundscape", "")
    music = fields.get("non_diegetic_music", "")
    if not (
        fields.get("detailed_description")
        or fields.get("integrated_multimodal_description")
    ):
        boundary = _H3_SOUND_BOUNDARY_RE.search(body)
        if boundary:
            body = body[:boundary.start()]

    if not soundscape:
        match = _H3_SOUND_PROSE_RE.search(body)
        if match:
            soundscape = match.group(1)
            body = f"{body[:match.start()]} {body[match.end():]}"
    if not music:
        match = _H3_MUSIC_PROSE_RE.search(body)
        if match:
            music = match.group(1)
            body = f"{body[:match.start()]} {body[match.end():]}"

    # Legacy Maestro added a long context anchor before the actual prompt.
    # The planner's native body starts at this sentence, so retain everything
    # after it and discard only the duplicated wrapper.
    marker = _H3_META_SENTENCE_RE.search(body)
    if marker and body.lstrip().lower().startswith("project continuity"):
        body = body[marker.end():]
    body = _H3_META_SENTENCE_RE.sub("", body)
    body = _strip_h3_custom_sections(body)
    body = re.sub(
        r"^\s*(?:integrated_multimodal_description|detailed_description)\s*:\s*",
        "",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(r"^\s*\[Shot\s+1\]\s*", "", body, flags=re.IGNORECASE)
    body = _normalized_space(body)

    context = _normalized_space(normalize_h3_text(project_context))
    if context and not _meaningful_context_present(context, body):
        if len(context) > 360:
            context = context[:360].rsplit(" ", 1)[0].rstrip(" ,;:-") + "..."
        body = f"Project context: {context}. {body}".strip()

    opening = _normalized_space(normalize_h3_text(opening_blocking))
    if opening and opening.casefold() not in body.casefold():
        body = f"Opening composition: {opening}. {body}".strip()
    closing = _normalized_space(normalize_h3_text(closing_blocking))
    if closing and closing.casefold() not in body.casefold():
        body = f"{body} By the final beat, {closing}.".strip()

    plan = audio_plan if isinstance(audio_plan, Mapping) else {}
    if not _trim_sentence(soundscape):
        sound_bits = []
        ambience = _trim_sentence(plan.get("ambience", ""))
        if ambience:
            sound_bits.append(ambience)
        sound_bits.extend(
            _trim_sentence(effect)
            for effect in (plan.get("effects") or [])
            if _trim_sentence(effect)
        )
        soundscape = ", ".join(sound_bits) or "Natural scene-appropriate stereo ambience"
    soundscape = _trim_sentence(
        _sanitize_scripted_ambience(normalize_h3_text(soundscape))
    )
    music = _trim_sentence(normalize_h3_text(music)) or "N/A"
    if music.casefold() in {"n/a", "none", "no music"}:
        music = "N/A"
    return body, soundscape, music, existing_blocks


def _speaker_registry_entry(
    registry: Mapping[str, Any], key: str,
) -> tuple[str, str] | None:
    value = registry.get(key) or registry.get(key.casefold())
    if isinstance(value, Mapping):
        stable_id = _normalized_space(value.get("stable_id", ""))
        name = _normalized_space(value.get("speaker_name", ""))
    elif value:
        stable_id = _normalized_space(value)
        name = ""
    else:
        return None
    if stable_id and not stable_id.startswith("("):
        stable_id = f"({stable_id})"
    return stable_id, name


def _subject_name_for_key(subjects: Sequence[Any], key: str) -> str:
    folded = key.casefold()
    for subject in subjects or []:
        character_id = _normalized_space(_field(subject, "character_id", ""))
        speaker_name = _normalized_space(_field(subject, "speaker_name", ""))
        if folded in {character_id.casefold(), speaker_name.casefold()}:
            return speaker_name or character_id
    return key or "the visible speaker"


def _build_stable_speaker_registry(
    clip_plans: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    """Assign speaker IDs once per Director project, not once per shot."""

    registry: dict[str, dict[str, str]] = {}
    used_numbers: set[int] = set()
    for plan in clip_plans:
        existing = plan.get("_director_speaker_registry") or {}
        if not isinstance(existing, Mapping):
            continue
        for raw_key, raw_value in existing.items():
            key = _normalized_space(raw_key).casefold()
            entry = _speaker_registry_entry(existing, str(raw_key))
            if not key or not entry or not entry[0]:
                continue
            match = re.fullmatch(r"\(S(\d+)\)", entry[0], re.IGNORECASE)
            if not match:
                continue
            used_numbers.add(int(match.group(1)))
            registry[key] = {
                "stable_id": f"(S{int(match.group(1))})",
                "speaker_name": entry[1],
            }

    next_number = 1
    for plan in clip_plans:
        subjects = plan.get("_director_subjects_on_screen") or []
        for beat in plan.get("_director_dialogue_beats") or []:
            raw_key = _normalized_space(_field(beat, "speaker_id", ""))
            name = _subject_name_for_key(subjects, raw_key)
            key = (raw_key or name).casefold()
            if not key or key in registry:
                continue
            while next_number in used_numbers:
                next_number += 1
            registry[key] = {
                "stable_id": f"(S{next_number})",
                "speaker_name": name,
            }
            used_numbers.add(next_number)
            next_number += 1
    return registry


def _ensure_speaker_before_tag(
    body: str,
    tag: str,
    *,
    speaker_name: str,
    stable_id: str,
    cursor: int,
) -> tuple[str, int]:
    tag_index = body.find(tag, cursor)
    if tag_index < 0:
        return body, cursor
    nearby_start = max(0, tag_index - 260)
    nearby = body[nearby_start:tag_index]
    if stable_id in nearby:
        return body, tag_index + len(tag)

    name_matches = list(re.finditer(
        re.escape(speaker_name), nearby, flags=re.IGNORECASE,
    )) if speaker_name else []
    if name_matches:
        insertion = nearby_start + name_matches[-1].end()
        body = f"{body[:insertion]} {stable_id}{body[insertion:]}"
        tag_index += len(stable_id) + 1
    else:
        prefix = f"{speaker_name or 'The visible speaker'} {stable_id} says: "
        body = f"{body[:tag_index]}{prefix}{body[tag_index:]}"
        tag_index += len(prefix)
    return body, tag_index + len(tag)


def _compile_official_dialogue(
    body: str,
    subjects: Sequence[Any],
    dialogue_beats: Sequence[Any],
    registry: Mapping[str, Any],
    existing_blocks: Sequence[str],
    *,
    has_driving_audio: bool = False,
    forced_language: str = "",
) -> tuple[str, str]:
    """Place exact tagged lines and stable speaker IDs in the visual field."""

    valid_beats: list[dict[str, str]] = []
    for beat in dialogue_beats or []:
        spoken = normalize_h3_text(_field(beat, "spoken_text", ""))
        if not _normalized_space(spoken):
            continue
        authored_language, words = _dialogue_payload(spoken)
        carries_language = bool(re.search(r"(?:<d>\s*)?\[[^\]]+\]", spoken, re.I))
        speaker_key = _normalized_space(_field(beat, "speaker_id", ""))
        entry = _speaker_registry_entry(registry, speaker_key)
        if entry:
            stable_id, speaker_name = entry
        else:
            speaker_name = _subject_name_for_key(subjects, speaker_key)
            stable_id = f"(S{len(valid_beats) + 1})"
        valid_beats.append({
            "words": normalize_h3_text(words),
            "tag": "",
            "authored_language": authored_language if carries_language else "",
            "stable_id": stable_id,
            "speaker_name": speaker_name,
            "delivery": _normalized_space(_field(beat, "delivery", "")),
            "physical_cue": _normalized_space(_field(beat, "physical_cue", "")),
        })

    body = _strip_h3_custom_sections(body)
    spans, malformed = _dialogue_spans(body)
    if malformed and not spans:
        raise H3DialogueContractError(
            "MiniMax H3 dialogue tags are unbalanced and cannot be repaired safely."
        )

    # An explicit language in the reviewed/source prompt is authoritative.
    # Previously, rebuilding from plain dialogue_beats silently reverted such
    # lines to English when no project-wide spoken-language contract existed.
    from .spoken_language import infer_h3_spoken_language

    source_languages = [
        _dialogue_payload(body[start:end])[0]
        for start, end in spans
    ]
    for index, beat in enumerate(valid_beats):
        language = (
            forced_language
            or (source_languages[index] if index < len(source_languages) else "")
            or beat["authored_language"]
            or infer_h3_spoken_language(beat["words"])
        )
        beat["tag"] = h3_dialogue_tag(
            f"[{language}] {beat['words']}",
        )

    if valid_beats:
        replacements = [
            valid_beats[index]["tag"] if index < len(valid_beats) else ""
            for index in range(len(spans))
        ]
        body = _replace_spans(body, spans, replacements)
        for beat in valid_beats[len(spans):]:
            body, replaced = _replace_first_outside_dialogue(
                body, beat["words"], beat["tag"],
            )
            if not replaced:
                delivery = (
                    f" with a {beat['delivery']} delivery"
                    if beat["delivery"] else ""
                )
                cue = (
                    f" While speaking, {beat['physical_cue']}"
                    if beat["physical_cue"] else ""
                )
                body = (
                    f"{body} {beat['speaker_name']} {beat['stable_id']} speaks"
                    f"{delivery}: {beat['tag']}.{cue}"
                ).strip()

        cursor = 0
        for beat in valid_beats:
            body, cursor = _ensure_speaker_before_tag(
                body,
                beat["tag"],
                speaker_name=beat["speaker_name"],
                stable_id=beat["stable_id"],
                cursor=cursor,
            )
        guard = (
            "Only the tagged lines are spoken, once each in order. After the "
            "final tagged line, every character remains silent with their "
            "mouth closed; no other speech or background voices occur."
        )
        if "only the tagged lines are spoken" not in body.casefold():
            body = f"{body} {guard}".strip()
        contract = " ".join(
            f"{beat['speaker_name']} {beat['stable_id']}: {beat['tag']}"
            for beat in valid_beats
        )
    else:
        canonical_blocks = [h3_dialogue_tag(block, forced_language) for block in existing_blocks]
        if spans:
            canonical_blocks = [h3_dialogue_tag(body[start:end], forced_language) for start, end in spans]
            body = _replace_spans(body, spans, canonical_blocks)
        elif canonical_blocks:
            additions = " ".join(
                f"A visible speaker (S{index}) says: {tag}."
                for index, tag in enumerate(canonical_blocks, start=1)
            )
            body = f"{body} {additions}".strip()
        if canonical_blocks:
            guard = (
                "Only the tagged lines are spoken; everyone remains silent "
                "with their mouth closed at all other times."
            )
            if "only the tagged lines are spoken" not in body.casefold():
                body = f"{body} {guard}".strip()
            contract = " ".join(canonical_blocks)
        elif has_driving_audio:
            driver_contract = (
                "Any audible voice or vocal comes only from the mapped driving "
                "audio and remains synchronized to it; do not generate "
                "additional dialogue or speech-like vocalization."
            )
            if "mapped driving audio" not in body.casefold():
                body = f"{body} {driver_contract}".strip()
            contract = driver_contract
        else:
            silence = (
                "No character speaks; all visible mouths remain closed, and "
                "no speech-like vocalization or background voice occurs."
            )
            if not re.search(r"\bno (?:one|character) speaks\b", body, re.IGNORECASE):
                body = f"{body} {silence}".strip()
            contract = silence

    body = _normalized_space(body)
    return body, contract


def _reference_relationships(
    references: Sequence[Mapping[str, Any]] | None,
    subjects: Sequence[Any] | None = None,
    registry: Mapping[str, Any] | None = None,
) -> tuple[
    list[str],
    list[str],
    bool,
    dict[int, list[str]],
    list[str],
    list[str],
]:
    """Build MiniMax's documented Ref2VA reference contract.

    Visual and audio retention markers intentionally use different fixed
    vocabularies. Identity/location pictures are bound through ``<Subject N>``
    instead of being misrepresented as concrete keyframes.
    """

    definitions: list[str] = []
    retention: list[str] = []
    subject_sources: dict[int, list[str]] = {}
    detail_bindings: list[str] = []
    task_types: list[str] = ["reference generation"]
    picture_no = video_no = audio_no = 0
    has_driving_audio = False
    next_subject_no = len(subjects or []) + 1
    registry = registry if isinstance(registry, Mapping) else {}

    def mapped_subject(role: str) -> tuple[int, str, str] | None:
        folded_role = role.casefold()
        for subject_index, subject in enumerate(subjects or [], start=1):
            character_id = _normalized_space(_field(subject, "character_id", ""))
            subject_name = _normalized_space(
                _field(subject, "speaker_name", "") or character_id
            )
            candidates = [
                value for value in (subject_name, character_id)
                if len(value) >= 2
            ]
            if not any(value.casefold() in folded_role for value in candidates):
                continue
            entry = _speaker_registry_entry(
                registry,
                character_id or subject_name,
            )
            stable_id = entry[0] if entry else ""
            return subject_index, subject_name or character_id, stable_id
        return None

    def add_task_type(value: str) -> None:
        if value not in task_types:
            task_types.append(value)

    for reference in references or []:
        kind = str(reference.get("type") or "").strip().lower()
        role = _trim_sentence(reference.get("role", "")) or f"the supplied {kind} reference"
        subject_match = mapped_subject(role)
        mapped_role = (
            f"<Subject {subject_match[0]}> ({subject_match[1]})"
            if subject_match else role
        )
        if kind == "image":
            picture_no += 1
            label = f"<Picture {picture_no}>"
            intent = str(reference.get("image_intent") or "identity").lower()
            if intent == "composition":
                definitions.append(
                    f"{label} is the soft composition and cast-layout anchor "
                    f"for [Shot 1], showing {mapped_role}."
                )
                retention.append(
                    f"{label} ([Shot 1] composition anchor): partially_preserved - "
                    "retain the intended subject placement, wardrobe, setting, "
                    "and spatial relationships while generating natural motion "
                    "rather than a frozen opening frame."
                )
                detail_bindings.append(
                    f"{label} softly guides the opening composition and cast layout."
                )
                continue

            if subject_match:
                subject_no, subject_name, _ = subject_match
            else:
                subject_no = next_subject_no
                next_subject_no += 1
                subject_name = role

            if intent == "scene":
                source_clause = f"environment and location identity come from {label}"
                explanation = (
                    f"preserve the architecture, materials, lighting context, and "
                    f"location identity supplied by {label}, but not incidental people"
                )
                marker = "fully_preserved"
                detail_bindings.append(
                    f"<Subject {subject_no}> is the environment established by {label}."
                )
            elif intent == "style":
                source_clause = f"visual style is guided by {label}"
                explanation = (
                    f"retain broad similarity to the medium, palette, lighting "
                    f"language, and texture of {label}, but not its people, pose, "
                    "framing, or exact composition"
                )
                marker = "weak_reference"
                detail_bindings.append(
                    f"The visual treatment of <Subject {subject_no}> follows {label} broadly."
                )
            else:
                source_clause = f"visual identity and appearance come from {label}"
                explanation = (
                    f"preserve the identity and appearance supplied by {label}; "
                    "use it for identity only and do not copy its background, "
                    "source location, framing, "
                    "composition, pose, or opening-still appearance"
                )
                marker = "fully_preserved"
                detail_bindings.append(
                    f"At first appearance, <Subject {subject_no}> uses identity and appearance from {label}."
                )

            if subject_match:
                subject_sources.setdefault(subject_no, []).append(source_clause)
            else:
                definitions.append(
                    f"<Subject {subject_no}> is {subject_name}, whose {source_clause}."
                )
            retention.append(
                f"<Subject {subject_no}> (appears in [Shot 1]): {marker} - {explanation}."
            )
        elif kind == "video":
            video_no += 1
            label = f"<Video {video_no}>"
            definitions.append(f"{label} provides motion and temporal reference for {mapped_role}.")
            retention.append(
                f"{label} (motion, camera, and temporal structure): weak_reference - "
                "retain only the requested motion, timing, camera, or scene traits "
                "while generating the described target video."
            )
            detail_bindings.append(
                f"The requested motion and temporal behavior follow {label} without copying it as source footage."
            )
        elif kind == "audio":
            audio_no += 1
            label = f"<Audio {audio_no}>"
            intent = str(reference.get("audio_intent") or "voice").lower()
            if intent == "drive":
                has_driving_audio = True
                add_task_type("audio reuse")
                definitions.append(
                    f"{label} is the performance-driving audio timeline for {mapped_role}."
                )
                retention.append(
                    f"{label}: partially_copy - reuse its audible content and "
                    "timing while synchronizing visible action and lip movement; "
                    "additional scene ambience or practical effects may be mixed around it."
                )
                detail_bindings.append(
                    f"Visible performance and lip movement remain synchronized to {label} throughout [Shot 1]."
                )
            elif intent == "style":
                add_task_type("audio reference")
                definitions.append(
                    f"{label} is the audio-style reference for {mapped_role}."
                )
                retention.append(
                    f"{label}: weak_reference - retain broad similarity to its "
                    "rhythm, texture, and style without copying its words, exact "
                    "timing, or waveform."
                )
                detail_bindings.append(
                    f"The requested audio treatment broadly follows {label}."
                )
            else:
                add_task_type("audio reference")
                speaker_suffix = ""
                if subject_match and subject_match[2]:
                    speaker_suffix = f" {subject_match[2]}"
                audio_target = (
                    f"<Subject {subject_match[0]}>"
                    if subject_match else mapped_role
                )
                definitions.append(
                    f"{label} is the voice-timbre reference for "
                    f"{audio_target}{speaker_suffix}."
                )
                retention.append(
                    f"{label}: reference - the target speaker follows its voice "
                    "timbre, emotion, and delivery without copying the source "
                    "words, timing, or waveform."
                )
                detail_bindings.append(
                    f"Newly scripted dialogue for {audio_target}{speaker_suffix} follows the voice timbre and delivery of {label}."
                )
    return (
        definitions,
        retention,
        has_driving_audio,
        subject_sources,
        detail_bindings,
        task_types,
    )


def _ref2va_subject_definitions(
    subjects: Sequence[Any],
    registry: Mapping[str, Any],
    source_bindings: Mapping[int, Sequence[str]] | None = None,
) -> list[str]:
    definitions: list[str] = []
    source_bindings = source_bindings or {}
    for index, subject in enumerate(subjects or [], start=1):
        character_id = _normalized_space(_field(subject, "character_id", ""))
        name = _normalized_space(
            _field(subject, "speaker_name", "") or character_id or f"subject {index}"
        )
        entry = _speaker_registry_entry(registry, character_id or name)
        speaker = f" {entry[0]}" if entry and entry[0] else ""
        description = _trim_sentence(_field(subject, "visual_description", ""))
        wardrobe = _trim_sentence(_field(subject, "wardrobe", ""))
        details = "; ".join(
            item for item in (
                description,
                f"wearing {wardrobe}" if wardrobe else "",
                *source_bindings.get(index, ()),
            ) if item
        )
        definitions.append(
            f"<Subject {index}> is {name}{speaker}" + (f": {details}." if details else ".")
        )
    return definitions


def _label_ref2va_subjects_in_body(
    body: str,
    subjects: Sequence[Any],
) -> str:
    """Insert each official subject label at its first named appearance."""

    result = body
    missing: list[str] = []
    for index, subject in enumerate(subjects or [], start=1):
        label = f"<Subject {index}>"
        if label in result:
            continue
        name = _normalized_space(
            _field(subject, "speaker_name", "")
            or _field(subject, "character_id", "")
        )
        if not name:
            continue
        pattern = re.compile(rf"(?<![\w>]){re.escape(name)}(?![\w<])", re.IGNORECASE)
        result, count = pattern.subn(f"{label} ({name})", result, count=1)
        if not count:
            missing.append(f"{label} ({name}) is visible in the described blocking.")
    if missing:
        result = f"{' '.join(missing)} {result}".strip()
    return result


def _alignment_header(
    mode: str,
    duration_seconds: float,
    final_shot_number: int = 1,
) -> str:
    duration = max(0.0, float(duration_seconds or 0.0))
    final_shot_number = max(1, int(final_shot_number or 1))
    if mode == "i2va":
        return (
            "For the target video, at 0.00 seconds into the target video, "
            "<Picture 1> (from [Shot 1]) is fully referenced."
        )
    if mode == "fl2va":
        return (
            "How the reference pictures align with the target video — "
            "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the "
            f"target video; Picture 2 (from Shot {final_shot_number}) aligns with the "
            f"{duration:.2f}-second "
            "mark of the target video."
        )
    if mode == "l2va":
        return (
            "How the reference pictures align with the target video — "
            f"<Picture 1> (from [Shot {final_shot_number}]) aligns with the "
            f"{duration:.2f}-second mark of the target video."
        )
    return ""


def compile_h3_official_prompt(
    prompt: str,
    subjects: Sequence[Any] | None,
    dialogue_beats: Sequence[Any] | None,
    *,
    mode: str = "t2va",
    duration_seconds: float = 0.0,
    references: Sequence[Mapping[str, Any]] | None = None,
    speaker_registry: Mapping[str, Any] | None = None,
    project_context: str = "",
    opening_blocking: str = "",
    closing_blocking: str = "",
    audio_plan: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Compile Director metadata into MiniMax's documented Context-IR shape."""

    mode = str(mode or "t2va").strip().lower()
    if mode not in {"t2va", "i2va", "fl2va", "l2va", "ref2va"}:
        raise H3DialogueContractError(f"Unknown MiniMax H3 prompt mode: {mode}")
    # In a silent shot an orphaned <d> / </d> is planner debris, not an
    # authorised line.  Keeping it makes the whole music-video plan fail even
    # though the canonical dialogue ledger is empty.  Real dialogue continues
    # to use the strict path below and malformed tags still fail loudly there.
    has_ledger_dialogue = any(
        _normalized_space(_field(beat, "spoken_text", ""))
        for beat in (dialogue_beats or [])
    )
    source_prompt = str(prompt or "")
    if not has_ledger_dialogue:
        source_prompt = _H3_DIALOGUE_TOKEN_RE.sub("", source_prompt)
    registry = speaker_registry if isinstance(speaker_registry, Mapping) else {}
    (
        reference_definitions,
        retention,
        has_driving_audio,
        subject_sources,
        detail_bindings,
        task_types,
    ) = _reference_relationships(
        references if mode == "ref2va" else None,
        subjects or [],
        registry,
    )
    body, soundscape, music, existing_blocks = _source_prompt_parts(
        source_prompt,
        project_context=project_context,
        opening_blocking=opening_blocking,
        closing_blocking=closing_blocking,
        audio_plan=audio_plan,
    )
    from .spoken_language import h3_language_tag
    forced_language = h3_language_tag(
        audio_plan.get("spoken_language")
        if isinstance(audio_plan, Mapping) else ""
    )
    has_structured_dialogue = has_ledger_dialogue or bool(existing_blocks)
    if has_ledger_dialogue and not existing_blocks:
        # Music planners commonly leave free-form "sings/raps" prose beside
        # a now-authoritative lyric ledger.  Keep only the exact <d> words as
        # a vocal instruction; visual delivery is converted to physical acting
        # and vocal ambience is removed before H3 sees it.
        body = _sanitize_silent_visual_vocals(body)
        soundscape = _sanitize_silent_soundscape(soundscape)
    elif not has_structured_dialogue and not has_driving_audio:
        body = _sanitize_silent_visual_vocals(body)
        soundscape = _sanitize_silent_soundscape(soundscape)
    body, vocal_contract = _compile_official_dialogue(
        body,
        subjects or [],
        dialogue_beats or [],
        registry,
        existing_blocks,
        has_driving_audio=has_driving_audio,
        forced_language=forced_language,
    )
    # H3 has a native minimum duration, so a short authored line may leave
    # several seconds that the audiovisual model otherwise fills with invented
    # speech. Bind every tagged line to a concrete interval and assign the
    # remaining time to closed-mouth action and production sound. The job
    # boundary reapplies this after frame-lattice rounding with the exact
    # physical duration.
    if duration_seconds:
        from ..minimax_h3_duration import inject_h3_vocal_timeline

        body, _ = inject_h3_vocal_timeline(body, duration_seconds)
    body = re.sub(r"^\s*\[Shot\s+1\]\s*", "", body, flags=re.IGNORECASE)
    body = f"[Shot 1] {body}".strip()

    if mode == "ref2va":
        subject_definitions = _ref2va_subject_definitions(
            subjects or [],
            registry,
            subject_sources,
        )
        definitions = "\n".join([*subject_definitions, *reference_definitions])
        if not definitions:
            definitions = "Use the explicitly described subjects and target scene."
        retention_text = "\n".join(retention) or (
            "Preserve the explicitly described identities, wardrobe, setting, action, and audio roles."
        )
        body = _label_ref2va_subjects_in_body(body, subjects or [])
        summary_body = re.sub(r"^\[Shot\s+1\]\s*", "", body, flags=re.IGNORECASE)
        summary_body = _H3_STRICT_DIALOGUE_RE.sub(
            "scripted dialogue",
            summary_body,
        )
        summary = _trim_sentence(re.split(r"(?<=[.!?])\s+", summary_body, maxsplit=1)[0])
        if len(summary) > 320:
            summary = summary[:320].rsplit(" ", 1)[0].rstrip(" ,;:-") + "..."
        summary = (
            f"[{' + '.join(task_types)}] "
            f"{summary or 'A complete audiovisual shot matching the mapped subjects and requested action.'}"
        )
        if detail_bindings:
            body = re.sub(r"^\[Shot\s+1\]\s*", "", body, flags=re.IGNORECASE)
            body = f"[Shot 1] {' '.join(detail_bindings)} {body}".strip()
        if has_driving_audio and music == "N/A":
            music = "Use the mapped driving audio according to retention_analysis."
        compiled = (
            f"subject_definitions: {definitions}\n\n"
            f"summary: {summary}\n\n"
            f"retention_analysis: {retention_text}\n\n"
            f"detailed_description: {body}\n\n"
            f"overall_soundscape: {soundscape}.\n\n"
            f"non_diegetic_music: {music}"
        )
    else:
        shot_numbers = [
            int(value)
            for value in re.findall(r"\[Shot\s+(\d+)\]", body, flags=re.IGNORECASE)
        ]
        header = _alignment_header(
            mode,
            duration_seconds,
            max(shot_numbers) if shot_numbers else 1,
        )
        compiled = (
            f"integrated_multimodal_description: {body}\n\n"
            f"overall_soundscape: {soundscape}.\n\n"
            f"non_diegetic_music: {music}"
        )
        if header:
            compiled = f"{header}\n\n{compiled}"
    return normalize_h3_text(compiled).strip(), vocal_contract


def validate_h3_prompt_contract(
    prompt: str,
    dialogue_beats: Sequence[Any] | None = None,
    *,
    mode: str = "t2va",
    references: Sequence[Mapping[str, Any]] | None = None,
    audio_plan: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate the official field order plus Maestro's exact dialogue data."""

    text = str(prompt or "")
    mode = str(mode or "t2va").strip().lower()
    expected = _H3_REF2VA_FIELDS if mode == "ref2va" else _H3_BASE_FIELDS
    errors = validate_h3_vocal_contract(text, dialogue_beats)
    positions: list[int] = []
    for field in expected:
        matches = list(re.finditer(
            rf"(?mi)^\s*{re.escape(field)}\s*:", text,
        ))
        if len(matches) != 1:
            errors.append(f"expected one {field} field, found {len(matches)}")
        elif matches:
            positions.append(matches[0].start())
    if len(positions) == len(expected) and positions != sorted(positions):
        errors.append("Context-IR fields are out of order")
    unexpected = set(_H3_ALL_FIELDS) - set(expected)
    for field in unexpected:
        if re.search(rf"(?mi)^\s*{re.escape(field)}\s*:", text):
            errors.append(f"unexpected {field} field for {mode}")
    extracted_fields = _extract_h3_fields(text)
    visual_field = "detailed_description" if mode == "ref2va" else "integrated_multimodal_description"
    visual = extracted_fields.get(visual_field, "")
    expected_dialogue = any(
        _normalized_space(_field(beat, "spoken_text", ""))
        for beat in (dialogue_beats or [])
    )
    audio = audio_plan if isinstance(audio_plan, Mapping) else {}
    _, _, has_driving_audio, _, _, _ = _reference_relationships(
        references or [], [], {}
    )
    if audio and not has_driving_audio:
        audio_mode = str(audio.get("mode") or "").strip().casefold()
        timing_anchor = str(audio.get("timing_anchor") or "").strip().casefold()
        lip_sync = bool(audio.get("lip_sync_critical"))
        if expected_dialogue:
            if audio_mode != "dialogue_driven":
                errors.append(
                    "exact dialogue requires audio_plan.mode=dialogue_driven"
                )
            if timing_anchor != "audio":
                errors.append(
                    "exact dialogue requires audio_plan.timing_anchor=audio"
                )
            if not lip_sync:
                errors.append(
                    "exact dialogue requires audio_plan.lip_sync_critical=true"
                )
        else:
            permitted_silent_modes = {
                "", "ambient_only", "music_driven", "audio_driven",
                "generated_audio",
            }
            if audio_mode not in permitted_silent_modes:
                errors.append(
                    "silent generation uses an unsupported audio_plan.mode"
                )
            if (
                audio_mode in {"", "ambient_only"}
                and timing_anchor not in {"", "video"}
            ):
                errors.append(
                    "silent generation requires audio_plan.timing_anchor=video"
                )
            if audio_mode in {"", "ambient_only", "music_driven"} and lip_sync:
                errors.append(
                    "silent generation requires audio_plan.lip_sync_critical=false"
                )
    remaining_vocals = h3_affirmative_vocal_cues(visual)
    non_speech_vocals = h3_non_speech_vocal_cues(visual)
    if non_speech_vocals:
        errors.append(
            "visual field still contains unstructured vocal performance: "
            + ", ".join(non_speech_vocals[:5])
        )
    sound_vocals = h3_vocal_sound_cues(
        extracted_fields.get("overall_soundscape", "")
    )
    if sound_vocals:
        errors.append(
            "overall_soundscape still contains vocal material: "
            + ", ".join(sound_vocals[:5])
        )
    if not expected_dialogue and not _dialogue_spans(text)[0]:
        if remaining_vocals:
            errors.append(
                "silent visual field still contains affirmative vocal cues: "
                + ", ".join(remaining_vocals[:5])
            )
    # With exact dialogue, descriptive prose may refer to the same tagged
    # delivery in more than one visual sentence (setup, action and payoff).
    # Those repeated verbs are not additional audible lines: <d> blocks and
    # the immutable dialogue ledger are authoritative.  Truly unstructured
    # vocalizations are still rejected above, while any affirmative vocal cue
    # remains forbidden for a silent shot.
    if not re.match(r"^\s*\[Shot\s+1\]", visual, flags=re.IGNORECASE):
        errors.append(f"{visual_field} does not begin with [Shot 1]")
    if re.search(
        r"\b(?:PROJECT CONTINUITY|OPENING CONTINUITY|FINAL BLOCKING|"
        r"DIALOGUE AND VOCAL PERFORMANCE|SILENCE AND VOCAL PERFORMANCE)\s*:",
        text,
        flags=re.IGNORECASE,
    ):
        errors.append("legacy Maestro prompt wrapper remains in the H3 payload")
    if any(0x80 <= ord(character) <= 0x9F for character in text):
        errors.append("prompt contains an orphaned C1 control character")
    if mode == "i2va" and not text.startswith(
        "For the target video, at 0.00 seconds into the target video, <Picture 1>"
    ):
        errors.append("I2VA prompt is missing the official 0.00-second alignment line")
    if mode == "fl2va" and not text.startswith(
        "How the reference pictures align with the target video"
    ):
        errors.append("FL2VA prompt is missing the official two-picture alignment line")
    if mode == "l2va" and not text.startswith(
        "How the reference pictures align with the target video — <Picture 1>"
    ):
        errors.append("L2VA prompt is missing the official last-picture alignment line")
    if mode == "t2va" and text.startswith((
        "For the target video,", "How the reference pictures align",
    )):
        errors.append("T2VA prompt must not contain a picture-alignment header")
    if mode == "ref2va":
        summary = extracted_fields.get("summary", "")
        if not re.match(
            r"^\[(?:reference generation|video editing|video continuation|"
            r"keyframe completion|audio reuse|audio reference)(?:\s+\+\s+"
            r"(?:reference generation|video editing|video continuation|"
            r"keyframe completion|audio reuse|audio reference))*\]\s+\S",
            summary,
            flags=re.IGNORECASE,
        ):
            errors.append("Ref2VA summary is missing its official task-type prefix")

        if references:
            expected_labels: list[str] = []
            counts = {"image": 0, "video": 0, "audio": 0}
            for reference in references:
                kind = str(reference.get("type") or "").strip().lower()
                if kind not in counts:
                    continue
                counts[kind] += 1
                noun = {"image": "Picture", "video": "Video", "audio": "Audio"}[kind]
                expected_labels.append(f"<{noun} {counts[kind]}>")
            missing_labels = [label for label in expected_labels if label not in text]
            if missing_labels:
                errors.append(
                    "Ref2VA prompt does not map supplied references: "
                    + ", ".join(missing_labels)
                )

            retention_text = extracted_fields.get("retention_analysis", "")
            if counts["image"] + counts["video"] and not re.search(
                r":\s*(?:fully_preserved|partially_preserved|"
                r"attribute_transfer|weak_reference)\s+-",
                retention_text,
            ):
                errors.append("Ref2VA visual retention uses no official marker")
            if counts["audio"] and not re.search(
                r":\s*(?:fully_copy|partially_copy|reference|weak_reference)\s+-",
                retention_text,
            ):
                errors.append("Ref2VA audio retention uses no official marker")
    return list(dict.fromkeys(errors))


def compile_h3_clip_plans(
    clip_plans: Sequence[MutableMapping[str, Any]],
    *,
    prompt_modes: Sequence[str] | None = None,
    durations: Sequence[float] | None = None,
    reference_manifests: Sequence[Sequence[Mapping[str, Any]]] | None = None,
) -> Sequence[MutableMapping[str, Any]]:
    """Compile every saved/renderable H3 clip immediately before queuing.

    ``_director_h3_source_prompt`` remains the immutable planner result. This
    lets generation recompile a prompt from T2VA to I2VA/FL2VA after the actual
    start/end files are known without nesting an alignment header or six-field
    Ref2VA wrapper around a previously compiled prompt.
    """

    candidates = copy.deepcopy(list(clip_plans))
    registry = _build_stable_speaker_registry(candidates)
    for index, plan in enumerate(candidates):
        beats = plan.get("_director_dialogue_beats") or []
        for beat in beats:
            if isinstance(beat, MutableMapping) and "spoken_text" in beat:
                beat["spoken_text"] = normalize_h3_text(beat["spoken_text"])

        current_prompt = str(plan.get("video_prompt", "") or "")
        last_compiled = str(plan.get("_director_h3_compiled_prompt", "") or "")
        source_prompt = plan.get("_director_h3_source_prompt")
        if source_prompt and last_compiled and current_prompt != last_compiled:
            # Prompt review/editing happens after the first preflight. Treat a
            # changed compiled prompt as the user's new authoritative source.
            source_prompt = current_prompt
            plan["_director_h3_source_prompt"] = source_prompt
        if not source_prompt:
            source_prompt = current_prompt
            plan["_director_h3_source_prompt"] = source_prompt
        mode = (
            prompt_modes[index]
            if prompt_modes is not None and index < len(prompt_modes)
            else plan.get("_director_h3_prompt_mode")
            or (
                "ref2va"
                if plan.get("_director_h3_model_family") == "ref2va"
                else "t2va"
            )
        )
        duration = (
            durations[index]
            if durations is not None and index < len(durations)
            else plan.get("_director_duration_sec") or 0.0
        )
        references = (
            reference_manifests[index]
            if reference_manifests is not None and index < len(reference_manifests)
            else plan.get("_director_h3_reference_manifest") or []
        )
        prompt, contract = compile_h3_official_prompt(
            source_prompt,
            plan.get("_director_subjects_on_screen") or [],
            beats,
            mode=mode,
            duration_seconds=duration,
            references=references,
            speaker_registry=registry,
            project_context=plan.get("_director_project_context", ""),
            opening_blocking=plan.get("_director_opening_blocking", ""),
            closing_blocking=plan.get("_director_closing_blocking", ""),
            audio_plan=plan.get("_director_audio_plan") or {},
        )
        plan["video_prompt"] = prompt
        plan["_director_h3_compiled_prompt"] = prompt
        plan["_director_vocal_contract"] = contract
        plan["_director_h3_prompt_mode"] = mode
        plan["_director_speaker_registry"] = registry
        errors = validate_h3_prompt_contract(
            prompt,
            beats,
            mode=mode,
            references=references,
            audio_plan=plan.get("_director_audio_plan") or {},
        )
        if errors:
            raise H3DialogueContractError(
                f"Shot {index + 1}: " + "; ".join(errors)
            )
    for original, candidate in zip(clip_plans, candidates):
        original.clear()
        original.update(candidate)
    return clip_plans

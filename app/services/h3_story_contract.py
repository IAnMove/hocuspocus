"""Canonical dialogue ownership shared by single and multi-window H3 planning.

Inspired by Maestro's story ledger, implemented around Hocuspocus' existing
window schema. Literal dialogue is data: visual planning cannot rewrite it.
"""
from __future__ import annotations

from collections import Counter
import re
from typing import Any

from .h3_prompt_policy import planning_style, tagged_dialogue, writing_contract
from .director.spoken_language import h3_language_tag, spoken_language_of

_TAG = re.compile(r"<d>\s*\[([^\]]+)\]\s*(.*?)</d>", re.I | re.S)
_QUOTE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|«([^»\n]+)»')
_SPEECH = re.compile(r"\b(?:says?|asks?|replies|shouts?|whispers?|sings?|dice|dicen|responde|pregunta|grita|susurra|canta|diciendo|diálogo|dialogue)\b", re.I)
_SILENT = re.compile(r"\b(?:silent(?:ly)?|no (?:speech|dialogue|voices)|without (?:speech|dialogue)|nonverbal|sin (?:hablar|diálogo|dialogo|voces)|en silencio|nadie habla)\b", re.I)
_ONLY = re.compile(r"\b(?:only (?:these|those|the supplied) (?:words|lines)|no (?:extra|additional) (?:speech|dialogue)|s[oó]lo (?:estas|esas) (?:frases|palabras)|sin (?:diálogo|dialogo) adicional)\b", re.I)
_VISIBLE = re.compile(r"\b(?:sign|title|banner|label|subtitle|reads?|written|cartel|título|titulo|letrero|subtítulo|subtitulo|escrito)\b", re.I)


def requests_silence(prompt: str) -> bool:
    # A quoted spoken line may itself contain 'no dialogue'. It is not policy.
    clean = _TAG.sub("", str(prompt))
    clean = _QUOTE.sub("", clean)
    return bool(_SILENT.search(clean))


def requests_only_supplied_lines(prompt: str) -> bool:
    """True when the user forbids extra speech outside quoted/tagged lines."""
    return bool(_ONLY.search(_QUOTE.sub("", str(prompt or ""))))


def _speaker_before(source: str, offset: int) -> str:
    prefix = source[max(0, offset-500):offset]
    named = re.search(r'([\wÀ-ÿ.-]+(?:\s+[\wÀ-ÿ.-]+){0,3})\s+(?:says?|asks?|replies|dice|responde|pregunta|grita|susurra|canta)\s*[:：]?\s*$', prefix, re.I)
    labelled = re.search(r'(?:^|\n)\s*([\wÀ-ÿ .-]{1,60}):\s*$', prefix)
    explicit_id = re.search(r'\((S\d+)\)[^()]*$', prefix)
    speaker = (named or labelled).group(1).strip() if (named or labelled) else ""
    if speaker and not speaker[0].isupper():
        speaker = ""
    if not speaker:
        # Actor attribution and intervening action are not the speaker's
        # name: "George Costanza, played by Jason Alexander, ... says".
        sentence_names = re.findall(r'(?:^|[.!?]\s+[»”"]?\s*|\n)\s*([A-ZÀ-Ý][\wÀ-ÿ-]+(?:\s+[A-ZÀ-Ý][\wÀ-ÿ-]+){0,2})', prefix)
        speaker = sentence_names[-1] if sentence_names else ""
    return speaker or (explicit_id.group(1) if explicit_id else "")


def _quote_is_speech(prefix: str) -> bool:
    speech = list(_SPEECH.finditer(prefix))
    visible = list(_VISIBLE.finditer(prefix))
    if speech and (not visible or speech[-1].start() > visible[-1].start()):
        return True
    return bool(re.search(r'(?:^|\n)\s*[\wÀ-ÿ .-]{1,60}:\s*$', prefix)) and not visible


def extract_locked_lines(prompt: str) -> list[dict[str, str]]:
    """Extract explicit spoken text without treating film names or signs as speech."""
    result = []
    source = str(prompt or "")
    spans = [(m.start(), m.end()) for m in _TAG.finditer(source)]
    matches = [(m.start(), m.group(2).strip(), m.group(1).strip()) for m in _TAG.finditer(source)]
    for m in _QUOTE.finditer(source):
        if any(start <= m.start() < end for start, end in spans):
            continue
        prefix = source[max(0, m.start()-160):m.start()]
        if not _quote_is_speech(prefix):
            continue
        words = next(group for group in m.groups() if group is not None)
        requested = re.search(r"\b(?:en|in)\s+(español|Spanish|English|inglés|French|francés|German|alemán|Italian|italiano|Portuguese|portugués)\b", source, re.I)
        language = h3_language_tag(requested.group(1)) if requested else spoken_language_of(words)
        matches.append((m.start(), words, language))
    for index, (offset, words, language) in enumerate(sorted(matches)):
        result.append({"id": f"D{index+1}", "text": words, "language": language,
                       "speaker": _speaker_before(source, offset)})
    return result


def _add_generated_line(line, text, index, seen, add):
    identity = (str(line.get("speaker") or "").casefold(), text)
    if identity in seen:
        return
    if not add(line, index):
        raise ValueError(f"H3 generated dialogue does not fit window {index+1}; shorten it or increase duration")
    seen.add(identity)


def _silence_without_script(source, locked):
    return requests_silence(source) and not locked


def _matching_literal(pending, line, text):
    return next((item for item in pending if item["text"] == text or item["id"] == line.get("id")), None)


def _consume_window_dialogue(windows, pending, locked, allow_extra, add):
    seen_generated = set()
    locked_words = {item["text"] for item in locked}
    for index, window in enumerate(windows):
        for line in window.get("dialogue") or []:
            if not isinstance(line, dict):
                continue
            text = str(line.get("text") or "").strip()
            literal = _matching_literal(pending, line, text)
            if literal:
                if add(line, index, literal):
                    pending.remove(literal)
            elif text not in locked_words and (not locked or allow_extra):
                _add_generated_line(line, text, index, seen_generated, add)


def reconcile_window_dialogue(
    plan: dict[str, Any], source: str, style: str, boundaries: list[dict],
) -> list[dict[str, Any]]:
    """Lock authored words and ownership, reject duplicates and impossible timing.

    The LLM chooses when a literal line happens, but cannot change its content.
    Missing lines are assigned deterministically to the next available window.
    Returns the canonical ledger persisted next to the rendered plan.
    """
    mode = planning_style(style)
    locked = extract_locked_lines(source)
    windows = plan.get("windows") or []
    if len(windows) != len(boundaries):
        raise ValueError("H3 dialogue ledger needs the exact window count")
    allow_extra = mode == "creative" and not _ONLY.search(_QUOTE.sub("", source))
    if _silence_without_script(source, locked):
        for window in windows:
            window["dialogue"] = []
        return []
    pending = list(locked)
    ledger = []
    speakers: dict[str, str] = {}
    budgets = [max(0.0, float(b["end_seconds"])-float(b["start_seconds"])) for b in boundaries]
    used = [0.0] * len(windows)

    def add(line: dict, index: int, literal: dict | None = None) -> bool:
        text = str((literal or line).get("text") or "").strip()
        if not text:
            return True
        speaker = str((literal or {}).get("speaker") or line.get("speaker") or "Speaker").strip()
        language = str((literal or line).get("language") or spoken_language_of(text))
        seconds = max(0.5, len(re.findall(r"\w+(?:['’-]\w+)*", text)) / 2)
        if used[index] + seconds > budgets[index] + 0.001:
            return False
        key = speaker.casefold()
        speaker_id = speakers.setdefault(key, f"S{len(speakers)+1}")
        event = {
            "id": literal["id"] if literal else f"G{len(ledger)+1}",
            "speaker": speaker, "speaker_id": speaker_id,
            "text": text, "language": language,
            "window": index+1, "locked": literal is not None,
            "start_seconds": round(used[index], 3),
            "end_seconds": round(used[index]+seconds, 3),
            "delivery": str(line.get("delivery") or "natural"),
            "action": str(line.get("action") or ""),
        }
        used[index] += seconds
        ledger.append(event)
        return True

    _consume_window_dialogue(windows, pending, locked, allow_extra, add)
    for literal in pending:
        if not any(add(literal, index, literal) for index in range(len(windows))):
            raise ValueError("H3 literal dialogue does not fit the requested duration; increase it instead of truncating words")
    # First actual vocal event determines IDs, even after missing-line recovery.
    speakers.clear()
    ledger.sort(key=lambda item: (item["window"], item["start_seconds"]))
    for event in ledger:
        event["speaker_id"] = speakers.setdefault(event["speaker"].casefold(), f"S{len(speakers)+1}")
    for index, window in enumerate(windows):
        window["dialogue"] = [dict(event) for event in ledger if event["window"] == index+1]
    return ledger


def ledger_instructions(source: str, style: str) -> str:
    import json
    locked = extract_locked_lines(source)
    return writing_contract(style) + (
        "\nCanonical literal dialogue (copy text and speaker exactly; assign each ID once to a window):\n"
        + json.dumps(locked, ensure_ascii=False)
        + "\nDo not place spoken text in action, continuity, closing_state or sound fields; use dialogue arrays only."
    )


def reference_window_prompt(prompt: str, reference_context: str) -> str:
    """Compile the same canonical reference map for every Ref2VA window.

    A reference image is identity evidence, never an output keyframe. Voice
    numbering remains independent of image/video numbering.
    """
    definitions = []
    retention = []
    for line in str(reference_context or "").splitlines():
        match = re.match(r"\s*(<(?:Picture|Video|Audio)\s+\d+>)\s*:\s*(.+)", line)
        if not match:
            continue
        label, role = match.groups()
        if label.startswith("<Audio"):
            definitions.append(f"{label}: {role}.")
            retention_mode = "fully_copy" if "DRIVER" in role else "weak_reference" if "weak_reference" in role else "reference"
            retention.append(f"{label}: {retention_mode}, according to its explicit role.")
        else:
            subject = f"<Subject {1 + sum(row.startswith('<Subject') for row in definitions)}>"
            definitions.append(f"{subject} is the described content from {label}: {role}.")
            retention.append(f"{subject}: fully_preserved identity and requested attributes.")
    if not definitions:
        raise ValueError("H3 References sequence requires an ordered reference map")
    visual = re.search(r"integrated_multimodal_description:\s*(.*?)(?=overall_soundscape:|$)", prompt, re.S)
    sound = re.search(r"overall_soundscape:\s*(.*?)(?=non_diegetic_music:|$)", prompt, re.S)
    music = re.search(r"non_diegetic_music:\s*(.*)$", prompt, re.S)
    return "\n\n".join([
        "subject_definitions:\n" + "\n".join(definitions),
        "summary: [reference generation] Continue the requested scene using the canonical references.",
        "retention_analysis:\n" + "\n".join(retention),
        "detailed_description: " + (visual.group(1).strip() if visual else prompt),
        "overall_soundscape: " + (sound.group(1).strip() if sound else "N/A"),
        "non_diegetic_music: " + (music.group(1).strip() if music else "N/A"),
    ])


def enforce_single_dialogue(result: str, source: str, style: str) -> str:
    """Drop invented tagged speech in Faithful and honor explicit no-speech requests.

    The enhancer's existing missing-line compiler owns literal recovery. This
    final gate prevents additional LLM lines surviving its structural checks.
    """
    locked = extract_locked_lines(source)
    silent = requests_silence(source) and not locked
    restrict = bool(locked) and (planning_style(style) == "faithful" or bool(_ONLY.search(_QUOTE.sub("", source))))
    remaining = Counter(line["text"] for line in locked)

    def keep(match):
        if silent:
            return ""
        if not restrict:
            return match.group(0)
        words = match.group(2).strip()
        if remaining[words]:
            remaining[words] -= 1
            return match.group(0)
        return ""

    return _TAG.sub(keep, result)


def tag_source_dialogue(source: str) -> str:
    locked = extract_locked_lines(source)
    used = Counter()
    def replace(match):
        words = next(group for group in match.groups() if group is not None)
        line = next((item for item in locked if item["text"] == words and not used[item["id"]]), None)
        if line is None:
            return match.group(0)
        used[line["id"]] += 1
        ordinal = locked.index(line) + 1
        return f'{line["speaker"] or "The intended speaker"} (S{ordinal}) {tagged_dialogue(line["language"], line["text"])}'
    return _QUOTE.sub(replace, source)


def repair_literal_tags(result: str, source: str, *, bind_speakers: bool = False) -> str:
    """Restore exact authored words after harmless LLM punctuation changes."""
    locked = extract_locked_lines(source)
    speakers = {}
    for line in locked:
        name = line["speaker"] or "Speaker"
        speakers.setdefault(name, f"S{len(speakers)+1}")
    def key(text):
        return ' '.join(text.strip().rstrip('.,!?;:').casefold().split())
    def repair(match):
        literal = next((line for line in locked if key(line['text']) == key(match.group(2))), None)
        if literal is None:
            return match.group(0)
        name = literal["speaker"] or "Speaker"
        binding = f'{name} ({speakers[name]}) ' if bind_speakers and not re.search(r"\(S\d+\)", result) else ""
        return binding + tagged_dialogue(literal["language"], literal["text"])
    return _TAG.sub(repair, str(result or ''))

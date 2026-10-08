"""Spanish phonetic comparison and pronunciation substitutions.

Used only to judge a take and to build the string sent to speech. The script,
the subtitle and the recording key stay on the written line.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from services.voice_pitch import pitch_notice, voice_checks

_VOWELS = "aeiou"


def phonetic_es(word: str) -> str:
    """A compare-only Spanish spelling. The steps stay in this order."""
    text = _silent_h(_letters(word).replace("v", "b").replace("ll", "y"))
    text = _soft_g(_hard_c(_seseo(text).replace("qu", "k")))
    return _singles(text)


def merge_names(tokens: list[str], names: list[str] | None) -> list[str]:
    """Join one to three consecutive words when they sound like one name.

    The longest window wins. Both sides of a comparison should pass through here,
    so «San Sebas Tián» and «San Sebastián» become the same single token.
    """
    phonetic = [phonetic_es(token) for token in tokens]
    targets = _name_targets(names or [])
    if not targets:
        return phonetic
    merged: list[str] = []
    index = 0
    while index < len(phonetic):
        width, canonical = _matching_window(phonetic, index, targets)
        if width:
            merged.append(canonical)
            index += width
        else:
            merged.append(phonetic[index])
            index += 1
    return merged


def token_error_rate(reference: list[str], hypothesis: list[str]) -> float:
    """Word error rate over tokens that are already normalized."""
    previous = list(range(len(hypothesis) + 1))
    for index, ref_word in enumerate(reference, start=1):
        current = [index] + [0] * len(hypothesis)
        for hyp_index, hyp_word in enumerate(hypothesis, start=1):
            current[hyp_index] = min(
                previous[hyp_index] + 1, current[hyp_index - 1] + 1,
                previous[hyp_index - 1] + (ref_word != hyp_word))
        previous = current
    return previous[-1] / max(1, len(reference))


def wer_threshold(word_count: int, *, spanish: bool, floor: float = 0.15) -> float:
    """Up to four Spanish words may miss one word; longer lines keep the floor."""
    if spanish and 0 < word_count <= 4:
        return max(floor, 1 / word_count)
    return floor


def dictionary_map(value: Any) -> dict[str, str]:
    """The UI object ``{word: pronunciation}``. A free-text blob migrates line by line."""
    if isinstance(value, dict):
        return _pairs(value.items())
    if not isinstance(value, str):
        return {}
    pairs = []
    for line in value.splitlines():
        if "=" in line:
            word, said = line.split("=", 1)
        elif ":" in line:
            word, said = line.split(":", 1)
        else:
            continue
        pairs.append((word, said))
    return _pairs(pairs)


def pronounce(text: str, dictionary: Any) -> str:
    """Replace whole words, ignoring case. The longest key wins. The script is not changed here."""
    mapping = dictionary_map(dictionary)
    if not mapping or not text:
        return str(text or "")
    keys = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(key) for key in keys) + r")\b", re.IGNORECASE)

    def replace(match: re.Match[str]) -> str:
        found = match.group(0)
        for key in keys:
            if key.lower() == found.lower():
                return mapping[key]
        return found

    return pattern.sub(replace, str(text))


def line_notes(series: dict, beat: dict, voice: dict) -> dict:
    """A copy of the kit voice plus the series dictionary and names.

    The caller hashes the original voice for the recording key before this copy exists.
    """
    dictionary = dictionary_map(_profile(series, beat.get("characterId")).get("pronunciationDictionary"))
    names = _speech_names(series, dictionary)
    if not dictionary and not names:
        return voice_checks(series, beat, voice)
    noted = dict(voice)
    if dictionary:
        noted["pronunciationDictionary"] = dictionary
    if names:
        noted["speechNames"] = names
    return voice_checks(series, beat, noted if dictionary or names else voice)


def _accent_warning(call, workspace: str, filename: str, text: str) -> dict[str, Any] | None:
    """The seseo warning, or None when the take is Castilian, unknown, or the tool did not answer."""
    checked = call("qa.accent", {"version": 1, "input": {
        "workspace": workspace, "file": filename, "text": text, "accent": "castilian"}})
    if not isinstance(checked, dict) or checked.get("_is_error"):
        return None
    found = checked.get("result") if isinstance(checked.get("result"), dict) else {}
    if found.get("verdict") != "seseo":
        return None
    return {"thetaRate": found.get("thetaRate"), "positions": found.get("positions"), "verdict": "seseo"}


def _take_notes(call, workspace: str, filename: str, said: str, voice: dict, result: dict) -> dict[str, Any]:
    """Pitch and accent warnings for the stored take. Neither one changes the accept limit."""
    notes: dict[str, Any] = {}
    notice = pitch_notice(result.get("medianPitchHz"), voice.get("pitchRange"))
    if notice:
        notes["pitch_out_of_range"] = notice
    if voice.get("accent") == "castilian":
        warning = _accent_warning(call, workspace, filename, said)
        if warning:
            notes["accent_seseo"] = warning
    return notes


def qa_verdict(call, workspace: str, filename: str, text: str, language: str,
               voice: dict | None, ceiling: float) -> tuple[float | None, float, dict]:
    """``(wer, accept_at, notes)`` for one take. A missing check accepts, as before.

    ``accept_at`` is the render ceiling unless the Spanish length threshold is higher,
    so a one-word line can miss and a long line is not judged more strictly.
    ``notes`` may carry ``pitch_out_of_range`` or ``accent_seseo``. They do not retry.
    """
    voice = voice or {}
    said = pronounce(text, voice.get("pronunciationDictionary"))
    payload: dict[str, Any] = {"workspace": workspace, "file": filename, "text": said, "language": language}
    names = [str(item) for item in voice.get("speechNames") or [] if str(item).strip()]
    if names:
        payload["names"] = names
    bounds = voice.get("pitchRange")
    if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
        payload["pitch_range"] = [bounds[0], bounds[1]]
    checked = call("qa.speech", {"version": 1, "input": payload})
    if not isinstance(checked, dict) or checked.get("_is_error"):
        return None, ceiling, {}
    result = checked.get("result") if isinstance(checked.get("result"), dict) else {}
    notes = _take_notes(call, workspace, filename, said, voice, result)
    limit = _accept_at(result.get("wer_threshold"), ceiling)
    wer = result.get("wer")
    if isinstance(wer, bool) or not isinstance(wer, (int, float)):
        return None, limit, notes
    return float(wer), limit, notes


def _letters(word: str) -> str:
    text = unicodedata.normalize("NFKD", str(word or "").lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "".join(char for char in text if "a" <= char <= "z")


def _silent_h(text: str) -> str:
    kept: list[str] = []
    for index, char in enumerate(text):
        if char == "h" and _h_is_silent(kept, text, index):
            continue
        kept.append(char)
    return "".join(kept)


def _h_is_silent(kept: list[str], text: str, index: int) -> bool:
    if not kept:
        return True
    nxt = text[index + 1] if index + 1 < len(text) else ""
    return kept[-1] in _VOWELS and nxt in _VOWELS


def _seseo(text: str) -> str:
    return _map_pairs(text, lambda char, nxt: "s" if char == "z" or (char == "c" and nxt in "ei") else char)


def _hard_c(text: str) -> str:
    return _map_pairs(text, lambda char, nxt: "k" if char == "c" and nxt in "aou" else char)


def _soft_g(text: str) -> str:
    return _map_pairs(text, lambda char, nxt: "j" if char == "g" and nxt in "ei" else char)


def _map_pairs(text: str, decide) -> str:
    out = []
    for index, char in enumerate(text):
        nxt = text[index + 1] if index + 1 < len(text) else ""
        out.append(decide(char, nxt))
    return "".join(out)


def _singles(text: str) -> str:
    out: list[str] = []
    for char in text:
        if not out or out[-1] != char:
            out.append(char)
    return "".join(out)


def _name_targets(names: list[str]) -> list[str]:
    targets: list[str] = []
    for name in names:
        joined = "".join(phonetic_es(part) for part in _name_parts(name))
        if joined and joined not in targets:
            targets.append(joined)
    return targets


def _name_parts(name: str) -> list[str]:
    return [part for part in re.split(r"[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", str(name)) if part]


def _matching_window(tokens: list[str], index: int, targets: list[str]) -> tuple[int, str]:
    for width in (3, 2, 1):
        if index + width > len(tokens):
            continue
        found = _close("".join(tokens[index:index + width]), targets)
        if found:
            return width, found
    return 0, ""


def _close(window: str, targets: list[str]) -> str:
    for target in targets:
        if abs(len(window) - len(target)) <= 1 and _distance(window, target) <= 1:
            return target
    return ""


def _distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for index, left_char in enumerate(left, start=1):
        current = [index] + [0] * len(right)
        for right_index, right_char in enumerate(right, start=1):
            current[right_index] = min(
                previous[right_index] + 1, current[right_index - 1] + 1,
                previous[right_index - 1] + (left_char != right_char))
        previous = current
    return previous[-1]


def _pairs(items) -> dict[str, str]:
    mapped = {}
    for key, value in items:
        word, said = str(key).strip(), str(value).strip()
        if word and said:
            mapped[word] = said
    return mapped


def _profile(series: dict, character_id: Any) -> dict:
    for item in series.get("characters") or []:
        if isinstance(item, dict) and item.get("id") == character_id:
            profile = item.get("voiceProfile")
            return profile if isinstance(profile, dict) else {}
    return {}


def _speech_names(series: dict, dictionary: dict[str, str]) -> list[str]:
    found: list[str] = []
    for key in ("characters", "locations"):
        for item in series.get(key) or []:
            if isinstance(item, dict):
                _add_name(found, item.get("name"))
    for key in dictionary:
        _add_name(found, key)
    return found


def _add_name(found: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in found:
        found.append(text)


def _accept_at(threshold: Any, ceiling: float) -> float:
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        return ceiling
    return max(ceiling, float(threshold))

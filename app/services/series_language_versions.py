"""One episode in several languages: same shots and line ids, its own words, voices, takes and cut.

The Uncanny Valley production needed two whole series (``uv-en`` and
``uv-es``) to dub one episode. A language version now lives inside the
episode::

    episode.languageVersions = {
      "english": {"title": "...", "dialogue": {beatId: text}, "cards": {shotId: {"title", "body"}},
                  "approvedAttemptIds": {shotId: attemptId}, "assemblyAssetIds": [...], "latestAssemblyAssetId": "..."}}

The series' own spoken language is the original and keeps using
``shot.approvedAttemptId``. ``localized_view`` gives the render and the
assembly a copy of the series and episode in one language, so voices
(``voicesByLanguage``), lines, cards and approved takes all switch together
without duplicating shots. ``translation_prompt`` asks the configured LLM for
a version from the original text.
"""
from __future__ import annotations

import copy
from typing import Any

from services.series_shot_plan import LANGUAGE_KEYS, language_key

LANGUAGES = tuple(sorted(set(LANGUAGE_KEYS.values())))
LABELS = {"english": "English", "spanish": "Español", "french": "Français", "german": "Deutsch", "italian": "Italiano",
          "portuguese": "Português", "japanese": "日本語", "korean": "한국어", "chinese": "中文", "russian": "Русский"}
_TEXT = 2000


def _texts(value: Any, known: set[str], limit: int = _TEXT) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {key: str(text).strip()[:limit] for key, text in value.items() if key in known and isinstance(text, str) and text.strip()}


def _cards(value: Any, shots: set[str]) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    return {key: {"title": str(card.get("title") or "")[:200], "body": str(card.get("body") or "")[:1200]}
            for key, card in value.items() if key in shots and isinstance(card, dict)}


def _version(value: dict[str, Any], beats: set[str], shots: set[str], attempts: dict[str, set[str]]) -> dict[str, Any]:
    approved = value.get("approvedAttemptIds") if isinstance(value.get("approvedAttemptIds"), dict) else {}
    assemblies = [item for item in value.get("assemblyAssetIds") or [] if isinstance(item, str) and item]
    version = {
        "title": str(value.get("title") or "")[:300], "dialogue": _texts(value.get("dialogue"), beats),
        "cards": _cards(value.get("cards"), shots),
        "approvedAttemptIds": {shot: attempt for shot, attempt in approved.items() if attempt in attempts.get(shot, set())},
        "assemblyAssetIds": list(dict.fromkeys(assemblies)),
    }
    if isinstance(value.get("latestAssemblyAssetId"), str) and value["latestAssemblyAssetId"] in version["assemblyAssetIds"]:
        version["latestAssemblyAssetId"] = value["latestAssemblyAssetId"]
    return version


def normalize_language_versions(value: Any, shots: list[dict[str, Any]], original: str) -> dict[str, Any]:
    """Known languages only, except the original; lines, cards and takes must belong to the episode."""
    if not isinstance(value, dict):
        return {}
    beats = {beat["id"] for shot in shots for beat in shot.get("dialogueBeats") or [] if beat.get("id")}
    shot_ids = {shot["id"] for shot in shots}
    attempts = {shot["id"]: {attempt["id"] for attempt in shot.get("attempts") or []} for shot in shots}
    return {language: _version(entry, beats, shot_ids, attempts) for language, entry in value.items()
            if language in LANGUAGES and language != original and isinstance(entry, dict)}


def _localized_shot(shot: dict[str, Any], version: dict[str, Any]) -> dict[str, Any]:
    shot = copy.deepcopy(shot)
    for beat in shot.get("dialogueBeats") or []:
        beat["text"] = version["dialogue"].get(beat["id"], beat.get("text", ""))
    card = version["cards"].get(shot["id"])
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else None
    if card and layout and isinstance(layout.get("card"), dict):
        layout["card"] = {**layout["card"], **{key: value for key, value in card.items() if value}}
    approved = version["approvedAttemptIds"].get(shot["id"])
    if approved:
        shot["approvedAttemptId"] = approved
    else:
        shot.pop("approvedAttemptId", None)
    return shot


def localized_view(series: dict[str, Any], episode: dict[str, Any], language: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Copies of the series and episode in ``language``; the original language returns them unchanged."""
    if not language or language == language_key(series):
        return series, episode
    version = (episode.get("languageVersions") or {}).get(language)
    if version is None:
        raise ValueError(f"The episode has no {language} version")
    view_series = {**series, "spokenLanguage": LABELS.get(language, language), "language": LABELS.get(language, language)}
    view_episode = {**episode, "title": version.get("title") or episode.get("title"),
                    "shots": [_localized_shot(shot, version) for shot in episode.get("shots") or []]}
    return view_series, view_episode


def missing_lines(episode: dict[str, Any], language: str, shot_ids: set[str] | None = None) -> list[str]:
    """Beat ids (of all shots, or of ``shot_ids``) that the version does not translate yet."""
    version = (episode.get("languageVersions") or {}).get(language) or {}
    dialogue = version.get("dialogue") or {}
    return [beat["id"] for shot in episode.get("shots") or [] if shot_ids is None or shot["id"] in shot_ids
            for beat in shot.get("dialogueBeats") or [] if str(beat.get("text") or "").strip() and beat["id"] not in dialogue]


def translation_request(series: dict[str, Any], episode: dict[str, Any], language: str) -> tuple[str, str, dict[str, Any]]:
    """Prompt, system prompt and JSON schema to translate an episode's lines and cards."""
    lines = [{"id": beat["id"], "speaker": beat.get("characterId", ""), "text": beat["text"]}
             for shot in episode.get("shots") or [] for beat in shot.get("dialogueBeats") or [] if str(beat.get("text") or "").strip()]
    cards = [{"shotId": shot["id"], **{key: shot["layout2d"]["card"].get(key, "") for key in ("title", "body")}}
             for shot in episode.get("shots") or [] if isinstance((shot.get("layout2d") or {}).get("card"), dict)]
    system = ("You translate animated comedy for dubbing. Keep each line's meaning, joke and character voice, keep it short "
              "enough to speak in about the same time, write numbers as spoken words, and never add stage directions. "
              "Keep every id exactly as given. Return only JSON.")
    prompt = (f"Series: {series.get('title')}. Tone: {series.get('tone') or 'comedy'}. Translate from "
              f"{series.get('spokenLanguage') or series.get('language')} to {LABELS.get(language, language)}.\n"
              f"Episode title: {episode.get('title')}\nLines: {lines}\nCards: {cards}")
    item = {"type": "object", "additionalProperties": False, "required": ["id", "text"],
            "properties": {"id": {"type": "string"}, "text": {"type": "string"}}}
    card = {"type": "object", "additionalProperties": False, "required": ["shotId", "title", "body"],
            "properties": {"shotId": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}}}
    schema = {"type": "object", "additionalProperties": False, "required": ["title", "lines", "cards"],
              "properties": {"title": {"type": "string"}, "lines": {"type": "array", "items": item}, "cards": {"type": "array", "items": card}}}
    return prompt, system, schema


def version_from_translation(result: Any, episode: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge an LLM translation into a version; ids the episode does not have are ignored."""
    version = copy.deepcopy(previous or {"title": "", "dialogue": {}, "cards": {}, "approvedAttemptIds": {}, "assemblyAssetIds": []})
    data = result if isinstance(result, dict) else {}
    beats = {beat["id"] for shot in episode.get("shots") or [] for beat in shot.get("dialogueBeats") or []}
    shots = {shot["id"] for shot in episode.get("shots") or []}
    version["title"] = str(data.get("title") or version.get("title") or "")[:300]
    for line in data.get("lines") or []:
        if isinstance(line, dict) and line.get("id") in beats and str(line.get("text") or "").strip():
            version["dialogue"][line["id"]] = str(line["text"]).strip()[:_TEXT]
    for card in data.get("cards") or []:
        if isinstance(card, dict) and card.get("shotId") in shots:
            version["cards"][card["shotId"]] = {"title": str(card.get("title") or "")[:200], "body": str(card.get("body") or "")[:1200]}
    return version

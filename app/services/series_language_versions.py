"""One episode in several languages: same shots and line ids, its own words, voices, takes and cut.

The Uncanny Valley production needed two whole series (``uv-en`` and
``uv-es``) to dub one episode. A language version now lives inside the
episode::

    episode.languageVersions = {
      "english": {"title": "...", "dialogue": {beatId: text}, "cards": {shotId: {"title", "body"}},
                  "approvedAttemptIds": {shotId: attemptId}, "assemblyAssetIds": [...], "latestAssemblyAssetId": "..."}}

The series' own spoken language is the original and keeps using
``shot.approvedAttemptId`` and ``shot.durationSeconds``; a version keeps its
own ``durations`` (set by its takes) and may swap a shot's ``music``. ``localized_view`` gives the render and the
assembly a copy of the series and episode in one language, so voices
(``voicesByLanguage``), lines, cards and approved takes all switch together
without duplicating shots. ``translation_prompt`` asks the configured LLM for
a version from the original text.

What the LLM translated (``series.episode.translate``) is marked until a person checks it::

    version.machineTranslated = {"dialogue": [beatId], "cards": [shotId], "title": true,
                                 "translatedAt": "...", "requestedBy": "agent" | "wizard" | "user" | "server"}

A person's edit of a line, card or title clears its mark (:func:`clear_checked`). An agent's or the Wizard's
write marks the lines, cards and title it just wrote (:func:`record_writer`), because a person has not checked
them. The server's own jobs leave the marks as they are.
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
    version.update(_optional_fields(value, version["assemblyAssetIds"], shots))
    machine = _machine(value.get("machineTranslated"), version)
    return {**version, **({"machineTranslated": machine} if machine else {})}


def _optional_fields(value: dict[str, Any], assemblies: list[str], shots: set[str]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(value.get("latestAssemblyAssetId"), str) and value["latestAssemblyAssetId"] in assemblies:
        found["latestAssemblyAssetId"] = value["latestAssemblyAssetId"]
    if isinstance(value.get("thumbnailAssetId"), str) and value["thumbnailAssetId"]:
        found["thumbnailAssetId"] = value["thumbnailAssetId"][:200]
    durations, music = _durations(value.get("durations"), shots), _music(value.get("music"), shots)
    return {**found, **({"durations": durations} if durations else {}), **({"music": music} if music else {})}


def _marked(ids: Any, kept: Any) -> list[str]:
    """The ids that ``kept`` (a version's dialogue or cards) still has, sorted."""
    if not isinstance(ids, list) or not isinstance(kept, dict):
        return []
    return sorted({item for item in ids if isinstance(item, str) and item in kept})


def _machine(value: Any, version: dict[str, Any]) -> dict[str, Any]:
    """The machine-translation marks of the lines, cards and title the version still has; {} when none is left."""
    if not isinstance(value, dict):
        return {}
    marks: dict[str, Any] = {"dialogue": _marked(value.get("dialogue"), version.get("dialogue")),
                             "cards": _marked(value.get("cards"), version.get("cards"))}
    if value.get("title") is True and str(version.get("title") or "").strip():
        marks["title"] = True
    if not (marks["dialogue"] or marks["cards"] or marks.get("title")):
        return {}
    for key in ("translatedAt", "requestedBy"):
        if isinstance(value.get(key), str) and value[key]:
            marks[key] = value[key][:40]
    return marks


def _written_ids(mapping: Any, *, cards: bool = False) -> list[str]:
    """Dialogue keys with text, or card keys with a title or a body."""
    if not isinstance(mapping, dict):
        return []
    found = []
    for key, value in mapping.items():
        if not isinstance(key, str) or not key:
            continue
        if cards:
            if isinstance(value, dict) and (str(value.get("title") or "").strip() or str(value.get("body") or "").strip()):
                found.append(key)
        elif isinstance(value, str) and value.strip():
            found.append(key)
    return found


def mark_written(version: dict[str, Any], update: dict[str, Any], requested_by: str) -> dict[str, Any]:
    """Mark the title, lines and cards an agent or the Wizard just wrote. Music is not text."""
    title = isinstance(update.get("title"), str) and bool(update["title"].strip())
    return _mark_translated(
        version, _written_ids(update.get("dialogue")), _written_ids(update.get("cards"), cards=True),
        title, requested_by, None,
    )


def record_writer(version: dict[str, Any], update: dict[str, Any], actor: str) -> dict[str, Any]:
    """A person clears marks on what they wrote. An agent or the Wizard marks that text. The server does neither."""
    if actor == "user":
        return clear_checked(version, update)
    if actor in ("agent", "wizard"):
        return mark_written(version, update, actor)
    return version


def clear_checked(version: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Drop the machine-translation mark of every line, card and title a person wrote in ``update``."""
    marks = version.get("machineTranslated")
    if not isinstance(marks, dict):
        return version
    edited_lines, edited_cards = set(update.get("dialogue") or {}), set(update.get("cards") or {})
    marks = {**marks, "dialogue": [item for item in marks.get("dialogue") or [] if item not in edited_lines],
             "cards": [item for item in marks.get("cards") or [] if item not in edited_cards]}
    if isinstance(update.get("title"), str):
        marks.pop("title", None)
    kept = _machine(marks, version)
    return {**{key: value for key, value in version.items() if key != "machineTranslated"},
            **({"machineTranslated": kept} if kept else {})}


def _durations(value: Any, shots: set[str]) -> dict[str, float]:
    """Seconds of each shot in this language: its own takes set it, the original keeps ``shot.durationSeconds``."""
    if not isinstance(value, dict):
        return {}
    return {key: round(float(seconds), 3) for key, seconds in value.items()
            if key in shots and isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and 0 < seconds <= 600}


def _music(value: Any, shots: set[str]) -> dict[str, str]:
    """A shot's music file in this language (a sung theme), replacing ``layout2d.music.file``."""
    if not isinstance(value, dict):
        return {}
    return {key: str(name).strip()[:300] for key, name in value.items()
            if key in shots and isinstance(name, str) and name.strip() and "/" not in name and ".." not in name}


def normalize_language_versions(value: Any, shots: list[dict[str, Any]], original: str) -> dict[str, Any]:
    """Known languages only, except the original; lines, cards and takes must belong to the episode."""
    if not isinstance(value, dict):
        return {}
    beats = {beat["id"] for shot in shots for beat in shot.get("dialogueBeats") or [] if beat.get("id")}
    shot_ids = {shot["id"] for shot in shots}
    attempts = {shot["id"]: {attempt["id"] for attempt in shot.get("attempts") or []} for shot in shots}
    return {language: _version(entry, beats, shot_ids, attempts) for language, entry in value.items()
            if language in LANGUAGES and language != original and isinstance(entry, dict)}


def _localize_layout(shot: dict[str, Any], version: dict[str, Any]) -> None:
    """Swap the card texts and the music file of a shot's 2D layout for the version's."""
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else None
    if layout is None:
        return
    card = version["cards"].get(shot["id"])
    if card and isinstance(layout.get("card"), dict):
        layout["card"] = {**layout["card"], **{key: value for key, value in card.items() if value}}
    music = (version.get("music") or {}).get(shot["id"])
    if music and isinstance(layout.get("music"), dict):
        layout["music"] = {**layout["music"], "file": music}


def _localized_shot(shot: dict[str, Any], version: dict[str, Any]) -> dict[str, Any]:
    shot = copy.deepcopy(shot)
    for beat in shot.get("dialogueBeats") or []:
        beat["text"] = version["dialogue"].get(beat["id"], beat.get("text", ""))
    _localize_layout(shot, version)
    if shot["id"] in (version.get("durations") or {}):
        shot["durationSeconds"] = version["durations"][shot["id"]]
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


def _shot(episode: dict[str, Any], shot_id: str) -> dict[str, Any]:
    shot = next((item for item in episode.get("shots") or [] if item.get("id") == shot_id), None)
    if shot is None:
        raise KeyError(shot_id)
    return shot


def set_version_duration(episode: dict[str, Any], language: str, shot_id: str, seconds: float) -> None:
    """A version's take sets that version's length of the shot; the original's is untouched."""
    _shot(episode, shot_id)
    version = (episode.get("languageVersions") or {}).get(language)
    if not isinstance(version, dict):
        raise ValueError(f"The episode has no {language} version")
    version.setdefault("durations", {})[shot_id] = round(float(seconds), 3)


def set_version_take(episode: dict[str, Any], language: str, shot_id: str, attempt_id: str, approved_by: str = "user",
                     now: str | None = None) -> None:
    """Approve a completed take for a language version and keep its length as the version's. The take records who
    approved it (``approvedBy``: user, agent, wizard or server, as ``series_library.REVIEWERS``)."""
    shot = _shot(episode, shot_id)
    attempt = next((item for item in shot.get("attempts") or [] if item.get("id") == attempt_id), None)
    if attempt is None or attempt.get("status") != "completed":
        raise ValueError("Approve a completed take of this shot")
    version = (episode.get("languageVersions") or {}).get(language)
    if not isinstance(version, dict):
        raise ValueError(f"The episode has no {language} version")
    version.setdefault("approvedAttemptIds", {})[shot_id] = attempt_id
    from services.series_library import REVIEWERS, _now
    attempt.update(approvedBy=approved_by if approved_by in REVIEWERS else "user", approvedAt=now or _now(),
                   approvedLanguage=language)
    seconds = (attempt.get("settings") or {}).get("sourceDurationSeconds")
    if isinstance(seconds, (int, float)) and seconds > 0:
        version.setdefault("durations", {})[shot_id] = round(float(seconds), 3)


def take_length_floor(series: dict[str, Any], episode: dict[str, Any] | None, shot: dict[str, Any], language: str | None) -> float:
    """How long a new take of ``shot`` must be: the shot's length in the original, the version's own length in a version."""
    if not language or language == language_key(series) or episode is None:
        return float(shot.get("durationSeconds") or 0)
    version = (episode.get("languageVersions") or {}).get(language) or {}
    return float((version.get("durations") or {}).get(shot.get("id"), 0))


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


def _merge_lines(dialogue: dict[str, str], lines: Any, beats: set[str]) -> list[str]:
    merged = []
    for line in lines if isinstance(lines, list) else []:
        text = str(line.get("text") or "").strip() if isinstance(line, dict) else ""
        if text and line.get("id") in beats:
            dialogue[line["id"]] = text[:_TEXT]
            merged.append(line["id"])
    return merged


def _merge_cards(cards: dict[str, dict[str, str]], found: Any, shots: set[str]) -> list[str]:
    merged = []
    for card in found if isinstance(found, list) else []:
        if isinstance(card, dict) and card.get("shotId") in shots:
            cards[card["shotId"]] = {"title": str(card.get("title") or "")[:200], "body": str(card.get("body") or "")[:1200]}
            merged.append(card["shotId"])
    return merged


def version_from_translation(result: Any, episode: dict[str, Any], previous: dict[str, Any] | None = None, *,
                             requested_by: str | None = None, now: str | None = None) -> dict[str, Any]:
    """Merge an LLM translation into a version; ids the episode does not have are ignored. Every line, card and title
    it wrote is marked ``machineTranslated`` (with when, and who asked for it) until a person edits it."""
    version = copy.deepcopy(previous or {"title": "", "dialogue": {}, "cards": {}, "approvedAttemptIds": {}, "assemblyAssetIds": []})
    data = result if isinstance(result, dict) else {}
    shots = episode.get("shots") or []
    title = str(data.get("title") or "").strip()[:300]
    version["title"] = title or str(version.get("title") or "")[:300]
    lines = _merge_lines(version["dialogue"], data.get("lines"), {beat["id"] for shot in shots for beat in shot.get("dialogueBeats") or []})
    cards = _merge_cards(version["cards"], data.get("cards"), {shot["id"] for shot in shots})
    return _mark_translated(version, lines, cards, bool(title), requested_by, now)


def _mark_translated(version: dict[str, Any], lines: list[str], cards: list[str], title: bool, requested_by: str | None,
                     now: str | None) -> dict[str, Any]:
    """Add what a translation wrote to the version's machine-translation marks (kept for what it did not touch)."""
    from services.series_library import REVIEWERS, _now
    marks = version.get("machineTranslated") if isinstance(version.get("machineTranslated"), dict) else {}
    found = _machine({
        "dialogue": [*marks.get("dialogue", []), *lines], "cards": [*marks.get("cards", []), *cards],
        "title": title or marks.get("title") is True, "translatedAt": now or _now(),
        "requestedBy": requested_by if requested_by in REVIEWERS else "user"}, version)
    version.pop("machineTranslated", None)
    return {**version, **({"machineTranslated": found} if found else {})}

"""Short search over the Video 3D shots the editor already ships.

The JSON is a projection of the UI library. It stores cards, not documents.
``world3d.templates.catalog`` is the bounded search, not a dump of every description.

A card carries, besides its copy, the traits the exporter read from the built document: how close the camera is
(``shot``), what it does (``moves``), what the template itself animates (``moving``, ``still``), who fits
(``subjects``, ``props``, ``authoredFor``), the ``floor``, the ``uses`` it is good for, its ``kind`` (scene, stage,
camera, look, transition, title), its ``place`` and whether a subject ``travel``s. A query is matched word by word in
both languages through ``world3d_template_vocabulary``; a literal word outranks a synonym and a trait outranks a stray
word in a line. Query words that no card of the library knows come back as ``unknown_words`` and never count against
the match. When no card has every known word, the best cards with at least half of them come back marked
``match: partial`` and nothing is applied.
"""
from __future__ import annotations

import json
import re
import unicodedata
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from services.template_search import stem
from services.world3d_stage_cards import stage_cards
from services.world3d_template_vocabulary import FORMATS, KINDS, MOVES, QUERY_STOP, SHOT_SIZES, USES, expand

CATALOG_FILE = "world3d_templates.json"
CATALOG_OPERATION = "world3d.templates.catalog"
USER_FILE = "world3d-user-templates.json"
DEFAULT_LIMIT = 8
MAX_LIMIT = 24
# A plain listing (no query) pages by id; a query stays the bounded search above.
LIST_DEFAULT_LIMIT = 50
LIST_MAX_LIMIT = 50
SUGGEST_LIMIT = 3
SUGGEST_MAX_LIMIT = 8
SUGGEST_BEATS = ("dialogue", "reaction", "establishing", "action", "speed", "impact", "reveal", "transition", "title",
                 "music", "product")
CARD_KEYS = (
    "id", "titleEs", "titleEn", "category", "family", "variantOf", "format", "width", "height", "duration",
    "playbackSpeed", "dressing", "setting", "lineEs", "lineEn", "notesEs", "notesEn", "preview", "roles", "required",
    "dependencies", "tags", "shot", "distance", "moves", "moving", "still", "subjects", "props", "screens",
    "authoredFor", "floor", "uses", "kind", "place", "travel", "reference", "cameras", "source")
TRAIT_DEFAULTS = {"notesEs": "", "notesEn": "", "shot": None, "distance": None, "moves": [], "moving": [], "still": None,
                  "subjects": 0, "props": 0, "screens": 0, "authoredFor": "none", "floor": None, "uses": [],
                  "kind": "scene", "place": None, "travel": False, "reference": None, "cameras": []}
_ROOT = Path(__file__).resolve().parents[1] / "shared" / CATALOG_FILE
_SUBJECT_ROLES = ("subject_1", "subject_2")
_ANIMATED_SLOT_KEYS = ("motion", "clip", "clips", "performance", "rhythm", "appearance", "speech")
# The values most cards share name the library, not the shot, so they are not search words.
_DEFAULT_TRAITS = {"category": "cinema", "setting": "studio"}
# Points per query word: a literal word in a field, else one of its synonyms. Traits outrank a stray word in a line.
_FIELD_POINTS = (("id", 8, 4), ("title", 6, 3), ("traits", 6, 4), ("line", 2, 1))
_NAME_FIELDS = ("id", "title")
_SHORT_TOKEN = 3
_MIN_STEM = 4
# Our own render of a shipped card (app/services/world3d_thumbnails.py). The JSON keeps ``preview: null``: the URL is
# added when a card is read, so the file stays free of URLs and the exporter's --check is unchanged.
THUMBNAIL_PATH = "/api/v1/world3d/templates/{template_id}/thumbnail"


class World3DTemplateError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        self.code = code
        self.status = status
        super().__init__(message)


@lru_cache(maxsize=1)
def builtin_cards() -> tuple[dict, ...]:
    data = json.loads(_ROOT.read_text(encoding="utf-8"))
    cards = data.get("catalog") if isinstance(data, dict) else None
    if not isinstance(cards, list) or not cards:
        raise World3DTemplateError("catalog_unreadable", "Video 3D template catalog is unreadable", 500)
    return (*cards, *stage_cards())


def builtin_card(template_id: str) -> dict | None:
    """The shipped card of one template, or None for a personal or unknown id."""
    return next((card for card in builtin_cards() if card.get("id") == template_id), None)


def search_templates(query: str = "", *, category: str | None = None, language: str | None = None,
                     limit: int | None = None, workspace_dir=None, workspace: str | None = None,
                     roles: list[str] | None = None, setting: str | None = None, **filters) -> list[dict]:
    """Return at most ``limit`` short cards. Both languages are always searched.

    Every card carries ``match``: ``full`` when every known query word is in it, ``partial`` when no card has them
    all and this one has at least half. Partial cards are never mixed with full ones."""
    return search_report(query, category=category, language=language, limit=limit, workspace_dir=workspace_dir,
                         workspace=workspace, roles=roles, setting=setting, **filters)["templates"]


def search_report(query: str = "", *, category: str | None = None, language: str | None = None,
                  limit: int | None = None, workspace_dir=None, workspace: str | None = None,
                  roles: list[str] | None = None, setting: str | None = None, **filters) -> dict:
    """The bounded search with what it could not read: ``templates``, ``unknown_words`` and ``partial``."""
    _require_language(language)
    bounded = _limit(limit)
    library = _cards(workspace_dir, workspace)
    ranked, unknown = _ranked(query, library, _fitting(library, roles, setting, filters), category)
    cards = [_public_card(card, score, match) for score, match, _index, card in ranked[:bounded]]
    return {"templates": cards, "unknown_words": unknown, "partial": bool(cards) and cards[0]["match"] == "partial"}


def page_templates(query: str = "", *, category: str | None = None, language: str | None = None,
                   limit: int | None = None, offset: int | None = None, workspace_dir=None,
                   workspace: str | None = None, roles: list[str] | None = None, setting: str | None = None,
                   **filters) -> dict:
    """One page of ``world3d.templates.list``. No query keeps id order."""
    _require_language(language)
    queried = bool(str(query or "").strip())
    bounded = _limit(limit) if queried else _list_limit(limit)
    start = _offset(offset)
    library = _cards(workspace_dir, workspace)
    cards = _fitting(library, roles, setting, filters)
    unknown: list[str] = []
    if queried:
        ranked, unknown = _ranked(query, library, cards, category)
        chosen = [(score, match, card) for score, match, _index, card in ranked]
    else:
        filtered = [card for card in cards if _in_category(card, category)]
        filtered.sort(key=lambda card: str(card.get("id") or ""))
        chosen = [(0, "full", card) for card in filtered]
    page = chosen[start:start + bounded]
    partial = bool(chosen) and chosen[0][1] == "partial"
    return {"templates": [_public_card(card, score, match) for score, match, card in page], "total": len(chosen),
            "partial": partial, "unknown_words": unknown}


def suggest_templates(*, line: str = "", speakers: int | None = None, place: str = "", mood: str = "",
                      beat: str | None = None, format: str | None = None, kind: str | None = None,
                      limit: int | None = None, workspace_dir=None, workspace: str | None = None) -> dict:
    """Up to ``limit`` cards for a shot described as a writer would (contract §5). Never instantiates.

    ``speakers`` becomes the ``subjects`` filter and ``talk``/``dialogue`` (none speaking: ``establishing``), ``beat``
    is the ``use`` and wins over the speakers' one, ``place`` and ``mood`` join the line as query words. Each card
    says in ``reason`` which of its traits answered."""
    filters = _suggest_filters(speakers, beat, format, kind)
    bounded = _suggest_limit(limit)
    query = " ".join(str(part or "").strip() for part in (line, place, mood) if str(part or "").strip())
    report = search_report(query, limit=bounded, workspace_dir=workspace_dir, workspace=workspace, **filters)
    for card in report["templates"]:
        card["reason"] = _reason(card)
    return {**report, "filters": filters}


def _suggest_filters(speakers, beat, format, kind) -> dict:
    filters: dict = {}
    if speakers is not None:
        if type(speakers) is not int or not 0 <= speakers <= 4:
            raise World3DTemplateError("invalid_speakers", "speakers must be an integer from 0 to 4")
        filters["use"] = "establishing" if speakers == 0 else "talk" if speakers == 1 else "dialogue"
        if speakers:
            filters["subjects"] = min(speakers, 2)
    chosen_beat = _choice(beat, SUGGEST_BEATS, "beat")
    if chosen_beat:
        filters["use"] = chosen_beat
    for name, allowed, value in (("format", FORMATS, format), ("kind", KINDS, kind)):
        chosen = _choice(value, allowed, name)
        if chosen:
            filters[name] = chosen
    return filters


def _suggest_limit(value: int | None) -> int:
    if value is None:
        return SUGGEST_LIMIT
    if type(value) is not int or not 1 <= value <= SUGGEST_MAX_LIMIT:
        raise World3DTemplateError("invalid_limit", f"limit must be an integer from 1 to {SUGGEST_MAX_LIMIT}")
    return value


_COUNT_WORDS = {0: "no subject", 1: "one subject", 2: "two subjects"}


def _reason(card: dict) -> str:
    """«two subjects, medium, moves: slide, uses: dialogue; place: cocina»: the traits in plain words."""
    subjects = int(card.get("subjects") or 0)
    parts = [_COUNT_WORDS.get(subjects, f"{subjects} subjects"), str(card.get("shot") or "unmeasured")]
    moves = card.get("moves") or []
    moving = [part for part in card.get("moving") or [] if part != "camera"]
    if moves:
        parts.append("moves: " + ", ".join(moves))
    elif moving:
        parts.append("moves on its own")
    else:
        parts.append("still")
    if card.get("uses"):
        parts.append("uses: " + ", ".join(card["uses"]))
    tail = []
    if card.get("place"):
        tail.append(f"place: {card['place']}")
    if card.get("travel"):
        tail.append("the subject crosses the set")
    if card.get("cameras"):
        tail.append("cameras: " + ", ".join(str(name) for name in card["cameras"]))
    if card.get("match") == "partial":
        tail.append("partial match")
    reason = ", ".join(parts)
    return f"{reason}; {'; '.join(tail)}" if tail else reason


def _fitting(cards: list[dict], roles: list[str] | None, setting: str | None, filters: dict) -> list[dict]:
    """Templates that have every asked role (subject_1, subject_2, background, prop), the asked setting and traits."""
    if roles is not None and (not isinstance(roles, list) or not all(isinstance(role, str) for role in roles)):
        raise World3DTemplateError("invalid_roles", "roles must be a list of role names")
    checks = [lambda card, wanted=set(roles or ()): wanted <= set(card.get("roles") or ())]
    place = _fold(setting or "")
    if place:
        checks.append(lambda card: _fold(str(card.get("setting") or "")) == place)
    checks.extend(_trait_checks(filters))
    return [card for card in cards if all(check(card) for check in checks)]


def _trait_checks(filters: dict) -> list:
    """One predicate per trait filter given: shot, use, move, format, kind, place, travel (exact) and subjects (at least)."""
    checks = []
    for name, allowed, key, exact in (("shot", SHOT_SIZES, "shot", True), ("use", USES, "uses", False),
                                      ("move", MOVES, "moves", False), ("format", FORMATS, "format", True),
                                      ("kind", KINDS, "kind", True)):
        wanted = _choice(filters.get(name), allowed, name)
        if wanted is None:
            continue
        if exact:
            checks.append(lambda card, key=key, wanted=wanted: card.get(key) == wanted)
        else:
            checks.append(lambda card, key=key, wanted=wanted: wanted in (card.get(key) or ()))
    subjects = _count(filters.get("subjects"))
    if subjects is not None:
        checks.append(lambda card: int(card.get("subjects") or 0) >= subjects)
    place = _place(filters.get("place"))
    if place:
        checks.append(lambda card: place in (_fold(str(card.get("place") or "")), _fold(str(card.get("dressing") or ""))))
    travel = filters.get("travel")
    if travel is not None:
        if not isinstance(travel, bool):
            raise World3DTemplateError("invalid_travel", "travel must be true or false: whether a subject crosses the set")
        checks.append(lambda card: bool(card.get("travel")) == travel)
    return checks


def _choice(value, allowed: tuple[str, ...], name: str) -> str | None:
    if value in (None, ""):
        return None
    folded = _fold(str(value)) if isinstance(value, str) else None
    if folded not in allowed:
        raise World3DTemplateError(f"invalid_{name}", f"{name} must be one of {', '.join(allowed)}")
    return folded


def _count(value) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 2:
        raise World3DTemplateError("invalid_subjects", "subjects must be an integer from 0 to 2: the subject slots a shot needs")
    return value


def _place(value) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise World3DTemplateError("invalid_place", "place must be a dressing, mold or world id")
    return _fold(value)


def _cards(workspace_dir, workspace: str | None) -> list[dict]:
    cards = list(builtin_cards())
    if workspace_dir is not None and workspace:
        cards.extend(_user_cards(workspace_dir, workspace))
    return cards


def _in_category(card: dict, category: str | None) -> bool:
    """``category`` names a category or a tag, as the editor's filter does."""
    return not category or card.get("category") == category or category in (card.get("tags") or ())


def _ranked(query: str, library: list[dict], cards: list[dict], category: str | None) -> tuple[list[tuple], list[str]]:
    """``(score, match, index, card)`` best first (full matches, else the partial ones) and the unknown words.

    A word is unknown when no card of the whole library has it; it is dropped before counting hits, so a query made
    only of unknown words returns nothing."""
    folded = _fold(query)
    tokens = _query_tokens(folded)
    known, unknown = _known_tokens(tokens, library)
    if tokens and not known:
        return [], unknown
    full, partial = [], []
    for index, card in enumerate(cards):
        if not _in_category(card, category):
            continue
        found = _match(folded, known, card)
        if found is None:
            continue
        hits, score = found
        if hits == len(known):
            full.append((score, hits, index, card))
        elif hits * 2 >= len(known):
            partial.append((score, hits, index, card))
    chosen = full or partial
    if known:
        chosen.sort(key=_rank_key)
    match = "full" if full else "partial"
    return [(score, match, index, card) for score, _hits, index, card in chosen], unknown


def _rank_key(item: tuple) -> tuple:
    """Contract §4 tie-break: score, hits, a card that moves before a still one, a base before a variant, the
    shorter id, catalogue order. An empty query keeps catalogue order instead."""
    score, hits, index, card = item
    return (-score, -hits, card.get("still") is True, card.get("variantOf") is not None, len(str(card.get("id") or "")), index)


def _known_tokens(tokens: list[str], library: list[dict]) -> tuple[list[str], list[str]]:
    """The query words some card knows, and the rest, each deduplicated in query order."""
    known, unknown = [], []
    personal = [card for card in library if card.get("source") == "workspace"]
    for token in dict.fromkeys(tokens):
        if _builtin_knows(token) or any(_token_hit(token, _card_words(card)) for card in personal):
            known.append(token)
        else:
            unknown.append(token)
    return known, unknown


@lru_cache(maxsize=4096)
def _builtin_knows(token: str) -> bool:
    return any(_token_hit(token, words) for words in _builtin_words().values())


@lru_cache(maxsize=1)
def _builtin_words() -> dict[str, dict[str, set[str]]]:
    return {str(card.get("id")): _words(card) for card in builtin_cards()}


def _card_words(card: dict) -> dict[str, set[str]]:
    if card.get("source") == "builtin":
        found = _builtin_words().get(str(card.get("id")))
        if found is not None:
            return found
    return _words(card)


def _require_language(language: str | None) -> None:
    if language not in (None, "es", "en"):
        raise World3DTemplateError("invalid_language", "language must be es or en")


def require_card(template_id: str, *, workspace_dir=None, workspace: str | None = None) -> dict:
    if not isinstance(template_id, str) or not template_id.strip():
        raise World3DTemplateError("unknown_template", "unknown_template:", 404)
    cards = list(builtin_cards())
    if workspace_dir is not None and workspace:
        cards.extend(_user_cards(workspace_dir, workspace))
    found = [card for card in cards if card.get("id") == template_id]
    if not found:
        raise World3DTemplateError("unknown_template", f"unknown_template:{template_id}", 404)
    return found[0]


def _limit(value: int | None) -> int:
    if value is None:
        return DEFAULT_LIMIT
    if type(value) is not int or not 1 <= value <= MAX_LIMIT:
        raise World3DTemplateError("invalid_limit", f"limit must be an integer from 1 to {MAX_LIMIT}")
    return value


def _list_limit(value: int | None) -> int:
    if value is None:
        return LIST_DEFAULT_LIMIT
    if type(value) is not int or not 1 <= value <= LIST_MAX_LIMIT:
        raise World3DTemplateError("invalid_limit", f"limit must be an integer from 1 to {LIST_MAX_LIMIT}")
    return value


def _offset(value: int | None) -> int:
    if value is None:
        return 0
    if type(value) is not int or value < 0:
        raise World3DTemplateError("invalid_offset", "offset must be an integer from 0")
    return value


def _user_rows(workspace_dir, workspace: str) -> list[dict]:
    path = Path(workspace_dir(workspace)) / USER_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise World3DTemplateError("user_templates_unreadable", "Personal Video 3D templates are unreadable", 409) from error
    rows = data.get("templates") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise World3DTemplateError("user_templates_unreadable", "Personal Video 3D templates are unreadable", 409)
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)]


def _user_cards(workspace_dir, workspace: str) -> list[dict]:
    return [_user_card(row) for row in _user_rows(workspace_dir, workspace)]


def list_user_templates(workspace_dir, workspace: str) -> list[dict]:
    """Every personal template of the workspace (newest first) for the Video 3D editor, without documents."""
    summaries = [_template_summary(row) for row in _user_rows(workspace_dir, workspace)]
    return sorted(summaries, key=lambda item: str(item.get("updatedAt") or ""), reverse=True)


def _template_summary(row: dict) -> dict:
    document = row.get("document") if isinstance(row.get("document"), dict) else {}
    slots = [slot for slot in document.get("slots") or [] if isinstance(slot, dict)]
    width, height = document.get("width") or 1280, document.get("height") or 720
    base = document.get("templateId")
    return {
        "id": row["id"], "title": row.get("title") or row["id"], "description": str(row.get("description") or ""),
        "createdAt": row.get("createdAt"), "updatedAt": row.get("updatedAt") or row.get("createdAt"),
        "createdBy": row.get("createdBy"), "baseTemplateId": base if isinstance(base, str) and not base.startswith("user-") else None,
        "duration": document.get("duration") or 0, "width": width, "height": height,
        "format": "portrait" if height > width else "landscape",
        "slots": len(slots), "pending": sum(1 for slot in slots if not slot.get("sourceUrl")),
    }


def user_template_row(template_id: str, workspace_dir, workspace: str) -> dict:
    """One stored personal template with its document exactly as saved (the editor keeps its base shot id)."""
    for row in _user_rows(workspace_dir, workspace):
        if row.get("id") == template_id and isinstance(row.get("document"), dict):
            return deepcopy(row)
    raise World3DTemplateError("unknown_template", f"unknown_template:{template_id}", 404)


def document_traits(document: dict) -> dict:
    """The traits a stored document shows without building it: who fits, what the slots animate, the floor.

    The camera estimate (``shot``, ``distance``, ``moves``) needs the UI's camera code, so a personal template keeps
    those unknown; ``moving`` lists what its slots and effects animate on their own."""
    slots = [slot for slot in document.get("slots") or [] if isinstance(slot, dict)]
    subjects = [slot for slot in slots if slot.get("slot") in _SUBJECT_ROLES]
    props = [slot for slot in slots if slot.get("slot") == "prop" and slot.get("media") != "screen"]
    media = {str(slot.get("media") or "model3d") for slot in subjects}
    environment = document.get("environment") if isinstance(document.get("environment"), dict) else {}
    return {
        "subjects": len(subjects), "props": len(props),
        "screens": sum(1 for slot in slots if slot.get("media") == "screen"),
        "authoredFor": "none" if not media else "mixed" if len(media) > 1 else "cutout" if "image" in media else "model",
        "floor": environment.get("floorStyle") or ("mirror" if environment.get("reflectiveFloor") else None),
        "moving": _document_moving(document, slots, subjects, props), "still": None,
        "travel": any(slot.get("motion") for slot in subjects),
    }


def _slot_animated(slot: dict) -> bool:
    return any(slot.get(key) for key in _ANIMATED_SLOT_KEYS)


def _slot_plays_video(slot: dict) -> bool:
    screen = slot.get("screen") if isinstance(slot.get("screen"), dict) else {}
    return screen.get("media") == "video" and bool(screen.get("sourceUrl"))


def _document_moving(document: dict, slots: list[dict], subjects: list[dict], props: list[dict]) -> list[str]:
    backdrop = document.get("screenBackdrop") if isinstance(document.get("screenBackdrop"), dict) else {}
    found = (
        ("subjects", any(_slot_animated(slot) for slot in subjects)),
        ("props", any(_slot_animated(slot) for slot in props)),
        ("screens", any(_slot_plays_video(slot) for slot in slots)),
        ("effects", bool(document.get("worldSfx") or document.get("sfx") or backdrop.get("sfx"))),
        ("texts", bool(document.get("texts") or document.get("lyrics"))),
    )
    return [name for name, moving in found if moving]


def _user_card(row: dict) -> dict:
    document = row.get("document") if isinstance(row.get("document"), dict) else {}
    slots = document.get("slots") if isinstance(document.get("slots"), list) else []
    width = document.get("width") or 1280
    height = document.get("height") or 720
    description = str(row.get("description") or "")
    return {
        "id": row.get("id"), "titleEs": row.get("title") or row.get("id"), "titleEn": row.get("title") or row.get("id"),
        "category": "personal", "family": "user", "variantOf": None,
        "format": "portrait" if height > width else "landscape", "width": width, "height": height,
        "duration": document.get("duration") or 0, "playbackSpeed": document.get("playbackSpeed") or 1,
        "dressing": document.get("dressing"), "setting": None, "lineEs": description, "lineEn": description,
        "preview": None, "roles": [slot.get("slot") for slot in slots if isinstance(slot, dict)],
        "required": [{"id": slot.get("id"), "role": slot.get("slot"), "media": slot.get("media")}
                     for slot in slots if isinstance(slot, dict) and not slot.get("sourceUrl")],
        "dependencies": [], "tags": [], **TRAIT_DEFAULTS, **document_traits(document),
        "place": document.get("dressing") or None, "source": "workspace",
    }


def thumbnail_url(card: dict) -> str | None:
    """The relative URL of our mid-shot render of a shipped or stage card; a personal template has none."""
    template_id = card.get("id")
    if card.get("source") == "workspace" or not isinstance(template_id, str) or not template_id:
        return None
    return THUMBNAIL_PATH.format(template_id=quote(template_id, safe=""))


def _public_card(card: dict, score: int, match: str = "full") -> dict:
    shown = {key: card.get(key, TRAIT_DEFAULTS.get(key)) for key in CARD_KEYS}
    shown["preview"] = thumbnail_url(card)
    shown["score"] = score
    shown["match"] = match
    return shown


def _query_tokens(folded: str) -> list[str]:
    tokens = folded.split()
    kept = [token for token in tokens if token not in QUERY_STOP]
    return kept or tokens


def _match(folded: str, tokens: list[str], card: dict) -> tuple[int, int] | None:
    """``(hits, points)`` for a card, or None when no query word is in it. An empty query matches everything."""
    if not tokens:
        return 0, 0
    words = _card_words(card)
    hits = sum(1 for token in tokens if _token_hit(token, words))
    if hits == 0:
        return None
    return hits, _points(folded, tokens, card, words)


def _token_hit(token: str, words: dict[str, set[str]]) -> bool:
    """The literal word anywhere in the card, or a synonym in its id, title or traits: a stray synonym in a line
    («sala de control» for a living room) is not the word."""
    literal = {token}
    return _hit(literal, words["all"]) or _hit(expand(token) - literal, words["core"])


def _points(folded: str, tokens: list[str], card: dict, words: dict[str, set[str]]) -> int:
    titles = {_fold(str(card.get("titleEs") or "")), _fold(str(card.get("titleEn") or ""))}
    ident = _fold(str(card.get("id") or "").replace("-", " "))
    score = 80 if folded in titles else 24 if len(folded) > _SHORT_TOKEN and any(folded in title for title in titles) else 0
    if ident == folded:
        score += 40
    for token in tokens:
        literal = {token}
        synonyms = expand(token) - literal
        short = len(token) <= _SHORT_TOKEN
        for field, exact, loose in _FIELD_POINTS:
            found = _hit(literal, words[field])
            # A short literal word («off», «bar») in the id or title is worth what a synonym is, not the literal points.
            if found and not (short and field in _NAME_FIELDS):
                score += exact
            elif found or _hit(synonyms, words[field]):
                score += loose
    return score


def _hit(candidates: frozenset[str] | set[str], words: set[str]) -> bool:
    for word in candidates:
        if word in words:
            return True
        root = stem(word)
        if len(root) >= _MIN_STEM and root in words:
            return True
    return False


def _words(card: dict) -> dict[str, set[str]]:
    """The words of each searchable field, with their stems, so «escenas» finds «escena»."""
    fields = {
        "id": str(card.get("id") or "").replace("-", " "),
        "title": f"{card.get('titleEs') or ''} {card.get('titleEn') or ''}",
        "line": f"{card.get('lineEs') or ''} {card.get('lineEn') or ''} {card.get('notesEs') or ''} {card.get('notesEn') or ''}",
        "traits": _trait_text(card),
    }
    found = {name: set(_fold(text).split()) for name, text in fields.items()}
    for name in found:
        # Short stems («mars» → «mar», «trees» → «tre») would make a sea of a planet.
        found[name] |= {root for root in (stem(word) for word in list(found[name])) if len(root) >= _MIN_STEM}
    found["core"] = found["id"] | found["title"] | found["traits"]
    found["all"] = found["core"] | found["line"]
    return found


_STILL_WORDS = {True: "still static", False: "animated", None: ""}
_SUBJECT_WORDS = {0: "nobody", 1: "solo", 2: "duo pair"}


def _speed_words(card: dict) -> str:
    speed = float(card.get("playbackSpeed") or 1)
    return "slowmotion" if speed < 1 else "timelapse fast" if speed > 1 else ""


def _trait_text(card: dict) -> str:
    """Trait words, tags, roles, kind, place, setting and format in the shared search vocabulary."""
    parts = [card.get(key) for key in ("category", "setting") if card.get(key) != _DEFAULT_TRAITS[key]]
    parts.extend(card.get(key) for key in ("family", "dressing", "shot", "authoredFor", "floor", "kind", "place"))
    parts.append(f"format{card.get('format') or ''}")
    parts.extend(" ".join(str(item) for item in card.get(key) or [])
                 for key in ("roles", "tags", "dependencies", "moves", "moving", "uses", "traitWords"))
    # A stage's camera names (close_1, wide, entrance) are one token each, so they are not shot-size or emotion words.
    parts.extend("cam" + _fold(str(name)).replace(" ", "") for name in card.get("cameras") or [])
    parts.append(_STILL_WORDS.get(card.get("still"), ""))
    parts.append(_SUBJECT_WORDS.get(int(card.get("subjects") or 0), "group"))
    parts.append("travel walk" if card.get("travel") else "")
    parts.append(_speed_words(card))
    return " ".join(str(part or "") for part in parts)


def _fold(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.lower()))


def user_template_document(template_id: str, workspace_dir, workspace: str) -> dict:
    path = Path(workspace_dir(workspace)) / USER_FILE
    if not path.is_file():
        raise World3DTemplateError("unknown_template", f"unknown_template:{template_id}", 404)
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data.get("templates") or []:
        if isinstance(row, dict) and row.get("id") == template_id and isinstance(row.get("document"), dict):
            document = deepcopy(row["document"])
            document["templateId"] = template_id
            return document
    raise World3DTemplateError("unknown_template", f"unknown_template:{template_id}", 404)

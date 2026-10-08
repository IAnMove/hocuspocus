"""Short search over the Video 3D shots the editor already ships.

The JSON is a projection of the UI library. It stores cards, not documents.
``world3d.templates.catalog`` is the bounded search, not a dump of every description.
"""
from __future__ import annotations

import json
import re
import unicodedata
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

CATALOG_FILE = "world3d_templates.json"
CATALOG_OPERATION = "world3d.templates.catalog"
USER_FILE = "world3d-user-templates.json"
DEFAULT_LIMIT = 8
MAX_LIMIT = 24
LIST_DEFAULT_LIMIT = 50
LIST_MAX_LIMIT = 200
_GROUPS = (
    frozenset({"orbit", "orbita", "girar", "alrededor", "around", "360"}),
    frozenset({"lluvia", "rain", "llueve"}),
    frozenset({"ralenti", "slow", "lento", "lenta", "slowmotion"}),
    frozenset({"zoom", "dolly"}),
)
_ROOT = Path(__file__).resolve().parents[1] / "shared" / CATALOG_FILE


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
    return tuple(cards)


def search_templates(query: str = "", *, category: str | None = None, language: str | None = None,
                     limit: int | None = None, workspace_dir=None, workspace: str | None = None) -> list[dict]:
    """Return at most ``limit`` short cards. Both languages are always searched."""
    _require_language(language)
    bounded = _limit(limit)
    ranked = _ranked(query, _cards(workspace_dir, workspace), category)
    return [_public_card(card, score) for score, _index, card in ranked[:bounded]]


def page_templates(query: str = "", *, category: str | None = None, language: str | None = None,
                   limit: int | None = None, offset: int | None = None, workspace_dir=None,
                   workspace: str | None = None) -> dict:
    """One page of ``world3d.templates.list``. No query keeps id order."""
    _require_language(language)
    bounded = _list_limit(limit)
    start = _offset(offset)
    cards = _cards(workspace_dir, workspace)
    if str(query or "").strip():
        chosen = [(score, card) for score, _index, card in _ranked(query, cards, category)]
    else:
        filtered = [card for card in cards if not category or card.get("category") == category]
        filtered.sort(key=lambda card: str(card.get("id") or ""))
        chosen = [(0, card) for card in filtered]
    page = chosen[start:start + bounded]
    return {"templates": [_public_card(card, score) for score, card in page], "total": len(chosen)}


def _cards(workspace_dir, workspace: str | None) -> list[dict]:
    cards = list(builtin_cards())
    if workspace_dir is not None and workspace:
        cards.extend(_user_cards(workspace_dir, workspace))
    return cards


def _ranked(query: str, cards: list[dict], category: str | None) -> list[tuple]:
    ranked = []
    for index, card in enumerate(cards):
        if category and card.get("category") != category:
            continue
        score = _score(query, card)
        if score is None:
            continue
        ranked.append((score, index, card))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked


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
        "dependencies": [], "tags": [], "source": "workspace",
    }


def _public_card(card: dict, score: int) -> dict:
    shown = {key: card.get(key) for key in (
        "id", "titleEs", "titleEn", "category", "family", "variantOf", "format", "width", "height",
        "duration", "playbackSpeed", "dressing", "setting", "lineEs", "lineEn", "preview", "roles",
        "required", "dependencies", "tags", "source")}
    shown["score"] = score
    return shown


def _score(query: str, card: dict) -> int | None:
    folded = _fold(query)
    if not folded:
        return 0
    blob = _blob(card)
    tokens = folded.split()
    if not all(_token_hits(token, blob) for token in tokens):
        return None
    return _points(folded, tokens, card)


def _points(folded: str, tokens: list[str], card: dict) -> int:
    titles = {_fold(str(card.get("titleEs") or "")), _fold(str(card.get("titleEn") or ""))}
    ident = _fold(str(card.get("id") or "").replace("-", " "))
    title_blob = _fold(f"{card.get('titleEs') or ''} {card.get('titleEn') or ''}")
    line_blob = _fold(f"{card.get('lineEs') or ''} {card.get('lineEn') or ''}")
    score = 80 if folded in titles else 24 if any(folded and folded in title for title in titles) else 0
    if ident == folded:
        score += 40
    for token in tokens:
        words = _expand(token)
        if any(word in ident.split() for word in words):
            score += 8
        if any(word in title_blob.split() for word in words):
            score += 6
        if any(word in line_blob.split() for word in words):
            score += 2
    return score


def _token_hits(token: str, blob: str) -> bool:
    words = blob.split()
    return any(word in words for word in _expand(token))


def _expand(token: str) -> set[str]:
    for group in _GROUPS:
        if token in group:
            return set(group)
    return {token}


def _blob(card: dict) -> str:
    parts = [str(card.get("id") or "").replace("-", " "), card.get("titleEs"), card.get("titleEn"), card.get("lineEs"),
             card.get("lineEn"), card.get("category"), card.get("family"), card.get("setting"), card.get("dressing"),
             " ".join(str(role) for role in card.get("roles") or []), " ".join(str(tag) for tag in card.get("tags") or []),
             " ".join(str(item) for item in card.get("dependencies") or [])]
    return _fold(" ".join(str(part or "") for part in parts))


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

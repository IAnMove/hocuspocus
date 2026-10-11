"""Read-only Video 2D catalogs shared with the UI. No GPU, save or export.

``scenes.catalog`` searches by words, not by a substring of the id: a writer's «plano general», «persecución» or
«rótulo con el nombre» goes through ``template_search.match`` over the id words, title, ``visualIntent``, family and
the ES/EN name and line of ``video2d_lines.json``, with the shared 3D vocabulary as synonyms. Words no entry knows
come back as ``unknown_words`` and do not count against a match.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from services.mcp_compact import summarize_entry
from services.template_search import match, query_words
from services.world3d_template_vocabulary import QUERY_STOP, expand

ROOT = Path(__file__).resolve().parents[1] / "shared"

CATALOG_FILES = {
    "scenes.templates.catalog": "scene_templates.json",
    "scenes.text.catalog": "text_templates.json",
    "scenes.finish.catalog": "finish_presets.json",
    "scenes.fonts.catalog": "fonts.json",
    "scenes.atmospheres.catalog": "atmospheres.json",
    "scenes.motion.catalog": "motion_presets.json",
}

BLURBS = {
    "scenes.templates.catalog": "List scene templates from scene_templates.json (id, family, review status, slots, controls, limits).",
    "scenes.text.catalog": "List kinetic text templates from text_templates.json (fields and 16:9 / 9:16 formats). Builders stay in the UI.",
    "scenes.finish.catalog": "List finish presets from finish_presets.json with clamp ranges.",
    "scenes.fonts.catalog": "List Video 2D font families from fonts.json (weights and license).",
    "scenes.atmospheres.catalog": "List atmosphere kinds from atmospheres.json with parameter defaults and ranges.",
    "scenes.motion.catalog": "List recipe motion and camera presets from motion_presets.json (a kind camera preset on a camera layer moves the view).",
}


class CatalogError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _entries(data: Any, name: str) -> list[Any]:
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = next((data[key] for key in ("entries", "items", "catalog") if isinstance(data.get(key), list)), None)
        if entries is None:
            raise CatalogError("catalog_invalid", name)
    else:
        raise CatalogError("catalog_invalid", name)
    if not entries or any(not isinstance(item, dict) for item in entries):
        raise CatalogError("catalog_invalid", name)
    return entries


def _require_ids(entries: list[Any], name: str) -> None:
    ids = [item.get("id") for item in entries]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        raise CatalogError("catalog_duplicate_id", name)


def load_catalog(name: str) -> Any:
    if not name or Path(name).name != name:
        raise CatalogError("catalog_missing", name)
    path = ROOT / name
    if not path.is_file():
        raise CatalogError("catalog_missing", name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as error:
        raise CatalogError("catalog_unreadable", name) from error
    except json.JSONDecodeError as error:
        raise CatalogError("catalog_invalid", name) from error
    _require_ids(_entries(data, name), name)
    return data


def _lyric_looks() -> dict[str, Any]:
    """lyric_looks.json keeps its looks under ``looks`` (production_lyric_looks reads it as it is)."""
    looks = {"entries": json.loads((ROOT / "lyric_looks.json").read_text(encoding="utf-8"))["looks"]}
    _require_ids(_entries(looks, "lyric_looks.json"), "lyric_looks.json")
    return looks


CATALOGS = {operation: load_catalog(filename) for operation, filename in CATALOG_FILES.items()}
EFFECTS_CATALOG = load_catalog("scene_effects.json")
GRAPHICS_CATALOG = load_catalog("scene_graphics.json")
LYRIC_LOOKS_CATALOG = _lyric_looks()
# One ES/EN name and line per text template, motion or camera preset, finish and lyric look, keyed by kind and id.
LINES = json.loads((ROOT / "video2d_lines.json").read_text(encoding="utf-8"))
LINE_KEYS = ("titleEs", "titleEn", "lineEs", "lineEn")

OPERATION = "scenes.catalog"
KINDS = ("templates", "text", "finish", "fonts", "atmospheres", "motion", "effects", "graphics", "lyric_looks")
PAGE_LIMIT = 200
QUERY_LIMIT = 80
MATCH_LIMIT = 20
_KIND_SOURCE = {
    "templates": "scenes.templates.catalog",
    "text": "scenes.text.catalog",
    "finish": "scenes.finish.catalog",
    "fonts": "scenes.fonts.catalog",
    "atmospheres": "scenes.atmospheres.catalog",
    "motion": "scenes.motion.catalog",
}
_SOURCE_KIND = {source: kind for kind, source in _KIND_SOURCE.items()}


def command_catalog() -> list[dict[str, Any]]:
    operations = []
    for name, data in CATALOGS.items():
        operations.append({
            "name": name,
            "description": (
                f"{BLURBS[name]} {len(_entries(data, name))} entries. "
                "Default result is id, name, one-line description, and counts. "
                "Pass detail true for the full JSON, or id for one full entry. "
                "Read-only; no GPU, save or export."
            ),
            "mutation": False,
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "version": {"type": "integer", "const": 1},
                    "input": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "detail": {"type": "boolean"},
                            "id": {"type": "string", "minLength": 1, "maxLength": QUERY_LIMIT},
                        },
                    },
                },
                "required": ["version", "input"],
            },
        })
    return operations


def execute(command: Any) -> dict[str, Any]:
    if not isinstance(command, dict) or set(command) != {"version", "operation", "input"}:
        raise CatalogError("catalog_bad_envelope", "Expected version, operation and input only")
    if type(command["version"]) is not int or command["version"] != 1:
        raise CatalogError("catalog_bad_envelope", "Expected version 1")
    name = command["operation"]
    if type(name) is not str or name not in CATALOGS:
        raise CatalogError("catalog_unknown_operation", "Unknown catalog operation")
    detail, identity = _catalog_options(command["input"])
    return {
        "version": 1,
        "status": "completed",
        "operation": name,
        "result": _project_catalog(CATALOGS[name], detail=detail, identity=identity, kind=_SOURCE_KIND[name]),
    }


def _handler(name: str) -> Callable[[Any], Any]:
    async def handle(arguments: Any) -> dict[str, Any]:
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool

        payload = arguments if isinstance(arguments, dict) else {}
        try:
            return await run_in_threadpool(execute, {**payload, "operation": name})
        except CatalogError as error:
            raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error

    return handle


def command_handlers() -> dict[str, Callable[[Any], Any]]:
    return {name: _handler(name) for name in CATALOGS}


def _kind_data(kind: str) -> Any:
    if kind == "effects":
        return EFFECTS_CATALOG
    if kind == "graphics":
        return GRAPHICS_CATALOG
    if kind == "lyric_looks":
        return LYRIC_LOOKS_CATALOG
    return CATALOGS[_KIND_SOURCE[kind]]


def lines_for(kind: str | None, identity: Any) -> dict[str, str]:
    """The ES/EN name and line of one entry, or {} when the kind has none."""
    found = (LINES.get(kind) or {}).get(identity) if kind and isinstance(identity, str) else None
    return found if isinstance(found, dict) else {}


def summary_row(kind: str | None, entry: dict) -> dict[str, Any]:
    """The short row: id, name, one-line description and counts, plus the ES/EN copy and ``covers`` when known."""
    row = summarize_entry(entry)
    copy = lines_for(kind, entry.get("id"))
    if copy:
        row.update({key: copy[key] for key in LINE_KEYS if key in copy})
        row["name"] = copy.get("titleEn") or row["name"]
        row["description"] = row["description"] or copy.get("lineEn", "")
    if entry.get("covers") is True:
        row["covers"] = True
    return row


def _texts(entry: dict, keys: tuple[str, ...], copy: dict, extra: tuple[str, ...]) -> str:
    values = [entry.get(key) for key in keys] + [copy.get(key) for key in extra]
    return " ".join(value for value in values if isinstance(value, str))


def _id_words(identity: str) -> list[str]:
    """«camera-pan-right» → camera pan right; «warmCinema» → warm Cinema."""
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", identity).replace("-", " ").replace("_", " ").split()


def _search_fields(kind: str, entry: dict) -> dict[str, Any]:
    copy = lines_for(kind, entry.get("id"))
    tags = _id_words(str(entry.get("id") or "")) + [entry[key] for key in ("family", "kind", "collection") if isinstance(entry.get(key), str)]
    return {"title": _texts(entry, ("title", "name", "label"), copy, ("titleEs", "titleEn")),
            "description": _texts(entry, ("visualIntent", "description"), copy, ("lineEs", "lineEn")), "tags": tags}


def _in_family(kind: str, entry: dict, family: str) -> bool:
    return kind != "templates" or not family or entry.get("family") == family


def _query_words(query: str) -> list[str]:
    """The query's words without filler and without one- or two-letter words («up» in «close-up»)."""
    return list(dict.fromkeys(word for word in query_words(query) if len(word) > 2 or word.isdigit()))


def _pool(kinds: tuple[str, ...]) -> list[tuple[str, dict]]:
    return [(kind, entry) for kind in kinds for entry in _entries(_kind_data(kind), kind)]


def _scored(kinds: tuple[str, ...], family: str, wanted: list[str]) -> tuple[list[tuple[set[str], int, int, str, dict]], set[str]]:
    """``[(words found, points, catalogue order, kind, entry)]`` of the entries in ``family``, and every word any entry
    of these kinds knows (another family included)."""
    known: set[str] = set()
    scored = []
    for order, (kind, entry) in enumerate(_pool(kinds)):
        found, points = match(wanted, **_search_fields(kind, entry), synonyms=expand)
        known.update(found)
        if found and _in_family(kind, entry, family):
            scored.append((set(found), points, order, kind, entry))
    return scored, known


def _ranked(kinds: tuple[str, ...], family: str, query: str) -> tuple[list[tuple[str, dict, int]], list[str], bool]:
    """``[(kind, entry, points)]`` best first, the unknown words, and whether the rows are only partial matches.

    A word no entry of these kinds knows is unknown and dropped. A word that names the thing searched («plano»,
    «cámara», «shot»: the 3D ``QUERY_STOP``) adds points but is not needed, unless the query has nothing else. Rows
    that have every needed word come first; when none does, the rows with at least half of them come back as partial.
    An empty query keeps catalogue order."""
    wanted = _query_words(query)
    if not wanted:
        return [(kind, entry, 0) for kind, entry in _pool(kinds) if _in_family(kind, entry, family)], [], False
    scored, known = _scored(kinds, family, wanted)
    chosen, partial = _chosen(scored, {word for word in known if word not in QUERY_STOP} or known)
    return chosen, [word for word in wanted if word not in known], partial


def _chosen(scored: list[tuple[set[str], int, int, str, dict]], needed: set[str]) -> tuple[list[tuple[str, dict, int]], bool]:
    """The rows with every needed word, best first, else those with at least half of them (partial)."""
    rows = sorted(((len(found & needed), points, order, kind, entry) for found, points, order, kind, entry in scored if found & needed),
                  key=lambda row: (-row[0], -row[1], row[2]))
    full = [row for row in rows if row[0] == len(needed)]
    chosen = full or [row for row in rows if row[0] * 2 >= len(needed)]
    return [(kind, entry, points) for _hits, points, _order, kind, entry in chosen], bool(chosen) and not full


def _require_text(value: Any, field: str, limit: int) -> str:
    if value is None:
        return ""
    if type(value) is not str:
        raise CatalogError("catalog_bad_envelope", field)
    if len(value) > limit:
        raise CatalogError("catalog_bad_envelope", field)
    return value


def _query_fields(data: Any) -> tuple[str, str, str, bool, str]:
    if not isinstance(data, dict):
        raise CatalogError("catalog_bad_envelope", "Expected an object")
    if set(data) - {"kind", "family", "q", "detail", "id"}:
        raise CatalogError("catalog_bad_envelope", "Unexpected catalog field")
    kind = _require_text(data.get("kind"), "kind", QUERY_LIMIT)
    family = _require_text(data.get("family"), "family", QUERY_LIMIT)
    query = _require_text(data.get("q"), "q", QUERY_LIMIT)
    identity = _require_text(data.get("id"), "id", QUERY_LIMIT)
    detail = data.get("detail", False)
    if type(detail) is not bool:
        raise CatalogError("catalog_bad_envelope", "detail")
    if kind and kind not in KINDS:
        raise CatalogError("catalog_unknown_kind", kind)
    if family and kind not in ("", "templates"):
        raise CatalogError("catalog_bad_envelope", "family filters templates")
    return kind, family, query.casefold(), detail, identity


def _summary(family: str, query: str) -> dict[str, Any]:
    rows, unknown, partial = _ranked(KINDS, family, query)
    result: dict[str, Any] = {"kinds": [{"kind": kind, "count": sum(1 for row in rows if row[0] == kind)} for kind in KINDS]}
    if _query_words(query):
        result.update(matches=[{"kind": kind, **summary_row(kind, entry), "score": points} for kind, entry, points in rows[:MATCH_LIMIT]],
                      unknown_words=unknown, partial=partial)
    return result


def _page(kind: str, family: str, query: str, detail: bool) -> dict[str, Any]:
    rows, unknown, partial = _ranked((kind,), family, query)
    total = len(rows)
    page = rows[:PAGE_LIMIT]
    searched = bool(_query_words(query))
    shown = [deepcopy(entry) if detail else {**summary_row(kind, entry), **({"score": points} if searched else {})}
             for _kind, entry, points in page]
    result: dict[str, Any] = {"kind": kind, "entries": shown, "total": total, "truncated": total > PAGE_LIMIT}
    if searched:
        result.update(unknown_words=unknown, partial=partial)
    return result


def _catalog_options(data: Any) -> tuple[bool, str]:
    if data == {}:
        return False, ""
    if not isinstance(data, dict) or set(data) - {"detail", "id"}:
        raise CatalogError("catalog_bad_envelope", "Catalog input accepts detail and id")
    detail = data.get("detail", False)
    if type(detail) is not bool:
        raise CatalogError("catalog_bad_envelope", "detail")
    identity = data.get("id", "")
    if identity is None:
        identity = ""
    if type(identity) is not str or len(identity) > QUERY_LIMIT:
        raise CatalogError("catalog_bad_envelope", "id")
    return detail, identity


def _project_catalog(data: Any, *, detail: bool, identity: str, kind: str | None = None) -> Any:
    entries = _entries(data, "catalog")
    if identity:
        found = next((item for item in entries if item.get("id") == identity), None)
        if found is None:
            raise CatalogError("catalog_unknown_id", identity)
        return {"entry": deepcopy(found)}
    if detail:
        return deepcopy(data)
    return {"entries": [summary_row(kind, item) for item in entries], "counts": {"entries": len(entries)}}


def _find_entries(identity: str, kind: str, family: str) -> list[tuple[str, dict]]:
    """Every entry with this id; nine atmosphere ids are also effects and ``space-cruise`` is a template and a motion."""
    kinds = (kind,) if kind else KINDS
    found = [(item_kind, entry) for item_kind in kinds for entry in _entries(_kind_data(item_kind), item_kind)
             if entry.get("id") == identity and _in_family(item_kind, entry, family)]
    if not found:
        raise CatalogError("catalog_unknown_id", identity)
    return found


def query_catalog(data: Any) -> dict[str, Any]:
    kind, family, query, detail, identity = _query_fields(data)
    if identity:
        found = _find_entries(identity, kind, family)
        result: dict[str, Any] = ({"kind": found[0][0], "entry": deepcopy(found[0][1])} if len(found) == 1
                                  else {"matches": [{"kind": item_kind, "entry": deepcopy(entry)} for item_kind, entry in found]})
    elif kind:
        result = _page(kind, family, query, detail)
    else:
        result = _summary(family, query)
    return {"version": 1, "status": "completed", "operation": OPERATION, "result": result}


def execute_query(command: Any) -> dict[str, Any]:
    if not isinstance(command, dict) or set(command) != {"version", "operation", "input"}:
        raise CatalogError("catalog_bad_envelope", "Expected version, operation and input only")
    if type(command["version"]) is not int or command["version"] != 1:
        raise CatalogError("catalog_bad_envelope", "Expected version 1")
    if command["operation"] != OPERATION:
        raise CatalogError("catalog_unknown_operation", "Unknown catalog operation")
    return query_catalog(command["input"])


def query_operation() -> dict[str, Any]:
    kinds = ", ".join(KINDS)
    return {
        "name": OPERATION,
        "description": (
            f"Query Video 2D catalogs ({kinds}). Omit kind for counts only "
            "({kinds:[{kind, count}]}, no entry dump). With kind, entries are summaries "
            "(id, name, one-line description, counts) unless detail is true. "
            "id returns that one full entry (q is ignored); an id found in several kinds (rain is an atmosphere and an "
            "effect) returns matches, one {kind, entry} each. family filters templates. "
            "q is a few words in Spanish or English, at most 80 characters: case, accents, plurals and filler words are "
            "forgiven and the Video 3D synonyms count («plano general», «persecución», «rótulo», «cámara en mano»). It "
            "scores id words, title, visualIntent, family and the ES/EN name and line, best first, each row with its "
            "score; unknown_words lists the words no entry knows, and partial is true when no row has all the others. "
            f"Without kind, q returns the counts plus the best {MATCH_LIMIT} matches of every kind. "
            "Rows carry titleEs, titleEn, lineEs and lineEn when the entry has them, and covers true for a text template "
            "that paints an opaque plate over the whole frame. lyric_looks are the production.run lyric styles. "
            f"At most {PAGE_LIMIT} entries; truncated and total when over the cap. "
            "Effects entries are scene_effects.json; world kinds stay on scenes.effects.catalog. "
            "Graphics entries are scene_graphics.json: parameterized drawings timed in beats, no custom code. "
            "Read-only; no GPU, save or export."
        ),
        "mutation": False,
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "input": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "family": {"type": "string", "maxLength": QUERY_LIMIT},
                        "q": {"type": "string", "maxLength": QUERY_LIMIT},
                        "detail": {"type": "boolean"},
                        "id": {"type": "string", "maxLength": QUERY_LIMIT},
                    },
                },
            },
            "required": ["version", "input"],
        },
    }


def query_handlers() -> dict[str, Callable[[Any], Any]]:
    async def handle(arguments: Any) -> dict[str, Any]:
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool

        payload = arguments if isinstance(arguments, dict) else {}
        try:
            return await run_in_threadpool(execute_query, {**payload, "operation": OPERATION})
        except CatalogError as error:
            raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error

    return {OPERATION: handle}


__all__ = [
    "CATALOG_FILES",
    "CatalogError",
    "EFFECTS_CATALOG",
    "GRAPHICS_CATALOG",
    "KINDS",
    "LINES",
    "LYRIC_LOOKS_CATALOG",
    "command_catalog",
    "command_handlers",
    "execute",
    "execute_query",
    "lines_for",
    "load_catalog",
    "query_catalog",
    "query_handlers",
    "query_operation",
    "summary_row",
]

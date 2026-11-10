"""The cards a shot could be: the search ladder behind ``world3d.templates.plan``.

The scoring is the one of ``world3d.templates.catalog`` (``search_pool``); this module only decides which searches to
ask for one shot, strictest first, until it has cards enough to vary:

1. the shot's words with the filters its cast and speakers imply (``subjects``, ``use``, ``format``);
2. the place words alone with the same filters, so a place card surfaces from a long line the half-of-the-words rule
   of a single query would drop;
3. a portrait frame with too few portrait cards also takes landscape cards (``adapted``);
4. the asked ``use`` is dropped (a place with no dialogue card still has cards that fit two subjects);
5. cards the filters allow, picked by the seed, when the words found too few to choose from.

The subjects a cast needs are never dropped: a card without the role would fail ``cast_role_not_on_card``.
Personal templates are not searched: the production compiler reads shipped ids only.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Callable

from services.world3d_template_catalog import search_pool
from services.world3d_template_plan_input import Need, Request

POOL_MIN = 8            # cards a shot needs before the ladder stops widening
FREE_CAP = 40           # cards the filters-only rung adds at most
ROWS_CAP = 60           # best rows kept of one search
USE_COST = 60           # what a card loses for answering a shot with the asked use dropped
ACTION_USES = {"action", "speed", "impact", "drive"}
STYLE_TAGS = {"pixel", "psx", "anime", "creative", "dark-fantasy", "perspective"}   # a look, not a place
ADAPT_COST = 25         # what a landscape card loses in a portrait frame

Search = Callable[..., dict]


@dataclass(frozen=True)
class Rung:
    filters: dict
    cost: int
    adapted: bool
    relaxed: str


@dataclass(frozen=True)
class Candidate:
    card: dict
    line: int = 0
    place: int = 0
    place_full: bool = False
    cost: int = 0
    adapted: bool = False
    relaxed: str = ""


def spread(seed: int, *parts) -> float:
    """A number in [0, 1) that depends only on the seed and the parts: the same plan every time, another for another seed."""
    digest = hashlib.sha1("|".join(str(part) for part in (seed, *parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 2 ** 32


def ladder(need: Need, frame: str | None) -> list[Rung]:
    subject = {"subjects": need.subjects} if need.subjects else {}
    use = {"use": need.use} if need.use else {}
    asked = {"format": frame} if frame else {}
    rungs = [Rung({**subject, **use, **asked}, 0, False, "")]
    if frame == "portrait":
        rungs.append(Rung({**subject, **use}, ADAPT_COST, True, ""))
    if need.use:
        rungs.append(Rung({**subject, **asked}, USE_COST, False, "use"))
        if frame == "portrait":
            rungs.append(Rung(subject, USE_COST + ADAPT_COST, True, "use"))
    return rungs


def _candidate(card: dict, rung: Rung, frame: str | None, line: int = 0) -> Candidate:
    adapted = bool(frame) and card.get("format") != frame
    cost = rung.cost - (ADAPT_COST if rung.adapted and not adapted else 0)
    return Candidate(card, line=line, cost=cost, adapted=adapted, relaxed=rung.relaxed)


def _add_line(found: dict, need: Need, rung: Rung, frame: str | None, search: Search) -> None:
    if not need.query:
        return
    for score, _match, card in search(need.query, **rung.filters)["rows"][:ROWS_CAP]:
        found.setdefault(card["id"], _candidate(card, rung, frame, line=score))


def _add_place(found: dict, need: Need, rung: Rung, frame: str | None, search: Search) -> None:
    if not need.place_words:
        return
    for score, match, card in search(" ".join(need.place_words), **rung.filters)["rows"][:ROWS_CAP]:
        candidate = found.get(card["id"]) or _candidate(card, rung, frame)
        if not candidate.place:
            found[card["id"]] = replace(candidate, place=max(score, 1), place_full=match == "full")


def _add_free(found: dict, need: Need, rung: Rung, request: Request, search: Search) -> None:
    rows = search("", **rung.filters)["rows"]
    rows = sorted(rows, key=lambda row: (spread(request.seed, need.key, row[2]["id"]), row[2]["id"]))
    for _score, _match, card in rows:
        if len(found) >= FREE_CAP:
            break
        found.setdefault(card["id"], _candidate(card, rung, request.format))


def _enough(found: dict, need: Need) -> bool:
    return len(found) >= POOL_MIN and (not need.place_words or any(item.place for item in found.values()))


def gather(need: Need, request: Request, search: Search = search_pool) -> list[Candidate]:
    """The candidates of one shot, in the order they were found (strict rungs first)."""
    found: dict[str, Candidate] = {}
    for rung in ladder(need, request.format):
        _add_line(found, need, rung, request.format, search)
        _add_place(found, need, rung, request.format, search)
        if len(found) < POOL_MIN:
            _add_free(found, need, rung, request, search)
        if _enough(found, need):
            break
    return list(found.values())


@dataclass(frozen=True)
class Anchors:
    """The cards that are a place itself: its stage (people talk there) and its best plain scene (a ``world`` names it)."""
    stage: dict | None = None
    plain: dict | None = None


def find_anchors(words: tuple[str, ...], search: Search = search_pool) -> Anchors:
    """The stage of a mold and the best scene that answer the place words. A stage card cannot be a ``world`` (the
    compiler reads a world as a template's place, never a stage), so the plain card is the one a ``world`` names."""
    if not words:
        return Anchors()
    cards = [card for _score, _match, card in search(" ".join(words))["rows"][:ROWS_CAP]]
    stages = [card for card in cards if card.get("kind") == "stage"]
    plain = [card for card in cards if card.get("kind") != "stage"]
    return Anchors(stages[0] if stages else None, min(plain, key=_world_rank) if plain else None)


def _world_rank(card: dict) -> tuple:
    """A scene that is the place, in no particular look and not an action in it, moving, first: the best card to play
    other cards in."""
    uses = set(card.get("uses") or ())
    return (card.get("kind") != "scene", bool(set(card.get("tags") or ()) & STYLE_TAGS), bool(card.get("still")),
            bool(uses & ACTION_USES), "establishing" not in uses)

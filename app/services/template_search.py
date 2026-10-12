"""Forgiving search over a template's title, description and tags.

``templates.list`` used to look for the whole query as one literal substring, so «escenas estilo PS1» found nothing in a
template called «Escena estilo PS1», and so did every phrase that was not copied from the text. The people and the language
models that ask do not know the exact words, and should not have to: a query is now a handful of words, each matched
regardless of case, accents and plural, in any order, and the results come back ranked (title words count most, then
tags, then the description). Function words are ignored, so a whole sentence can be passed as the query.

This is deliberately not semantic: it only forgives spelling. Choosing between templates by meaning is the job of the
caller, who reads the ranked titles and descriptions (or lists everything by leaving the query out). ``match`` can also
take a synonym table (the Video 2D catalogs pass the shared 3D vocabulary): a word found only through a synonym scores half
what the literal word would in the same field, so the literal word always ranks first.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable

_STOP = frozenset((
    "a al ante con de del e el en la las lo los o para por que se sin su sus u un una unas unos y "
    "an and as at by for from in into of on or the to with"
).split())
_WEIGHT = {"title": 3, "tags": 2, "description": 1}
_MIN_PREFIX = 4        # «scene» and «scenes» match; «pre» does not match «prerendered»


def fold(text: str) -> str:
    """Lower-case without accents: «Gráficos» and «graficos» are the same word."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


def stem(word: str) -> str:
    """Drop a plural ending: escenas → escena, graficos → grafico, scenes → scen (matched by prefix below).

    A five-letter «-es» word loses only the «s» (naves → nave, lines → line): two letters off would leave a root too
    short for the prefix match, and the plural would never meet its singular."""
    if len(word) > 5 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    return min(len(a), len(b)) >= _MIN_PREFIX and (a.startswith(b) or b.startswith(a))


def query_words(query: str) -> list[str]:
    """The folded words of a query without filler words."""
    return [word for word in words(query) if word not in _STOP]


def query_stems(query: str) -> list[str]:
    return [stem(word) for word in query_words(query)]


def score(query: str, *, title: str, description: str, tags: list[str]) -> int:
    """0 when no word of the query is in the template; otherwise higher is better. An empty query matches everything."""
    wanted = query_stems(query)
    if not wanted:
        return 1
    fields = {"title": title, "tags": " ".join(tags or []), "description": description}
    stems = {name: [stem(word) for word in words(text)] for name, text in fields.items()}
    total = 0
    for word in wanted:
        best = max((_WEIGHT[name] for name, candidates in stems.items() if any(same_word(word, other) for other in candidates)), default=0)
        total += best
    return total


def match(wanted: list[str], *, title: str, description: str, tags: list[str],
          synonyms: Callable[[str], Iterable[str]] | None = None) -> tuple[list[str], int]:
    """``(query words found, points)`` for one entry. ``wanted`` are folded query words (``query_words``).

    A literal word scores twice its best field weight (title 6, tags 4, description 2); a word found only through
    ``synonyms`` scores the weight once, so the literal word always outranks it in the same field."""
    fields = {"title": title, "tags": " ".join(tags or []), "description": description}
    stems = {name: {stem(word) for word in words(text)} for name, text in fields.items()}
    found: list[str] = []
    points = 0
    for word in dict.fromkeys(wanted):
        root = stem(word)
        best = _field_points(stems, {root}, 2)
        if not best and synonyms is not None:
            best = _field_points(stems, {stem(item) for item in (*synonyms(word), *synonyms(root))} - {root}, 1)
        if best:
            found.append(word)
            points += best
    return found, points


def _field_points(stems: dict[str, set[str]], forms: set[str], factor: int) -> int:
    """``factor`` times the weight of the best field that has one of ``forms``."""
    return max((factor * _WEIGHT[name] for name, candidates in stems.items()
                if any(_near(form, candidate) for form in forms for candidate in candidates)), default=0)


def _near(a: str, b: str) -> bool:
    """``same_word`` with the longer word at most four letters longer: «escena» finds «escenas» and «cine» finds
    «cinema», but «esta» does not find «establishing»."""
    return a == b or (same_word(a, b) and abs(len(a) - len(b)) <= 4)

"""Where a shot happens, read from its words, and the cameras a stage card offers there.

A director names the place first («en la cocina», «on the rooftop») and the rest of a long line is colour. The place
words are the words of the shared search vocabulary that belong to a place group (``PLACE_GROUPS``) and the id of a
stage mold. «cocina» and «kitchen» are one place: ``place_key`` is the same for both, so two shots that say it in
different languages still count as one place.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from services import set_molds
from services.world3d_stage_cards import DEFAULT_CAMERA, PREFIX, measure, speaking_marks
from services.world3d_template_vocabulary import NOT_PLACE_WORDS, PLACE_GROUPS, QUERY_STOP

# A stage card is shot from these fixed cameras; ``entrance`` is a walk-in, so it is only taken when a line asks for it.
STAGE_CAMERAS = ("two_shot", "ots_a", "ots_b", "wide", "close_1", "close_2")
SHOT_ORDER = ("close", "medium", "wide", "far")
# A place a stage mold names that the shared vocabulary does not: the mold's own word is its key.
_MOLD_WORDS = {"sala": "sala", "salas": "sala", "vagon": "vagon", "vagones": "vagon", "wagon": "vagon"}


def fold(text) -> str:
    ascii_text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.lower()))


@lru_cache(maxsize=1)
def _place_of_word() -> dict[str, str]:
    """Every place word of the vocabulary and the key of its group (its alphabetically first word)."""
    found = {word: min(group) for group in PLACE_GROUPS for word in group if word not in NOT_PLACE_WORDS}
    return {**found, **_MOLD_WORDS}


def _lookup(word: str) -> str | None:
    places = _place_of_word()
    return places.get(word) or (places.get(word[:-1]) if word.endswith("s") else None)


def _words(text: str) -> list[str]:
    return [word for word in dict.fromkeys(fold(text).split()) if word not in QUERY_STOP]


def _first_place(words: list[str]) -> tuple[str, tuple[str, ...]] | None:
    keys = [(word, _lookup(word)) for word in words]
    first = next((key for _word, key in keys if key), None)
    return (first, tuple(word for word, key in keys if key == first)) if first else None


def read_place(text: str, place: str = "") -> tuple[str, tuple[str, ...]]:
    """``(key, words)`` of the place a shot names: its own ``place`` field when it has one, else the first place the
    line says. ``words`` are the words of that one place in the order they came, without repeats. A ``place`` the
    vocabulary does not know is its own words; no place at all is ``("", ())``."""
    named = _words(place)
    if named:
        return _first_place(named) or ("-".join(named), tuple(named))
    return _first_place(_words(text)) or ("", ())


@lru_cache(maxsize=64)
def stage_camera_shots(template_id: str) -> dict[str, str]:
    """The shot size each fixed camera of a ``stage-<mold>`` card shows: the nearest of its speaking marks, measured
    as the card's own ``shot`` is (the default camera is the card's own, from the first mark). A card that is not a stage
    has none."""
    if not template_id.startswith(PREFIX):
        return {}
    mold = next((item for item in set_molds.catalog() if item["id"] == template_id[len(PREFIX):]), None)
    if mold is None:
        return {}
    marks = speaking_marks(mold)
    sizes = {camera["id"]: min((measure(camera, mark)[0] for mark in marks), key=SHOT_ORDER.index) for camera in mold["cameras"]}
    default = next((camera for camera in mold["cameras"] if camera["id"] == DEFAULT_CAMERA), None)
    if default is not None:
        sizes[DEFAULT_CAMERA] = measure(default, marks[0])[0]       # as the card's own ``shot`` is read
    return sizes

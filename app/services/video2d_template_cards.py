"""The Video 2D scene template cards an agent reads: derived traits, ES/EN copy, aliases, narrative twins and the
music-card suggestion (contract: docs/development/VIDEO2D_TEMPLATE_MODEL.md).

Traits come from ``video2d_template_traits.json``, which ``ui/scripts/export-video2d-traits.mjs`` writes by compiling
every card at its defaults and sampling what moves; they are never written by hand. The copy is the ``templates``
section of ``video2d_lines.json``. A merged id is an alias of the card that absorbed it (decision 1) and two ids are
retired (decision 8): neither is a catalog row, and asking for one by id says which card or tool answers instead.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable

from services.template_search import match
from services.world3d_template_vocabulary import QUERY_STOP, expand

ROOT = Path(__file__).resolve().parents[1] / "shared"
TRAITS_FILE = "video2d_template_traits.json"

USES = ("music", "dance", "performance", "product", "transition", "entrance", "exit", "establishing", "dialogue",
        "documentary", "space")
MOVES = ("push", "pull", "slide", "rise", "descend", "orbit", "roll", "shake", "drift", "bounce", "spin")
MOVING = ("camera", "subject", "subjects", "props", "background", "particles", "text")
TRAVEL = ("none", "cross", "rise", "fall", "orbit", "in", "out")
FORMATS = ("landscape", "portrait")
BACKGROUNDS = ("still", "drift", "strip", "video")
TRAIT_KEYS = ("moves", "moving", "still", "holdShare", "subjects", "props", "travel", "format", "uses", "background",
              "duration")
LINE_KEYS = ("titleEs", "titleEn", "lineEs", "lineEn")
STILL_SHARE = 0.5
MAX_SUBJECTS = 2

# Decision 1, the merge table: alias id → (card, control preset the alias compiles with).
ALIASES: dict[str, tuple[str, dict[str, str]]] = {
    "cinema-isolation": ("cinema-establishing", {"mood": "lonely"}),
    "music-parallax": ("cinema-tracking", {"atmosphere": "streaks"}),
    "music-stage": ("music-pulse", {"camera": "sweep"}),
    "music-finale": ("music-pulse", {"camera": "open", "atmosphere": "confetti"}),
    "music-chorus": ("music-pulse", {"camera": "beat", "atmosphere": "confetti"}),
    "music-satellite-swarm": ("music-orbit", {"bounce": "off"}),
    "music-ricochet-pass": ("music-pinball", {"bouncer": "prop"}),
    "space-shield": ("space-broadside", {"outcome": "shield"}),
    "space-explosion": ("space-broadside", {"outcome": "explode"}),
}
# Decision 8: retired ids and what does their job now.
RETIRED: dict[str, dict[str, Any]] = {
    "trailer-teaser": {
        "use_instead": [{"kind": "text", "id": "title-card"}, {"kind": "text", "id": "trailer-slam"}],
        "message": "trailer-teaser is retired: it was a sequence of titles. Put the text templates title-card or "
                   "trailer-slam in a scene (scenes.text.template or add_title).",
    },
    "lyric-vertical": {
        "use_instead": [{"operation": "scenes.lyrics.import"}, {"kind": "lyric_looks"}],
        "message": "lyric-vertical is retired: lyrics come from scenes.lyrics.import and the lyric looks "
                   "(scenes.catalog kind lyric_looks) over any moving shot.",
    },
}
# Decision 5 and review §H9: the narrative shot (ui/src/lib/sceneNarrative.ts) that covers each cinema card.
TWINS: dict[str, tuple[str, ...]] = {
    "cinema-establishing": ("place-establishing", "high-angle-isolation"),
    "cinema-reveal": ("foreground-reveal",),
    "cinema-closeup": ("emotional-close-up",),
    "cinema-two-shot": ("two-shot-master",),
    "cinema-detail": ("detail-insert", "pov-detail-glance"),
    "cinema-hero": ("hero-arrival", "low-angle-hero"),
    "cinema-tracking": ("run-travel-parallax", "surreal-transit"),
}

# Words a writer uses for 2D motion that the Video 3D vocabulary groups otherwise (it puts «sube» and «baja» with
# reveal, «baile» with every music word, «vacío» with empty plates and «cañón» with canyons). A word listed here
# means only its 2D group; every other word keeps its 3D synonyms.
GROUPS_2D: tuple[frozenset[str], ...] = tuple(frozenset(words.split()) for words in (
    "bounce bounces bouncing bouncy rebote rebotes rebota rebotan rebotar rebotando bote bota botan botar botando "
    "hop hops hopping brinca brincar brinco brincos",
    "dance dances dancing dancer dancers baile bailes bailar baila bailan bailando bailarin bailarina bailarines "
    "coreografia coreografias choreography",
    "fall falls falling cae caen caer cayendo caida caidas drop drops dropping plunge plunges vacio abismo abyss",
    "rise rises rising sube suben subir subiendo subida ascenso asciende ascender ascending climb climbs climbing "
    "trepa trepar",
    "descend descends descending baja bajan bajar bajando bajada desciende descenso",
    "cross crosses crossing cruza cruzan cruzar cruzando atraviesa atravesar traverse pasada",
    "exit exits salida salidas sale salen salir saliendo leave leaves leaving desaparece desaparecen desaparecer "
    "vanish vanishes disappear disappears",
    "clone clones clon copia copias copy copies duplicate duplicates",
    "swing swings sway sways pendulo pendulum balanceo balancea vaiven oscila oscilan oscilar",
    "drift drifts drifting deriva flota flotan flotar float floats floating",
    "cannon canon canones launch launches launched lanza lanzan lanzar lanzado lanzada lanzamiento catapult "
    "catapulta disparada disparado",
    "documentary documental documentales archive archivo historico historica history historical",
    "postcard postcards postal postales",
))
_GROUP_2D = {word: group for group in GROUPS_2D for word in group}
# Comparison words a writer puts in a line («rebota como una bola», «swinging like a pendulum»): never a search word.
FILLER_WORDS = frozenset({"como", "like", "cual"})


class TemplateCardError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def expand2d(token: str) -> frozenset[str]:
    """The 2D group of ``token`` when it has one, else its Video 3D synonyms."""
    return _GROUP_2D.get(token) or expand(token)


def duplicated_2d_words() -> set[str]:
    """Words listed in more than one 2D group (meant to be empty)."""
    seen: set[str] = set()
    twice: set[str] = set()
    for group in GROUPS_2D:
        twice |= seen & group
        seen |= group
    return twice


def _load_traits() -> dict[str, dict]:
    """The derived traits by card id; {} until the exporter has written the file."""
    path = ROOT / TRAITS_FILE
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    templates = data.get("templates") if isinstance(data, dict) else None
    return templates if isinstance(templates, dict) else {}


TRAITS = _load_traits()


def listed(identity: Any) -> bool:
    """Aliases and retired ids are not rows of the catalog: it lists the surviving cards only."""
    return identity not in ALIASES and identity not in RETIRED


def traits_of(identity: Any) -> dict:
    found = TRAITS.get(identity) if isinstance(identity, str) else None
    return found if isinstance(found, dict) else {}


def aliases_of(identity: Any) -> list[dict]:
    return [{"id": alias, "preset": dict(preset)} for alias, (card, preset) in ALIASES.items() if card == identity]


def card_fields(entry: dict, copy: dict) -> dict:
    """What a template row adds to the plain summary: copy, family, status, traits, aliases, twins and warnings."""
    identity = entry.get("id")
    fields: dict[str, Any] = {key: copy[key] for key in LINE_KEYS if key in copy}
    fields.update(family=entry.get("family"), reviewStatus=entry.get("reviewStatus"))
    traits = traits_of(identity)
    fields.update({key: traits[key] for key in TRAIT_KEYS if key in traits})
    aliases = aliases_of(identity)
    if aliases:
        fields["aliases"] = aliases
    if identity in TWINS:
        fields["twins"] = list(TWINS[identity])
    if float(traits.get("holdShare") or 0) > STILL_SHARE:
        fields["warnings"] = ["template_still"]
    return fields


def trait_words(identity: Any) -> list[str]:
    """The search words of a card's traits and of the ids merged into it («stage», «explosion»)."""
    traits = traits_of(identity)
    words = [*traits.get("moves", []), *traits.get("uses", [])]
    if traits.get("travel") not in (None, "none"):
        words.append(str(traits["travel"]))
    if traits.get("still"):
        words.append("still")
    for alias, (card, _preset) in ALIASES.items():
        if card == identity:
            words.extend(alias.split("-")[1:])
    return words


def _choice(value: Any, allowed: tuple[str, ...], name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or value not in allowed:
        raise TemplateCardError("catalog_bad_envelope", f"{name} must be one of {', '.join(allowed)}")
    return value


def _count(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_SUBJECTS:
        raise TemplateCardError("catalog_bad_envelope", f"subjects must be an integer from 0 to {MAX_SUBJECTS}")
    return value


def trait_filters(data: dict) -> dict:
    """The validated trait filters of a query: use, move, format (exact names) and subjects (at least)."""
    filters: dict[str, Any] = {}
    for name, allowed in (("use", USES), ("move", MOVES), ("format", FORMATS)):
        chosen = _choice(data.get(name), allowed, name)
        if chosen:
            filters[name] = chosen
    subjects = _count(data.get("subjects"))
    if subjects is not None:
        filters["subjects"] = subjects
    return filters


def fits(identity: Any, filters: dict) -> bool:
    """A card has every asked trait; a card without traits fits only an empty filter."""
    if not filters:
        return True
    traits = traits_of(identity)
    checks = (
        ("use", lambda wanted: wanted in traits.get("uses", ())),
        ("move", lambda wanted: wanted in traits.get("moves", ())),
        ("format", lambda wanted: traits.get("format") == wanted),
        ("subjects", lambda wanted: int(traits.get("subjects") or 0) >= wanted),
    )
    return all(check(filters[name]) for name, check in checks if name in filters)


def alias_note(identity: str) -> dict | None:
    if identity not in ALIASES:
        return None
    card, preset = ALIASES[identity]
    return {"id": identity, "card": card, "preset": dict(preset),
            "message": f"{identity} is now {card} compiled with {json.dumps(preset)}; compile either id."}


def retired_note(identity: str) -> dict | None:
    found = RETIRED.get(identity)
    if found is None:
        return None
    return {"kind": "templates", "id": identity, "retired": True,
            "use_instead": [dict(item) for item in found["use_instead"]], "message": found["message"]}


# --- scenes.templates.suggest -------------------------------------------------------------------------------------

SUGGEST_LIMIT = 3
SUGGEST_MAX_LIMIT = 8
LINE_LIMIT = 400
MOOD_LIMIT = 120
MAX_SPEAKERS = 4
_COUNTS = {1: "one subject", 2: "two subjects"}


def music_cards(entries: Iterable[dict]) -> list[dict]:
    """The cards production and the Wizard can play: the music family, listed (no alias, no retired id)."""
    return [entry for entry in entries if entry.get("family") == "music" and listed(entry.get("id"))]


def _text(value: Any, name: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise TemplateCardError("catalog_bad_envelope", f"{name} must be a string of at most {limit} characters")
    return value


def _speakers(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_SPEAKERS:
        raise TemplateCardError("catalog_bad_envelope", f"speakers must be an integer from 0 to {MAX_SPEAKERS}")
    return value


def _limit(value: Any) -> int:
    if value is None:
        return SUGGEST_LIMIT
    if type(value) is not int or not 1 <= value <= SUGGEST_MAX_LIMIT:
        raise TemplateCardError("catalog_bad_envelope", f"limit must be an integer from 1 to {SUGGEST_MAX_LIMIT}")
    return value


SUGGEST_FIELDS = {"line", "speakers", "mood", "beat", "format", "limit"}


def suggest_request(data: Any) -> dict:
    """The validated suggest input: line and mood words, speakers, beat (a use), format and limit."""
    if not isinstance(data, dict):
        raise TemplateCardError("catalog_bad_envelope", "Expected an object")
    if set(data) - SUGGEST_FIELDS:
        raise TemplateCardError("catalog_bad_envelope", "suggest accepts line, speakers, mood, beat, format and limit")
    return {
        "line": _text(data.get("line"), "line", LINE_LIMIT), "mood": _text(data.get("mood"), "mood", MOOD_LIMIT),
        "speakers": _speakers(data.get("speakers")), "beat": _choice(data.get("beat"), USES, "beat"),
        "format": _choice(data.get("format"), FORMATS, "format"), "limit": _limit(data.get("limit")),
    }


def _subject_fit(speakers: int | None) -> Callable[[dict], bool]:
    """One person on screen needs a one-subject card; two or more need a card with two subjects."""
    if not speakers:
        return lambda traits: True
    if speakers == 1:
        return lambda traits: int(traits.get("subjects") or 0) == 1
    return lambda traits: int(traits.get("subjects") or 0) >= MAX_SUBJECTS


def suggest_pool(entries: list[dict], request: dict) -> tuple[list[dict], dict, list[str]]:
    """The music cards that fit the speakers, the beat and the format; the filters applied; plain notes.

    Every card is authored for landscape. A portrait request keeps them (they compile at 9:16 with their paths in
    percent of the frame) and says so, rather than suggesting nothing."""
    filters: dict[str, Any] = {}
    notes: list[str] = []
    speakers = request["speakers"]
    if speakers:
        filters["subjects"] = min(speakers, MAX_SUBJECTS)
    if request["beat"]:
        filters["use"] = request["beat"]
    subject_fit = _subject_fit(speakers)
    beat = {"use": request["beat"]} if request["beat"] else {}
    pool = [entry for entry in music_cards(entries) if subject_fit(traits_of(entry.get("id"))) and fits(entry.get("id"), beat)]
    wanted = request["format"]
    if wanted and any(traits_of(entry.get("id")).get("format") == wanted for entry in pool):
        filters["format"] = wanted
        pool = [entry for entry in pool if traits_of(entry.get("id")).get("format") == wanted]
    elif wanted:
        notes.append(f"no music card is authored for {wanted}: these are landscape cards; they compile at {wanted} "
                     "with their paths in percent of the frame")
    return pool, filters, notes


def _motion(row: dict) -> str:
    """The named moves, else what the card animates without one (a figure that crosses), else that it holds."""
    if row.get("moves"):
        return "moves: " + ", ".join(row["moves"])
    animated = [part for part in row.get("moving") or [] if part not in ("particles", "text")]
    return "animates: " + ", ".join(animated) if animated else "nothing but particles moves"


def reason(row: dict) -> str:
    """«one subject, moves: push, bounce, travel: none, uses: music, dance»: the traits that answered, in plain words."""
    subjects = int(row.get("subjects") or 0)
    parts = [_COUNTS.get(subjects, f"{subjects} subjects")]
    parts.append(_motion(row))
    if row.get("travel") not in (None, "none"):
        parts.append(f"travel: {row['travel']}")
    if row.get("uses"):
        parts.append("uses: " + ", ".join(row["uses"]))
    tail = []
    if row.get("background") in ("strip", "video"):
        tail.append(f"background: {row['background']}")
    if row.get("still"):
        tail.append(f"holds still {round(float(row.get('holdShare') or 0) * 100)}% of the shot")
    if row.get("match") == "partial":
        tail.append("partial match")
    text = ", ".join(parts)
    return f"{text}; {'; '.join(tail)}" if tail else text


def rank(pool: list[dict], wanted: list[str], fields: Callable[[dict], dict]) -> tuple[list[tuple[dict, int, str]], list[str]]:
    """``[(entry, points, match)]`` best first and the unknown words, scored like ``scenes.catalog`` but over the pool.

    A word no card of the pool knows is unknown and does not count. Cards with every other word come first (match
    full); when none has them all, those with at least half come back as partial. A card that moves outranks a still
    one at the same points. No words keep the pool in catalog order, moving cards first."""
    if not wanted:
        ordered = sorted(enumerate(pool), key=lambda item: (bool(traits_of(item[1].get("id")).get("still")), item[0]))
        return [(entry, 0, "full") for _index, entry in ordered], []
    scored, known = [], set()
    for order, entry in enumerate(pool):
        found, points = match(wanted, **fields(entry), synonyms=expand2d)
        known.update(found)
        if found:
            scored.append((set(found), points, order, entry))
    needed = {word for word in known if word not in QUERY_STOP} or known
    rows = sorted(((len(found & needed), points, order, entry) for found, points, order, entry in scored if found & needed),
                  key=lambda row: (-row[0], -row[1], bool(traits_of(row[3].get("id")).get("still")), row[2]))
    full = [row for row in rows if row[0] == len(needed)]
    chosen = full or [row for row in rows if row[0] * 2 >= len(needed)]
    label = "full" if full else "partial"
    return [(entry, points, label) for _hits, points, _order, entry in chosen], [word for word in wanted if word not in known]


__all__ = [
    "ALIASES", "BACKGROUNDS", "FILLER_WORDS", "FORMATS", "GROUPS_2D", "MOVES", "MOVING", "RETIRED", "SUGGEST_LIMIT",
    "SUGGEST_MAX_LIMIT", "TRAITS", "TRAITS_FILE", "TRAIT_KEYS", "TRAVEL", "TWINS", "TemplateCardError", "USES",
    "alias_note", "aliases_of", "card_fields", "duplicated_2d_words", "expand2d", "fits", "listed", "music_cards",
    "LINE_LIMIT", "MAX_SPEAKERS", "MAX_SUBJECTS", "MOOD_LIMIT", "rank", "reason", "retired_note", "suggest_pool", "suggest_request", "trait_filters", "trait_words", "traits_of",
]

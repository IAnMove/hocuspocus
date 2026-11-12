"""One way to shoot a shot: a card and the camera or world that goes with it.

A plain card is one option. A ``stage-<mold>`` card is one option per fixed camera (``roomCamera``): the same room from
``ots_a``, ``close_1``... is how the spec says «same place, different camera». A card that is not at the shot's place
gets a second option that plays it ``world``-ed in the place of the best scene of that place (the compiler keeps the
card's camera, cast and moves and moves them to that place). Shots that say one place more than once keep one family:
the stage of that place, or that scene and the cards played in its world.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.world3d_template_compact import short_why
from services.world3d_template_places import STAGE_CAMERAS, stage_camera_shots
from services.world3d_template_plan_input import Need
from services.world3d_template_plan_pool import ADAPT_COST, Anchors, Candidate

PLACE_BONUS = 60        # a card that answers the place words
PLACE_CAP = 30          # of the place query's own score
WORLD_BONUS = 45        # a card played in the world of the place (below the place card itself)
SHOT_BONUS = 20         # the asked shot size
MOVE_BONUS = 8          # moves (or does not) as asked
CAMERA_BONUS = 3        # a stage camera that suits who talks
NEAR_ADAPT = 10         # close and medium shots reframe to a portrait frame better than wide ones
NON_SHOT_KINDS = ("title", "transition")
NON_SHOT_PENALTY = 40   # a title or a transition that no word of the line asked for
GENERIC_PLACE = "citadel"   # the dressing of the generic cards (dialogue, reaction, camera techniques): they have no place of their own
OWN_PLACE_PENALTY = 15  # a card with a place of its own played in another place's world
PORTRAIT_NOTE = ("landscape card in a portrait frame: width 1080 and height 1920 are set and the export reframes its "
                 "camera; a card drawn portrait frames better")
TALK_CAMERAS = {"talk": ("close_1", "close_2"), "dialogue": ("two_shot", "ots_a", "ots_b")}


@dataclass(frozen=True)
class Group:
    """The shots that name one place: how many, and the cards that are that place."""
    size: int
    anchors: Anchors
    talks: bool

    @property
    def family(self) -> dict | None:
        """The card the group's shots all play in; only when the place comes up more than once."""
        if self.size < 2:
            return None
        return (self.anchors.stage if self.talks and self.anchors.stage else self.anchors.plain) or self.anchors.stage


@dataclass(frozen=True)
class Option:
    card: dict
    score: int
    shot: str | None
    moves: tuple[str, ...]
    family: str
    room_camera: str | None = None
    world: str | None = None
    place_hit: bool = False
    adapted: bool = False
    relaxed: str = ""

    @property
    def key(self) -> tuple[str, str | None]:
        """Template and camera: what the production gate calls one shot's look."""
        return self.card["id"], self.room_camera


def family_of(card: dict) -> str:
    return str(card.get("place") or card["id"])


def _base(cand: Candidate) -> int:
    score = cand.line - cand.cost
    if cand.place:
        score += (PLACE_BONUS if cand.place_full else PLACE_BONUS // 2) + min(cand.place, PLACE_CAP)
    if cand.card.get("kind") in NON_SHOT_KINDS and not cand.line:
        score -= NON_SHOT_PENALTY
    return score


def _traits(need: Need, shot: str | None, moves: tuple[str, ...], moving: bool, adapted: bool) -> int:
    bonus = SHOT_BONUS if need.shot and shot == need.shot else 0
    if need.moving is not None and need.moving == bool(moves or moving):
        bonus += MOVE_BONUS
    if adapted:
        bonus += NEAR_ADAPT if shot in ("close", "medium") else -NEAR_ADAPT if shot in ("far", "plate", "wide") else 0
    return bonus


def _stage_options(cand: Candidate, need: Need) -> list[Option]:
    card = cand.card
    sizes = stage_camera_shots(card["id"])
    cameras = [camera for camera in STAGE_CAMERAS if camera in (card.get("cameras") or ())]
    found = []
    for camera in cameras:
        shot = sizes.get(camera)
        fits = CAMERA_BONUS if camera in TALK_CAMERAS.get(need.use or "", ()) else 0
        score = _base(cand) + fits + _traits(need, shot, (), False, cand.adapted)
        found.append(Option(card, score, shot, (), family_of(card), room_camera=camera, place_hit=bool(cand.place),
                            adapted=cand.adapted, relaxed=cand.relaxed))
    return found


def _native_options(cand: Candidate, need: Need, plain: dict | None) -> list[Option]:
    card = cand.card
    moves = tuple(card.get("moves") or ())
    moving = bool([part for part in card.get("moving") or [] if part != "camera"])
    traits = _traits(need, card.get("shot"), moves, moving, cand.adapted)
    if plain is not None and need.place_words and not cand.place and card["id"] != plain["id"]:
        # Not at that place: the same card, played in the place's own world.
        own = card.get("place") not in (None, GENERIC_PLACE)
        score = cand.line - cand.cost + WORLD_BONUS + traits - (OWN_PLACE_PENALTY if own else 0)
        return [Option(card, score, card.get("shot"), moves, family_of(plain), world=plain["id"], place_hit=True,
                       adapted=cand.adapted, relaxed=cand.relaxed)]
    return [Option(card, _base(cand) + traits, card.get("shot"), moves, family_of(card), place_hit=bool(cand.place),
                   adapted=cand.adapted, relaxed=cand.relaxed)]


def _expand(cand: Candidate, need: Need, anchors: Anchors) -> list[Option]:
    if cand.card.get("kind") == "stage":
        return _stage_options(cand, need)
    return _native_options(cand, need, anchors.plain)


def _family_candidate(card: dict, frame: str | None) -> Candidate:
    adapted = bool(frame) and card.get("format") != frame
    return Candidate(card, place=PLACE_CAP, place_full=True, cost=ADAPT_COST if adapted else 0, adapted=adapted)


def _best_by_key(options: list[Option]) -> list[Option]:
    best: dict[tuple, Option] = {}
    for option in options:
        if option.key not in best or option.score > best[option.key].score:
            best[option.key] = option
    return list(best.values())


def build_options(need: Need, candidates: list[Candidate], group: Group, frame: str | None) -> list[Option]:
    """Every way to shoot the shot, best of each template and camera. In a group that names its place more than once only
    the options of the group's family stay."""
    options = [option for cand in candidates for option in _expand(cand, need, group.anchors)]
    family = group.family
    if family is None:
        return _best_by_key(options)
    if family.get("kind") == "stage":
        # A stage fits every shot of its place; a plain scene of that place only when it fits the cast, so it must be found.
        options.extend(_expand(_family_candidate(family, frame), need, group.anchors))
    inside = [option for option in options if option.family == family_of(family)]
    return _best_by_key(inside or options)


def fragment(option: Option, frame: str | None) -> dict:
    """The ``scene3d`` keys a production shot takes (a Series ``kind: "3d"`` shot reads ``template`` and ``roomCamera``;
    its frame and its set come from the series)."""
    scene3d: dict = {"template": option.card["id"]}
    if option.room_camera:
        scene3d["roomCamera"] = option.room_camera
    if option.world:
        scene3d["world"] = option.world
    if frame == "portrait":
        scene3d.update({"width": 1080, "height": 1920})
    return scene3d


def why(option: Option, need: Need) -> str:
    """One line: the place it answers, what it shows and what was given up."""
    card = option.card
    if option.room_camera:
        count = int(card.get("subjects") or 0)
        text = f"stage {card.get('place')}, {option.room_camera} camera: {option.shot}, {count} subjects"
    else:
        # Played in another world, the card's own place is not where the shot happens.
        text = short_why({**card, "place": None} if option.world else card, shot=option.shot, moves=list(option.moves))
    notes = []
    if option.world:
        notes.append(f"played in the {option.world} world")
    if option.relaxed:
        notes.append(f"no {need.use} card at that place")
    if option.adapted:
        notes.append("landscape card, reframed")
    return text + (f" ({'; '.join(notes)})" if notes else "")

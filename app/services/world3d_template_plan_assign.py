"""Choosing across a list of shots: the variety rules of ``world3d.templates.plan``, applied one shot at a time.

Each shot has its options (``world3d_template_plan_options``), already scored for what it needs. Going down the list:

- the same template and camera never come twice in a row, and the same template only comes straight after itself in a
  place that is named again, from another room camera;
- a template is used at most twice, four times in a place that is named again (the dry run warns ``template_reused``
  beyond four); a template or a template and camera seen in the last four shots costs points, and so does the same
  shot size or the same camera move as the shot before;
- ``avoid`` ids are never taken; a ``still`` card is taken only when nothing else is left;
- near-ties go to the seed (``spread``), never to the order of the catalogue.

When no option passes the hard rules the best one is taken anyway and the shot says so (``repeat``).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from services.world3d_template_plan_input import Need, Request
from services.world3d_template_plan_options import Option
from services.world3d_template_plan_pool import spread

WINDOW = 4              # shots looked back at
MAX_USES = 2            # uses of one template in a plan
FAMILY_USES = 4         # …when its place is named again (production_quality_gate's template_reused limit)
IN_WINDOW = 30          # per earlier shot of the window with the same template and camera
REUSED = 15             # the template was already used
SAME_SHOT = 12          # the same shot size as the shot before
SAME_MOVE = 8           # the same camera move as the shot before
JITTER = 8              # the seed's share of a score: it decides near-ties only
CAMERA_HAIR = 1         # …and between the cameras of one stage


@dataclass
class State:
    chosen: list[Option] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    uses: Counter = field(default_factory=Counter)

    @property
    def last(self) -> Option | None:
        return self.chosen[-1] if self.chosen else None

    def add(self, option: Option, need: Need) -> None:
        self.chosen.append(option)
        self.places.append(need.place_key)
        self.uses[option.card["id"]] += 1


def _same_place_again(need: Need, state: State) -> bool:
    return bool(need.place_key) and bool(state.places) and state.places[-1] == need.place_key


def blocked(option: Option, need: Need, state: State, group_size: int) -> bool:
    """The hard rules: a repeat in a row, or a template used past its share."""
    last = state.last
    if last is not None and option.key == last.key:
        return True
    if last is not None and option.card["id"] == last.card["id"]:
        if not (option.room_camera and last.room_camera and _same_place_again(need, state)):
            return True
    return state.uses[option.card["id"]] >= (FAMILY_USES if group_size >= 2 else MAX_USES)


def penalty(option: Option, state: State) -> int:
    """What the shots before take off an option: its template recently seen, already used, or a look like the last one's."""
    recent = state.chosen[-WINDOW:]
    cost = IN_WINDOW * sum(1 for earlier in recent if earlier.key == option.key)
    cost += REUSED if state.uses[option.card["id"]] else 0
    last = state.last
    if last is not None:
        cost += SAME_SHOT if option.shot and option.shot == last.shot else 0
        cost += SAME_MOVE if option.moves and option.moves == last.moves else 0
    return cost


def rank(option: Option, need: Need, state: State, request: Request) -> tuple:
    """Sort key, best last: a card that is not still, then the score with the penalties and the seed's share."""
    # The seed's share is the card's, so a stage with six cameras does not outdraw a card with one; its cameras differ by a hair.
    jitter = JITTER * spread(request.seed, need.key, option.card["id"]) + CAMERA_HAIR * spread(request.seed, need.key, option.key)
    return (not option.card.get("still"), option.score - penalty(option, state) + jitter, option.card["id"], option.room_camera or "")


def _alternates(ranked: list[Option], primary: Option, count: int) -> list[Option]:
    """The next best, one per template first; a stage's other cameras only fill what is left."""
    others = [option for option in ranked if option.key != primary.key]
    picked: list[Option] = []
    seen = {primary.card["id"]}
    for option in others:
        if option.card["id"] not in seen:
            picked.append(option)
            seen.add(option.card["id"])
    picked = picked[:count]
    spare = [option for option in others if option not in picked]
    return picked + spare[:count - len(picked)]


def choose(options: list[Option], need: Need, state: State, request: Request, group_size: int) -> tuple[Option | None, list[Option], list[str]]:
    """``(primary, alternates, warnings)`` for one shot."""
    pool = [option for option in options if option.card["id"] not in request.avoid]
    allowed = [option for option in pool if not blocked(option, need, state, group_size)]
    warnings: list[str] = []
    if not allowed and pool:
        allowed = pool
        warnings.append("repeat: no other card fits this shot, so a template of the plan comes again")
    if not allowed:
        return None, [], ["no_card: no card fits this shot with the other choices"]
    ranked = sorted(allowed, key=lambda option: rank(option, need, state, request), reverse=True)
    primary = ranked[0]
    if primary.card.get("still"):
        warnings.append("still_card: nothing else fits; give it a clip, a motion, a camera or a world")
    return primary, _alternates(ranked, primary, request.per_shot - 1), warnings

"""``world3d.templates.plan``: the Video 3D cards for a whole list of shots in one call, with variety.

``world3d.templates.suggest`` answers one shot. Asked once per shot it gives the same card to every shot that sounds
alike, and nothing knows the shots around it. The plan ranks each shot with the same search (``search_pool``, see
``world3d_template_plan_pool`` for the ladder), then chooses down the list (``world3d_template_plan_assign``): no template
twice in a row, none more than twice, the shot size and the camera move alternating, ``avoid`` honoured, a still card
last, the seed deciding near-ties. Shots that name one place keep one family: the stage of that place with another
``roomCamera`` each time, or one scene and the cards played in its ``world``.

Each entry is the compact card of the primary and its alternates plus the ``scene3d`` keys to copy into a production
shot; a Series ``kind: "3d"`` shot reads ``template`` and ``roomCamera`` of it.
"""
from __future__ import annotations

from collections import Counter

from services.world3d_template_catalog import search_pool
from services.world3d_template_compact import compact_card
from services.world3d_template_plan_assign import State, choose
from services.world3d_template_plan_input import Need, Request, read_request
from services.world3d_template_plan_options import PORTRAIT_NOTE, Group, Option, build_options, fragment, why
from services.world3d_template_plan_pool import Anchors, Search, find_anchors, gather

OPERATION = "world3d.templates.plan"
TALKING = ("talk", "dialogue")


def _groups(needs: tuple[Need, ...], search: Search) -> dict[str, Group]:
    sizes = Counter(need.place_key for need in needs if need.place_key)
    groups: dict[str, Group] = {}
    for need in needs:
        if need.place_key and need.place_key not in groups:
            talks = any(other.place_key == need.place_key and other.use in TALKING for other in needs)
            groups[need.place_key] = Group(sizes[need.place_key], find_anchors(need.place_words, search), talks)
    return groups


def _entry(option: Option, need: Need, request: Request) -> dict:
    entry = compact_card(option.card, language=request.language, shot=option.shot, moves=list(option.moves),
                         why=why(option, need))
    entry["scene3d"] = fragment(option, request.format)
    if option.adapted:
        entry.update({"adapted": True, "note": PORTRAIT_NOTE})
    return entry


def _summary(primaries: list[Option]) -> dict:
    used = Counter(option.card["id"] for option in primaries)
    return {"templates_used": len(used), "repeats": sum(used.values()) - len(used),
            "formats": dict(Counter(str(option.card.get("format")) for option in primaries))}


def plan_templates(data: dict, search: Search = search_pool) -> dict:
    """``{plan: [{key, primary, alternates, warnings}], summary: {templates_used, repeats, formats}}`` for the shots of ``data``."""
    request = read_request(data)
    groups = _groups(request.needs, search)
    state, plan, primaries = State(), [], []
    for need in request.needs:
        group = groups.get(need.place_key) or Group(1, Anchors(), False)
        options = build_options(need, gather(need, request, search), group, request.format)
        primary, alternates, warnings = choose(options, need, state, request, group.size)
        if primary is not None:
            state.add(primary, need)
            primaries.append(primary)
            if need.place_words and not primary.place_hit:
                warnings.append(f"place: no card is at «{' '.join(need.place_words)}»")
        plan.append({"key": need.key, "primary": _entry(primary, need, request) if primary else None,
                     "alternates": [_entry(option, need, request) for option in alternates], "warnings": warnings})
    return {"plan": plan, "summary": _summary(primaries)}

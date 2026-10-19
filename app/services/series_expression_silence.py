"""A sheet of a character never plays while that same character speaks.

A kit animation (``angry``, ``wave``, a ``determined-full`` made with ``characters.animation.make``...) takes the figure's place for
its window, and the pose with its mouth is hidden meanwhile, whatever the animation's group (``gateSheets`` in
``ui/scripts/seriesSheet.ts`` hides the pose and every mouth, eye and blink layer bound to it for every window). The sheet has no
lip-sync, so a character who talks during it talks with a still mouth. The rule, once the voices are recorded and the lines are placed in
time (``series_shot_plan.build_shot_spec``):

* it covers every approved animation but the group ``cycle`` and the id ``walk`` (continuous body motion, with their own treatment):
  an ``expression``, a ``gesture``, a ``custom`` sheet and one with no group at all (``determined-full``);
* the window ``[at, at + length]`` of such a sheet must not overlap a line that character speaks (the speaker is the
  cast member the compiler moves the mouth of: ``lineOwnsAppearance`` in ``ui/scripts/seriesShot.ts``). A character who
  *listens* while another speaks keeps its sheet. The length is the compiler's: an explicit ``duration``, else one pass, and an
  expression at least ``expressionHold`` (``windowLength`` in ``seriesSheet.ts``);
* a sheet that overlaps is moved: (a) to end 0.2 s before the character's first phrase, when that fits inside the shot (and after
  the walk-in the compiler plays first); else (b) to the first silence of that character that holds it plus 0.2 s on each side; else
  (c) dropped, and the figure stays on its pose;
* ``allowDuringSpeech: true`` on the animation keeps it where it was asked; a shot without lines is not touched.

Nothing is written to the shot: the move is made on the spec the render hands the compiler, so the script and its
fingerprint stay as they were, and a shot with no overlap compiles exactly as before. Each move or drop is a grouped
warning (``code``, ``subject``, ``shots``, ``message``, as ``expression_too_short``) kept on the render job's item.

A Video 2D card (``character-reaction``) plays its sheet from the first second and has nothing to move: ``card_warnings``
only says that the character speaks over it (``series.shot.card.apply`` returns it in ``warnings``), with the same criterion.
"""
from __future__ import annotations

from typing import Any

from services import series_cast_animation as animations
from services.character_animation_directions import walk_sheet
from services.character_animations import catalog

MOVED = "expression_moved_for_speech"
DROPPED = "expression_dropped_during_speech"
CARD = "expression_during_speech"
CODES = (MOVED, DROPPED)
# Silence kept between the end of an expression and the phrase after it, and before it after the phrase before it.
MARGIN = 0.2
EPSILON = 1e-6
EXPRESSION = "expression"
CYCLE = "cycle"


def _is_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _owns(cast: list[dict[str, Any]], line: dict[str, Any], index: int) -> bool:
    """True when ``line`` moves the mouth of ``cast[index]`` (``lineOwnsAppearance`` of ``ui/scripts/seriesShot.ts``)."""
    kit = cast[index].get("kitId")
    if line.get("kitId") != kit or line.get("visible") is False:
        return False
    if _is_index(line.get("castIndex")):
        return line["castIndex"] == index
    return next(number for number, item in enumerate(cast) if item.get("kitId") == kit) == index


def speech_of(spec: dict[str, Any], index: int) -> list[tuple[float, float]]:
    """The intervals ``(start, end)`` in which ``spec["cast"][index]`` speaks, in time order."""
    cast = spec.get("cast") or []
    return sorted((float(line["start"]), float(line["end"])) for line in spec.get("lines") or [] if _owns(cast, line, index))


def _floor(item: dict[str, Any], kit_animations: dict[str, Any]) -> float:
    """The second before which the compiler cannot start the animation: it waits for the walk sheet of the entrance."""
    enter = item.get("enter") or {}
    if enter.get("gait") == "walk" and walk_sheet(kit_animations) is not None:
        return float(enter["end"])
    return 0.0


def _length(request: dict[str, Any], made: dict[str, Any], group: str | None) -> float:
    """How long the sheet plays, as the compiler plays it (``windowLength``): its explicit duration, else one pass, held at least
    ``expressionHold`` when it is an expression."""
    if "duration" in request:
        return float(request["duration"])
    one_pass = animations.pass_length(made, request.get("loop") or made.get("loop") or "loop")
    return max(one_pass, float(catalog()["sheet"].get("expressionHold", 2.5))) if group == EXPRESSION else one_pass


def guarded(group: str | None, animation_id: Any) -> bool:
    """True for a sheet that hides its character's mouth and must keep clear of its voice: any group (``expression``, ``gesture``,
    ``custom`` or none) but ``cycle``, and any id but ``walk``, which are continuous body motion."""
    return group != CYCLE and animation_id != animations.WALK


def _noun(group: str | None) -> str:
    return "expression" if group == EXPRESSION else "animation"


def _overlaps(start: float, end: float, speech: list[tuple[float, float]]) -> bool:
    return any(start < spoken_end - EPSILON and end > spoken_start + EPSILON for spoken_start, spoken_end in speech)


def _silences(speech: list[tuple[float, float]], floor: float, duration: float) -> list[tuple[float, float]]:
    """The stretches of the shot, from ``floor``, in which this character says nothing."""
    gaps, cursor = [], floor
    for start, end in speech:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    return [*gaps, (cursor, duration)] if duration > cursor else gaps


def new_start(length: float, floor: float, speech: list[tuple[float, float]], duration: float) -> float | None:
    """Where an expression of ``length`` seconds goes: just before the first phrase, else in the first silence that holds it
    with ``MARGIN`` on each side; None when it fits nowhere."""
    before = speech[0][0] - length - MARGIN
    if before >= floor - EPSILON:
        return max(before, floor)
    room = length + 2 * MARGIN
    return next((start + MARGIN for start, end in _silences(speech, floor, duration) if end - start >= room - EPSILON), None)


def _kit_animations(kits: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    kit = kits.get(item.get("kitId")) or {}
    return kit.get("animations") if isinstance(kit.get("animations"), dict) else {}


def _guarded_sheet(item: dict[str, Any], kit_animations: dict[str, Any]) -> tuple[dict[str, Any], str | None] | None:
    """``(kit animation, group)`` of a cast item's animation when it must keep clear of the voice: approved in the kit, not
    opted out, not a cycle or the walk."""
    request = item.get("animation")
    if not isinstance(request, dict) or request.get("allowDuringSpeech"):
        return None
    made = kit_animations.get(request.get("id"))
    if not isinstance(made, dict) or made.get("reviewState") != "approved":
        return None
    group = animations.animation_group(kit_animations, request["id"])
    return (made, group) if guarded(group, request["id"]) else None


def _said(code: str, item: dict[str, Any], shot_id: str, text: str, warnings: list[dict[str, Any]]) -> None:
    from services.series_script_warnings import group_warning
    group_warning(warnings, code, str(item.get("characterId")), shot_id, text)


def _quiet_item(spec: dict[str, Any], index: int, kits: dict[str, Any], shot_id: str, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    """``spec["cast"][index]`` with its sheet moved clear of its voice, or without it; the same object when nothing overlaps."""
    item = spec["cast"][index]
    kit_animations = _kit_animations(kits, item)
    sheet = _guarded_sheet(item, kit_animations)
    speech = speech_of(spec, index) if sheet else []
    if not sheet or not speech:
        return item
    made, group = sheet
    request, duration = item["animation"], float(spec.get("duration") or 0)
    floor, length, noun = _floor(item, kit_animations), _length(request, made, group), _noun(group)
    start = max(float(request.get("at", 0.0)), floor)
    if not _overlaps(start, min(duration, start + length), speech):
        return item
    found = new_start(length, floor, speech, duration)
    if found is None:
        _said(DROPPED, item, shot_id, f"{noun} '{request['id']}' dropped: it would play over {item.get('characterId')}'s own voice and there is "
              f"no silence of {length + 2 * MARGIN:g} s to hold it (allowDuringSpeech: true keeps it)", warnings)
        return {key: value for key, value in item.items() if key != "animation"}
    found = round(found, 3)
    _said(MOVED, item, shot_id, f"{noun} '{request['id']}' moved from {start:g} s to {found:g} s so it does not play over "
          f"{item.get('characterId')}'s own voice", warnings)
    return {**item, "animation": {**request, "at": found, "duration": round(length, 3)}}


def quiet_expressions(spec: dict[str, Any], kits: dict[str, Any], shot_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """``(spec, warnings)`` with every sheet of the shot's cast clear of its own character's voice. ``spec`` is returned as it
    came (the same object) when nothing needed to change. ``kits`` maps kit id to kit."""
    cast = spec.get("cast") or []
    warnings: list[dict[str, Any]] = []
    quiet = [_quiet_item(spec, index, kits, shot_id, warnings) if item.get("animation") else item for index, item in enumerate(cast)]
    if all(after is before for after, before in zip(quiet, cast)):
        return spec, warnings
    return {**spec, "cast": quiet}, warnings


def note(item: dict[str, Any], found: list[dict[str, Any]]) -> None:
    """Put ``found`` on a render job item's ``warnings`` in place of the expression warnings it had (a scene asked for again must
    not list them twice); the key goes away when nothing is left."""
    kept = [warning for warning in item.get("warnings") or [] if warning.get("code") not in CODES]
    if kept or found:
        item["warnings"] = [*kept, *found]
    else:
        item.pop("warnings", None)


def card_warnings(bindings: list[dict[str, Any]], lines: list[dict[str, Any]], kit_animations: Any) -> list[str]:
    """Texts for the characters of a card who speak over a sheet the card plays (any but a cycle or the walk, as ``quiet_expressions``).
    ``bindings`` are the card's ``{characterId, animation?}``, ``lines`` the shot's lines (``name`` is the speaker) and
    ``kit_animations(character_id)`` the animations of that character's kit."""
    speakers = {str(line.get("name")) for line in lines}
    found = []
    for bound in bindings:
        who, name = str(bound.get("characterId")), bound.get("animation")
        if not name or who not in speakers:
            continue
        group = animations.animation_group(kit_animations(who), name)
        if guarded(group, name):
            found.append(f"{CARD}: {who} speaks while its '{name}' {_noun(group)} plays; a card plays its sheet from the start of the shot and "
                         f"cannot be moved: use the shot's own cast animation (at, duration) or apply the card to a shot where {who} is silent")
    return found

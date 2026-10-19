"""What a Series shot gives a Video 2D card: the pictures of its slots, its controls and its length (``series.shot.card.apply``).

A card (``app/shared/scene_templates.json``) has slots. The ``subject_N`` slots take a character of the series:

* a card that plays a sprite sheet (``walk-cycle-sheet``, ``walk-two-pose``, ``character-reaction``) takes the character's
  ``animation`` sheet (``walk`` by default for the walk cards, always named for ``character-reaction``) and sets the card's
  ``frames``, ``columns`` and ``facing``/``step`` or ``fps``/``loop`` from it, the way the Video 2D composer does
  (``templateControls`` in ``ui/src/lib/characterAnimations.ts``). Only an ``approved`` animation is played, and a pending or
  rejected one is refused with the words of the script check (``series_cast_animation.playable_problem``);
* every other card takes the character's pose picture (``poseId``: the shot's own pose for that character, else ``base``).

``background`` is the shot's location plate; ``foreground``, ``prop_N`` and anything else come from ``assets``
(``{slot: URL or workspace file}``). Nothing is invented: a required slot nobody fills is an error that names it.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from services import series_cast_animation as cast_animation
from services.character_animation_directions import walk_sheet
from services.series_shot_plan import background_for, kit_ref
from services.video2d_compile import canonical_slot

SHEET_CARDS = frozenset({"walk-cycle-sheet", "walk-two-pose", "character-reaction"})
SUBJECT = "subject_"
BACKGROUND = "background"
_DURABLE = ("/api/v1/", "/examples/", "http://", "https://", "data:image/")


class CardBindError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def slot_ids(entry: dict[str, Any]) -> list[str]:
    return [str(slot.get("id")) for slot in entry.get("slots") or [] if isinstance(slot, dict)]


def _subject_slots(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return [slot for slot in entry.get("slots") or [] if str(slot.get("id")).startswith(SUBJECT)]


# Controls ---------------------------------------------------------------------------------

def _fits(spec: Any, value: Any) -> bool:
    if not isinstance(spec, dict):
        return False
    if "options" in spec:
        return value in (spec.get("options") or [])
    return isinstance(value, (int, float)) and not isinstance(value, bool) and spec.get("min", float("-inf")) <= value <= spec.get("max", float("inf"))


def sheet_controls(animation: dict[str, Any], card: str) -> dict[str, Any]:
    """The controls a card needs to play a made animation: a cycle at its step (two steps make a cycle, one for a two-pose
    sheet), a reaction at its own fps and loop."""
    sheet = animation.get("sheet") or {}
    frames, columns = int(sheet.get("count") or 1), int(sheet.get("columns") or 1)
    base = {"frames": frames, "columns": columns}
    if card in ("walk-cycle-sheet", "walk-two-pose"):
        steps = 2 if card == "walk-cycle-sheet" else 1
        fps = max(1.0, float(animation.get("fps") or 4))
        return {**base, "facing": "left" if animation.get("facing") == "left" else "right", "step": min(1.0, max(0.3, round(frames / (steps * fps), 2)))}
    return {**base, "fps": animation.get("fps") or 4, "loop": animation.get("loop") or "once"}


def card_controls(entry: dict[str, Any], wanted: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """``wanted`` kept to the controls the card has and to values it accepts, and the names it had to drop."""
    declared = entry.get("controls") or {}
    kept = {name: value for name, value in wanted.items() if _fits(declared.get(name), value)}
    return kept, [name for name in wanted if name not in kept]


def card_duration(entry: dict[str, Any], controls: dict[str, Any], needed: float) -> float | None:
    """The card's ``duration``: the caller's own, else the shot's length held inside the card's range. None leaves the card's default.
    A shot longer than the card allows is an error: a take shorter than its shot is refused on import."""
    spec = (entry.get("controls") or {}).get("duration") or {}
    if "duration" in controls:
        return float(controls["duration"])
    if needed <= 0:
        return None
    low, high = float(spec.get("min", 0)), float(spec.get("max", 600))
    if needed > high:
        raise CardBindError("card_shorter_than_shot", f"Card {entry['id']} lasts at most {high:g} s and the shot needs {needed:g} s: "
                            "shorten the shot (series.shot.update duration) or choose a longer card")
    return round(max(low, needed), 3)


# Characters -------------------------------------------------------------------------------

def shot_cast(shot: dict[str, Any]) -> list[tuple[str, str]]:
    """(character id, pose id) of the people the shot shows, in its own order."""
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    entries = [(str(item["characterId"]), str(item.get("poseId") or "base")) for item in layout.get("cast") or []
               if isinstance(item, dict) and item.get("characterId")]
    return entries or [(str(person), "base") for person in shot.get("visibleCharacterIds") or []]


def _kit_of(series: dict[str, Any], kits: dict[str, Any], character_id: str) -> dict[str, Any]:
    if not any(item.get("id") == character_id for item in series.get("characters") or []):
        raise CardBindError("unknown_character", f"The series has no character {character_id}", 404)
    ref = kit_ref(series, character_id)
    kit = kits.get(ref["id"]) if ref else None
    if not kit:
        raise CardBindError("no_kit", f"{character_id} has no Character Kit: make one in Characters", 409)
    return kit


def _pose_source(kit: dict[str, Any], who: str, pose_id: str) -> str:
    picture = kit.get("base") if pose_id == "base" else (kit.get("poses") or {}).get(pose_id)
    source = picture.get("source") if isinstance(picture, dict) else None
    if not isinstance(source, str) or not source:
        have = ", ".join(["base", *sorted(kit.get("poses") or {})])
        raise CardBindError("unknown_pose", f"{who} has no pose {pose_id} (poses: {have})")
    return source


def _animation_id(raw: Any, card: str, who: str) -> str:
    if raw is None:
        if card.startswith("walk"):
            return cast_animation.WALK
        raise CardBindError("animation_required", f"Card {card} plays an animation of {who}: pass animation (a walk, a wave, an angry...)")
    found = cast_animation.request(raw)
    if found is None:
        raise CardBindError("bad_animation", f"{who}: animation must be an animation id such as walk or angry")
    return found["id"]


def _sheet_of(kit: dict[str, Any], who: str, card: str, slot: str, raw: Any) -> tuple[str, str, dict[str, Any]]:
    animation_id = _animation_id(raw, card, who)
    animations = kit.get("animations") if isinstance(kit.get("animations"), dict) else {}
    if raw is None and card.startswith("walk") and walk_sheet(animations):
        animation_id = walk_sheet(animations)[0]  # a walk card with no animation named plays the best approved walk: walk-12, else walk
    problem = cast_animation.playable_problem(animations, who, animation_id, f"cast {slot}")
    if problem:
        raise CardBindError("animation_not_approved" if animations.get(animation_id) else "animation_not_found", problem, 409)
    animation = animations[animation_id]
    return str((animation.get("sheet") or {}).get("source") or ""), animation_id, animation


def _character_slot(card: str, series: dict[str, Any], kits: dict[str, Any], slot: str, item: dict[str, Any],
                    fallback_pose: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """The picture a ``subject`` slot gets for one cast entry, what was bound and the controls that follow from it."""
    who = str(item["characterId"])
    kit = _kit_of(series, kits, who)
    if card in SHEET_CARDS:
        if item.get("poseId"):
            raise CardBindError("card_plays_sheet", f"Card {card} plays an animation sheet, not a pose: leave poseId out of {slot}")
        source, animation_id, animation = _sheet_of(kit, who, card, slot, item.get("animation"))
        return source, {"slot": slot, "characterId": who, "animation": animation_id}, sheet_controls(animation, card)
    if item.get("animation") is not None:
        raise CardBindError("card_not_sheet", f"Card {card} draws a pose picture and does not play animations: use walk-cycle-sheet, "
                            "walk-two-pose or character-reaction to play a character's animation sheet")
    pose_id = str(item.get("poseId") or fallback_pose)
    return _pose_source(kit, who, pose_id), {"slot": slot, "characterId": who, "poseId": pose_id}, {}


def _assigned(entry: dict[str, Any], cast: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Cast entries by slot; an entry without a slot takes the first free character slot."""
    subjects = [str(slot["id"]) for slot in _subject_slots(entry)]
    by_slot: dict[str, dict[str, Any]] = {}
    for item in cast:
        slot = item.get("slot") or next((name for name in subjects if name not in by_slot), None)
        if slot not in subjects:
            raise CardBindError("bad_slot", f"Card {entry['id']} has no character slot {slot} (character slots: {', '.join(subjects) or 'none'})")
        if slot in by_slot:
            raise CardBindError("bad_slot", f"cast gives slot {slot} twice")
        by_slot[str(slot)] = item
    return by_slot


def _from_shot(entry: dict[str, Any], by_slot: dict[str, dict[str, Any]], shot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The shot's own people fill the required character slots the cast left empty, in the shot's order."""
    taken = {str(item["characterId"]) for item in by_slot.values()}
    people = [who for who, _pose in shot_cast(shot) if who not in taken]
    filled = dict(by_slot)
    for slot in _subject_slots(entry):
        name = str(slot["id"])
        if name in filled or not slot.get("required"):
            continue
        if not people:
            raise CardBindError("slot_missing", f"Card {entry['id']} needs a character in {name}: pass cast [{{slot: \"{name}\", characterId}}]")
        filled[name] = {"characterId": people.pop(0)}
    return filled


# Other slots ------------------------------------------------------------------------------

def _source(raw: Any, slot: str, workspace: str, root: str) -> str:
    """A durable URL as it is; a bare name is a file of the workspace."""
    if not isinstance(raw, str) or not raw.strip():
        raise CardBindError("bad_asset", f"assets {slot} must be a workspace file or a URL")
    text = raw.strip()
    if text.lower().startswith(_DURABLE):
        return text
    if "/" in text or not os.path.isfile(os.path.join(root, text)):
        raise CardBindError("bad_asset", f"assets {slot}: {text} is not a file of this workspace")
    return f"/api/v1/file/{quote(text)}?workspace={quote(workspace)}"


def _extra_assets(entry: dict[str, Any], assets: dict[str, Any], workspace: str, root: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for name, raw in (assets or {}).items():
        slot = canonical_slot(entry, name) if isinstance(name, str) else None
        if slot is None:
            raise CardBindError("bad_slot", f"Card {entry['id']} has no slot {name} (slots: {', '.join(slot_ids(entry))})")
        found[slot] = _source(raw, slot, workspace, root)
    return found


def bind_card(entry: dict[str, Any], *, series: dict[str, Any], kits: dict[str, Any], shot: dict[str, Any], workspace: str, root: str,
              cast: list[dict[str, Any]] | None, assets: dict[str, Any] | None) -> dict[str, Any]:
    """``{assets, controls, bindings, warnings}`` for the card: the picture of every slot it needs, the controls the sheets set."""
    card = str(entry["id"])
    by_slot = _from_shot(entry, _assigned(entry, cast or []), shot)
    fallback = dict(shot_cast(shot))
    sources: dict[str, str] = {}
    bindings: list[dict[str, Any]] = []
    controls: dict[str, Any] = {}
    for slot, item in by_slot.items():
        source, bound, auto = _character_slot(card, series, kits, slot, item, fallback.get(str(item["characterId"]), "base"))
        sources[slot] = source
        bindings.append(bound)
        controls.update(auto)
    extra = _extra_assets(entry, assets or {}, workspace, root)
    sources = {**sources, **{slot: source for slot, source in extra.items() if slot not in sources}}
    if BACKGROUND in slot_ids(entry) and BACKGROUND not in sources:
        plate = background_for(series, shot, workspace)
        if plate:
            sources[BACKGROUND] = plate["source"]
    missing = [str(slot["id"]) for slot in entry.get("slots") or [] if slot.get("required") and str(slot["id"]) not in sources]
    if missing:
        raise CardBindError("slot_missing", f"Card {card} needs {', '.join(missing)}: "
                            + ("the shot's location has no plate; " if BACKGROUND in missing else "")
                            + "pass assets {slot: workspace file or URL}")
    return {"assets": sources, "bindings": bindings, "autoControls": controls}

"""Continuity between a 2D Series shot and its neighbours: where each character stands in a location, and the camera
of a shot that shows the same picture as the one before it.

A single character's ``medium`` or ``close`` pans the plate toward that character's place in the room (``place``):
its x in the nearest ``wide`` or ``two`` shot of the same location (the same scene first), else its location home.
Shot and reverse shot then show two sides of the room, not the same patch of wall behind both faces.

Two shots in a row that show the same picture (the same plate, framing and crop, ``picture``) would cut back to
where the first one's push started. The second one's camera starts where the first one's ended instead, and a push
goes on from there (``camera_start``) up to ``CAMERA_LIMIT``, past which the camera holds. ``from_script`` warns about
each such pair (``same_picture_warnings``): the same still plate twice in a row is one shot, or the second one needs
its own framing or location.

Both depend on other shots, so ``series_take_inputs`` fingerprints them (``inputs``) and a take renders again when a
neighbour moves its picture. A shot whose crop and camera are the plain ones adds nothing and keeps its digest.
"""
from __future__ import annotations

from typing import Any

from services.series_shot_plan import (_cast_entries, _cast_x, _homes, _shot_camera, _shot_framing, background_for,
                                       frame_size, spread)

# The push of ``cameraLayer`` in ui/scripts/seriesShot.ts: it grows the camera this much and lifts it this many %.
PUSH_SCALE, PUSH_RISE = 0.07, 1.5
CAMERA_LIMIT = 1.3
REST = (1.0, 50.0)
_WIDE, _TIGHT = ("wide", "two"), ("medium", "close")


def ordered(episode: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(episode.get("shots") or [], key=lambda shot: shot.get("order", 0))


def _layout(shot: dict[str, Any]) -> dict[str, Any]:
    return shot["layout2d"] if isinstance(shot.get("layout2d"), dict) else {}


def framing_of(shot: dict[str, Any]) -> str:
    """The shot's 2D framing as ``build_shot_spec`` plans it; a document card is a title."""
    layout = _layout(shot)
    card = layout.get("card") if isinstance(layout.get("card"), dict) else None
    return "title" if card and card.get("kind") == "document" else _shot_framing(layout, shot, card)


def _drawn(shot: dict[str, Any]) -> bool:
    return (shot.get("productionMethod") or "animation_2d") == "animation_2d"


def cast_places(series: dict[str, Any], shot: dict[str, Any], framing: str) -> list[tuple[str, float]]:
    """(character id, x %) of each cast member, where ``plan_cast`` stands it."""
    entries = _cast_entries(shot)
    width, height = frame_size(series)
    homes, defaults = _homes(series, shot), spread(len(entries), height > width)
    return [(entry["characterId"], _cast_x(entry, framing, len(entries), homes, defaults[index]))
            for index, entry in enumerate(entries)]


def place(series: dict[str, Any], shots: list[dict[str, Any]], shot: dict[str, Any], character_id: str) -> float | None:
    """Where ``character_id`` stands in the shot's location: its x in the nearest wide or two shot there (the same
    scene first, an earlier shot on a tie), else its home in the location, else None."""
    index = next((i for i, other in enumerate(shots) if other.get("id") == shot.get("id")), 0)
    best: tuple[tuple, float] | None = None
    for i, other in enumerate(shots):
        if other.get("locationId") != shot.get("locationId") or not _drawn(other):
            continue
        framing = framing_of(other)
        x = next((x for cid, x in cast_places(series, other, framing) if cid == character_id), None) if framing in _WIDE else None
        rank = (other.get("sceneId") != shot.get("sceneId"), abs(i - index), i > index)
        if x is not None and (best is None or rank < best[0]):
            best = (rank, x)
    return best[1] if best else _homes(series, shot).get(character_id)


def focus(series: dict[str, Any], shots: list[dict[str, Any]], shot: dict[str, Any], framing: str) -> float:
    """Where a tighter framing pans the plate: the cast's mean x, or a lone character's place in the room."""
    places = cast_places(series, shot, framing)
    if framing in _TIGHT and len(places) == 1:
        found = place(series, shots, shot, places[0][0])
        if found is not None:
            return found
    return sum(x for _cid, x in places) / len(places) if places and framing in ("two", *_TIGHT) else 50.0


def _plain_focus(series: dict[str, Any], shot: dict[str, Any], framing: str) -> float:
    places = cast_places(series, shot, framing)
    return sum(x for _cid, x in places) / len(places) if places and framing in ("two", *_TIGHT) else 50.0


def picture(series: dict[str, Any], shots: list[dict[str, Any]], shot: dict[str, Any]) -> tuple | None:
    """What a 2D shot shows behind its cast: its plate, framing and crop. None for a title, a 3D or video shot, or a
    shot without a plate."""
    framing = framing_of(shot)
    plate = background_for(series, shot, "") if _drawn(shot) and framing != "title" else None
    if not plate:
        return None
    return plate["source"], framing, round(focus(series, shots, shot, framing), 1)


def _same(series: dict[str, Any], shots: list[dict[str, Any]], index: int) -> bool:
    """The shot at ``index`` shows the same picture as the one before it."""
    if index <= 0:
        return False
    here = picture(series, shots, shots[index])
    return here is not None and here == picture(series, shots, shots[index - 1])


def camera_start(series: dict[str, Any], shots: list[dict[str, Any]], shot: dict[str, Any]) -> tuple[float, float, bool] | None:
    """(scale, y, push) of a shot that goes on from the previous shot's camera; None when it starts at rest."""
    index = next((i for i, other in enumerate(shots) if other.get("id") == shot.get("id")), None)
    if index is None or not _same(series, shots, index):
        return None
    first = index
    while _same(series, shots, first):
        first -= 1
    scale, y = REST
    for other in shots[first:index]:
        if _shot_camera(_layout(other), other) == "push" and scale + PUSH_SCALE <= CAMERA_LIMIT + 1e-9:
            scale, y = scale + PUSH_SCALE, y - PUSH_RISE
    push = _shot_camera(_layout(shot), shot) == "push" and scale + PUSH_SCALE <= CAMERA_LIMIT + 1e-9
    return (round(scale, 3), round(y, 3), push) if (scale, y) != REST else None


def inputs(series: dict[str, Any], episode: dict[str, Any] | None, shot: dict[str, Any]) -> dict[str, Any]:
    """What the shot's picture takes from its neighbours, for the take fingerprint; empty when nothing."""
    if not episode or not _drawn(shot):
        return {}
    shots = ordered(episode)
    framing = framing_of(shot)
    found: dict[str, Any] = {}
    crop = focus(series, shots, shot, framing)
    if crop != _plain_focus(series, shot, framing):
        found["focus"] = round(crop, 3)
    start = camera_start(series, shots, shot)
    if start:
        found["cameraStart"] = list(start)
    return found


def same_picture_warnings(series: dict[str, Any], shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One ``same_picture`` warning per shot that shows the picture of the shot before it."""
    shots = sorted(shots, key=lambda shot: shot.get("order", 0))
    warnings = []
    for index in range(1, len(shots)):
        if not _same(series, shots, index):
            continue
        before, here = shots[index - 1]["id"], shots[index]["id"]
        _source, framing, _crop = picture(series, shots, shots[index])
        empty = not _cast_entries(shots[index]) and not _cast_entries(shots[index - 1])
        advice = ("the same still plate twice: make it one shot, or give the second its own location"
                  if empty else "give the second another framing, or its own location if it is another place")
        warnings.append({"code": "same_picture", "subject": here, "shots": [before, here],
                         "message": f"{before} → {here}: the same picture ({shots[index].get('locationId')}, {framing}) "
                                    f"twice in a row; the camera of {here} goes on from {before}'s; {advice}"})
    return warnings

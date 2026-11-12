"""Which way ``beside`` stands: the side of the object, and a bed's own head, foot, left and right.

``side`` in degrees goes round the object from its front (+z of its GLB, turned with it) toward its right as seen from
the front (+x): ``front`` 0, ``right`` 90, ``back`` 180, ``left`` 270. ``offset`` slides the object along that side:
on the front toward the right, on the right toward the back, on the back toward the left, on the left toward the front.

A bed has a head, so ``left`` and ``right`` mean what a person means by them. A bed is ``furniture {kind: bed}`` (its
head, the headboard, is at the -x end of its GLB: seen from its front, the long side people sit on, the head is on the
left) or the bed of a stage card's room (its head is the end toward the back wall). For a bed:

- ``head`` / ``foot``: past the headboard end / past the foot end, centred on it;
- ``left`` / ``right``: its long sides as for someone lying in it on their back, by the head end, where a bedside table
  stands (``furniture {kind: bed}``: ``right`` is its front, ``left`` its back); ``offset`` slides toward the foot;
- a nightstand (``furniture {kind: nightstand}``) with no side stands on its ``right``, by the head end.

Another bed GLB has no head this code can find: ``head`` and ``foot`` warn (give degrees), and the other sides and
``offset`` work as for any object. ``front``, ``back`` and degrees work as for any object on a bed too.
"""
from __future__ import annotations

import math

import numpy as np

SIDES = {"front": 0.0, "right": 90.0, "back": 180.0, "left": 270.0}
BED_SIDES = ("head", "foot")
SIDE_WORDS = (*SIDES, *BED_SIDES)
_NIGHTSTAND_WORDS = ("nightstand", "bedside", "mesilla", "mesita")


def bed_head(furniture, target: dict) -> np.ndarray | None:
    """The scene floor direction (x, z) from a bed's middle toward its head, or None when ``target`` is no bed with a known head."""
    declared = target.get("furniture") if isinstance(target.get("furniture"), dict) else {}
    if declared.get("kind") == "bed" and furniture.frame is not None:
        return furniture.frame.direction([-1.0, 0.0])
    block = target.get("roomBlock") if isinstance(target.get("roomBlock"), dict) else {}
    if block.get("kind") == "bed":
        width, depth = float(block["box"][3]), float(block["box"][5])
        return np.array([0.0, -1.0]) if depth >= width else np.array([-1.0, 0.0])
    return None


def _nightstand(slot: dict) -> bool:
    declared = slot.get("furniture") if isinstance(slot.get("furniture"), dict) else {}
    if declared.get("kind") == "nightstand":
        return True
    named = f"{slot.get('id') or ''} {slot.get('sourceUrl') or ''}".lower()
    return any(word in named for word in _NIGHTSTAND_WORDS)


def beside_way(near: dict, furniture, target: dict, slot: dict) -> tuple[np.ndarray, np.ndarray | None] | str:
    """``(out, head)``: the scene floor direction from the object toward the side the mover stands on, and, by a bed's
    head end, the bed's head direction to line the mover up with it (else None). A warning string when the side cannot be
    resolved."""
    side = near.get("side")
    head = bed_head(furniture, target)
    if head is not None and (side in (*BED_SIDES, "left", "right") or (side is None and _nightstand(slot))):
        if side == "head":
            return head, None
        if side == "foot":
            return -head, None
        right = np.array([head[1], -head[0]])                     # someone lying on their back, head at the headboard
        return (-right if side == "left" else right), head
    if side in BED_SIDES:
        return (f"beside_unresolved: {slot.get('id')} beside {target.get('id')}: side {side!r} is a bed's {side} end and "
                f"{target.get('id')} is not a bed whose head is known (furniture {{kind: \"bed\"}} or a stage's bed); give side "
                f"front, right, back, left or degrees")
    degrees = SIDES.get(side, 0.0) if isinstance(side, str) or side is None else float(side)
    angle = float(target.get("rotationY") or 0) + math.radians(degrees)
    return np.array([math.sin(angle), math.cos(angle)]), None


def along_side(theirs: np.ndarray, ours: np.ndarray, across: np.ndarray, offset: float, head: np.ndarray | None) -> float:
    """Where the mover's origin goes along the side (the ``across`` axis): centred on the object plus ``offset``, or, by a
    bed's head end, its head-ward edge in line with the bed's head end and ``offset`` toward the foot."""
    mine, other = ours @ across, theirs @ across
    if head is None:
        return float((other.min() + other.max()) / 2 + offset - (mine.min() + mine.max()) / 2)
    if float(head @ across) > 0:
        return float(other.max() - mine.max() - offset)
    return float(other.min() - mine.min() + offset)

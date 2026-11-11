"""A workspace GLB named like furniture (a table, a chair, a bed...) that nobody sits on or at yet, said to be the wrong
size before a sitter finds it out.

Every model is drawn 1.7 m x ``scale`` tall until it is sized, so a ``cc0-table.glb`` bound with no ``height`` is a
1.70 m table: the reply says the usual height of that kind (``furniture_size_unusual``, with the binding to paste). A
table sized to a height no table has (under 0.6 m or over 1.15 m) is said too. Furniture made by ``furniture`` and the
stage's own blocks are sized by construction; a piece someone already rests on or at is judged by the contact check.
"""
from __future__ import annotations

import re

KIND_HEIGHTS = {"table": 0.75, "mesa": 0.75, "desk": 0.75, "escritorio": 0.75, "chair": 0.9, "silla": 0.9, "bed": 0.55, "cama": 0.55,
                "sofa": 0.85, "couch": 0.85, "stool": 0.46, "taburete": 0.46, "bench": 0.45, "banco": 0.45, "nightstand": 0.55,
                "mesilla": 0.55}
TABLE_WORDS = ("table", "mesa", "desk", "escritorio")
TABLE_RANGE = (0.6, 1.15)


def _kind(slot: dict) -> str | None:
    """The first furniture word among the object's id and file name words (``cc0-table.glb``: table; ``tablet``: none)."""
    words = re.split(r"[^a-z]+", f"{slot.get('id') or ''} {str(slot.get('sourceUrl') or '').split('?', 1)[0].rsplit('/', 1)[-1]}".lower())
    return next((word for word in words if word in KIND_HEIGHTS), None)


def size_hints(pieces: list, drawn: dict, judged: set) -> list[str]:
    """Warnings for furniture-named pieces not yet judged by a sitter: unsized, or a table at no table's height."""
    lines = []
    for piece in pieces:
        slot = piece.slot
        if piece.id in judged or piece.id not in drawn or slot.get("furniture") or slot.get("roomBlock"):
            continue
        kind = _kind(slot)
        if kind is None:
            continue
        height, scale = drawn[piece.id]
        usual = KIND_HEIGHTS[kind]
        if abs(height - 1.7) <= 0.01 and abs(scale - 1) <= 1e-6:
            lines.append(f"furniture_size_unusual: {piece.id} is drawn 1.70 m tall (every model is 1.7 m x scale until it is sized); a "
                         f"{kind} is about {usual:g} m: give {piece.id} height {usual:g}")
        elif kind in TABLE_WORDS and not TABLE_RANGE[0] <= height <= TABLE_RANGE[1]:
            lines.append(f"furniture_size_unusual: {piece.id} is {height:.2f} m high and a table is {TABLE_RANGE[0]:g} to {TABLE_RANGE[1]:g} m "
                         f"(a dining table 0.75, a bar table 1.05): give {piece.id} height {usual:g} unless it is meant that way")
    return lines

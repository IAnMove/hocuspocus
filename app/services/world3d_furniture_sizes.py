"""A workspace GLB named like furniture (a table, a chair, a bed...) that nobody sits on or at yet, said to be the wrong
size before a sitter finds it out.

Every model is drawn 1.7 m x ``scale`` tall until it is sized, so a ``cc0-table.glb`` bound with no ``height`` is a
1.70 m table: the reply says the usual height of that kind (``furniture_size_unusual``, with the binding to paste). The
name's words decide the kind (``coffee-table``: a coffee table, 0.45 m; ``table-lamp``: not furniture, nothing said).
Furniture made by ``furniture`` and the stage's own blocks are sized by construction; a piece someone already rests on
or at is judged by the contact check.
"""
from __future__ import annotations

import re

KIND_HEIGHTS = {"table": 0.75, "mesa": 0.75, "desk": 0.75, "escritorio": 0.75, "chair": 0.9, "silla": 0.9, "bed": 0.55, "cama": 0.55,
                "sofa": 0.85, "couch": 0.85, "stool": 0.46, "taburete": 0.46, "bench": 0.45, "banco": 0.45, "nightstand": 0.55,
                "mesilla": 0.55}
QUALIFIED = {("coffee", "table"): 0.45, ("side", "table"): 0.55, ("bar", "table"): 1.05, ("bar", "stool"): 0.75}
NOT_FURNITURE = {"lamp", "light", "cloth", "clock", "runner", "mat", "top"}


def _kind(slot: dict) -> tuple[str, float] | None:
    """``(name, usual height)`` from the object's id and file name words (``cc0-table.glb``: table; ``tablet``,
    ``table-lamp``: none)."""
    words = [word for word in re.split(r"[^a-z]+", f"{slot.get('id') or ''} {str(slot.get('sourceUrl') or '').split('?', 1)[0].rsplit('/', 1)[-1]}".lower()) if word]
    kind = next((word for word in words if word in KIND_HEIGHTS), None)
    if kind is None or NOT_FURNITURE & set(words):
        return None
    qualifier = next((word for word in words if (word, kind) in QUALIFIED), None)
    return (f"{qualifier} {kind}", QUALIFIED[(qualifier, kind)]) if qualifier else (kind, KIND_HEIGHTS[kind])


def size_hints(pieces: list, drawn: dict, judged: set) -> list[str]:
    """Warnings for furniture-named pieces not yet judged by a sitter and still drawn at the 1.7 m every model starts at."""
    lines = []
    for piece in pieces:
        slot = piece.slot
        if piece.id in judged or piece.id not in drawn or slot.get("furniture") or slot.get("roomBlock"):
            continue
        found = _kind(slot)
        height, scale = drawn[piece.id]
        if found is not None and abs(height - 1.7) <= 0.01 and abs(scale - 1) <= 1e-6:
            lines.append(f"furniture_size_unusual: {piece.id} is drawn 1.70 m tall (every model is 1.7 m x scale until it is sized); a "
                         f"{found[0]} is about {found[1]:g} m: give {piece.id} height {found[1]:g}")
    return lines

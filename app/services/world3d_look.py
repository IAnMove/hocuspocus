"""Video 3D render looks, checked before a document reaches the editor parser.

Mirrors ``SCENE3D_RENDER_LOOKS`` in ``ui/src/features/scene3d/types.ts`` and ``parseToon`` in
``ui/src/features/scene3d/toonLook.ts``. The editor parser clamps stored documents; agent input
that is out of range is refused here instead, so the caller learns what was wrong.
"""
from __future__ import annotations

import re

RENDER_LOOKS = ("n64", "toon")
_INK = re.compile(r"^#[0-9a-fA-F]{6}$")


def check_render_look(value) -> None:
    if value is not None and value not in RENDER_LOOKS:
        raise ValueError(f"renderLook must be one of {', '.join(RENDER_LOOKS)}")


_TOON_RULES = {
    "steps": (lambda value: type(value) is int and 2 <= value <= 4, "toon.steps must be 2, 3 or 4", int),
    "outline": (lambda value: type(value) in (int, float) and 0 <= value <= 8, "toon.outline must be between 0 and 8 pixels",
                lambda value: round(float(value), 2)),
    "ink": (lambda value: isinstance(value, str) and _INK.fullmatch(value) is not None, "toon.ink must be a #rrggbb colour", str.lower),
}


def normalize_toon(raw) -> dict:
    """Toon settings: ``steps`` 2-4 light bands, ``outline`` 0-8 px of a 1080p frame, ``ink`` as #rrggbb."""
    if not isinstance(raw, dict) or set(raw) - set(_TOON_RULES):
        raise ValueError("toon takes only steps, outline and ink")
    toon = {}
    for key, value in raw.items():
        valid, message, clean = _TOON_RULES[key]
        if not valid(value):
            raise ValueError(message)
        toon[key] = clean(value)
    return toon


def check_document_look(document: dict) -> None:
    check_render_look(document.get("renderLook"))
    if "toon" in document:
        normalize_toon(document["toon"])

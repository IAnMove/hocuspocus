"""MCP ``characters.face.make``.

The Characters panel and the Wizard post the same route (``POST /api/v1/character-kits/face``). A retried
``intent_id`` replays the first result (``series_commands.INTENT_OPERATIONS``).
"""
from __future__ import annotations

from typing import Any, Callable

WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
ID = {"type": "string", "minLength": 1, "maxLength": 160}
REVISION = {"type": "integer", "minimum": 0}

_TRAITS = {"type": "object", "description": "eyes (dot|oval|halflid|wide, or {shape, size, separation}), brows (thick|thin|none), nose (none|dot|line|bulb), moustache (none|walrus|pencil|handlebar, or {style, color}), glasses (none|round|square), freckles, stubble, ink (#rrggbb), line (2-24), mouth (paper|ink), skin (#rrggbb), style (blob|anime), eye_color (#rrggbb, anime), blush (anime). Pass skin equal to the head colour: the blink patch is painted in it."}

OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "characters.face.make": (
        {"workspace": WORKSPACE, "traits": _TRAITS, "name": {"type": "string", "maxLength": 240},
         "kit_id": ID, "base_revision": REVISION},
        ["workspace", "traits"], True,
        "Draw a 2D blob face and save it as a Character Kit: eight expressions, nine paper or ink mouths and a blink, "
        "with anchors on the pixels that were drawn. traits selects eyes, brows, nose, moustache, glasses, freckles, "
        "stubble, ink and line. The same traits update the same kit. Open it in Characters like any other kit, then "
        "paint it on a model with world3d.scene.face. Returns kit_id, poses and preview.",
    ),
}


def _make(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body = {"workspace": data["workspace"], "traits": data["traits"]}
    if "name" in data:
        body["name"] = data["name"]
    if "kit_id" in data:
        body["kit_id"] = data["kit_id"]
    if "base_revision" in data:
        body["baseRevision"] = data["base_revision"]
    saved = request("POST", "/api/v1/character-kits/face", body=body)
    return {"kit_id": saved.get("kit_id"), "poses": saved.get("poses"), "preview": saved.get("preview")}


RUNNERS: dict[str, Callable[..., Any]] = {"characters.face.make": _make}

"""The animation clips of a GLB, read from its JSON chunk alone (a few kilobytes, never a buffer), and the one a still figure should play.

``glb_clips`` never raises: an unreadable file has no clips. ``idle_clip`` picks the clip named like a rest pose (``Idle``, ``idle_loop``,
``Stand``...) and nothing else: a model whose only clip is a walk keeps its bind pose rather than walking on the spot."""
from __future__ import annotations

import re
from pathlib import Path

from services.procedural_3d.glb_bounds import MAX_JSON_BYTES, _read_document

_IDLE = re.compile(r"\b(idle|stand(ing)?|rest)\b|idle", re.IGNORECASE)


def glb_clips(path, *, max_json_bytes: int = MAX_JSON_BYTES) -> list[str]:
    """The clip names in file order (an unnamed clip is ``clip_<index>``)."""
    try:
        document = _read_document(Path(path), max_json_bytes)
    except Exception:  # noqa: BLE001 - the contract is that a bad file never raises
        return []
    animations = document.get("animations") if isinstance(document, dict) else None
    if not isinstance(animations, list):
        return []
    return [str(item.get("name") or f"clip_{index}") if isinstance(item, dict) else f"clip_{index}" for index, item in enumerate(animations)]


def idle_clip(names: list[str]) -> dict | None:
    """``{"index", "name"}`` of the first clip whose name says it is a rest pose, else None."""
    for index, name in enumerate(names):
        if _IDLE.search(name):
            return {"index": index, "name": name}
    return None

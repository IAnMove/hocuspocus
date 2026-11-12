"""The workspace file that holds the metric box rooms: ``scene3d-rooms.json`` and ``rooms/<name>.glb``.

A record is ``{"spec", "file", "surfaces", "paint"}``. ``spec`` is the normalised room, ``file`` its GLB, ``surfaces`` what each
surface wears (``room_surfaces``) and ``paint`` the state of the look: ``status`` (``not_painted``, ``queued``, ``running``,
``completed``, ``failed``), ``look`` (the fingerprint a Series shot compares) and, once painted, the request, the style and the
warnings. Old records have no ``surfaces`` or ``paint``: they read as an unpainted room with its default materials.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from services.prop_library import atomic_json
from services.room_box import build_room
from services.room_surfaces import default_entries, look_fingerprint, textures_of

STORE = "scene3d-rooms.json"
LOCK = threading.RLock()


def read(root: Path) -> dict:
    path = root / STORE
    if not path.is_file():
        return {"rooms": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rooms"), dict):
        raise ValueError("scene3d-rooms.json is unreadable")
    return data


def write(root: Path, library: dict) -> None:
    atomic_json(root / STORE, library)


def record_of(root: Path, name: str) -> dict | None:
    record = (read(root).get("rooms") or {}).get(name)
    return record if isinstance(record, dict) and isinstance(record.get("spec"), dict) else None


def surfaces_of(record: dict) -> dict:
    """What each surface wears. A record from before painting wears the procedural defaults of its words."""
    stored = record.get("surfaces")
    return stored if isinstance(stored, dict) and stored else default_entries(record["spec"])


def look_of(record: dict) -> str:
    """The fingerprint of how the room looks now."""
    paint = record.get("paint")
    if isinstance(paint, dict) and isinstance(paint.get("look"), str):
        return paint["look"]
    return look_fingerprint(record["spec"], surfaces_of(record))


def rebuild(root: Path, name: str, spec: dict, entries: dict) -> str:
    """Write the room's GLB from its surfaces at ``rooms/<name>.glb``; a failure leaves the old file where it was."""
    file = f"rooms/{name}.glb"
    target = root / file
    temporary = target.with_name(f"{name}.glb.tmp")
    try:
        build_room(temporary, spec, textures_of(root, spec, entries))
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return file


def new_record(root: Path, name: str, spec: dict) -> dict:
    """A room with the procedural look its words choose, and its GLB written."""
    if spec.get("plate"):
        from services.room_plate_commands import entries_of
        entries = entries_of(root, spec)
    else:
        entries = default_entries(spec)
    file = rebuild(root, name, spec, entries)
    return {"spec": spec, "file": file, "surfaces": entries,
            "paint": {"status": "not_painted", "look": look_fingerprint(spec, entries)}}


def summary(record: dict) -> dict:
    """What an agent needs to see of each surface: where its look comes from and what it is."""
    rows = {}
    for surface, entry in surfaces_of(record).items():
        rows[surface] = {key: entry[key] for key in ("source", "material", "color", "file", "tile_m") if key in entry}
    return rows

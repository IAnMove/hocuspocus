"""The workspace side of a plate room: reading its pictures, storing them as surfaces, and ``scene3d.room.paint`` with a picture.

``scene3d.room.put`` calls ``read_room`` so ``walls`` (and a prop's ``image``) may name a picture of the workspace; the stored
room keeps ``{file, w, h}`` and the picture's hash in its surface entries, so a plate that changes changes the room's look
and the shots that stand in it render again. ``paint`` with a picture does not call the image model: the picture is the paint.
"""
from __future__ import annotations

import copy
from pathlib import Path

from PIL import Image

from services import room_plate, room_store, set_skins
from services.room_box import normalize
from services.room_surfaces import file_sha, look_fingerprint

MAX_BYTES = 60 * 1024 * 1024
_PAINT_FIELDS = {"workspace", "name", "walls", "back", "left", "right", "stage", "fov", "range", "seed", "engine"}


def resolver(root: Path, workspace: str):
    """``ref -> {file, w, h}`` for a picture that lives in the workspace; an error names what is wrong with it."""

    def resolve(ref: dict) -> dict:
        value = next(iter(ref.values()))
        try:
            path = set_skins.asset_path(value, root, workspace)
        except ValueError as error:
            raise ValueError(f"picture {value}: it must be a file of this workspace") from error
        if path.stat().st_size > MAX_BYTES:
            raise ValueError(f"picture {value} is larger than {MAX_BYTES // 2**20} MB")
        try:
            with Image.open(path) as opened:
                width, height = opened.size
        except OSError as error:
            raise ValueError(f"picture {value} is not an image the server can read") from error
        return {"file": path.relative_to(root.resolve()).as_posix(), "w": int(width), "h": int(height)}

    return resolve


def read_room(root: Path, workspace: str, room: dict) -> dict:
    """The room as ``normalize`` takes it: every picture it names read, the plate's options gathered."""
    return room_plate.prepare(room, resolver(root, workspace))


def entries_of(root: Path, spec: dict) -> dict:
    """The surfaces of a plate room: its pictures, each with the hash of the file it was made from."""
    rows = {}
    for side in room_plate.SIDES:
        picture = spec["plate"].get(side)
        if picture:
            rows["plate" if side == "back" else side] = {"source": "plate", "file": picture["file"], "w": picture["w"], "h": picture["h"],
                                                         "sha": file_sha(root / picture["file"])}
    return rows


def warnings_of(spec: dict) -> list[dict]:
    """What an agent should know about a plate room: the stage it has to measure, and a camera height that looks odd."""
    plate = spec.get("plate")
    if not plate:
        return []
    found = []
    if plate.get("stage_assumed"):
        found.append({"code": "stage_assumed", "message": "no stage: the plate is taken to be seen from a 1.6 m camera with a 2 m door 40 % of its "
                      "height. Measure its horizon, a reference object and its floor on a grid and pass stage {horizon, ref: {baseY, heightPct, heightM}}"})
    note = room_plate.eye_note(plate["stage"])
    if note and not plate.get("stage_assumed"):
        found.append({"code": "eye_height", "message": note})
    return found


def paint_plate(root: Path, workspace: str, name: str, data: dict) -> dict:
    """``scene3d.room.paint`` with a picture: replace a plate room's pictures (and, if given, its stage, lens or range). The room's
    size follows the new plate; a person stands where they stood. Returns the paint status."""
    from services.room_paint import status

    with room_store.LOCK:
        record = room_store.record_of(root, name)
        if record is None:
            raise ValueError(f"unknown room {name}")
        spec = record["spec"]
        if not spec.get("plate"):
            raise ValueError("this room is not a plate room: put it again with walls as a picture {file} to use one")
        unknown = set(data) - _PAINT_FIELDS
        if unknown:
            raise ValueError(f"a plate room is painted with its pictures: unknown {', '.join(sorted(unknown))} "
                             f"(walls, back, left, right, stage, fov, range)")
        raw = {key: copy.deepcopy(value) for key, value in spec.items() if key != "size"}
        raw["plate"] = _merged(spec["plate"], data, resolver(root, workspace))
        made = normalize(raw)
        entries = entries_of(root, made)
        file = room_store.rebuild(root, name, made, entries)
        library = room_store.read(root)
        library["rooms"][name] = {**record, "spec": made, "file": file, "surfaces": entries,
                                  "paint": {"status": "completed", "engine": "plate", "look": look_fingerprint(made, entries),
                                            "warnings": warnings_of(made)}}
        room_store.write(root, library)
    return status(root, name)


def _merged(plate: dict, data: dict, resolve) -> dict:
    refs = room_plate._wall_refs(data.get("walls")) or {}
    refs.update({side: data[side] for side in room_plate.SIDES if side in data})
    for side, ref in refs.items():
        if not room_plate.is_plate_ref(ref):
            raise ValueError(f"{side} is a picture of the workspace: {{file}} or {{asset}}")
    merged = {key: copy.deepcopy(value) for key, value in plate.items() if key in (*room_plate.SIDES, "stage", "fov", "range")}
    merged.update({side: resolve(ref) for side, ref in refs.items()})
    for key in ("stage", "fov", "range"):
        if data.get(key) is not None:
            merged[key] = data[key]
    if "stage" in data and data["stage"] is not None:
        merged["stage_assumed"] = False
    elif plate.get("stage_assumed"):
        merged["stage_assumed"] = True
    return merged


def wants_picture(data: dict) -> bool:
    """A ``paint`` request that names a picture or a plate option (it is answered here, with no model)."""
    return isinstance(data.get("walls"), dict) or any(key in data for key in ("back", "left", "right", "stage", "fov", "range"))

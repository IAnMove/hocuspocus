"""``scene3d.room.paint``: texture a stored box room with the image model, as a job in the background.

Every stored room already wears procedural materials (``room_materials``), so it is never flat. Painting replaces them with
pictures from the image model (the project's fastest installed Qwen Image 2.1, through the same admission as sets and
props): a seamless floor, walls, ceiling and trim, and a front view of the door. Each tiling picture is healed at its wrap
with ``set_skins`` (inpaint, as ``location.set3d`` does) and, if a seam is still visible, its edges are blended; a picture
that will still not repeat is not used and the surface keeps its procedural look, with a warning. A picture the model never
returns does the same: the room keeps what it wears and the job says what failed.

The result is a PNG per surface (``rooms/<name>/<surface>.png``, so it can be opened again), the rebuilt GLB at the same path
and a fingerprint of the new look, which a Series shot that stands in the room compares to know it must render again.
The same room, words, style and seed give the same request, so a second call finds the finished look and runs nothing.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageOps

from services import room_materials, room_store, set_skins
from services.diorama_set import trim_border
from services.game_tiles import seam_error
from services.production_diorama import GROUND_STAGING
from services.production_room_box import CEILING_STAGING, WALL_STAGING
from services.room_surfaces import GEOMETRY_VERSION, SURFACES, default_entries, file_sha, look_fingerprint, present
from services.set_generation import generate_batch
from services.set_molds import defaults

RECIPE = 1
TILING = ("floor", "walls", "ceiling", "trim")
SIZE = {"floor": "1024x1024", "walls": "1024x1024", "ceiling": "1024x1024", "trim": "1024x1024", "door": "576x1280"}
# Metres one repeat of a painted picture covers, unless the request gives ``tile_m``.
TILE_M = {"floor": 1.0, "walls": 1.5, "ceiling": 1.5, "trim": 0.8}
NEGATIVE = "text, watermark, people, perspective, furniture, objects"
_FIELDS = {"workspace", "name", "style", "floor", "walls", "ceiling", "door", "trim", "tile_m", "seed", "engine"}
_BUSY = ("queued", "running")
_ACTIVE: set[tuple[str, str, str]] = set()
_ACTIVE_LOCK = threading.Lock()

Call = Callable[[str, dict], dict]


# ---------------------------------------------------------------- the request


def _text(value: Any, what: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{what} is text of at most {limit} characters")
    return value.strip()


def parse(data: dict, spec: dict) -> dict:
    """The validated request: engine, style, the words of each surface, metres per repeat and the seed."""
    unknown = set(data) - _FIELDS
    if unknown:
        raise ValueError(f"unknown paint fields: {', '.join(sorted(unknown))}")
    engine = data.get("engine", "ai")
    if engine not in ("ai", "procedural"):
        raise ValueError('engine is "ai" (the image model, the default) or "procedural" (no model)')
    words = {}
    for surface in SURFACES:
        text = _text(data.get(surface), surface, 400)
        if text is None:
            continue
        if surface == "ceiling" and not spec.get("ceiling"):
            raise ValueError("this room has no ceiling; put it again with a ceiling to paint one")
        words[surface] = text
    tiles = data.get("tile_m", {})
    if not isinstance(tiles, dict) or set(tiles) - set(SURFACES):
        raise ValueError("tile_m is {floor, walls, ceiling, door, trim}: metres one repeat covers")
    for surface, value in tiles.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.1 <= float(value) <= 10:
            raise ValueError(f"tile_m.{surface} is metres (0.1-10)")
    seed = data.get("seed")
    if seed is not None and (type(seed) is not int or not 0 <= seed <= 2**31 - 1):
        raise ValueError("seed is an integer from 0")
    return {"engine": engine, "style": _text(data.get("style"), "style", 300) or "", "words": words,
            "tile_m": {key: float(value) for key, value in tiles.items()}, "seed": seed}


def _default_words(surface: str, spec: dict, metal: bool) -> str:
    if surface in ("floor", "walls", "ceiling"):
        return spec[surface]
    if surface == "door":
        return "a painted steel hangar door" if metal else "a wooden panelled door"
    return "painted skirting board and door frame"


def _prompt(surface: str, words: str, tile: float, style: str) -> str:
    scale = f"One repeat of this picture covers about {tile:g} m." if surface in TILING else ""
    if surface == "floor":
        text = f"A seamless tileable floor texture seen from straight above: {words}. {GROUND_STAGING}. {scale}"
    elif surface == "walls":
        text = f"A seamless tileable wall texture: {words}. {WALL_STAGING}. {scale}"
    elif surface == "ceiling":
        text = f"A seamless tileable ceiling texture: {words}. {CEILING_STAGING}. {scale}"
    elif surface == "trim":
        text = f"A seamless tileable texture of {words}, straight-on flat view, the pattern fills the picture edge to edge, no perspective, no people. {scale}"
    else:
        text = (f"A closed door seen straight on from the front: {words}. The door leaf fills the whole picture edge to edge, "
                "no frame, no wall, no floor, flat even lighting, no perspective, no people, no text.")
    return f"{text} Material look: {style}." if style else text


def plan_of(spec: dict, request: dict, name: str) -> dict:
    """Per surface: the prompt, size, metres per repeat and seed the image model is asked for."""
    metal = room_materials.pick("walls", request["words"].get("walls") or spec["walls"])["material"] in ("metal_panels", "riveted_steel")
    base = request["seed"] if request["seed"] is not None else spec.get("seed", int(hashlib.sha256(name.encode()).hexdigest()[:6], 16))
    plan = {}
    for index, surface in enumerate(present(spec)):
        tile = request["tile_m"].get(surface) or TILE_M.get(surface, 1.0)
        words = request["words"].get(surface) or _default_words(surface, spec, metal)
        plan[surface] = {"words": words, "prompt": _prompt(surface, words, tile, request["style"]), "size": SIZE[surface],
                         "tile_m": tile, "seed": (base + index) % 2**31}
    return plan


def fingerprint_of(spec: dict, style: str, plan: dict) -> str:
    """Identity of a paint request: the room, the style, each surface's words, size, scale and seed, and the model settings."""
    payload = {"spec": spec, "style": style, "plan": plan, "recipe": RECIPE, "geometry": GEOMETRY_VERSION,
               "materials": room_materials.VERSION, "defaults": defaults()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()[:20]


# ---------------------------------------------------------------- starting and reading


def paint(call: Call | None, workspace: str, root: Path, name: str, data: dict, *, inline: bool = False) -> dict:
    """Start (or find) the paint of a stored room. ``engine: "procedural"`` finishes here; ``ai`` runs in the background."""
    with room_store.LOCK:
        record = room_store.record_of(root, name)
        if record is None:
            raise ValueError(f"unknown room {name}")
        spec = record["spec"]
        request = parse(data, spec)
        if request["engine"] == "procedural":
            return _procedural(root, name, record, request)
        plan = plan_of(spec, request, name)
        fp = fingerprint_of(spec, request["style"], plan)
        paint_state = record.get("paint") or {}
        if paint_state.get("request") == fp:
            found = _existing(root, name, record, fp)
            if found:
                return found
        if call is None:
            raise ValueError('the image model is not reachable from this server; use engine "procedural"')
        _mark(root, name, record, {"status": "queued", "request": fp, "style": request["style"]})
        with _ACTIVE_LOCK:
            _ACTIVE.add((str(root), name, fp))
    job = (call, workspace, root, name, spec, plan, fp, request["style"])
    if inline:
        _work(*job)
    else:
        threading.Thread(target=_work, args=job, daemon=True).start()
    return status(root, name)


def _existing(root: Path, name: str, record: dict, fp: str) -> dict | None:
    state = record.get("paint") or {}
    if state.get("status") in _BUSY and (str(root), name, fp) in _ACTIVE:
        return status(root, name)
    if state.get("status") == "completed" and all((root / entry["file"]).is_file() for entry in room_store.surfaces_of(record).values()
                                                  if entry.get("source") == "ai"):
        return {**status(root, name), "cached": True}
    return None


def status(root: Path, name: str) -> dict:
    """The state of a room's look. A job a restart cut short reads ``interrupted``: call paint again."""
    record = room_store.record_of(root, name)
    if record is None:
        raise ValueError(f"unknown room {name}")
    state = copy.deepcopy(record.get("paint") or {"status": "not_painted", "look": room_store.look_of(record)})
    if state.get("status") in _BUSY and (str(root), name, state.get("request")) not in _ACTIVE:
        state["status"] = "interrupted"
        state["error"] = "the server restarted while this room was being painted; call scene3d.room.paint again"
    return {"name": name, "file": record.get("file"), **state, "surfaces": room_store.summary(record)}


def _mark(root: Path, name: str, record: dict, state: dict) -> None:
    """Record a queued paint. The look stays the one the room has now: a paint that has not finished changes nothing a shot sees."""
    library = room_store.read(root)
    library["rooms"][name] = {**record, "surfaces": room_store.surfaces_of(record),
                              "paint": {"look": room_store.look_of(record), **state, "warnings": []}}
    room_store.write(root, library)


def _procedural(root: Path, name: str, record: dict, request: dict) -> dict:
    """Give every surface the procedural look its words choose, undoing any painted picture. No model, no job."""
    spec = record["spec"]
    spoken = {**spec, **{key: request["words"][key] for key in ("floor", "walls", "ceiling") if key in request["words"]}}
    entries = default_entries(spoken, request["style"])
    for surface in ("door", "trim"):
        if surface in request["words"]:
            entries[surface] = {**entries[surface], **room_materials.pick(surface, request["words"][surface])}
    for surface, tile in request["tile_m"].items():
        if surface in entries:
            entries[surface]["tile_m"] = tile
    file = room_store.rebuild(root, name, spec, entries)
    library = room_store.read(root)
    library["rooms"][name] = {**record, "file": file, "surfaces": entries,
                              "paint": {"status": "completed", "engine": "procedural", "style": request["style"],
                                        "look": look_fingerprint(spec, entries), "warnings": []}}
    room_store.write(root, library)
    return status(root, name)


# ---------------------------------------------------------------- the job


def _work(call: Call, workspace: str, root: Path, name: str, spec: dict, plan: dict, fp: str, style: str) -> None:
    try:
        with room_store.LOCK:
            _set_state(root, name, fp, {"status": "running"})
        entries, warnings = _paint_all(call, workspace, root, name, plan, fp)
        _finish(root, name, spec, fp, style, entries, warnings)
    except Exception as error:  # noqa: BLE001 - a failed paint must leave the room as it was and say why
        with room_store.LOCK:
            _set_state(root, name, fp, {"status": "failed", "error": str(error)[:400]})
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard((str(root), name, fp))
        _drop_staging(root, name, fp)


def _staging_dir(root: Path, name: str, fp: str) -> Path:
    """Pictures of this request, away from the canonical ``rooms/<name>/<surface>.png`` a newer paint already published."""
    return root / "rooms" / name / f".paint-{fp}"


def _is_current(root: Path, name: str, fp: str) -> bool:
    record = room_store.record_of(root, name)
    return isinstance(record, dict) and (record.get("paint") or {}).get("request") == fp


def _drop_staging(root: Path, name: str, fp: str) -> None:
    folder = _staging_dir(root, name, fp)
    if not folder.is_dir():
        return
    for item in folder.iterdir():
        item.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        folder.rmdir()


def _publish(root: Path, name: str, painted: dict) -> dict:
    """Move each staged picture onto ``rooms/<name>/<surface>.png`` once this request still owns the room."""
    published = {}
    for surface, entry in painted.items():
        canonical = f"rooms/{name}/{surface}.png"
        source = root / entry["file"]
        if not source.is_file():
            raise FileNotFoundError(f"staged {surface} picture is missing")
        os.replace(source, root / canonical)
        published[surface] = {**entry, "file": canonical, "sha": file_sha(root / canonical)}
    return published


def _set_state(root: Path, name: str, fp: str, changes: dict) -> bool:
    """Change the paint state while this request is still the room's current one; False when a newer one replaced it."""
    library = room_store.read(root)
    record = (library.get("rooms") or {}).get(name)
    if not isinstance(record, dict) or (record.get("paint") or {}).get("request") != fp:
        return False
    record["paint"] = {**record["paint"], **changes}
    room_store.write(root, library)
    return True


def _paint_all(call: Call, workspace: str, root: Path, name: str, plan: dict, fp: str) -> tuple[dict, list]:
    """Ask the model for every surface at once (each its own job, one failing does not stop the others) and process each."""
    folder = root / "rooms" / name
    folder.mkdir(parents=True, exist_ok=True)
    tag = f"room-{fp[:14]}"
    requests = {surface: {"prompt": item["prompt"], "negative": NEGATIVE, "resolution": item["size"], "seed": item["seed"]}
                for surface, item in plan.items()}

    def make(surface: str):
        try:
            return generate_batch(call, workspace, [requests[surface]], f"{tag}-{surface}")[0], None
        except Exception as error:  # noqa: BLE001
            return None, str(error)[:300]

    with ThreadPoolExecutor(max_workers=max(1, len(requests))) as pool:
        made = dict(zip(requests, pool.map(make, requests)))
    if not _is_current(root, name, fp):
        return {}, []
    entries, warnings = {}, []
    for surface, (row, failure) in made.items():
        if row is None:
            warnings.append({"code": "paint_failed", "surface": surface, "error": failure})
            continue
        try:
            entry = _process(call, workspace, root, name, fp, surface, plan[surface], requests[surface], row,
                             f"{tag}-{surface}", warnings)
        except Exception as error:  # noqa: BLE001
            warnings.append({"code": "paint_failed", "surface": surface, "error": str(error)[:300]})
            continue
        if entry:
            entries[surface] = entry
    return entries, warnings


def _process(call, workspace, root, name, fp, surface, item, request, row, tag, warnings) -> dict | None:
    path = set_skins.asset_path(row["files"][0], root, workspace)
    with Image.open(path) as opened:
        picture = opened.convert("RGB")
    metrics: dict = {}
    if surface == "door":
        picture = ImageOps.fit(trim_border(picture), tuple(int(v) for v in item["size"].split("x")), method=Image.Resampling.LANCZOS)
    else:
        picture, ok, metrics = _tileable(picture, request, root, workspace, call, tag)
        if not ok:
            warnings.append({"code": "seam_fallback", "surface": surface, "seam_error": metrics["seam_error"],
                             "limit": defaults()["texture"]["seamMax"]})
            return None
    folder = _staging_dir(root, name, fp)
    folder.mkdir(parents=True, exist_ok=True)
    file = f"rooms/{name}/.paint-{fp}/{surface}.png"
    picture.save(root / file)
    return {"source": "ai", "file": file, "tile_m": item["tile_m"], "prompt": item["prompt"], "seed": item["seed"],
            "sha": file_sha(root / file), **({"metrics": metrics} if metrics else {})}


def blend_edges(picture: Image.Image) -> Image.Image:
    """Make a picture repeat by cross-fading it into itself shifted half a picture: the edges become the shifted copy's
    middle, which is continuous, and the middle stays as it was. The fade keeps the grain's strength (a plain average of two
    grains is smoother than either), so the blend does not read as a soft patch. Used only when healing fell short."""
    data = np.asarray(picture.convert("RGB"), dtype=np.float32)
    height, width = data.shape[:2]
    shifted = np.roll(data, (height // 2, width // 2), axis=(0, 1))
    mean = data.mean(axis=(0, 1), keepdims=True)

    def window(length: int) -> np.ndarray:
        ramp = 1 - np.abs(np.linspace(-1, 1, length))
        return ramp * ramp * (3 - 2 * ramp)

    weight = (window(height)[:, None] * window(width)[None, :])[..., None]
    mixed = (weight * (data - mean) + (1 - weight) * (shifted - mean)) / np.sqrt(weight**2 + (1 - weight) ** 2)
    return Image.fromarray(np.clip(mean + mixed, 0, 255).astype(np.uint8))


def _tileable(picture: Image.Image, request: dict, root: Path, workspace: str, call: Call, tag: str):
    """The picture, whether it now repeats, and what it took: healed by the model, then edge-blended, then give up."""
    limit = defaults()["texture"]["seamMax"]
    error = seam_error(picture)
    metrics: dict = {"seam_error": round(error, 3)}
    if error > limit:
        picture, error = set_skins._heal_texture(picture, request, root, workspace, call, tag)
        metrics["healed"] = True
    if error > limit:
        picture = blend_edges(picture)
        error = seam_error(picture)
        metrics["blended"] = True
    metrics["seam_error"] = round(error, 3)
    for leftover in (*root.glob(f"{tag}-guide-*.png"), *root.glob(f"{tag}-mask-*.png")):
        leftover.unlink(missing_ok=True)   # the heal's own guide and mask; the pictures the model made stay in the workspace
    return picture, error <= limit, metrics


def _finish(root: Path, name: str, spec: dict, fp: str, style: str, painted: dict, warnings: list) -> None:
    with room_store.LOCK:
        library = room_store.read(root)
        record = (library.get("rooms") or {}).get(name)
        if not isinstance(record, dict) or (record.get("paint") or {}).get("request") != fp:
            return
        if not painted:
            record["paint"] = {**record["paint"], "status": "failed", "warnings": warnings,
                               "error": "no surface could be painted; the room keeps its procedural materials"}
            room_store.write(root, library)
            return
        # Rebuild from the staged pictures so a superseded job never overwrites the published PNGs; then publish.
        record["file"] = room_store.rebuild(root, name, spec, {**room_store.surfaces_of(record), **painted})
        published = _publish(root, name, painted)
        entries = {**room_store.surfaces_of(record), **published}
        record["surfaces"] = entries
        record["paint"] = {**record["paint"], "status": "completed", "engine": "ai", "style": style, "warnings": warnings,
                           "look": look_fingerprint(spec, entries), "painted": sorted(published)}
        record["paint"].pop("error", None)
        room_store.write(root, library)

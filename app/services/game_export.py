"""Pack approved game assets into a generic ZIP (brief section 3.8).

Only assets with status ``approved`` are packed, from the files of their
approved attempt. Every other asset, and every approved file that could not
be packed, is listed in ``missing``. Files stream from the workspace into the
ZIP under sanitized, unique names. The ZIP is written beside its final name
and renamed into place, so a failed export leaves no partial file. Entries
are dated from ``generatedAt`` and added in a fixed order.

The WAV is copied byte for byte so the ``smpl`` loop chunk survives. OGG
files are copied when the attempt stored one. Otherwise each WAV is encoded
to OGG when an encoder is available; a music loop is encoded with
``LOOPSTART`` and ``LOOPLENGTH`` or not at all.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from services.game_library import GameConflictError, action_catalog
from services.game_sheet import pack_rows, uniform_cell

SCHEMA = "hocuspocus.game-pack"
_AUDIO_DIR = {
    "sfx": "audio/sfx",
    "music": "audio/music",
    "jingle": "audio/jingles",
    "voice": "audio/voice",
}
_STILL_DIR = {"sprite": "sprites", "ui": "ui", "tile": "tiles", "tileset": "tiles"}
_SKIP = {"character", "animation", "icon"}
_VARIANT = re.compile(r"^variant-\d+$")
_CHUNK = 1024 * 1024
_EPOCH = (1980, 1, 1, 0, 0, 0)


class _Pack:
    """The ZIP being written: names in use, files per asset id, and files that could not be read."""

    def __init__(self, root: Path, archive: zipfile.ZipFile, prefix: str, date_time: tuple) -> None:
        self.root = root.resolve()
        self.archive = archive
        self.prefix = prefix
        self.date_time = date_time
        self.taken: set[str] = set()
        self.bag: dict = {}
        self.lost: dict = {}

    def source(self, asset: dict, value) -> Path | None:
        """The workspace file ``value`` names. A name that does not resolve is recorded as lost."""
        if not isinstance(value, str) or not value:
            return None
        path = _resolve(self.root, value)
        if path is None:
            self.lose(asset, value)
        return path

    def lose(self, asset: dict, value) -> None:
        _note(self.lost, asset.get("id"), str(value))

    def write(self, relative: str, data, owners: list) -> str:
        """Add ``data`` (bytes, or a file to stream) under a free name like ``relative``; return that name."""
        name = self._claim(_entry_name(relative))
        info = zipfile.ZipInfo(f"{self.prefix}/{name}", date_time=self.date_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        if isinstance(data, Path):
            info.file_size = data.stat().st_size
            with data.open("rb") as handle, self.archive.open(info, "w") as target:
                shutil.copyfileobj(handle, target, _CHUNK)
        else:
            self.archive.writestr(info, data)
        for owner in owners:
            _note(self.bag, owner.get("id"), name)
        return name

    def _claim(self, relative: str) -> str:
        path = PurePosixPath(relative)
        name, index = relative, 2
        while name in self.taken:
            name = str(path.with_name(f"{path.stem}-{index}{path.suffix}"))
            index += 1
        self.taken.add(name)
        return name


def export_game(workspace_dir, game, *, workspace: str = "", now: str | None = None) -> dict:
    """Write ``game-exports/<id>-r<revision>.zip`` and append ``game["exports"]``.

    Returns ``{file, url, counts, missing}``. ``counts`` covers the packed
    assets. ``missing`` lists every unapproved asset with its status, and every
    approved asset that lost files with a ``problem`` and the ``files`` it
    names. Raises ``GameConflictError`` (``nothing_to_export``) when no
    approved asset has a file to pack; then no ZIP is written.
    """
    root = Path(workspace_dir)
    stamp = now or _stamp()
    assets = [item for item in (game.get("assets") or []) if isinstance(item, dict)]
    approved = [item for item in assets if item.get("status") == "approved"]
    revision = _revision(game)
    stem = f"{_safe_id(game.get('id'), 'game')}-r{revision}"
    relative = _zip_relative(root, stem)
    pack, packed = _write_zip(root, relative, stem, game, approved, stamp)
    counts = _counts(packed)
    _remember(game, relative, revision, counts, stamp)
    return {"file": relative, "url": _url(relative, workspace), "counts": counts, "missing": _missing(assets, pack)}


def _write_zip(root: Path, relative: str, stem: str, game: dict, approved: list, stamp: str) -> tuple:
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            pack = _Pack(root, archive, stem, _zip_time(stamp))
            _pack_approved(pack, game, approved)
            packed = [asset for asset in approved if pack.bag.get(asset.get("id"))]
            if not packed:
                raise GameConflictError("no approved asset has a file to export", code="nothing_to_export")
            _write_sidecars(pack, game, packed, stamp)
        os.replace(temporary, destination)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
    return pack, packed


def _pack_approved(pack: _Pack, game: dict, approved: list) -> None:
    loops: list = []
    _pack_characters(pack, game, approved)
    _pack_icons(pack, approved)
    for asset in approved:
        _dispatch(pack, asset, loops)
    pack.write("audio/loops.json", _json_bytes(loops), [])


def _dispatch(pack: _Pack, asset: dict, loops: list) -> None:
    kind = asset.get("kind")
    if kind in _SKIP:
        return
    if kind in _AUDIO_DIR:
        _pack_audio(pack, asset, loops)
        return
    directory = _STILL_DIR.get(kind)
    if directory:
        _pack_still(pack, asset, directory)
        return
    packer = _EXTRA.get(kind)
    if packer is not None:
        packer(pack, asset)


def _pack_characters(pack: _Pack, game: dict, approved: list) -> None:
    grouped: dict[str, list] = {}
    for asset in approved:
        if asset.get("kind") == "animation":
            grouped.setdefault(_anim_slug(asset), []).append(asset)
    characters = {
        _safe_id(asset.get("id"), "character"): asset
        for asset in approved
        if asset.get("kind") == "character"
    }
    order = [str(item.get("id") or "") for item in action_catalog()]
    for slug in dict.fromkeys([*characters, *grouped]):
        character = characters.get(slug)
        if character is not None:
            _copy_base(pack, character, slug)
        anims = sorted(grouped.get(slug) or [], key=lambda item: _action_rank(item, order))
        if anims:
            _pack_anim_sheet(pack, game, slug, character, anims)


def _pack_anim_sheet(pack: _Pack, game: dict, slug: str, character, anims: list) -> None:
    rows, frames, owners = _anim_rows(pack, anims)
    if not rows:
        return
    if character is not None:
        owners.append(character)
    cell = uniform_cell(frames, _grid(game.get("style") or {}), 1)
    mirror = (game.get("view") or "side") != "topdown"
    _write_sheet(pack, f"characters/{slug}/{slug}.png", pack_rows(rows, cell), owners, mirror=mirror)


def _anim_rows(pack: _Pack, anims: list) -> tuple[list, list, list]:
    rows: list = []
    frames: list = []
    owners: list = []
    used: set[str] = set()
    for asset in anims:
        images = _load_frames(pack, asset)
        if not images:
            continue
        rows.append({
            "name": _unique_tag(asset, used),
            "frames": images,
            "fps": _fps(asset),
            "loop": bool((asset.get("spec") or {}).get("loop")),
        })
        frames.extend(images)
        owners.append(asset)
    return rows, frames, owners


def _pack_icons(pack: _Pack, approved: list) -> None:
    groups: dict[str, list] = {}
    loose: list = []
    for asset in approved:
        if asset.get("kind") != "icon":
            continue
        label = _icon_label(asset)
        if not label:
            loose.append(asset)
        else:
            groups.setdefault(label, []).append(asset)
    for asset in loose:
        _pack_still(pack, asset, "icons")
    for label, icons in groups.items():
        if len(icons) == 1:
            _pack_still(pack, icons[0], "icons")
        else:
            _pack_icon_sheet(pack, label, icons)


def _pack_icon_sheet(pack: _Pack, label: str, icons: list) -> None:
    rows: list = []
    frames: list = []
    owners: list = []
    used: set[str] = set()
    for asset in icons:
        images = _load_frames(pack, asset)
        if not images:
            continue
        name = _unique(_safe_id(asset.get("id"), "icon"), used)
        rows.append({"name": name, "frames": [images[0]], "fps": 1, "loop": False})
        frames.append(images[0])
        owners.append(asset)
    if rows:
        _write_sheet(pack, f"icons/{label}.png", pack_rows(rows, uniform_cell(frames, 1, 1)), owners, mirror=False)


def _pack_item(pack: _Pack, asset: dict) -> None:
    files = _files(asset)
    if files.get("atlas") or files.get("frames"):
        _pack_one_row(pack, asset, "items", _load_frames(pack, asset))
        return
    _pack_still(pack, asset, "items")


def _pack_one_row(pack: _Pack, asset: dict, directory: str, frames: list) -> None:
    if not frames:
        return
    name = _safe_id(asset.get("id"), "item")
    packed = pack_rows([{
        "name": name,
        "frames": frames,
        "fps": _fps(asset),
        "loop": bool((asset.get("spec") or {}).get("loop")),
    }], uniform_cell(frames, 1, 1))
    _write_sheet(pack, f"{directory}/{name}.png", packed, [asset], mirror=False)


def _write_sheet(pack: _Pack, png_rel: str, packed: tuple, owners: list, *, mirror: bool) -> None:
    sheet, atlas = packed
    written = pack.write(png_rel, _png_bytes(sheet), owners)
    atlas["meta"]["image"] = PurePosixPath(written).name
    atlas["meta"]["mirror"] = mirror
    pack.write(str(PurePosixPath(written).with_suffix(".json")), _json_bytes(atlas), owners)


def _pack_background(pack: _Pack, asset: dict) -> None:
    value = _files(asset).get("parallax")
    spec_path = pack.source(asset, value)
    if spec_path is None:
        _pack_still(pack, asset, "backgrounds")
        return
    payload = _read_json(spec_path)
    layers = payload.get("layers") if payload is not None else None
    if not isinstance(layers, list):
        pack.lose(asset, value)
        return
    name = _safe_id(asset.get("id"), "background")
    kept = [row for row in (_pack_layer(pack, asset, spec_path, layer, name) for layer in layers) if row is not None]
    pack.write(f"backgrounds/{name}/parallax.json", _json_bytes({**payload, "layers": kept}), [asset])


def _pack_layer(pack: _Pack, asset: dict, spec_path: Path, layer, name: str) -> dict | None:
    """Pack one parallax layer; the returned row names the file as packed."""
    if not isinstance(layer, dict) or not isinstance(layer.get("file"), str):
        return None
    source = _resolve(pack.root, layer["file"], spec_path.parent)
    if source is None:
        pack.lose(asset, layer["file"])
        return None
    leaf = _safe_id(PurePosixPath(layer["file"].replace("\\", "/")).stem, "layer") + _suffix(source)
    written = pack.write(f"backgrounds/{name}/{leaf}", source, [asset])
    return {**layer, "file": PurePosixPath(written).name}


def _pack_vfx(pack: _Pack, asset: dict) -> None:
    files = _files(asset)
    png = pack.source(asset, files.get("main"))
    if png is None:
        return
    written = pack.write(f"vfx/{_safe_id(asset.get('id'), 'vfx')}.png", png, [asset])
    atlas_path = pack.source(asset, files.get("atlas"))
    if atlas_path is None:
        return
    atlas = _read_json(atlas_path)
    if atlas is None:
        pack.lose(asset, files.get("atlas"))
        return
    # The sheet was renamed; its atlas must name it. ``meta.pivot`` stays as the generator set it.
    meta = atlas.get("meta") if isinstance(atlas.get("meta"), dict) else {}
    atlas["meta"] = {**meta, "image": PurePosixPath(written).name}
    pack.write(str(PurePosixPath(written).with_suffix(".json")), _json_bytes(atlas), [asset])


def _pack_model(pack: _Pack, asset: dict) -> None:
    source = pack.source(asset, _model_source(asset))
    if source is not None:
        pack.write(f"models/{_safe_id(asset.get('id'), 'model')}.glb", source, [asset])


def _pack_audio(pack: _Pack, asset: dict, loops: list) -> None:
    name = _safe_id(asset.get("id"), "audio")
    directory = _AUDIO_DIR[str(asset.get("kind"))]
    entries = _audio_entries(asset)
    stored_ogg = any(suffix == ".ogg" and _resolve(pack.root, value) for _key, value, suffix in entries)
    loop_wav = None
    for key, value, suffix in entries:
        source = pack.source(asset, value)
        if source is None:
            continue
        relative = pack.write(f"{directory}/{_audio_name(name, key, suffix)}", source, [asset])
        if suffix != ".wav":
            continue
        loop_wav = loop_wav or (source, relative)
        if not stored_ogg:
            _add_ogg(pack, asset, source, relative)
    if loop_wav and asset.get("kind") == "music":
        loops.append(_loop_row(asset, *loop_wav))


def _add_ogg(pack: _Pack, asset: dict, wav: Path, wav_rel: str) -> None:
    loop = _loop_points(asset, wav) if asset.get("kind") == "music" else None
    with tempfile.TemporaryDirectory(prefix="game-pack-") as temporary:
        dest = Path(temporary) / "encoded.ogg"
        if _encode_ogg(wav, dest, loop):
            pack.write(str(PurePosixPath(wav_rel).with_suffix(".ogg")), dest, [asset])


def _pack_still(pack: _Pack, asset: dict, directory: str) -> None:
    files = _files(asset)
    source = pack.source(asset, files.get("main"))
    if source is None:
        return
    name = _safe_id(asset.get("id"), directory)
    written = PurePosixPath(pack.write(f"{directory}/{name}{_suffix(source)}", source, [asset]))
    for key in sorted(key for key in files if _VARIANT.match(str(key))):
        variant = pack.source(asset, files[key])
        if variant is not None:
            pack.write(f"{directory}/{written.stem}-{key}{_suffix(variant)}", variant, [asset])
    sidecar = pack.source(asset, _sidecar(asset))
    if sidecar is not None:
        pack.write(str(written.with_suffix(".json")), sidecar, [asset])


def _copy_base(pack: _Pack, character: dict, slug: str) -> None:
    # ``main`` is the approved sprite; ``rawKey`` is the unprocessed cut-out it was rendered from.
    files = _files(character)
    source = pack.source(character, files.get("main") or files.get("rawKey"))
    if source is not None:
        pack.write(f"characters/{slug}/{slug}-base.png", source, [character])


def _write_sidecars(pack: _Pack, game: dict, packed: list, stamp: str) -> None:
    pack.write("manifest.json", _json_bytes(_manifest(game, packed, pack.bag, stamp)), [])
    pack.write("provenance.json", _json_bytes(_provenance_doc(packed)), [])
    pack.write("README.txt", _readme(game, _models(packed)).encode("utf-8"), [])


def _manifest(game: dict, packed: list, bag: dict, stamp: str) -> dict:
    return {
        "schema": SCHEMA,
        "version": 1,
        "game": {
            "id": game.get("id"),
            "title": game.get("title"),
            "revision": _revision(game),
            "style": game.get("style") if isinstance(game.get("style"), dict) else {},
        },
        "assets": [
            {
                "id": asset.get("id"),
                "kind": asset.get("kind"),
                "name": asset.get("name"),
                "files": list(bag.get(asset.get("id")) or []),
            }
            for asset in packed
        ],
        "generatedAt": stamp,
    }


def _provenance_doc(packed: list) -> dict:
    return {
        "assets": [
            {
                "id": asset.get("id"),
                "kind": asset.get("kind"),
                "attemptId": asset.get("approvedAttemptId"),
                "provenance": _provenance(asset),
            }
            for asset in packed
        ]
    }


def _readme(game: dict, models: list[str]) -> str:
    title = game.get("title") or game.get("id") or "game"
    listed = ", ".join(models) if models else ""
    models_es = listed or "no hay llamadas a modelos registradas en la procedencia"
    models_en = listed or "no model calls are recorded in the provenance"
    return (
        f"Paquete de recursos HocusPocus / HocusPocus game pack\n"
        f"Juego / Game: {title} ({game.get('id')}) r{_revision(game)}\n\n"
        "Cómo usar / How to use\n"
        "- manifest.json lista los archivos de cada recurso.\n"
        "- manifest.json lists the files of each asset.\n"
        "- La hoja de un personaje está en characters/<id>/<id>.png con el atlas <id>.json. Una fila por animación.\n"
        "- A character sheet lives in characters/<id>/<id>.png with the atlas <id>.json. One row per animation.\n"
        "- Cada atlas da su pivote en meta.pivot: el centro inferior de la celda en personajes, objetos e iconos,\n"
        "  y el centro de la celda en los efectos de vfx/.\n"
        "- Every atlas gives its pivot in meta.pivot: the bottom center of the cell for characters, items and icons,\n"
        "  and the center of the cell for the effects in vfx/.\n"
        "- En vista lateral el personaje mira a la derecha. Si meta.mirror es true, la izquierda es el espejo.\n"
        "- In side view the character faces right. When meta.mirror is true, left is the mirrored sprite.\n"
        "- frameTags nombra cada animación. from y to son índices inclusivos.\n"
        "- frameTags names each animation. from and to are inclusive indices.\n"
        "- Los bucles de audio están en audio/loops.json. loopEnd es inclusivo, como en el bloque smpl del WAV.\n"
        "- Audio loops are listed in audio/loops.json. loopEnd is inclusive, as in the WAV smpl chunk.\n"
        "- El OGG de una música lleva LOOPSTART y LOOPLENGTH (loopEnd - loopStart + 1).\n"
        "- A music OGG carries LOOPSTART and LOOPLENGTH (loopEnd - loopStart + 1).\n\n"
        "Declaración de uso de IA / AI use statement\n"
        "Este paquete se generó en local con HocusPocus. "
        f"Modelos según provenance.json: {models_es}.\n"
        "This pack was generated locally with HocusPocus. "
        f"Models recorded in provenance.json: {models_en}.\n"
    )


def _remember(game: dict, relative: str, revision: int, counts: dict, stamp: str) -> None:
    exports = game.get("exports")
    if not isinstance(exports, list):
        exports = []
        game["exports"] = exports
    exports.append({
        "id": f"e{len(exports) + 1}",
        "revision": revision,
        "file": relative,
        "createdAt": stamp,
        "counts": counts,
    })


def _loop_row(asset: dict, wav: Path, relative: str) -> dict:
    metrics = _metrics(asset)
    start, end = _loop_points(asset, wav)
    return {
        "file": relative,
        "loopStart": start,
        "loopEnd": end,
        "bpm": metrics.get("bpm"),
        "lufs": metrics.get("lufs"),
    }


def _loop_points(asset: dict, wav: Path) -> tuple[int, int]:
    """``(start, end)`` with an inclusive end, as the ``smpl`` chunk stores it; the whole file when unknown."""
    metrics = _metrics(asset)
    start = max(0, _int(metrics.get("loopStart"), 0))
    end = _int(metrics.get("loopEnd"), -1)
    if end < start:
        end = max(start, _frame_count(wav) - 1)
    return start, end


def _frame_count(wav: Path) -> int:
    try:
        import soundfile as sf

        return int(sf.info(str(wav)).frames)
    except (OSError, RuntimeError, ValueError, TypeError):
        return 0


def _load_frames(pack: _Pack, asset: dict) -> list:
    files = _files(asset)
    listed = files.get("frames")
    if isinstance(listed, list) and listed:
        return [image for image in (_open_rgba(pack, asset, item) for item in listed) if image is not None]
    if isinstance(files.get("atlas"), str) and isinstance(files.get("main"), str):
        sliced = _slice_atlas(pack, asset, files["main"], files["atlas"])
        if sliced:
            return sliced
    image = _open_rgba(pack, asset, files.get("main"))
    return [image] if image is not None else []


def _slice_atlas(pack: _Pack, asset: dict, main: str, atlas_path: str) -> list:
    spec_path = pack.source(asset, atlas_path)
    payload = _read_json(spec_path) if spec_path is not None else None
    frames = payload.get("frames") if payload is not None else None
    if not isinstance(frames, dict):
        return []
    sheet = _open_rgba(pack, asset, main)
    if sheet is None:
        return []
    boxes = [box for box in (_box(info) for info in frames.values()) if box is not None]
    return [sheet.crop(box) for box in boxes]


def _box(info) -> tuple[int, int, int, int] | None:
    rect = info.get("frame") if isinstance(info, dict) else None
    if not isinstance(rect, dict):
        return None
    width, height = _int(rect.get("w"), 0), _int(rect.get("h"), 0)
    if width <= 0 or height <= 0:
        return None
    x, y = _int(rect.get("x"), 0), _int(rect.get("y"), 0)
    return (x, y, x + width, y + height)


def _open_rgba(pack: _Pack, asset: dict, value):
    path = pack.source(asset, value)
    if path is None:
        return None
    from PIL import Image

    try:
        with Image.open(path) as opened:
            return opened.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError):
        pack.lose(asset, value)
        return None


def _audio_entries(asset: dict) -> list[tuple[str, str, str]]:
    rows = []
    for key, value in _files(asset).items():
        if not isinstance(value, str):
            continue
        suffix = Path(value).suffix.lower()
        if suffix in {".wav", ".ogg"}:
            rows.append((str(key), value, suffix))
    return rows


def _audio_name(asset_id: str, key: str, suffix: str) -> str:
    if key in {"wav", "ogg"}:
        return f"{asset_id}{suffix}"
    return f"{asset_id}-{_safe_id(key, 'take')}{suffix}"


def _model_source(asset: dict):
    files = _files(asset)
    for key in ("rig", "model", "main"):
        value = files.get(key)
        if isinstance(value, str) and value.lower().endswith(".glb"):
            return value
    return None


def _sidecar(asset: dict):
    files = _files(asset)
    for key in ("nine", "atlas", "tiles", "json"):
        if isinstance(files.get(key), str):
            return files[key]
    return None


def _encode_ogg(wav_path: Path, dest: Path, loop: tuple[int, int] | None) -> bool:
    """Encode ``wav_path``. A loop goes through ffmpeg so the OGG carries ``LOOPSTART``/``LOOPLENGTH``."""
    try:
        import soundfile as sf

        audio, sample_rate = sf.read(str(wav_path), always_2d=False, dtype="float32")
        if loop is None:
            sf.write(str(dest), audio, int(sample_rate), format="OGG", subtype="VORBIS")
        else:
            from services.game_audio import write_ogg_loop

            # A warning means it wrote a WAV fallback instead; the pack already has the WAV.
            if write_ogg_loop(dest, audio, int(sample_rate), loop[0], loop[1] - loop[0] + 1) is not None:
                return False
    except (OSError, RuntimeError, ValueError, TypeError):
        return False
    return dest.is_file() and dest.stat().st_size > 0


def _attempt(asset: dict) -> dict:
    """The approved attempt, or ``{}`` when it is absent, failed or rejected."""
    wanted = asset.get("approvedAttemptId")
    for attempt in asset.get("attempts") or []:
        if wanted and isinstance(attempt, dict) and attempt.get("id") == wanted:
            usable = attempt.get("status", "ok") == "ok" and attempt.get("decision") != "rejected"
            return attempt if usable else {}
    return {}


def _files(asset: dict) -> dict:
    files = _attempt(asset).get("files")
    return files if isinstance(files, dict) else {}


def _metrics(asset: dict) -> dict:
    metrics = _attempt(asset).get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _provenance(asset: dict) -> dict:
    raw = _attempt(asset).get("provenance")
    return raw if isinstance(raw, dict) else {"steps": []}


def _models(packed: list) -> list[str]:
    found: list[str] = []
    for asset in packed:
        steps = _provenance(asset).get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            model = step.get("model") if isinstance(step, dict) else None
            if isinstance(model, str) and model and model not in found:
                found.append(model)
    return found


def _icon_label(asset: dict) -> str:
    tags = asset.get("tags") if isinstance(asset.get("tags"), list) else []
    if not tags:
        return ""
    return _safe_id(tags[0], "")


def _anim_slug(asset: dict) -> str:
    raw = (asset.get("spec") or {}).get("character")
    if isinstance(raw, str) and raw.strip():
        return _safe_id(raw, "character")
    return _safe_id(asset.get("id"), "character")


def _unique_tag(asset: dict, used: set[str]) -> str:
    """The action name; a repeated action takes the asset id, then a number (``pack_rows`` rejects repeats)."""
    action = str((asset.get("spec") or {}).get("action") or asset.get("id") or "anim")
    wanted = action if action not in used else f"{action}-{_safe_id(asset.get('id'), 'anim')}"
    return _unique(wanted, used)


def _unique(wanted: str, used: set[str]) -> str:
    name, index = wanted, 2
    while name in used:
        name = f"{wanted}-{index}"
        index += 1
    used.add(name)
    return name


def _action_rank(asset: dict, order: list[str]) -> tuple:
    action = str((asset.get("spec") or {}).get("action") or "")
    index = order.index(action) if action in order else len(order)
    return (index, str(asset.get("id") or ""))


def _fps(asset: dict) -> float:
    try:
        rate = float((asset.get("spec") or {}).get("fps") or 8)
    except (TypeError, ValueError):
        return 8.0
    return rate if rate > 0 else 8.0


def _grid(style: dict) -> int:
    pixel = style.get("pixel") if isinstance(style.get("pixel"), dict) else {}
    if not pixel.get("enabled"):
        return 1
    return max(1, _int(pixel.get("tile"), 1))


def _missing(assets: list, pack: _Pack) -> list[dict]:
    rows = []
    for asset in assets:
        row = {"id": asset.get("id"), "kind": asset.get("kind"), "status": asset.get("status")}
        if asset.get("status") != "approved":
            rows.append(row)
            continue
        lost = list(pack.lost.get(asset.get("id")) or [])
        if not _attempt(asset):
            rows.append({**row, "problem": "no_approved_attempt", "files": lost})
        elif not pack.bag.get(asset.get("id")):
            rows.append({**row, "problem": "not_packed", "files": lost})
        elif lost:
            rows.append({**row, "problem": "files_missing", "files": lost})
    return rows


def _counts(packed: list) -> dict:
    counts: dict = {}
    for asset in packed:
        kind = str(asset.get("kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    counts["total"] = len(packed)
    return counts


def _zip_relative(root: Path, stem: str) -> str:
    folder = root / "game-exports"
    if not (folder / f"{stem}.zip").exists():
        return f"game-exports/{stem}.zip"
    index = 2
    while (folder / f"{stem}-{index}.zip").exists():
        index += 1
    return f"game-exports/{stem}-{index}.zip"


def _zip_time(stamp: str) -> tuple:
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return _EPOCH
    if moment.year < 1980:
        return _EPOCH
    return (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second)


def _entry_name(relative: str) -> str:
    """``relative`` as a ZIP name: ``/`` separated, no ``..``, no absolute path, no backslash."""
    parts = [_entry_part(part) for part in relative.replace("\\", "/").split("/") if part]
    return "/".join(parts) or "file"


def _entry_part(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", part).strip("-.") or "file"


def _note(bag: dict, asset_id, relative: str) -> None:
    if not asset_id:
        return
    paths = bag.setdefault(asset_id, [])
    if relative not in paths:
        paths.append(relative)


def _suffix(path: Path) -> str:
    return path.suffix.lower() or ".png"


def _png_bytes(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _json_bytes(payload) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve(root: Path, relative, base: Path | None = None) -> Path | None:
    """The file ``relative`` names under ``base`` (default ``root``), if it is inside ``root``.

    ``root`` must be resolved. Stored paths may use ``\\`` (written on Windows).
    """
    if not isinstance(relative, str) or not relative:
        return None
    text = relative.replace("\\", "/")
    if text.startswith("/"):
        return None
    try:
        candidate = ((base or root) / text).resolve()
    except (OSError, RuntimeError):
        return None
    if not _inside(root, candidate) or not candidate.is_file():
        return None
    return candidate


def _inside(root: Path, candidate: Path) -> bool:
    return candidate == root or root in candidate.parents


def _safe_id(value, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").lower()).strip("-")
    return text or fallback


def _url(relative: str, workspace: str) -> str:
    url = "/api/v1/file/" + quote(relative, safe="/")
    if workspace:
        url += "?workspace=" + quote(str(workspace), safe="")
    return url


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _revision(game: dict) -> int:
    return _int(game.get("revision"), 0)


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_EXTRA = {
    "item": _pack_item,
    "background": _pack_background,
    "vfx": _pack_vfx,
    "model3d": _pack_model,
    "character3d": _pack_model,
}

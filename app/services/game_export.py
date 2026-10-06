"""Pack approved game assets into a generic ZIP (brief section 3.8).

The WAV is copied byte for byte so the ``smpl`` loop chunk survives.
OGG files are copied when the attempt stored one, and encoded from the WAV
when the encoder is available and no OGG was stored.
"""
from __future__ import annotations

import json
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from services.game_library import action_catalog
from services.game_sheet import pack_rows, uniform_cell

SCHEMA = "hocuspocus.game-pack"
_AUDIO_DIR = {
    "sfx": "audio/sfx",
    "music": "audio/music",
    "jingle": "audio/jingles",
    "voice": "audio/voice",
}
_STILL_DIR = {"sprite": "sprites", "ui": "ui", "tile": "tiles", "tileset": "tiles"}
_EXTRA = {}
_SKIP = {"character", "animation", "icon"}


def export_game(workspace_dir, game, *, workspace: str = "", now: str | None = None) -> dict:
    """Write ``game-exports/<id>-r<revision>.zip`` and append ``game["exports"]``.

    Returns ``{file, url, counts, missing}``. Approved assets are packed.
    Every other asset is listed in ``missing`` with its status.
    """
    root = Path(workspace_dir)
    stamp = now or _stamp()
    assets = [item for item in (game.get("assets") or []) if isinstance(item, dict)]
    approved = [item for item in assets if item.get("status") == "approved"]
    revision = _revision(game)
    game_id = _safe_id(game.get("id"), "game")
    relative = _zip_relative(root, game_id, revision)
    counts = _counts(approved)
    with tempfile.TemporaryDirectory(prefix="game-pack-") as temporary:
        folder = Path(temporary) / f"{game_id}-r{revision}"
        bag = _pack_approved(root, folder, game, approved)
        _write_sidecars(folder, game, approved, bag, stamp)
        _zip_folder(folder, root / relative)
    _remember(game, relative, revision, counts, stamp)
    return {"file": relative, "url": _url(relative, workspace), "counts": counts, "missing": _missing(assets)}


def _pack_approved(root: Path, folder: Path, game: dict, approved: list) -> dict:
    bag: dict = {}
    loops: list = []
    _pack_characters(root, folder, game, approved, bag)
    _pack_icons(root, folder, approved, bag)
    for asset in approved:
        _dispatch(root, folder, asset, bag, loops)
    folder.joinpath("audio").mkdir(parents=True, exist_ok=True)
    _save_json(loops, folder / "audio" / "loops.json")
    return bag


def _dispatch(root: Path, folder: Path, asset: dict, bag: dict, loops: list) -> None:
    kind = asset.get("kind")
    if kind in _SKIP:
        return
    if kind in _AUDIO_DIR:
        _pack_audio(root, folder, asset, bag, loops)
        return
    directory = _STILL_DIR.get(kind)
    if directory:
        _pack_still(root, folder, asset, bag, directory)
        return
    packer = _EXTRA.get(kind)
    if packer is not None:
        packer(root, folder, asset, bag)


def _pack_characters(root: Path, folder: Path, game: dict, approved: list, bag: dict) -> None:
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
        if not slug:
            continue
        character = characters.get(slug)
        if character is not None:
            _copy_base(root, folder, character, bag, slug)
        anims = sorted(grouped.get(slug) or [], key=lambda item: _action_rank(item, order))
        if anims:
            _pack_anim_sheet(root, folder, game, slug, character, anims, bag)


def _pack_anim_sheet(root, folder, game, slug, character, anims, bag) -> None:
    rows, frames = _anim_rows(root, anims)
    if not rows:
        return
    cell = uniform_cell(frames, _grid(game.get("style") or {}), 1)
    sheet, atlas = pack_rows(rows, cell)
    atlas["meta"]["image"] = f"{slug}.png"
    atlas["meta"]["mirror"] = (game.get("view") or "side") != "topdown"
    png_rel = f"characters/{slug}/{slug}.png"
    json_rel = f"characters/{slug}/{slug}.json"
    _save_image(sheet, folder / png_rel)
    _save_json(atlas, folder / json_rel)
    owners = [asset.get("id") for asset in anims]
    if character is not None:
        owners.append(character.get("id"))
    for asset_id in owners:
        _note(bag, asset_id, png_rel)
        _note(bag, asset_id, json_rel)


def _anim_rows(root: Path, anims: list) -> tuple[list, list]:
    rows: list = []
    frames: list = []
    used: set[str] = set()
    for asset in anims:
        images = _load_frames(root, asset)
        if not images:
            continue
        rows.append({
            "name": _unique_tag(asset, used),
            "frames": images,
            "fps": _fps(asset),
            "loop": bool((asset.get("spec") or {}).get("loop")),
        })
        frames.extend(images)
    return rows, frames


def _pack_icons(root: Path, folder: Path, approved: list, bag: dict) -> None:
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
        _pack_still(root, folder, asset, bag, "icons")
    for label, icons in groups.items():
        if len(icons) == 1:
            _pack_still(root, folder, icons[0], bag, "icons")
        else:
            _pack_icon_sheet(root, folder, label, icons, bag)


def _pack_icon_sheet(root, folder, label, icons, bag) -> None:
    rows: list = []
    frames: list = []
    for asset in icons:
        images = _load_frames(root, asset)
        if not images:
            continue
        rows.append({"name": _safe_id(asset.get("id"), "icon"), "frames": [images[0]], "fps": 1, "loop": False})
        frames.append(images[0])
    if not rows:
        return
    sheet, atlas = pack_rows(rows, uniform_cell(frames, 1, 1))
    atlas["meta"]["image"] = f"{label}.png"
    atlas["meta"]["mirror"] = False
    png_rel = f"icons/{label}.png"
    json_rel = f"icons/{label}.json"
    _save_image(sheet, folder / png_rel)
    _save_json(atlas, folder / json_rel)
    for asset in icons:
        _note(bag, asset.get("id"), png_rel)
        _note(bag, asset.get("id"), json_rel)


def _pack_item(root, folder, asset, bag) -> None:
    frames = _load_frames(root, asset)
    if _files(asset).get("atlas") or len(frames) > 1:
        _pack_one_row(folder, asset, bag, "items", frames)
        return
    _pack_still(root, folder, asset, bag, "items")


def _pack_one_row(folder, asset, bag, directory: str, frames: list) -> None:
    if not frames:
        return
    name = _safe_id(asset.get("id"), "item")
    sheet, atlas = pack_rows([{
        "name": name,
        "frames": frames,
        "fps": _fps(asset),
        "loop": bool((asset.get("spec") or {}).get("loop")),
    }], uniform_cell(frames, 1, 1))
    atlas["meta"]["image"] = f"{name}.png"
    png_rel = f"{directory}/{name}.png"
    json_rel = f"{directory}/{name}.json"
    _save_image(sheet, folder / png_rel)
    _save_json(atlas, folder / json_rel)
    _note(bag, asset.get("id"), png_rel)
    _note(bag, asset.get("id"), json_rel)


def _pack_background(root, folder, asset, bag) -> None:
    spec_path = _resolve(root, _files(asset).get("parallax"))
    if spec_path is None:
        _pack_still(root, folder, asset, bag, "backgrounds")
        return
    payload = _read_json(spec_path)
    layers = payload.get("layers") if isinstance(payload, dict) else None
    if not isinstance(layers, list):
        return
    name = _safe_id(asset.get("id"), "background")
    for layer in layers:
        _copy_layer(root, folder, asset, bag, spec_path, layer, name)
    relative = f"backgrounds/{name}/parallax.json"
    _copy(spec_path, folder / relative)
    _note(bag, asset.get("id"), relative)


def _copy_layer(root, folder, asset, bag, spec_path: Path, layer, name: str) -> None:
    if not isinstance(layer, dict) or not isinstance(layer.get("file"), str):
        return
    source = (spec_path.parent / layer["file"]).resolve()
    if not _inside(root, source) or not source.is_file():
        return
    leaf = _safe_id(Path(layer["file"]).stem, "layer") + source.suffix.lower()
    relative = f"backgrounds/{name}/{leaf}"
    _copy(source, folder / relative)
    _note(bag, asset.get("id"), relative)


def _pack_vfx(root, folder, asset, bag) -> None:
    name = _safe_id(asset.get("id"), "vfx")
    png = _resolve(root, _files(asset).get("main"))
    if png is None:
        return
    png_rel = f"vfx/{name}.png"
    _copy(png, folder / png_rel)
    _note(bag, asset.get("id"), png_rel)
    atlas = _resolve(root, _files(asset).get("atlas"))
    if atlas is None:
        return
    json_rel = f"vfx/{name}.json"
    _copy(atlas, folder / json_rel)
    _note(bag, asset.get("id"), json_rel)


def _pack_model(root, folder, asset, bag) -> None:
    source = _resolve(root, _model_source(asset))
    if source is None:
        return
    relative = f"models/{_safe_id(asset.get('id'), 'model')}.glb"
    _copy(source, folder / relative)
    _note(bag, asset.get("id"), relative)


def _pack_audio(root, folder, asset, bag, loops: list) -> None:
    name = _safe_id(asset.get("id"), "audio")
    directory = _AUDIO_DIR[str(asset.get("kind"))]
    wav_path = None
    wav_rel = ""
    saw_ogg = False
    for key, value, suffix in _audio_entries(asset):
        source = _resolve(root, value)
        if source is None:
            continue
        relative = f"{directory}/{_audio_name(name, key, suffix)}"
        _copy(source, folder / relative)
        _note(bag, asset.get("id"), relative)
        if suffix == ".wav" and wav_path is None:
            wav_path = folder / relative
            wav_rel = relative
        if suffix == ".ogg":
            saw_ogg = True
    if wav_path is not None and not saw_ogg:
        ogg_rel = f"{directory}/{Path(wav_rel).stem}.ogg"
        if _encode_ogg(wav_path, folder / ogg_rel):
            _note(bag, asset.get("id"), ogg_rel)
    if wav_rel and asset.get("kind") == "music":
        loops.append(_loop_row(asset, wav_rel))


def _pack_still(root, folder, asset, bag, directory: str) -> None:
    source = _resolve(root, _files(asset).get("main"))
    if source is None:
        return
    name = _safe_id(asset.get("id"), directory)
    relative = f"{directory}/{name}.png"
    _copy(source, folder / relative)
    _note(bag, asset.get("id"), relative)
    sidecar = _resolve(root, _sidecar(asset))
    if sidecar is None:
        return
    json_rel = f"{directory}/{name}.json"
    _copy(sidecar, folder / json_rel)
    _note(bag, asset.get("id"), json_rel)


def _copy_base(root, folder, character, bag, slug: str) -> None:
    files = _files(character)
    source = _resolve(root, files.get("rawKey") or files.get("main"))
    if source is None:
        return
    relative = f"characters/{slug}/{slug}-base.png"
    _copy(source, folder / relative)
    _note(bag, character.get("id"), relative)


def _write_sidecars(folder: Path, game: dict, approved: list, bag: dict, stamp: str) -> None:
    models = _models(approved)
    _save_json(_manifest(game, approved, bag, stamp), folder / "manifest.json")
    _save_json(_provenance_doc(approved), folder / "provenance.json")
    (folder / "README.txt").write_text(_readme(game, models), encoding="utf-8")


def _manifest(game: dict, approved: list, bag: dict, stamp: str) -> dict:
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
            for asset in approved
        ],
        "generatedAt": stamp,
    }


def _provenance_doc(approved: list) -> dict:
    return {
        "assets": [
            {
                "id": asset.get("id"),
                "kind": asset.get("kind"),
                "attemptId": asset.get("approvedAttemptId"),
                "provenance": _provenance(asset),
            }
            for asset in approved
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
        "- La hoja de un personaje está en characters/<id>/<id>.png con el atlas <id>.json.\n"
        "- A character sheet lives in characters/<id>/<id>.png with the atlas <id>.json.\n"
        "- El pivote es el centro inferior de la celda (meta.pivot). Una fila por animación.\n"
        "- The pivot is the bottom center of the cell (meta.pivot). One row per animation.\n"
        "- En vista lateral el personaje mira a la derecha. La izquierda es el espejo (meta.mirror).\n"
        "- In side view the character faces right. Left is the mirrored sprite (meta.mirror).\n"
        "- frameTags nombra cada animación. from y to son índices inclusivos.\n"
        "- frameTags names each animation. from and to are inclusive indices.\n"
        "- Los bucles de audio están en audio/loops.json. El WAV conserva el bloque smpl.\n"
        "- Audio loops are listed in audio/loops.json. The WAV keeps its smpl chunk.\n"
        "- El OGG, cuando existe, lleva LOOPSTART y LOOPLENGTH.\n"
        "- The OGG file, when present, carries LOOPSTART and LOOPLENGTH.\n\n"
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


def _loop_row(asset: dict, relative: str) -> dict:
    metrics = _metrics(asset)
    return {
        "file": relative,
        "loopStart": _int(metrics.get("loopStart"), 0),
        "loopEnd": _int(metrics.get("loopEnd"), 0),
        "bpm": metrics.get("bpm"),
        "lufs": metrics.get("lufs"),
    }


def _load_frames(root: Path, asset: dict) -> list:
    files = _files(asset)
    listed = files.get("frames")
    if isinstance(listed, list) and listed:
        return [image for image in (_open_rgba(root, item) for item in listed) if image is not None]
    if isinstance(files.get("atlas"), str) and isinstance(files.get("main"), str):
        sliced = _slice_atlas(root, files["main"], files["atlas"])
        if sliced:
            return sliced
    image = _open_rgba(root, files.get("main"))
    return [image] if image is not None else []


def _slice_atlas(root: Path, main: str, atlas_path: str) -> list:
    sheet_path = _resolve(root, main)
    spec_path = _resolve(root, atlas_path)
    if sheet_path is None or spec_path is None:
        return []
    payload = _read_json(spec_path)
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if not isinstance(frames, dict):
        return []
    from PIL import Image

    with Image.open(sheet_path) as opened:
        sheet = opened.convert("RGBA")
    crops = []
    for info in frames.values():
        rect = info.get("frame") if isinstance(info, dict) else None
        if not isinstance(rect, dict):
            continue
        width, height = int(rect.get("w") or 0), int(rect.get("h") or 0)
        if width <= 0 or height <= 0:
            continue
        x, y = int(rect.get("x") or 0), int(rect.get("y") or 0)
        crops.append(sheet.crop((x, y, x + width, y + height)))
    return crops


def _open_rgba(root: Path, relative) -> object | None:
    path = _resolve(root, relative)
    if path is None:
        return None
    from PIL import Image

    with Image.open(path) as opened:
        return opened.convert("RGBA")


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
    return f"{asset_id}-{key}{suffix}"


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


def _encode_ogg(wav_path: Path, dest: Path) -> bool:
    try:
        import soundfile as sf

        audio, sample_rate = sf.read(str(wav_path), always_2d=False)
        dest.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(dest), audio, int(sample_rate), format="OGG", subtype="VORBIS")
    except (OSError, RuntimeError, ValueError, TypeError):
        return False
    return dest.is_file() and dest.stat().st_size > 0


def _attempt(asset: dict) -> dict:
    wanted = asset.get("approvedAttemptId")
    for attempt in asset.get("attempts") or []:
        if isinstance(attempt, dict) and attempt.get("id") == wanted:
            return attempt
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


def _models(approved: list) -> list[str]:
    found: list[str] = []
    for asset in approved:
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
    action = str((asset.get("spec") or {}).get("action") or asset.get("id") or "anim")
    name = action
    if name in used:
        name = f"{action}-{_safe_id(asset.get('id'), 'anim')}"
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


def _missing(assets: list) -> list[dict]:
    return [
        {"id": asset.get("id"), "kind": asset.get("kind"), "status": asset.get("status")}
        for asset in assets
        if asset.get("status") != "approved"
    ]


def _counts(approved: list) -> dict:
    counts: dict = {}
    for asset in approved:
        kind = str(asset.get("kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    counts["total"] = len(approved)
    return counts


def _zip_relative(root: Path, game_id: str, revision: int) -> str:
    stem = f"{game_id}-r{revision}"
    folder = root / "game-exports"
    if not (folder / f"{stem}.zip").exists():
        return f"game-exports/{stem}.zip"
    index = 2
    while (folder / f"{stem}-{index}.zip").exists():
        index += 1
    return f"game-exports/{stem}-{index}.zip"


def _zip_folder(folder: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(folder.parent).as_posix())


def _note(bag: dict, asset_id, relative: str) -> None:
    if not asset_id:
        return
    paths = bag.setdefault(asset_id, [])
    if relative not in paths:
        paths.append(relative)


def _copy(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(source.read_bytes())


def _save_image(image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def _save_json(payload, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve(workspace: Path, relative) -> Path | None:
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")):
        return None
    root = workspace.resolve()
    candidate = (root / relative).resolve()
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


_EXTRA.update({
    "item": _pack_item,
    "background": _pack_background,
    "vfx": _pack_vfx,
    "model3d": _pack_model,
    "character3d": _pack_model,
})

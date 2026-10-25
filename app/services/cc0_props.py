"""CC0 furniture for interior molds.

The GLB bytes are not in git. ``app/resources/cc0_props.json`` names each file,
its SHA-256 and its real size. The asset library installs them as one optional
collection, ``cc0-furniture``. A mold keeps its boxes until that collection is
installed and the set asks for library furniture. Opening or instantiating a
stage in a workspace copies each GLB to ``cc0/<sha>.glb`` and stores that file's
URL, so the scene still exports after the pack is removed. Export does the same
copy for a document that still names ``/api/v1/library/files/``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

APP_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = APP_ROOT / "resources" / "cc0_props.json"
PACK = "cc0-furniture"
SCHEMA = "hocuspocus.cc0-props"
MODEL_HEIGHT = 1.7
NOT_INSTALLED = "CC0 furniture is not installed. Install the cc0-furniture library collection first."
# Kenney meshes face the file's +z. three.js yaw then turns that face onto the block's +z front.
_YAW = {"+z": 0.0, "-z": math.pi, "+x": -math.pi / 2, "-x": math.pi / 2}
_BAR_MOLDS = frozenset({"bar", "mostrador"})
_BAR_BLOCKS = frozenset({"bar", "mostrador"})
# Mold kind -> manifest id. bedside is the hospital name for a nightstand.
_KIND_ID = {
    "sofa": "sofa", "armchair": "armchair", "chair": "chair", "table": "table", "desk": "desk",
    "bed": "bed", "wardrobe": "wardrobe", "shelf": "shelf", "stove": "stove", "fridge": "fridge",
    "lamp": "lamp", "plant": "plant", "tv": "tv", "bench": "bench", "cabinet": "cabinet",
    "rug": "rug", "stool": "stool", "nightstand": "nightstand", "bedside": "nightstand", "coffee": "coffee",
}
_REQUIRED_IDS = frozenset({
    "sofa", "armchair", "chair", "table", "desk", "bed", "wardrobe", "shelf", "bar-counter",
    "kitchen-counter", "stove", "fridge", "lamp", "plant", "tv", "bench", "cabinet", "rug",
})
_AXES = ("x", "y", "z")
# Furniture shares ``scene3d.cast`` with the people. Stay at production_scene3d.CAST_MEMBERS.
STAGE_CAST_LIMIT = 16


class PropManifestError(ValueError):
    """The CC0 prop manifest breaks its contract."""


def _fail(problem: str) -> None:
    raise PropManifestError(problem)


def _positive(value) -> bool:
    return type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _vec(entry: dict, key: str, positive: bool) -> dict:
    value = entry.get(key)
    if not isinstance(value, dict) or set(value) != set(_AXES):
        _fail(f"{entry.get('id')}: {key} needs x, y and z")
    for axis in _AXES:
        number = value[axis]
        if positive and not _positive(number):
            _fail(f"{entry.get('id')}: {key}.{axis} must be a positive number")
        if not positive and (type(number) not in (int, float) or isinstance(number, bool) or not math.isfinite(number)):
            _fail(f"{entry.get('id')}: {key}.{axis} must be finite")
    return value


def _check_identity(model, seen: set[str]) -> str:
    if not isinstance(model, dict):
        _fail("each model must be an object")
    ident = model.get("id")
    if not isinstance(ident, str) or not ident or ident in seen:
        _fail("model ids must be unique non-empty strings")
    seen.add(ident)
    if model.get("licence") != "CC0-1.0":
        _fail(f"{ident}: licence must be CC0-1.0")
    return ident


def _check_download(model: dict, ident: str) -> None:
    if not isinstance(model.get("sha256"), str) or len(model["sha256"]) != 64:
        _fail(f"{ident}: sha256 is required")
    if not isinstance(model.get("bytes"), int) or model["bytes"] <= 0:
        _fail(f"{ident}: bytes must be a positive integer")
    file_name = model.get("file")
    if not isinstance(file_name, str) or not file_name.endswith(".glb") or file_name.startswith(("/", "~")):
        _fail(f"{ident}: file must be a relative .glb path")
    url = model.get("url")
    if not isinstance(url, str) or not url.startswith("https://") or "raw.githubusercontent.com" not in url:
        _fail(f"{ident}: url must be an https raw.githubusercontent.com link")


def _check_labels(model: dict, ident: str) -> None:
    if model.get("front") not in _YAW:
        _fail(f"{ident}: front must be +z, -z, +x or -x")
    for key in ("credit", "source", "author", "kind"):
        if not isinstance(model.get(key), str) or not model[key].strip():
            _fail(f"{ident}: {key} is required")
    try:
        date.fromisoformat(str(model.get("retrieved_at")))
    except ValueError:
        _fail(f"{ident}: retrieved_at must be YYYY-MM-DD")
    tags = model.get("tags")
    if not isinstance(tags, dict) or not tags.get("es") or not tags.get("en"):
        _fail(f"{ident}: tags need es and en")


def _check_model(model: dict, seen: set[str]) -> None:
    ident = _check_identity(model, seen)
    _check_download(model, ident)
    _check_labels(model, ident)
    _vec(model, "size_m", True)
    _vec(model, "center_m", False)


def validate_manifest(manifest) -> dict:
    """Return ``manifest`` when it is a CC0 furniture pack; raise otherwise."""
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        _fail(f"schema must be {SCHEMA}")
    if not isinstance(manifest.get("revision"), int) or manifest["revision"] < 1:
        _fail("revision must be a positive integer")
    if manifest.get("licence") != "CC0-1.0" or manifest.get("pack") != PACK:
        _fail("pack must be cc0-furniture under CC0-1.0")
    models = manifest.get("models")
    if not isinstance(models, list) or not models or len(models) > 40:
        _fail("models must list 1 to 40 entries")
    seen: set[str] = set()
    for model in models:
        _check_model(model, seen)
    missing = _REQUIRED_IDS - seen
    if missing:
        _fail(f"missing models: {', '.join(sorted(missing))}")
    return manifest


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return validate_manifest(json.loads(Path(path).read_text(encoding="utf-8")))


def models_by_id(manifest: dict | None = None) -> dict[str, dict]:
    data = manifest if manifest is not None else load_manifest()
    return {model["id"]: model for model in data["models"]}


def model_for(kind, block_id: str = "", mold_id: str = "", models: dict | None = None):
    """The manifest row for a mold block, or None when that kind stays a box."""
    table = models if models is not None else models_by_id()
    if kind == "counter":
        ident = "bar-counter" if mold_id in _BAR_MOLDS or block_id in _BAR_BLOCKS else "kitchen-counter"
        return table.get(ident)
    return table.get(_KIND_ID.get(kind, ""))


def fit_block(model: dict, box: list) -> dict:
    """Uniform scale that fits ``box`` (x, y, z, w, h, d) and keeps the mesh's aspect.

    ``size_m`` and ``center_m`` are the file's AABB after the manifest's metre scale.
    The renderer normalises every GLB to 1.7 m, so ``scale`` cancels that. The mesh
    origin is not the footprint centre; the yawed centre is subtracted so the model
    sits on the block. Y stays the block bottom: a grounded slot then rests on the floor.
    """
    x, y, z, width, _height, depth = (float(number) for number in box)
    size, centre, front = model["size_m"], model["center_m"], model.get("front", "+z")
    if front in ("+x", "-x"):
        file_w, file_d = size["z"], size["x"]
    else:
        file_w, file_d = size["x"], size["z"]
    stretch = min(width / file_w, depth / file_d)
    yaw = _YAW[front]
    cos, sin = math.cos(yaw), math.sin(yaw)
    cx, cz = centre["x"] * stretch, centre["z"] * stretch
    # three.js Y rotation: x' = x cos θ + z sin θ, z' = -x sin θ + z cos θ.
    offset_x = cx * cos + cz * sin
    offset_z = -cx * sin + cz * cos
    return {
        "scale": stretch * (size["y"] / MODEL_HEIGHT),
        "position": [x - offset_x, y, z - offset_z],
        "rotationY": yaw,
        "stretch": stretch,
    }


def library_url(model: dict) -> str:
    return f"/api/v1/library/files/{model['sha256']}.glb"


# The content-addressed name the library route serves: ``<sha256>.glb``.
_LIBRARY_KEY = re.compile(r"/api/v1/library/files/([0-9a-f]{64}\.[a-z0-9]{1,8})(?:\?|#|$)")


def library_key(url: str) -> str | None:
    """The ``<sha256>.ext`` of a library file URL, or None when ``url`` is not one."""
    if not isinstance(url, str):
        return None
    found = _LIBRARY_KEY.search(url.strip())
    return found.group(1) if found else None


def workspace_file_url(relative: str, workspace: str) -> str:
    """The same workspace file URL ``scene3d.item.add`` stores for a copied GLB."""
    return f"/api/v1/file/{quote(relative, safe='/')}?workspace={quote(workspace, safe='')}"


def _library_file(key: str) -> Path | None:
    """The installed library file for ``key``, or None when that collection is absent."""
    from services.asset_library import asset_library
    from services.example_assets import ExampleUnavailable
    name = asset_library.file_for(key)
    if not name:
        return None
    try:
        return asset_library.resolve(name)
    except (ExampleUnavailable, KeyError, OSError):
        return None


def ensure_workspace_copy(key: str, root: Path) -> str | None:
    """Copy ``cc0/<key>`` once into ``root``. None when the library file is not installed."""
    source = _library_file(key)
    if source is None:
        return None
    relative = f"cc0/{key}"
    target = Path(root) / relative
    try:
        size = source.stat().st_size
        if target.is_file() and target.stat().st_size == size:
            return relative
        data = source.read_bytes()
    except OSError:
        return None
    if not data or len(data) != size:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    temporary.write_bytes(data)
    temporary.replace(target)
    return relative


def bind_library_url(url: str, root: Path, workspace: str) -> str:
    """A library file URL rewritten to the workspace copy. Anything else, including a missing file, stays."""
    key = library_key(url)
    if key is None:
        return url
    relative = ensure_workspace_copy(key, Path(root))
    if relative is None:
        return url
    return workspace_file_url(relative, workspace)


def bind_document(document: dict, root: Path, workspace: str) -> list:
    """Point dressed furniture at the workspace copy. Returns the slot ids that changed."""
    changed = []
    if not isinstance(document, dict):
        return changed
    for slot in document.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        url = str(slot.get("sourceUrl") or "").strip()
        if library_key(url) is None:
            continue
        bound = bind_library_url(url, root, workspace)
        if bound == url:
            continue
        slot["sourceUrl"] = bound
        changed.append(slot.get("id"))
    return changed


def choice_of(value) -> str:
    """``library`` (the default) or ``box``. Anything else is an error."""
    if value is None or value == "library":
        return "library"
    if value == "box":
        return "box"
    raise ValueError("furniture must be library or box")


def pack_ready() -> bool:
    """True only when every CC0 furniture file is in the library cache."""
    from services.asset_library import asset_library
    if PACK not in asset_library.collections:
        return False
    return asset_library.installed(PACK)


def placements(mold: dict, *, models: dict, limit: int, taken: int = 0) -> list[dict]:
    """Known blocks that still fit in ``limit``, in mold order. The rest stay boxes."""
    rows = []
    mold_id = mold.get("id", "")
    for block in mold.get("blocks") or []:
        if taken + len(rows) >= limit:
            break
        model = model_for(block.get("kind"), block.get("id", ""), mold_id, models)
        if model is None:
            continue
        rows.append({"block_id": block["id"], "model": model, **fit_block(model, block["box"])})
    return rows


def slot_row(placed: dict) -> dict:
    return {
        "id": f"furniture-{placed['block_id']}", "slot": "prop", "media": "model3d",
        "sourceUrl": library_url(placed["model"]), "position": placed["position"],
        "rotationY": placed["rotationY"], "scale": placed["scale"], "grounded": True,
        "clip": None, "name": placed["model"]["id"],
    }


def object_row(placed: dict, file_name: str) -> dict:
    return {
        "objectId": f"furniture-{placed['block_id']}", "file": file_name, "media": "model3d",
        "position": placed["position"], "rotationY": placed["rotationY"], "scale": placed["scale"],
        "grounded": True, "add": True,
    }


def _use_library(choice, explicit: bool, ready) -> tuple[bool, str | None]:
    installed = pack_ready() if ready is None else bool(ready)
    if choice_of(choice) != "library" or not installed:
        warning = NOT_INSTALLED if explicit and choice == "library" and not installed else None
        return False, warning
    return True, None


def dress_room(document: dict, *, ready=None, models: dict | None = None, limit: int = 24) -> dict:
    """Replace known blocks with prop slots. A missing pack leaves the document unchanged."""
    room = document.get("room")
    if not isinstance(room, dict) or not isinstance(room.get("mold"), dict):
        return document
    use, warning = _use_library(room.get("furniture"), room.get("furniture") == "library", ready)
    if warning:
        document["furnitureWarning"] = warning
    if not use:
        return document
    table = models if models is not None else models_by_id()
    taken = sum(1 for slot in document.get("slots") or [] if slot.get("slot") != "background")
    placed = placements(room["mold"], models=table, limit=limit, taken=taken)
    if not placed:
        return document
    room["libraryBlocks"] = [row["block_id"] for row in placed]
    document["slots"] = [*(document.get("slots") or []), *[slot_row(row) for row in placed]]
    return document


def cast_load(cast) -> int:
    """How many models a production cast already occupies. Groups count by member."""
    if not isinstance(cast, dict):
        return 0
    total = 0
    for value in cast.values():
        entry = value if isinstance(value, dict) else {}
        sources = entry.get("sources")
        total += len(sources) if isinstance(sources, list) and sources else 1
    return total


def stage_cast(config: dict, *, ready=None, models: dict | None = None) -> dict:
    """The same replacement, as cast entries the production compiler already binds."""
    background = config.get("background") if isinstance(config, dict) else None
    room = background.get("room") if isinstance(background, dict) else None
    if not isinstance(room, dict) or not isinstance(room.get("mold"), dict):
        return config
    use, warning = _use_library(room.get("furniture"), room.get("furniture") == "library", ready)
    if warning:
        config["furnitureWarning"] = warning
    if not use:
        return config
    table = models if models is not None else models_by_id()
    cast = config.setdefault("cast", {})
    if not isinstance(cast, dict):
        cast = {}
        config["cast"] = cast
    placed = placements(room["mold"], models=table, limit=STAGE_CAST_LIMIT, taken=cast_load(cast))
    if not placed:
        return config
    room["libraryBlocks"] = [row["block_id"] for row in placed]
    for row in placed:
        cast.setdefault(f"furniture-{row['block_id']}", {
            "source": library_url(row["model"]), "position": row["position"], "rotationY": row["rotationY"],
            "scale": row["scale"], "grounded": True, "add": True,
        })
    return config


def copy_into(root: Path, model: dict) -> str:
    """Copy one installed GLB into the workspace under a content-addressed name."""
    from services.asset_library import asset_library
    from services.example_assets import ExampleUnavailable
    try:
        source = asset_library.resolve(model["file"])
    except (ExampleUnavailable, KeyError) as error:
        raise ValueError(NOT_INSTALLED) from error
    relative = f"cc0/{model['sha256']}.glb"
    target = Path(root) / relative
    if not target.is_file() or target.stat().st_size != model["bytes"]:
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != model["sha256"]:
            raise ValueError(NOT_INSTALLED)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return relative


def furniture_objects(mold: dict, *, choice=None, explicit: bool = False, ready=None, models: dict | None = None,
                      taken: int = 0, limit: int = 12, root: Path | None = None, file_of=None) -> tuple[list, list, str | None]:
    """Object rows for a set, the replaced block ids, and a warning when library was asked for but missing."""
    use, warning = _use_library(choice, explicit, ready)
    if not use:
        return [], [], warning
    table = models if models is not None else models_by_id()
    placed = placements(mold, models=table, limit=limit, taken=taken)
    rows = []
    for row in placed:
        if file_of is not None:
            file_name = file_of(row["model"])
        elif root is not None:
            file_name = copy_into(root, row["model"])
        else:
            file_name = library_url(row["model"])
        rows.append(object_row(row, file_name))
    return rows, [row["block_id"] for row in placed], None


def list_library(query: str = "") -> dict:
    """Every CC0 model, including while the pack is not installed."""
    data = load_manifest()
    installed = pack_ready()
    needle = (query or "").casefold()
    rows = []
    for model in data["models"]:
        text = " ".join([model["id"], model["kind"], *model["tags"]["es"], *model["tags"]["en"]]).casefold()
        if needle and needle not in text:
            continue
        rows.append({
            "id": model["id"], "kind": model["kind"], "tags": model["tags"], "size_m": model["size_m"],
            "heightM": model["size_m"]["y"], "licence": model["licence"], "credit": model["credit"],
            "file": library_url(model), "installed": installed,
        })
    return {"pack": PACK, "installed": installed, "licence": data["licence"], "props": rows}


def library_item(model_id: str, root: Path) -> dict:
    """One installed model as a workspace file at its real height, for ``scene3d.item.add``."""
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("library item needs a model id")
    if not pack_ready():
        raise ValueError(NOT_INSTALLED)
    model = models_by_id().get(model_id)
    if model is None:
        raise ValueError(f"unknown CC0 furniture: {model_id}")
    return {"file": copy_into(root, model), "heightM": model["size_m"]["y"], "media": "model3d", "name": model["id"]}


def _digest(files: dict, names: list[str]) -> str:
    body = "".join(f"{name}:{files[name]['sha256']}\n" for name in sorted(names))
    return hashlib.sha256(body.encode()).hexdigest()


def collection_fragment(manifest: dict | None = None) -> tuple[dict, dict]:
    """Files and the one collection the asset library merges in. No archive: each GLB has its own URL."""
    data = manifest if manifest is not None else load_manifest()
    validate_manifest(data)
    files = {}
    names = []
    for model in data["models"]:
        name = model["file"]
        names.append(name)
        files[name] = {
            "kind": "model3d", "size": model["bytes"], "sha256": model["sha256"], "collection": PACK,
            "license": "CC0-1.0", "source": model["source"], "source_url": model["source_url"],
            "author": model["author"], "retrieved_at": model["retrieved_at"], "url": model["url"],
        }
    pack = {
        "title": data["title"]["en"], "files": names, "dependencies": [],
        "size": sum(files[name]["size"] for name in names), "digest": _digest(files, names),
    }
    return files, {PACK: pack}


__all__ = [
    "MANIFEST_PATH", "NOT_INSTALLED", "PACK", "PropManifestError", "STAGE_CAST_LIMIT", "cast_load",
    "choice_of", "collection_fragment", "bind_document", "bind_library_url", "copy_into", "dress_room",
    "ensure_workspace_copy", "fit_block", "furniture_objects", "library_item", "library_key",
    "library_url", "list_library", "load_manifest", "model_for", "models_by_id", "pack_ready",
    "placements", "stage_cast", "validate_manifest", "workspace_file_url",
]

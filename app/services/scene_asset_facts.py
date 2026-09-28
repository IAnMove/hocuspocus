"""Measured facts for files a Video 2D scene can place.

Pixel size, alpha and duration are probed once (PIL or ffprobe, no GPU) and
stored beside the file. A fresh sidecar is reused when size and mtime match.
The generation ``.meta.json`` is only read. ``seamlessHorizontal`` and
``suggestedRole`` are copied when that metadata already records them, never
guessed from pixels or filenames. Thumbnail URLs point at the existing output
thumbnail route; this module does not render images.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

MAX_NAMES = 20
FACTS_VERSION = 1
FACTS_SUFFIX = ".scene-asset-facts.json"
_KINDS = frozenset({"image", "video", "audio"})
_ROLES = frozenset({"plate", "cutout", "overlay"})
_ROLE_KEYS = (
    "suggestedRole", "suggested_role", "sceneRole", "scene_role",
    "assetRole", "asset_role", "role", "kind", "style",
)
_SEAM_KEYS = ("seamlessHorizontal", "seamless_horizontal")
_IMAGE = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_VIDEO = frozenset({".mp4", ".webm", ".gif", ".mov", ".mkv", ".avi", ".m4v"})
_AUDIO = frozenset({".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus"})
_WORKSPACE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]{0,119})")
_NAME = {"type": "string", "minLength": 1, "maxLength": 300}

OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "scenes.assets.inspect": (
        {
            "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
            "names": {
                "type": "array", "minItems": 1, "maxItems": MAX_NAMES, "items": _NAME,
            },
        },
        ["workspace", "names"],
        False,
        "Describe up to 20 existing workspace files a Video 2D scene can use. "
        "Reports type, pixel size, aspect, image alpha, and audio or video duration when PIL or ffprobe can read them. "
        "Copies seamlessHorizontal and suggestedRole only when sidecar metadata already records them. "
        "Image and video results include the existing thumbnail URL. No generation and no GPU.",
    ),
}


class SceneAssetFactsError(ValueError):
    def __init__(self, message: str, *, status: int = 422, code: str = "invalid_command") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def facts_sidecar_path(path: str) -> str:
    return path + FACTS_SUFFIX


def media_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE:
        return "image"
    if ext in _VIDEO:
        return "video"
    if ext in _AUDIO:
        return "audio"
    return ""


def aspect_ratio(width: int, height: int) -> str:
    divisor = math.gcd(int(width), int(height))
    return f"{int(width) // divisor}:{int(height) // divisor}"


def duration_from_probe(payload: object) -> float | None:
    """Duration in seconds from an ffprobe JSON document, or None."""
    if not isinstance(payload, dict):
        return None
    block = payload.get("format")
    if not isinstance(block, dict):
        return None
    try:
        duration = float(block.get("duration"))
    except (TypeError, ValueError):
        return None
    if duration <= 0:
        return None
    return round(duration, 3)


def _pixels(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _image_has_alpha(image: Any) -> bool:
    if "A" in image.getbands():
        return True
    info = getattr(image, "info", {})
    return image.mode == "P" and isinstance(info, dict) and "transparency" in info


def _image_record(width: object, height: object, alpha: object) -> dict[str, Any]:
    record: dict[str, Any] = {}
    if _pixels(width) and _pixels(height):
        record["width"] = int(width)
        record["height"] = int(height)
        record["aspect"] = aspect_ratio(int(width), int(height))
    if isinstance(alpha, bool):
        record["alpha"] = alpha
    return record


def image_facts(path: str) -> dict[str, Any]:
    """Width, height, aspect and alpha from the image header. No pixel guess."""
    try:
        from PIL import Image
    except ImportError:
        return {}
    try:
        with Image.open(path) as image:
            width, height = image.size
            alpha = _image_has_alpha(image)
    except Exception:
        return {}
    return _image_record(width, height, alpha)


def _video_size(path: str) -> tuple[int, int] | None:
    try:
        from services.media_dimensions import probe_video_size
    except ImportError:
        return None
    return probe_video_size(path)


def _copy_video_size(facts: dict[str, Any], path: str) -> None:
    size = _video_size(path)
    if size is None:
        return
    facts["width"], facts["height"] = size
    facts["aspect"] = aspect_ratio(size[0], size[1])


def _duration(path: str) -> float | None:
    if shutil.which("ffprobe") is None:
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20, check=False,
        )
        payload = json.loads(result.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return duration_from_probe(payload)


def probe_av(path: str, kind: str) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    if kind == "video":
        _copy_video_size(facts, path)
    duration = _duration(path)
    if duration is not None:
        facts["duration"] = duration
    return facts


def measure_media(path: str) -> dict[str, Any]:
    kind = media_type(path)
    if kind == "image":
        return {"type": "image", **image_facts(path)}
    if kind in {"video", "audio"}:
        return {"type": kind, **probe_av(path, kind)}
    return {}


def _role_sources(meta: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = [meta]
    for key in ("params", "technical", "asset"):
        value = meta.get(key)
        if isinstance(value, dict):
            sources.append(value)
    generation = meta.get("generation")
    if isinstance(generation, dict) and isinstance(generation.get("parameters"), dict):
        sources.append(generation["parameters"])
    return sources


def _first_role(source: Mapping[str, Any]) -> str | None:
    # Label fields only. Prompts and filenames are not roles.
    for key in _ROLE_KEYS:
        value = source.get(key)
        if isinstance(value, str) and value in _ROLES:
            return value
    return None


def _has_seam(source: Mapping[str, Any]) -> bool:
    return any(source.get(key) is True for key in _SEAM_KEYS)


def declared_from_metadata(meta: object) -> dict[str, Any]:
    """Copy a recorded role or verified horizontal seam. Omit anything else."""
    if not isinstance(meta, dict):
        return {}
    role = None
    seam = False
    for source in _role_sources(meta):
        if role is None:
            role = _first_role(source)
        if not seam and _has_seam(source):
            seam = True
    result: dict[str, Any] = {}
    if seam:
        result["seamlessHorizontal"] = True
    if role:
        result["suggestedRole"] = role
    return result


def _copy_pixels(asset: dict[str, Any], kind: str | None, measured: Mapping[str, Any]) -> None:
    if kind not in {"image", "video"}:
        return
    width = measured.get("width")
    height = measured.get("height")
    if not _pixels(width) or not _pixels(height):
        return
    asset["width"] = int(width)
    asset["height"] = int(height)
    aspect = measured.get("aspect")
    asset["aspect"] = aspect if isinstance(aspect, str) and aspect else aspect_ratio(int(width), int(height))


def _copy_alpha(asset: dict[str, Any], kind: str | None, measured: Mapping[str, Any]) -> None:
    if kind == "image" and isinstance(measured.get("alpha"), bool):
        asset["alpha"] = measured["alpha"]


def _copy_duration(asset: dict[str, Any], kind: str | None, measured: Mapping[str, Any]) -> None:
    if kind not in {"audio", "video"}:
        return
    duration = measured.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return
    if duration <= 0:
        return
    asset["duration"] = round(float(duration), 3)


def _copy_declared(asset: dict[str, Any], declared: object) -> None:
    if not isinstance(declared, dict):
        return
    if declared.get("seamlessHorizontal") is True:
        asset["seamlessHorizontal"] = True
    role = declared.get("suggestedRole")
    if role in _ROLES:
        asset["suggestedRole"] = role


def assemble_asset(
    name: str,
    *,
    kind: str | None,
    measured: object,
    declared: object,
    thumbnail_url: str | None,
) -> dict[str, Any]:
    """Public asset record. Unknown probe fields and unrecorded roles are omitted."""
    asset: dict[str, Any] = {"name": name}
    if kind in _KINDS:
        asset["type"] = kind
    if isinstance(measured, dict):
        _copy_pixels(asset, kind, measured)
        _copy_alpha(asset, kind, measured)
        _copy_duration(asset, kind, measured)
    _copy_declared(asset, declared)
    if thumbnail_url and kind in {"image", "video"}:
        asset["thumbnailUrl"] = thumbnail_url
    return asset


def thumbnail_url(name: str, workspace: str, kind: str | None, *, size: int, mtime: float) -> str | None:
    """Same URL the gallery already serves. Does not create a thumbnail file."""
    if kind not in {"image", "video"}:
        return None
    stamp = int(mtime * 1_000_000)
    return (
        f"/api/v1/outputs/thumbnail/{quote(name, safe='')}?v={stamp}-{size}"
        f"&workspace={quote(workspace, safe='')}"
    )


def read_cache(path: str, size: int, mtime_ns: int) -> dict[str, Any] | None:
    try:
        with open(facts_sidecar_path(path), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != FACTS_VERSION:
        return None
    if payload.get("size") != size or payload.get("mtime_ns") != mtime_ns:
        return None
    measured = payload.get("measured")
    return measured if isinstance(measured, dict) else None


def write_cache(path: str, size: int, mtime_ns: int, measured: Mapping[str, Any]) -> None:
    sidecar = facts_sidecar_path(path)
    temporary = os.path.join(
        os.path.dirname(sidecar) or ".",
        "." + os.path.basename(sidecar) + "." + uuid.uuid4().hex + ".tmp",
    )
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(
                {"version": FACTS_VERSION, "size": size, "mtime_ns": mtime_ns, "measured": dict(measured)},
                handle, separators=(",", ":"),
            )
        os.replace(temporary, sidecar)
    except OSError:
        return
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                return


def _read_meta(path: str) -> dict[str, Any] | None:
    sidecar = os.path.splitext(path)[0] + ".meta.json"
    try:
        with open(sidecar, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _fresh_measured(path: str, size: int, mtime_ns: int, measure: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    measured = read_cache(path, size, mtime_ns)
    actual = media_type(path)
    if isinstance(measured, dict) and (not actual or measured.get("type") == actual):
        return measured
    fresh = measure(path)
    if not isinstance(fresh, dict):
        fresh = {}
    if actual and fresh.get("type") not in _KINDS:
        fresh = {"type": actual, **fresh}
    write_cache(path, size, mtime_ns, fresh)
    return fresh


def _describe(workspace: str, name: str, path: str, measure: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    stat = os.stat(path)
    size = int(stat.st_size)
    measured = _fresh_measured(path, size, int(stat.st_mtime_ns), measure)
    kind = measured.get("type") if measured.get("type") in _KINDS else media_type(path)
    return assemble_asset(
        name,
        kind=kind or None,
        measured=measured,
        declared=declared_from_metadata(_read_meta(path)),
        thumbnail_url=thumbnail_url(name, workspace, kind or None, size=size, mtime=stat.st_mtime),
    )


def _names(names: object) -> list[str]:
    if not isinstance(names, list) or not names:
        raise SceneAssetFactsError("names must list 1 to 20 workspace files")
    if len(names) > MAX_NAMES:
        raise SceneAssetFactsError("Inspect at most 20 files", code="too_many_names")
    for name in names:
        if not isinstance(name, str) or not name or len(name) > 300:
            raise SceneAssetFactsError("Each name must be a workspace-relative file", code="invalid_name")
    return names


def _reject_name(name: str) -> None:
    if name != name.strip() or "\\" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise SceneAssetFactsError("Media path is not allowed", status=400, code="path_not_allowed")
    if os.path.isabs(name):
        raise SceneAssetFactsError("Media path is not allowed", status=400, code="path_not_allowed")


def _parts(name: str) -> list[str]:
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SceneAssetFactsError("Media path is not allowed", status=400, code="path_not_allowed")
    return parts


def _contained(root: str, candidate: str) -> bool:
    try:
        return os.path.commonpath((root, candidate)) == root and candidate != root
    except (TypeError, ValueError, OSError):
        return False


def _resolve(root: str, name: str) -> str:
    _reject_name(name)
    parts = _parts(name)
    try:
        candidate = os.path.realpath(os.path.join(root, *parts))
    except (OSError, ValueError) as error:
        raise SceneAssetFactsError("Media path is not allowed", status=400, code="path_not_allowed") from error
    if not _contained(root, candidate):
        raise SceneAssetFactsError("Media path is not allowed", status=400, code="path_not_allowed")
    if not os.path.isfile(candidate):
        raise SceneAssetFactsError("File not found", status=404, code="file_not_found")
    return candidate


def inspect_scene_assets(
    workspace: str,
    names: object,
    *,
    workspace_dir: Callable[[str], str],
    measure: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(workspace, str) or _WORKSPACE.fullmatch(workspace) is None:
        raise SceneAssetFactsError("Use an explicit valid workspace", status=422, code="invalid_workspace")
    selected = _names(names)
    root = os.path.realpath(os.path.abspath(str(workspace_dir(workspace))))
    if not os.path.isdir(root):
        raise SceneAssetFactsError("Workspace is not available", status=422, code="invalid_workspace")
    resolved = [(name, _resolve(root, name)) for name in selected]
    probe = measure or measure_media
    assets = [_describe(workspace, name, path, probe) for name, path in resolved]
    return {"workspace": workspace, "assets": assets}


def _payload(arguments: object) -> dict[str, Any]:
    if not isinstance(arguments, dict) or arguments.get("version") != 1:
        raise SceneAssetFactsError("Use version 1 and an input object")
    if set(arguments) - {"version", "input"}:
        raise SceneAssetFactsError("Use version 1 and an input object")
    data = arguments.get("input")
    if not isinstance(data, dict) or set(data) != {"workspace", "names"}:
        raise SceneAssetFactsError("Use version 1 with workspace and names")
    return data


def command_catalog() -> list[dict[str, Any]]:
    properties, required, mutation, description = OPERATIONS["scenes.assets.inspect"]
    payload = {"type": "object", "additionalProperties": False, "properties": properties, "required": required}
    return [{
        "name": "scenes.assets.inspect",
        "version": 1,
        "domain": "scenes",
        "mutation": mutation,
        "description": description,
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "input": payload,
            },
            "required": ["version", "input"],
        },
    }]


def command_handlers(workspace_dir: Callable[[str], str]) -> dict[str, Callable[[Any], Any]]:
    def run(arguments: Any) -> dict[str, Any]:
        data = _payload(arguments)
        result = inspect_scene_assets(data["workspace"], data["names"], workspace_dir=workspace_dir)
        return {
            "version": 1, "status": "completed", "operation": "scenes.assets.inspect", "result": result,
        }

    async def handle(arguments: Any) -> dict[str, Any]:
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool
        try:
            return await run_in_threadpool(run, arguments)
        except SceneAssetFactsError as error:
            raise HTTPException(error.status, {"code": error.code, "message": str(error)}) from error

    return {"scenes.assets.inspect": handle}


__all__ = [
    "MAX_NAMES",
    "OPERATIONS",
    "SceneAssetFactsError",
    "assemble_asset",
    "aspect_ratio",
    "command_catalog",
    "command_handlers",
    "declared_from_metadata",
    "duration_from_probe",
    "facts_sidecar_path",
    "inspect_scene_assets",
    "measure_media",
]

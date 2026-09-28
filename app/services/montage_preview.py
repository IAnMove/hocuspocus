"""Contact sheet for a whole montage (``montages.preview``).

Samples up to eight instants on the montage timeline. A Video 2D scene clip
is painted with ``scenes.video2d.preview``'s painter; a plain video clip uses
the editor's ffmpeg frame extract. The PNG is stored in the workspace. The
JSON reply is the file, URL, sha256 and times — never the PNG bytes. An
instant that cannot be painted is omitted and listed under a stable warning
code. No GPU and no application server.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from services.montage_documents import FILE_RE, WORKSPACE_RE, MontageError, MontageStore
from services.montage_shots import media_duration, timeline_slots
from services.scene2d_export import validated_document
from services.video2d_preview import (
    PreviewError,
    bind_preview_origin,
    paint_contact_sheet,
    preview_frame_size,
    sheet_columns,
)
from services.video_editor import extract_frame
from services.video_editor_frames import VideoEditorError

OPERATION = "montages.preview"
MAX_INSTANTS = 8
DEFAULT_COUNT = 4
UNPAINTABLE = "montage_preview_unpaintable"
FIELDS = frozenset({"workspace", "file", "times", "count"})
REQUIRED = ("workspace", "file")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class _Unpaintable(Exception):
    """One instant could not be painted; the sheet can continue without it."""


def _payload(arguments: Any) -> dict:
    version_ok = isinstance(arguments, dict) and arguments.get("version") == 1
    data = arguments.get("input") if version_ok else None
    if not isinstance(data, dict):
        raise MontageError("Use version 1 and an input object", code="invalid_command")
    missing = [key for key in REQUIRED if key not in data]
    if set(data) - FIELDS or missing:
        raise MontageError("input requires workspace and file; optional times or count", code="invalid_command")
    workspace = data.get("workspace")
    file_name = data.get("file")
    if not isinstance(workspace, str) or not WORKSPACE_RE.fullmatch(workspace):
        raise MontageError("Use an explicit valid workspace", code="invalid_workspace")
    if not isinstance(file_name, str) or not FILE_RE.fullmatch(file_name):
        raise MontageError("Use an exact <name>.montage.json file", code="invalid_file")
    return data


def _count(value: Any) -> int:
    if isinstance(value, bool) or type(value) is not int or not 1 <= value <= MAX_INSTANTS:
        raise MontageError("count must be an integer from 1 to 8", code="montage_preview_bad_count")
    return value


def _one_time(value: Any, duration: float) -> float:
    if isinstance(value, bool) or type(value) not in (int, float):
        raise MontageError("times must be numbers", code="montage_preview_bad_times")
    number = float(value)
    if number != number or number < 0 or number > duration + 1e-3:
        raise MontageError("times must fall inside the montage", code="montage_preview_time_out_of_range")
    return round(min(number, duration), 3)


def _explicit_times(raw: Any, duration: float) -> list[float]:
    if not isinstance(raw, list) or not raw:
        raise MontageError("times must list at least one instant", code="montage_preview_bad_times")
    if len(raw) > MAX_INSTANTS:
        raise MontageError("At most 8 instants", code="montage_preview_too_many")
    return [_one_time(item, duration) for item in raw]


def _sample(duration: float, count: int) -> list[float]:
    step = duration / count
    times = []
    for index in range(count):
        times.append(round(min(duration, (index + 0.5) * step), 3))
    return times


def _choose_times(data: dict, duration: float, count: int) -> list[float]:
    if duration <= 0:
        raise MontageError("Montage has no timeline to preview", code="montage_preview_empty")
    if "times" in data:
        return _explicit_times(data["times"], duration)
    return _sample(duration, count)


def _inside_root(root: Path, name: str) -> Path | None:
    if not name or name in {".", ".."} or name != Path(name).name:
        return None
    path = (root / name).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


def _media_path(root: Path, source: Any) -> Path | None:
    text = str(source or "").split("?", 1)[0].strip()
    return _inside_root(root, Path(text).name)


def _clip_duration(root: Path, clip: dict) -> float:
    path = _media_path(root, clip.get("source"))
    if path is None:
        return 0.0
    return media_duration(path)


def _scene_path(root: Path, clip: dict) -> Path | None:
    origin = clip.get("origin")
    if not isinstance(origin, dict) or origin.get("kind") != "scene2d":
        return None
    name = str(origin.get("scene") or "")
    if not name.endswith(".scene.json"):
        return None
    return _inside_root(root, name)


def _scene_document(root: Path, clip: dict) -> dict | None:
    path = _scene_path(root, clip)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _owner(slots: list[tuple[float, float]], instant: float) -> int | None:
    found = None
    for index, (start, end) in enumerate(slots):
        if start - 1e-3 <= instant <= end + 1e-3:
            found = index
        elif start > instant + 1e-3:
            break
    return found


def _source_time(clip: dict, slot: tuple[float, float], instant: float) -> float:
    start, end = slot
    local = min(max(0.0, instant - start), max(0.0, end - start))
    return float(clip.get("trimStart") or 0) + local


def _scene_instant(document: dict, source_time: float) -> float:
    raw = document.get("duration", source_time)
    try:
        duration = float(raw)
    except (TypeError, ValueError):
        duration = source_time
    if duration != duration or duration <= 0:
        duration = max(source_time, 0.0)
    return round(min(max(0.0, source_time), duration), 3)


def _http_text(error: HTTPException) -> str:
    detail = error.detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("code") or "scene")[:300]
    return str(detail or "scene")[:300]


def _scene_png(raw: dict, source_time: float) -> bytes:
    try:
        document = validated_document(raw)
        when = _scene_instant(document, source_time)
        return paint_contact_sheet(document, [when], preview_frame_size(document))
    except HTTPException as error:
        raise _Unpaintable(_http_text(error)) from error
    except PreviewError as error:
        raise _Unpaintable(error.code) from error


def _fit_image(image: Image.Image, cell: tuple[int, int]) -> Image.Image:
    fitted = image.convert("RGB")
    fitted.thumbnail(cell, Image.Resampling.NEAREST)
    canvas = Image.new("RGB", cell, (0, 0, 0))
    left = (cell[0] - fitted.width) // 2
    top = (cell[1] - fitted.height) // 2
    canvas.paste(fitted, (left, top))
    return canvas


def _fit_png(png: bytes, cell: tuple[int, int]) -> Image.Image:
    if not png.startswith(PNG_MAGIC):
        raise _Unpaintable("painter did not return a PNG")
    try:
        with Image.open(io.BytesIO(png)) as image:
            return _fit_image(image, cell)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise _Unpaintable("painter PNG could not be read") from error


def _video_frame(path: Path, instant: float, cell: tuple[int, int]) -> Image.Image:
    handle = tempfile.NamedTemporaryFile(prefix="montage-frame-", suffix=".png", delete=False)
    name = handle.name
    handle.close()
    try:
        extract_frame(str(path), name, instant)
        with Image.open(name) as image:
            return _fit_image(image, cell)
    except (OSError, ValueError, VideoEditorError, UnidentifiedImageError) as error:
        raise _Unpaintable(str(error)[:300] or "frame extract failed") from error
    finally:
        try:
            os.remove(name)
        except OSError:
            pass


def _paint_clip(root: Path, clip: dict, slot: tuple[float, float], instant: float, cell: tuple[int, int]) -> Image.Image:
    when = _source_time(clip, slot, instant)
    scene = _scene_document(root, clip)
    if scene is not None:
        return _fit_png(_scene_png(scene, when), cell)
    path = _media_path(root, clip.get("source"))
    if path is None:
        raise _Unpaintable("clip media is missing")
    return _video_frame(path, when, cell)


def _warning(clip: dict | None, instant: float, detail: str) -> dict[str, Any]:
    body: dict[str, Any] = {"code": UNPAINTABLE, "time": instant, "message": detail[:300]}
    if isinstance(clip, dict) and clip.get("id"):
        body["clip"] = clip["id"]
    return body


def _one_frame(root, clips, slots, instant, cell, warnings) -> Image.Image | None:
    index = _owner(slots, instant)
    if index is None:
        warnings.append(_warning(None, instant, "no clip covers this instant"))
        return None
    clip = clips[index]
    try:
        return _paint_clip(root, clip, slots[index], instant, cell)
    except _Unpaintable as error:
        warnings.append(_warning(clip, instant, str(error)))
        return None


def _collect(root, clips, slots, times, cell):
    frames = []
    painted = []
    warnings: list[dict[str, Any]] = []
    for instant in times:
        image = _one_frame(root, clips, slots, instant, cell, warnings)
        if image is None:
            continue
        frames.append(image)
        painted.append(instant)
    return frames, painted, warnings


def _cell_size(montage: dict) -> tuple[int, int]:
    width, height, _fps = preview_frame_size(montage)
    return width, height


def _compose(frames: list[Image.Image], columns: int) -> bytes:
    cell = frames[0].size
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell[0], rows * cell[1]), (0, 0, 0))
    for index, frame in enumerate(frames):
        sheet.paste(frame, ((index % columns) * cell[0], (index // columns) * cell[1]))
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG", compress_level=9)
    return buffer.getvalue()


def _store_sheet(root: Path, workspace: str, png: bytes) -> dict[str, str]:
    digest = hashlib.sha256(png).hexdigest()
    name = f"montage-contact-{digest[:20]}.png"
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    if not target.is_file():
        temporary = root / f".{name}.{uuid.uuid4().hex}.tmp"
        temporary.write_bytes(png)
        os.replace(temporary, target)
    return {
        "file": name,
        "url": "/api/v1/file/" + quote(name) + "?workspace=" + quote(workspace, safe=""),
        "sha256": digest,
    }


def _fail_empty(warnings: list[dict[str, Any]]) -> None:
    error = MontageError("No montage instant could be painted", code="montage_preview_empty")
    error.warnings = list(warnings)
    raise error


def _finish(root: Path, workspace: str, frames, painted, warnings) -> dict[str, Any]:
    if not frames:
        _fail_empty(warnings)
    stored = _store_sheet(root, workspace, _compose(frames, sheet_columns(len(frames))))
    result: dict[str, Any] = {**stored, "times": painted}
    if warnings:
        result["warnings"] = warnings
    return {"version": 1, "status": "completed", "operation": OPERATION, "result": result}


def _preview_saved(store: MontageStore, data: dict, saved: dict, count: int) -> dict[str, Any]:
    montage = saved["montage"]
    root = Path(store.workspace_dir(data["workspace"]))
    slots = timeline_slots(montage.get("clips") or [], lambda clip: _clip_duration(root, clip))
    duration = slots[-1][1] if slots else 0.0
    times = _choose_times(data, duration, count)
    frames, painted, warnings = _collect(root, montage.get("clips") or [], slots, times, _cell_size(montage))
    return _finish(root, data["workspace"], frames, painted, warnings)


def preview_montage(store: MontageStore, arguments: Any, *, app_url: Callable[[], str] | None = None) -> dict[str, Any]:
    data = _payload(arguments)
    count = DEFAULT_COUNT if "times" in data else _count(data.get("count", DEFAULT_COUNT))
    if app_url is not None:
        bind_preview_origin(app_url() or "")
    saved = store.get(data["workspace"], data["file"])
    return _preview_saved(store, data, saved, count)


def command_catalog() -> list[dict[str, Any]]:
    payload = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
            "file": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.montage\.json$"},
            "times": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_INSTANTS,
                "items": {"type": "number", "minimum": 0},
            },
            "count": {"type": "integer", "minimum": 1, "maximum": MAX_INSTANTS},
        },
        "required": ["workspace", "file"],
    }
    return [{
        "name": OPERATION,
        "version": 1,
        "domain": "montages",
        "mutation": False,
        "description": (
            "Paint one contact sheet of up to 8 instants across a saved montage (scenes and clips). "
            "A scene2d origin is painted with the Video 2D contact-sheet painter; a plain video clip "
            "uses one ffmpeg frame. The PNG is saved in the workspace. The reply is file, url, sha256 "
            "and times, never the PNG bytes. Pass times, or count from 1 to 8 (default 4). "
            "An instant that cannot be painted is omitted and listed in warnings with code "
            "montage_preview_unpaintable. No GPU and no MP4."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"version": {"type": "integer", "const": 1}, "input": payload},
            "required": ["version", "input"],
        },
    }]


def command_handlers(store: MontageStore, app_url: Callable[[], str] | None = None) -> dict[str, Callable[[Any], Any]]:
    async def handle(arguments: Any) -> dict[str, Any]:
        from starlette.concurrency import run_in_threadpool

        try:
            return await run_in_threadpool(preview_montage, store, arguments, app_url=app_url)
        except MontageError as error:
            detail: dict[str, Any] = {"code": error.code, "message": str(error)}
            warnings = getattr(error, "warnings", None)
            if warnings:
                detail["warnings"] = warnings
            raise HTTPException(error.status, detail) from error

    return {OPERATION: handle}


__all__ = [
    "OPERATION",
    "UNPAINTABLE",
    "command_catalog",
    "command_handlers",
    "preview_montage",
]

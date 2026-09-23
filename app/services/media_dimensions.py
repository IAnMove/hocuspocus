"""Per-file facts the media gallery needs before any pixel loads.

The gallery sizes every row from an output's aspect ratio and paints a
placeholder in its average colour while the preview travels. Those facts are
kept here, keyed by path, size and modification time, and persisted beside the
thumbnail cache so a restart does not re-read thousands of headers.

* Images report their size from the file header (cheap, done inline).
* Videos without a recorded resolution are probed with ffprobe, and every
  image/video gets its colour from its small preview. Both happen on one
  low-priority background thread, which also warms the preview cache and keeps
  it under its size cap.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from collections import OrderedDict
from typing import Iterable, Mapping

_RESOLUTION = re.compile(r"^\s*(\d{1,5})\s*[x×]\s*(\d{1,5})\s*$")
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".gif", ".mov", ".mkv", ".avi", ".m4v"})
_CACHE_LIMIT = 50_000
FACTS_FILENAME = "media-facts.json"
THUMBNAIL_CACHE_MAX_BYTES = 512 * 1024 * 1024
_PRUNE_EVERY = 300
_SAVE_DELAY_SECONDS = 2.0

_lock = threading.Lock()
_facts: "OrderedDict[str, dict]" = OrderedDict()
_cache_dir: str | None = None
_dirty = False
_last_save = 0.0

_queue: "OrderedDict[str, str]" = OrderedDict()
_queue_ready = threading.Condition(_lock)
_worker: threading.Thread | None = None


def parse_resolution(value: object) -> tuple[int, int] | None:
    """``"832x480"`` → ``(832, 480)``; anything else (``"auto"``, ``None``) → ``None``."""
    if not isinstance(value, str):
        return None
    match = _RESOLUTION.match(value)
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    return (width, height) if width > 0 and height > 0 else None


def _key(path: str, size: int, mtime: float) -> str:
    return f"{os.path.normpath(path)}|{size}|{mtime!r}"


def _stat_key(path: str) -> str | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return _key(path, stat.st_size, stat.st_mtime)


def configure(cache_dir: str) -> None:
    """Persist facts under ``cache_dir`` and allow background warming there."""
    global _cache_dir
    with _lock:
        if _cache_dir == cache_dir:
            return
        _cache_dir = cache_dir
        try:
            with open(os.path.join(cache_dir, FACTS_FILENAME), "r", encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, ValueError):
            stored = {}
        if isinstance(stored, dict):
            for key, value in list(stored.items())[-_CACHE_LIMIT:]:
                if isinstance(value, dict):
                    _facts[key] = value


def _remember(key: str, **values) -> dict:
    """Merge ``values`` into the facts for ``key``. Caller holds ``_lock``."""
    global _dirty
    entry = dict(_facts.pop(key, {}))
    entry.update(values)
    _facts[key] = entry
    while len(_facts) > _CACHE_LIMIT:
        _facts.popitem(last=False)
    _dirty = True
    return entry


def save_facts(force: bool = False) -> None:
    global _dirty, _last_save
    with _lock:
        if not _cache_dir or not _dirty or (not force and time.monotonic() - _last_save < _SAVE_DELAY_SECONDS):
            return
        snapshot = dict(_facts)
        _dirty = False
        _last_save = time.monotonic()
        directory = _cache_dir
    try:
        os.makedirs(directory, exist_ok=True)
        temporary = os.path.join(directory, f".{FACTS_FILENAME}.{uuid.uuid4().hex}.tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, separators=(",", ":"))
        os.replace(temporary, os.path.join(directory, FACTS_FILENAME))
    except OSError:
        with _lock:
            _dirty = True


def image_header_size(path: str) -> tuple[int, int] | None:
    """Width and height from the image header, without decoding pixels."""
    key = _stat_key(path)
    if key is None:
        return None
    with _lock:
        known = _facts.get(key)
        if known and "w" in known:
            return (known["w"], known["h"]) if known["w"] else None
    size: tuple[int, int] | None = None
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            if width > 0 and height > 0:
                size = (int(width), int(height))
    except Exception:
        size = None
    with _lock:
        _remember(key, w=size[0] if size else 0, h=size[1] if size else 0)
    return size


def probe_video_size(path: str) -> tuple[int, int] | None:
    """Display size of the first video stream, honouring rotation metadata."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:stream_tags=rotate:stream_side_data=rotation", "-of", "json", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20, check=False,
        )
        stream = (json.loads(result.stdout or "{}").get("streams") or [{}])[0]
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    rotation = 0
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = int(float(side["rotation"]))
    rotation = rotation or int(float((stream.get("tags") or {}).get("rotate") or 0))
    return (height, width) if abs(rotation) % 180 == 90 else (width, height)


def average_color(preview_path: str) -> str:
    """``#rrggbb`` of the visible pixels, or ``""`` for a blank/transparent preview."""
    try:
        from PIL import Image

        with Image.open(preview_path) as opened:
            image = opened.convert("RGBA")
            image.thumbnail((24, 24))
            pixels = image.getdata()
    except Exception:
        return ""
    red = green = blue = weight = 0
    for r, g, b, a in pixels:
        red += r * a
        green += g * a
        blue += b * a
        weight += a
    if weight < 255 * 4:
        return ""
    half = weight // 2
    return "#{:02x}{:02x}{:02x}".format((red + half) // weight, (green + half) // weight, (blue + half) // weight)


def listing_fields(ftype: str, filepath: str, size: int, mtime: float, resolution: object = None) -> dict:
    """Extra listing fields for one output: ``width``/``height`` and ``color`` when known."""
    if ftype not in ("image", "video"):
        return {}
    key = _key(filepath, size, mtime)
    with _lock:
        known = dict(_facts.get(key) or {})
    fields: dict = {}
    dims = (known["w"], known["h"]) if known.get("w") else None
    if dims is None and ftype == "image" and "w" not in known:
        dims = image_header_size(filepath)
    if dims is None:
        dims = parse_resolution(resolution)
    if dims:
        fields["width"], fields["height"] = dims
    if known.get("c"):
        fields["color"] = known["c"]
    needs_probe = ftype == "video" and "w" not in known
    if "c" not in known or needs_probe:
        enqueue(filepath, ftype)
    return fields


def listing_dimensions(
    raw_entries: Iterable[tuple[str, str, str, float]],
    sidecars: Mapping[str, Mapping[str, object]],
) -> dict[str, dict]:
    """Map output name → listing fields for a directory snapshot."""
    result: dict[str, dict] = {}
    for name, filepath, ext, mtime in raw_entries:
        ftype = "image" if ext in _IMAGE_EXTENSIONS else "video" if ext in _VIDEO_EXTENSIONS else ""
        if not ftype:
            continue
        try:
            size = os.path.getsize(filepath)
        except OSError:
            size = 0
        fields = listing_fields(ftype, filepath, size, mtime, (sidecars.get(name) or {}).get("resolution"))
        if fields:
            result[name] = fields
    return result


def note_preview(source: str, preview_path: str) -> None:
    """Record the colour of a preview that was just produced for ``source``."""
    key = _stat_key(source)
    if key is None:
        return
    with _lock:
        if "c" in (_facts.get(key) or {}):
            return
    color = average_color(preview_path)
    with _lock:
        _remember(key, c=color)
    save_facts()


def enqueue(path: str, ftype: str) -> None:
    """Ask the background worker to probe and colour ``path``. No-op until configured."""
    global _worker
    with _lock:
        if not _cache_dir or path in _queue:
            return
        _queue[path] = ftype
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="media-facts", daemon=True)
            _worker.start()
        _queue_ready.notify()


def _warm(path: str, ftype: str, cache_dir: str) -> bool:
    """Probe and colour one file. Returns True when a preview was generated."""
    from services.media_thumbnails import ensure_fitted_thumbnail

    key = _stat_key(path)
    if key is None:
        return False
    with _lock:
        known = dict(_facts.get(key) or {})
    if ftype == "video" and "w" not in known:
        dims = probe_video_size(path)
        with _lock:
            _remember(key, w=dims[0] if dims else 0, h=dims[1] if dims else 0)
    if "c" in known:
        return False
    try:
        preview = ensure_fitted_thumbnail(path, cache_dir, is_video=ftype == "video", size="sm")
    except Exception:
        with _lock:
            _remember(key, c="")
        return False
    color = average_color(preview)
    with _lock:
        _remember(key, c=color)
    return True


def _work() -> None:
    generated = 0
    pruned = False
    while True:
        with _lock:
            while not _queue:
                if not _queue_ready.wait(timeout=_SAVE_DELAY_SECONDS * 2):
                    break
            if not _queue:
                cache_dir = None
            else:
                path, ftype = _queue.popitem(last=False)
                cache_dir = _cache_dir
        if cache_dir is None:
            save_facts(force=True)
            with _lock:
                if not _queue:
                    return
            continue
        if not pruned:
            prune_thumbnail_cache(cache_dir)
            pruned = True
        try:
            if _warm(path, ftype, cache_dir):
                generated += 1
                if generated % _PRUNE_EVERY == 0:
                    prune_thumbnail_cache(cache_dir)
        except Exception:
            pass
        save_facts()
        # Stay out of the way of generations and the UI's own preview requests.
        time.sleep(0.03)


def prune_thumbnail_cache(cache_dir: str, max_bytes: int = THUMBNAIL_CACHE_MAX_BYTES) -> int:
    """Delete least recently used previews until the cache is below 80 % of ``max_bytes``."""
    entries = []
    total = 0
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return 0
    for name in names:
        if name == FACTS_FILENAME or name.startswith("."):
            continue
        path = os.path.join(cache_dir, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        total += stat.st_size
        entries.append((max(stat.st_atime, stat.st_mtime), stat.st_size, path))
    if total <= max_bytes:
        return 0
    removed = 0
    target = max_bytes * 0.8
    for _used, size, path in sorted(entries):
        if total <= target:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        removed += 1
    return removed

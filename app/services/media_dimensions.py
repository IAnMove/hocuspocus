"""Pixel dimensions for the media gallery listing.

The gallery sizes every row before any image arrives, so it needs each
output's aspect ratio up front. Images report their real size from the file
header (Auto-canvas edits can differ from the requested resolution); videos
fall back to the resolution recorded in their generation sidecar. Headers are
read once per file version and cached, so rebuilding a listing snapshot after
a new output only opens the new files.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Iterable, Mapping

_RESOLUTION = re.compile(r"^\s*(\d{1,5})\s*[x×]\s*(\d{1,5})\s*$")
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".gif", ".mov", ".mkv", ".avi", ".m4v"})
_CACHE_LIMIT = 50_000

_header_cache: dict[tuple[str, int, int], tuple[int, int] | None] = {}
_header_cache_lock = threading.Lock()


def parse_resolution(value: object) -> tuple[int, int] | None:
    """``"832x480"`` → ``(832, 480)``; anything else (``"auto"``, ``None``) → ``None``."""
    if not isinstance(value, str):
        return None
    match = _RESOLUTION.match(value)
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    return (width, height) if width > 0 and height > 0 else None


def image_header_size(path: str) -> tuple[int, int] | None:
    """Width and height from the image header, without decoding pixels."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_size, stat.st_mtime_ns)
    with _header_cache_lock:
        if key in _header_cache:
            return _header_cache[key]
    size: tuple[int, int] | None = None
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            if width > 0 and height > 0:
                size = (int(width), int(height))
    except Exception:
        size = None
    with _header_cache_lock:
        if len(_header_cache) >= _CACHE_LIMIT:
            _header_cache.clear()
        _header_cache[key] = size
    return size


def listing_dimensions(
    raw_entries: Iterable[tuple[str, str, str, float]],
    sidecars: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, int]]:
    """Map output name → ``{"width", "height"}`` for images and videos whose size is known."""
    dimensions: dict[str, dict[str, int]] = {}
    for name, filepath, ext, _mtime in raw_entries:
        size = None
        if ext in _IMAGE_EXTENSIONS:
            size = image_header_size(filepath)
        if size is None and (ext in _IMAGE_EXTENSIONS or ext in _VIDEO_EXTENSIONS):
            size = parse_resolution((sidecars.get(name) or {}).get("resolution"))
        if size:
            dimensions[name] = {"width": size[0], "height": size[1]}
    return dimensions

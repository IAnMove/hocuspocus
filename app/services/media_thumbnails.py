"""Lazy, reusable static thumbnails for Maestro images and videos."""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import uuid


_thumbnail_locks_guard = threading.Lock()
_thumbnail_locks: dict[str, threading.Lock] = {}
# Opening the editor for the first time can request a page of thumbnails at
# once. Keep FFmpeg fan-out intentionally small so preview creation never
# competes with a generation for all CPU/disk bandwidth.
_thumbnail_generation_slots = threading.Semaphore(2)


def _lock_for(key: str) -> threading.Lock:
    with _thumbnail_locks_guard:
        return _thumbnail_locks.setdefault(key, threading.Lock())


def thumbnail_cache_key(source: str) -> str:
    stat = os.stat(source)
    identity = f"{os.path.realpath(source)}\0{stat.st_size}\0{stat.st_mtime_ns}"
    return hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()


def ensure_media_thumbnail(
    source: str,
    cache_dir: str,
    *,
    is_video: bool,
    width: int = 384,
    height: int = 216,
) -> str:
    """Return a cached JPEG preview, creating it atomically when necessary."""
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    key = thumbnail_cache_key(source)
    os.makedirs(cache_dir, exist_ok=True)
    destination = os.path.join(cache_dir, f"{key}-{width}x{height}.jpg")
    if os.path.isfile(destination) and os.path.getsize(destination) > 0:
        return destination

    with _lock_for(destination):
        if os.path.isfile(destination) and os.path.getsize(destination) > 0:
            return destination
        temporary = os.path.join(
            cache_dir,
            f".{key}-{uuid.uuid4().hex}.tmp.jpg",
        )
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )

        def capture(seek: bool) -> subprocess.CompletedProcess[str]:
            command = ["ffmpeg", "-v", "error", "-y"]
            if seek:
                command.extend(["-ss", "0.1"])
            command.extend(
                [
                    "-i",
                    source,
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-vf",
                    video_filter,
                    "-q:v",
                    "4",
                    temporary,
                ]
            )
            return subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=90,
                check=False,
            )

        try:
            with _thumbnail_generation_slots:
                result = capture(is_video)
                if result.returncode != 0 or not os.path.isfile(temporary) or os.path.getsize(temporary) <= 0:
                    # Very short/corrupt-timestamp videos occasionally have no
                    # frame at 0.1 s. A first-frame fallback covers those files.
                    result = capture(False)
            if result.returncode != 0 or not os.path.isfile(temporary) or os.path.getsize(temporary) <= 0:
                detail = (result.stderr or "FFmpeg did not produce a thumbnail").strip()
                raise RuntimeError(detail[-800:])
            os.replace(temporary, destination)
            return destination
        finally:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass

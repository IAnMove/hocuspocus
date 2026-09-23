"""Lazy, reusable static thumbnails for Maestro images and videos."""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
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


def _cached(destination: str) -> bool:
    """True for a usable cached preview; marks it recently used for LRU pruning."""
    try:
        stat = os.stat(destination)
    except OSError:
        return False
    if stat.st_size <= 0:
        return False
    if time.time() - stat.st_atime > 86_400:
        try:
            os.utime(destination, (time.time(), stat.st_mtime))
        except OSError:
            pass
    return True


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
    if _cached(destination):
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


# Gallery previews keep the source aspect (no letterbox) so cropped grid cells
# and justified mosaic rows show the picture rather than black bars. Stills are
# resized in-process: spawning FFmpeg per image made a page of fresh cards
# arrive two at a time behind the generation slots above.
FITTED_THUMBNAIL_SIZES = {"sm": 320, "md": 640}
_fitted_image_slots = threading.Semaphore(4)


def _write_atomically(destination: str, key: str, suffix: str, write) -> str:
    temporary = os.path.join(os.path.dirname(destination), f".{key}-{uuid.uuid4().hex}.tmp{suffix}")
    try:
        write(temporary)
        if not os.path.isfile(temporary) or os.path.getsize(temporary) <= 0:
            raise RuntimeError("thumbnail writer produced no data")
        os.replace(temporary, destination)
        return destination
    finally:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass


def ensure_fitted_thumbnail(source: str, cache_dir: str, *, is_video: bool, size: str) -> str:
    """Return a cached preview whose longest side is at most ``FITTED_THUMBNAIL_SIZES[size]``.

    Stills become WebP so transparent outputs stay transparent; videos become
    a JPEG of an early frame.
    """
    if size not in FITTED_THUMBNAIL_SIZES:
        raise ValueError(f"unknown thumbnail size: {size}")
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    limit = FITTED_THUMBNAIL_SIZES[size]
    key = thumbnail_cache_key(source)
    os.makedirs(cache_dir, exist_ok=True)
    suffix = ".jpg" if is_video else ".webp"
    destination = os.path.join(cache_dir, f"{key}-fit{limit}{suffix}")
    if _cached(destination):
        return destination

    def write_still(path: str) -> None:
        from PIL import Image, ImageOps

        with Image.open(source) as opened:
            opened.draft("RGB", (limit, limit))
            image = ImageOps.exif_transpose(opened)
            image.thumbnail((limit, limit), Image.Resampling.BICUBIC, reducing_gap=2.0)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            image.save(path, format="WEBP", quality=80, method=4)

    def write_frame(path: str) -> None:
        video_filter = f"scale=w='min({limit},iw)':h='min({limit},ih)':force_original_aspect_ratio=decrease"
        for seek in (True, False):
            command = ["ffmpeg", "-v", "error", "-y", *(["-ss", "0.1"] if seek else []),
                       "-i", source, "-map", "0:v:0", "-frames:v", "1", "-vf", video_filter, "-q:v", "4", path]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, timeout=90, check=False)
            if result.returncode == 0 and os.path.isfile(path) and os.path.getsize(path) > 0:
                return
        raise RuntimeError((result.stderr or "FFmpeg did not produce a thumbnail").strip()[-800:])

    with _lock_for(destination):
        if os.path.isfile(destination) and os.path.getsize(destination) > 0:
            return destination
        slots = _thumbnail_generation_slots if is_video else _fitted_image_slots
        with slots:
            return _write_atomically(destination, key, suffix, write_frame if is_video else write_still)

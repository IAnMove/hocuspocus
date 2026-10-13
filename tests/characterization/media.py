"""Tiny media files for characterization tests, made the same way on every machine."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

# A fixed clock for files the gallery sorts by modification time.
BASE_MTIME = 1_760_000_000


def need_ffmpeg() -> None:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg and ffprobe are needed on PATH (CI installs them)")


def video(path: Path, *, seconds: int = 1, size: str = "64x36", fps: int = 8) -> Path:
    """A silent MPEG-4 Part 2 clip: the encoder is built into every ffmpeg."""
    need_ffmpeg()
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=blue:s={size}:r={fps}:d={seconds}",
         "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-an", str(path)],
        check=True, timeout=60,
    )
    return path


def sound(path: Path, *, seconds: float = 0.5, rate: int = 8000) -> Path:
    """Silent 16-bit mono PCM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def image(path: Path, *, size: tuple[int, int] = (8, 8)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 40, 40)).save(path)
    return path


def sidecar(media: Path, meta: dict) -> Path:
    """The ``<name>.meta.json`` a generation writes next to its output."""
    path = media.with_name(media.stem + ".meta.json")
    path.write_text(json.dumps(meta), encoding="utf-8")
    return path


def stamp(path: Path, offset: int) -> None:
    os.utime(path, (BASE_MTIME + offset, BASE_MTIME + offset))

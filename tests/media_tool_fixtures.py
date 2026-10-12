"""Synthetic media and a two-workspace layout for the production media tool tests (no committed files)."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from services.production_media_commands import command_handlers

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="ffmpeg required")


class Install:
    """A base output folder: ``default`` is the base itself, other workspaces are its subfolders."""

    def __init__(self, tmp_path: Path) -> None:
        self.base = tmp_path / "outputs"
        self.uploads = tmp_path / "uploads"
        self.base.mkdir()
        self.uploads.mkdir()
        self.handlers = command_handlers(self.workspace_dir, lambda: str(self.uploads))

    def workspace_dir(self, name: str) -> str:
        if not isinstance(name, str) or not name or "/" in name or name.startswith((".", "_")):
            raise ValueError(name)
        return str(self.base if name == "default" else self.base / name)

    def folder(self, name: str) -> Path:
        path = Path(self.workspace_dir(name))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def call(self, operation: str, payload: dict, **envelope) -> dict:
        return asyncio.run(self.handlers[operation]({"version": 1, "input": payload, **envelope}))


def frames_video(path: Path, count: int = 24, fps: int = 24, size: tuple[int, int] = (64, 48), codec: str = "ffv1") -> None:
    """Frame ``i`` is a flat red of ``10 * i`` (so the first is black-red 0 and the last 10 * (count - 1))."""
    width, height = size
    raw = b"".join(np.full((height, width, 3), (10 * index, 40, 200), dtype=np.uint8).tobytes() for index in range(count))
    args = ["-c:v", "ffv1"] if codec == "ffv1" else ["-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                    "-r", str(fps), "-i", "pipe:0", *args, str(path)], input=raw, check=True, capture_output=True)


def tone(path: Path, seconds: float = 2.0, rate: int = 44100, channels: int = 2) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={rate}:duration={seconds}",
                    "-ac", str(channels), "-c:a", "pcm_s16le", str(path)], check=True, capture_output=True)


def probe(path: Path) -> dict:
    import json
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels,codec_name:format=duration",
                             "-of", "json", str(path)], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return {"duration": float(data["format"]["duration"]), "sample_rate": int(stream.get("sample_rate") or 0),
            "channels": int(stream.get("channels") or 0), "codec": stream.get("codec_name")}

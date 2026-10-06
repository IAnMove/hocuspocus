"""Encode rendered scene frames to delivery MP4 or an optional ProRes master (CPU)."""
from pathlib import Path
import os
import shutil
import struct
import subprocess
import zlib

from services.scene_recording import SceneRecordingTranscodeError


def write_png(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    row = b"\x00" + bytes(rgb) * width
    raw = row * height

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def mux_frame_sequence(frames: list[Path], destination: Path, *, fps: int, duration: float,
                       quality: str = "draft", width: int | None = None, height: int | None = None,
                       profiles: dict, level_for, validate_output, pending_error) -> Path:
    if not shutil.which("ffmpeg"):
        raise pending_error("real-render pending: ffmpeg is not available")
    if not frames:
        raise RuntimeError("Export produced no frames")
    temporary = destination.with_name(f".{destination.stem}.{os.getpid()}.partial.mp4")
    destination.parent.mkdir(parents=True, exist_ok=True)
    profile = profiles[quality]
    command = [
        "ffmpeg", "-v", "error", "-y", "-framerate", str(int(fps)),
        "-i", str(frames[0].parent / "frame_%06d.png"),
        "-c:v", "libx264", "-preset", profile["preset"], "-crf", str(profile["crf"]),
    ]
    if width and height:
        level = level_for(int(width), int(height), int(fps))
        if level:
            command.extend(["-level", level])
    command.extend([
        "-pix_fmt", "yuv420p", "-threads", profile["threads"],
        "-t", f"{float(duration):.3f}", "-movflags", "+faststart", str(temporary),
    ])
    try:
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=1800, check=False,
        )
        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            detail = (result.stderr or "FFmpeg did not produce an MP4").strip()
            raise RuntimeError(detail[-1000:])
        expected = duration if float(duration) >= 0.5 else None
        validate_output(temporary, expected_duration=expected, expected_fps=fps)
        os.replace(temporary, destination)
        return destination
    except SceneRecordingTranscodeError as error:
        raise RuntimeError(str(error)) from error
    finally:
        temporary.unlink(missing_ok=True)


def write_prores_master(frames: list[Path], destination: Path, *, fps: int, duration: float) -> Path:
    """Optional ProRes 422 HQ master from the same PNG sequence as the H.264 delivery."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ProRes master needs ffmpeg")
    if not frames:
        raise RuntimeError("Export produced no frames")
    temporary = destination.with_name(f".{destination.stem}.{os.getpid()}.partial.mov")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-v", "error", "-y", "-framerate", str(int(fps)),
        "-i", str(frames[0].parent / "frame_%06d.png"),
        "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le",
        "-t", f"{float(duration):.3f}", str(temporary),
    ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=1800, check=False,
        )
        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            detail = (result.stderr or "FFmpeg did not produce a ProRes master").strip()
            raise RuntimeError(detail[-1000:])
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)

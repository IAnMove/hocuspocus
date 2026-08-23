"""Finalize browser Scene Animator captures as gallery-ready MP4 files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class SceneRecordingTranscodeError(RuntimeError):
    """Raised when FFmpeg cannot finalize a browser recording."""


def build_scene_recording_command(
    source: str,
    destination: str,
    *,
    fps: int,
) -> list[str]:
    """Build a broadly playable H.264/yuv420p MP4 transcode command."""

    normalized_fps = 60 if int(fps) == 60 else 30
    return [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-vf",
        (
            f"fps={normalized_fps},"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"
        ),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-movflags",
        "+faststart",
        destination,
    ]


def transcode_scene_recording(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    fps: int,
    timeout: float = 1800,
) -> None:
    """Transcode atomically, exposing the MP4 only after FFmpeg succeeds."""

    source_path = Path(source)
    destination_path = Path(destination)
    temporary_path = destination_path.with_name(
        f".{destination_path.stem}.{os.getpid()}.partial.mp4"
    )
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            build_scene_recording_command(
                str(source_path),
                str(temporary_path),
                fps=fps,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        if (
            result.returncode != 0
            or not temporary_path.is_file()
            or temporary_path.stat().st_size <= 0
        ):
            detail = (result.stderr or "FFmpeg did not produce an MP4").strip()
            raise SceneRecordingTranscodeError(detail[-1000:])
        os.replace(temporary_path, destination_path)
    except subprocess.TimeoutExpired as error:
        raise SceneRecordingTranscodeError(
            "Timed out while converting the scene recording to MP4"
        ) from error
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass

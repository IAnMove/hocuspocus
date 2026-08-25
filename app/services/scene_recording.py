"""Finalize browser Scene Animator captures as gallery-ready MP4 files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, Mapping


class SceneRecordingTranscodeError(RuntimeError):
    """Raised when FFmpeg cannot finalize a browser recording."""


def build_scene_recording_command(
    source: str,
    destination: str,
    *,
    fps: int,
    audio_tracks: Iterable[Mapping[str, object]] = (),
    duration: float | None = None,
) -> list[str]:
    """Build a broadly playable H.264/yuv420p MP4 transcode command."""

    normalized_fps = 60 if int(fps) == 60 else 30
    tracks = list(audio_tracks)
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        source,
        *[part for track in tracks for part in ("-i", str(track["path"]))],
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
    ]
    if tracks:
        filters = []
        labels = []
        for index, track in enumerate(tracks, start=1):
            start_ms = max(0, round(float(track.get("start_time", 0)) * 1000))
            volume = max(0, min(2, float(track.get("volume", 1))))
            label = f"audio{index}"
            filters.append(f"[{index}:a]aresample=48000,adelay={start_ms}|{start_ms},volume={volume:.3f}[{label}]")
            labels.append(f"[{label}]")
        mixed = "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,apad"
        if duration and duration > 0:
            mixed += f",atrim=0:{float(duration):.3f}"
        command.extend(["-filter_complex", ";".join(filters + [f"{mixed}[mixed_audio]"]), "-map", "[mixed_audio]", "-c:a", "aac", "-b:a", "192k"])
    else:
        command.append("-an")
    if duration and duration > 0:
        command.extend(["-t", f"{float(duration):.3f}"])
    command.extend(["-movflags", "+faststart", destination])
    return command


def transcode_scene_recording(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    fps: int,
    audio_tracks: Iterable[Mapping[str, object]] = (),
    duration: float | None = None,
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
                audio_tracks=audio_tracks,
                duration=duration,
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

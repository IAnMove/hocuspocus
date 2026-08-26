"""Finalize browser Scene Animator captures as gallery-ready MP4 files."""

from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path
from typing import Iterable, Mapping


class SceneRecordingTranscodeError(RuntimeError):
    """Raised when FFmpeg cannot finalize a browser recording."""


def probe_scene_recording_output(path: str | os.PathLike[str]) -> dict[str, object]:
    """Return machine-readable stream/container metadata for a finalized MP4."""

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-show_format", os.fspath(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as error:
        raise SceneRecordingTranscodeError("ffprobe is not available to verify the MP4") from error
    if result.returncode != 0:
        detail = (result.stderr or "ffprobe could not read the MP4").strip()
        raise SceneRecordingTranscodeError(detail[-1000:])
    try:
        metadata = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise SceneRecordingTranscodeError("ffprobe returned invalid metadata") from error
    if not isinstance(metadata, dict):
        raise SceneRecordingTranscodeError("ffprobe returned invalid metadata")
    return metadata


def validate_scene_recording_output(
    path: str | os.PathLike[str],
    *,
    expected_duration: float | None = None,
    expected_fps: int | None = None,
    expected_audio: bool = False,
    tolerance: float | None = None,
) -> dict[str, object]:
    """Validate the playable streams and timing of a finalized scene MP4."""

    metadata = probe_scene_recording_output(path)
    streams = metadata.get("streams")
    if not isinstance(streams, list):
        raise SceneRecordingTranscodeError("Finalized MP4 has no readable streams")
    video = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"), None)
    if video is None or video.get("codec_name") != "h264":
        raise SceneRecordingTranscodeError("Finalized MP4 has no H.264 video stream")
    audio = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]
    if expected_audio and not audio:
        raise SceneRecordingTranscodeError("Finalized MP4 is missing the requested audio track")
    if expected_duration is not None and expected_duration > 0:
        format_data = metadata.get("format")
        raw_duration = video.get("duration") or (format_data.get("duration") if isinstance(format_data, dict) else None)
        try:
            actual_duration = float(raw_duration)
        except (TypeError, ValueError):
            actual_duration = 0.0
        allowed = tolerance if tolerance is not None else max(0.05, 1 / max(1, int(expected_fps or 30)))
        if actual_duration <= 0 or abs(actual_duration - expected_duration) > allowed:
            raise SceneRecordingTranscodeError(
                f"Finalized MP4 duration {actual_duration:.3f}s differs from target {expected_duration:.3f}s"
            )
    if audio and any(item.get("codec_name") != "aac" for item in audio):
        raise SceneRecordingTranscodeError("Finalized MP4 contains a non-AAC audio stream")
    return metadata


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
        target_frames = max(1, round(float(duration) * normalized_fps))
        command.extend(["-t", f"{float(duration):.3f}", "-frames:v", str(target_frames)])
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
    tracks = list(audio_tracks)
    try:
        result = subprocess.run(
            build_scene_recording_command(
                str(source_path),
                str(temporary_path),
                fps=fps,
                audio_tracks=tracks,
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
        validate_scene_recording_output(
            temporary_path,
            expected_duration=duration,
            expected_fps=fps,
            expected_audio=bool(tracks),
        )
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

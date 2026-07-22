"""Small, dependable FFmpeg assembly backend for Maestro's video editor.

The editor deliberately stores only references to uploads/workspace outputs.
Path validation remains the responsibility of the API layer; every path passed
to this module must already be resolved to a permitted local file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any


ProgressCallback = Callable[[int, str], None]


def _run(command: list[str], *, timeout: int, label: str) -> None:
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown FFmpeg error").strip()
        raise RuntimeError(f"{label} failed: {detail[-1200:]}")


def probe_media(path: str) -> dict[str, Any]:
    """Return the timing and primary stream information needed by the editor."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,width,height,r_frame_rate,pix_fmt:stream_tags=alpha_mode",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError((result.stderr or "ffprobe could not read this media file").strip()[-600:])

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe returned invalid media information") from exc

    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not video:
        raise ValueError("The selected file does not contain a video stream")

    duration = float((payload.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("The selected video has no readable duration")

    rate = str(video.get("r_frame_rate") or "0/1")
    try:
        numerator, denominator = rate.split("/", 1)
        fps = float(numerator) / max(float(denominator), 1)
    except (TypeError, ValueError, ZeroDivisionError):
        fps = 0

    pixel_format = str(video.get("pix_fmt") or "unknown").lower()
    alpha_formats = ("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya8", "ya16")
    video_tags = video.get("tags") if isinstance(video.get("tags"), dict) else {}
    alpha_mode = str(video_tags.get("ALPHA_MODE") or video_tags.get("alpha_mode") or "")

    return {
        "duration": round(duration, 4),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": round(fps, 3),
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
        "pixel_format": pixel_format,
        "has_alpha": alpha_mode == "1" or any(marker in pixel_format for marker in alpha_formats),
    }


def extract_frame(
    source: str,
    destination: str,
    time_seconds: float,
) -> dict[str, Any]:
    """Extract one accurately-seeked native-resolution PNG from a video."""
    media = probe_media(source)
    fps = max(float(media.get("fps") or 0), 1.0)
    duration = float(media["duration"])
    timestamp = max(0.0, min(float(time_seconds), duration - (1.0 / fps)))
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            source,
            "-ss",
            f"{timestamp:.6f}",
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-c:v",
            "png",
            destination,
        ],
        timeout=120,
        label=f"Capturing {os.path.basename(source)} at {timestamp:.3f}s",
    )
    return {
        "time": round(timestamp, 6),
        "width": int(media["width"]),
        "height": int(media["height"]),
    }


def _video_filter(width: int, height: int, fps: int, fit: str) -> str:
    if fit == "fill":
        sizing = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    else:
        sizing = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    return f"{sizing},fps={fps},setsar=1,format=yuv420p"


def _normalise_clip(
    source: str,
    destination: str,
    clip: dict[str, Any],
    width: int,
    height: int,
    fps: int,
) -> float:
    media = probe_media(source)
    source_duration = float(media["duration"])
    trim_start = max(0.0, min(float(clip.get("trim_start") or 0), source_duration - 0.05))
    requested_end = float(clip.get("trim_end") or source_duration)
    trim_end = max(trim_start + 0.05, min(requested_end, source_duration))
    duration = trim_end - trim_start
    volume = 0.0 if clip.get("muted") else max(0.0, min(float(clip.get("volume", 1)), 2.0))
    fit = "fill" if clip.get("fit") == "fill" else "fit"

    command = ["ffmpeg", "-y", "-ss", f"{trim_start:.6f}", "-i", source]
    if not media["has_audio"]:
        command.extend(
            ["-f", "lavfi", "-t", f"{duration:.6f}", "-i", "anullsrc=r=48000:cl=stereo"]
        )

    command.extend(["-t", f"{duration:.6f}", "-map", "0:v:0"])
    command.extend(["-map", "0:a:0" if media["has_audio"] else "1:a:0"])
    command.extend(
        [
            "-vf",
            _video_filter(width, height, fps, fit),
            "-af",
            f"aresample=48000:async=1:first_pts=0,volume={volume:.4f},apad",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            destination,
        ]
    )
    _run(command, timeout=max(300, int(duration * 20)), label=f"Preparing {os.path.basename(source)}")
    return duration


def _concat_without_transition(segments: list[str], output_path: str) -> None:
    if len(segments) == 1:
        shutil.copy2(segments[0], output_path)
        return

    list_path = os.path.join(os.path.dirname(segments[0]), "concat.txt")
    with open(list_path, "w", encoding="utf-8") as handle:
        for segment in segments:
            escaped = os.path.abspath(segment).replace("\\", "/").replace("'", "'\\''")
            handle.write(f"file '{escaped}'\n")
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_path,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            output_path,
        ],
        timeout=1200,
        label="Joining clips",
    )


def _concat_with_transitions(
    segments: list[str],
    durations: list[float],
    output_path: str,
    transitions: list[dict[str, Any]],
) -> None:
    command = ["ffmpeg", "-y"]
    for segment in segments:
        command.extend(["-i", segment])

    filters: list[str] = []
    video_label = "0:v"
    audio_label = "0:a"
    running_duration = durations[0]
    for index in range(1, len(segments)):
        out_video = f"v{index}"
        out_audio = f"a{index}"
        transition = transitions[index - 1]
        transition_type = str(transition.get("type") or "none")
        fade_duration = float(transition.get("duration") or 0)
        if transition_type == "none" or fade_duration <= 0:
            filters.append(
                f"[{video_label}][{index}:v]concat=n=2:v=1:a=0[{out_video}]"
            )
            filters.append(
                f"[{audio_label}][{index}:a]concat=n=2:v=0:a=1[{out_audio}]"
            )
            running_duration += durations[index]
        else:
            transition_name = {
                "crossfade": "fade",
                "fade-black": "fadeblack",
                "wipe-left": "wipeleft",
                "slide-left": "slideleft",
                "slide-right": "slideright",
                "circle-open": "circleopen",
                "dissolve": "dissolve",
                "pixelize": "pixelize",
                "blur": "hblur",
                "zoom-in": "zoomin",
            }.get(transition_type, "fade")
            offset = max(0.0, running_duration - fade_duration)
            filters.append(
                f"[{video_label}][{index}:v]xfade=transition={transition_name}:"
                f"duration={fade_duration:.6f}:offset={offset:.6f}[{out_video}]"
            )
            filters.append(
                f"[{audio_label}][{index}:a]acrossfade=d={fade_duration:.6f}:"
                f"c1=tri:c2=tri[{out_audio}]"
            )
            running_duration += durations[index] - fade_duration
        video_label = out_video
        audio_label = out_audio

    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{video_label}]",
            "-map",
            f"[{audio_label}]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            output_path,
        ]
    )
    _run(
        command,
        timeout=max(1200, int(sum(durations) * 30)),
        label="Rendering transitions",
    )


def render_project(
    clips: list[dict[str, Any]],
    output_path: str,
    *,
    width: int,
    height: int,
    fps: int,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Normalise, trim and assemble clips into a shareable H.264 MP4."""
    if not clips:
        raise ValueError("Add at least one video clip")
    if width < 240 or height < 240 or width > 3840 or height > 3840:
        raise ValueError("Output resolution must be between 240 and 3840 pixels")
    if width % 2 or height % 2:
        raise ValueError("Output width and height must be even numbers")
    if fps not in (24, 25, 30, 50, 60):
        raise ValueError("Unsupported frame rate")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    total_stages = len(clips) + 1
    with tempfile.TemporaryDirectory(prefix=".video_editor_", dir=os.path.dirname(output_path)) as temp_dir:
        segments: list[str] = []
        durations: list[float] = []
        for index, clip in enumerate(clips):
            if progress:
                progress(
                    round((index / total_stages) * 100),
                    f"Preparing clip {index + 1} of {len(clips)}…",
                )
            segment = os.path.join(temp_dir, f"segment_{index:04d}.mp4")
            durations.append(
                _normalise_clip(
                    str(clip["resolved_path"]),
                    segment,
                    clip,
                    width,
                    height,
                    fps,
                )
            )
            segments.append(segment)

        if progress:
            progress(
                round((len(clips) / total_stages) * 100),
                "Joining clips and writing the final MP4…",
            )
        transitions: list[dict[str, Any]] = []
        for index in range(max(0, len(clips) - 1)):
            transition_type = str(clips[index].get("transition") or "none")
            requested_duration = float(clips[index].get("transition_duration") or 0.4)
            actual_duration = (
                max(
                    0.05,
                    min(requested_duration, durations[index] * 0.45, durations[index + 1] * 0.45),
                )
                if transition_type != "none"
                else 0.0
            )
            transitions.append({"type": transition_type, "duration": actual_duration})

        if not any(item["type"] != "none" for item in transitions) or len(segments) == 1:
            _concat_without_transition(segments, output_path)
        else:
            _concat_with_transitions(
                segments,
                durations,
                output_path,
                transitions,
            )

    if progress:
        progress(100, "Video export complete")
    return {
        "duration": round(
            sum(durations)
            - sum(float(item["duration"]) for item in transitions),
            3,
        ),
        "clip_count": len(clips),
        "transitions": transitions,
    }


def _render_still_segment(
    source: str,
    destination: str,
    *,
    duration: float,
    width: int,
    height: int,
    fps: int,
    motion: str,
) -> None:
    """Turn one lettered comic panel into a silent animated video shot."""
    frames = max(2, round(duration * fps))
    progress = f"on/{max(frames - 1, 1)}"
    if motion == "pull-out":
        zoom = f"1.10-0.10*{progress}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan-left":
        zoom = "1.08"
        x = f"(iw-iw/zoom)*(1-{progress})"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan-right":
        zoom = "1.08"
        x = f"(iw-iw/zoom)*{progress}"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "none":
        zoom = "1"
        x = "0"
        y = "0"
    else:
        zoom = f"1+0.10*{progress}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
        "setsar=1,format=yuv420p"
    )
    _run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", source,
            "-f", "lavfi", "-t", f"{duration:.6f}",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-t", f"{duration:.6f}", "-map", "0:v:0", "-map", "1:a:0",
            "-vf", video_filter,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k", "-shortest", destination,
        ],
        timeout=max(180, int(duration * 30)),
        label=f"Animating {os.path.basename(source)}",
    )


def render_comic_animatic(
    panels: list[dict[str, Any]],
    output_path: str,
    *,
    width: int,
    height: int,
    fps: int = 30,
    transition: str = "crossfade",
    transition_duration: float = 0.35,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Render ordered, already-lettered comic panels as a cinematic animatic."""
    if not panels:
        raise ValueError("The comic has no panels to animate")
    if width < 240 or height < 240 or width > 3840 or height > 3840 or width % 2 or height % 2:
        raise ValueError("Invalid animatic resolution")
    if fps not in (24, 25, 30, 50, 60):
        raise ValueError("Unsupported animatic frame rate")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".comic_animatic_", dir=os.path.dirname(output_path)) as temp_dir:
        segments: list[str] = []
        durations: list[float] = []
        for index, panel in enumerate(panels):
            if progress:
                progress(round(index / (len(panels) + 1) * 100), f"Animating panel {index + 1} of {len(panels)}…")
            duration = max(0.8, min(float(panel.get("duration") or 3.0), 20.0))
            destination = os.path.join(temp_dir, f"panel_{index:04d}.mp4")
            _render_still_segment(
                str(panel["resolved_path"]), destination, duration=duration,
                width=width, height=height, fps=fps,
                motion=str(panel.get("motion") or "push-in"),
            )
            segments.append(destination)
            durations.append(duration)
        transitions = []
        for index in range(max(0, len(segments) - 1)):
            duration = max(0.05, min(transition_duration, durations[index] * .45, durations[index + 1] * .45)) if transition != "none" else 0
            transitions.append({"type": transition, "duration": duration})
        if len(segments) == 1 or transition == "none":
            _concat_without_transition(segments, output_path)
        else:
            _concat_with_transitions(segments, durations, output_path, transitions)
    if progress:
        progress(100, "Comic animatic complete")
    return {
        "duration": round(sum(durations) - sum(item["duration"] for item in transitions), 3),
        "clip_count": len(segments),
        "transitions": transitions,
    }

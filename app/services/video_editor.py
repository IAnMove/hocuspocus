"""Small, dependable FFmpeg assembly backend for Maestro's video editor.

The editor deliberately stores only references to uploads/workspace outputs.
Path validation remains the responsibility of the API layer; every path passed
to this module must already be resolved to a permitted local file.

Frame / PTS contract
--------------------
Assembly is counted in integer frames at the integer output fps
``{24, 25, 30, 50, 60}``. Seconds are the rational ``frames / fps``; they are
never rounded to 4 decimals and then multiplied back by fps.

Each source frame ``i`` covers the half-open interval ``[i/fps, (i+1)/fps)``.
Trim endpoints snap to the nearest source frame. A full-span clip whose
source fps matches the output fps keeps every decoded source frame: a
193-frame 30fps file stays 193 frames, not 192. The historical 589-from-590
export came from ``round(duration, 4)`` (6.4333s for 193/30) feeding ``-t``,
which stopped short of the last frame before concat.

Crossfades subtract ``round(overlap_seconds * fps)`` frames. Interstitial
time cards add ``round(card_seconds * fps)`` frames. Audio is padded to the
video span and compared by decoded samples / stream duration, not by
container duration alone. Export writes a staging file and replaces the
destination only after that validation; failures and cancels leave any
previous output untouched.
"""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import tempfile
from typing import Any

from services.video_editor_time_cards import (
    INTERSTITIAL_TRANSITIONS,
    is_interstitial_transition,
    normalise_time_card_text,
    _draw_time_card,
    _load_time_card_font,
    _materialise_time_cards,
    _render_time_card_segment,
    _time_card_text_width,
    _wrap_time_card_text,
)
from services.video_editor_frames import (
    AbortCallback,
    MIN_TRIM_SECONDS,
    ProgressCallback,
    SUPPORTED_FPS,
    VideoEditorCancelled,
    VideoEditorError,
    _check_abort,
    _concat_with_transitions,
    _concat_without_transition,
    _expected_concat_frames,
    _layout_filter,
    _normalise_clip,
    _promote_output,
    _run,
    _seconds_for_ffmpeg,
    _validate_export_artifact,
    count_decoded_video_frames,
    plan_clip_frames,
    plan_transition_frames,
    probe_assembly_source,
    probe_audio_timing,
)

SOURCE_SIDECAR_LIMIT_BYTES = 4 * 1024 * 1024


def _source_sidecar_path(source: str) -> str:
    return os.path.splitext(source)[0] + ".meta.json"


def _without_nested_source_manifest(metadata: dict[str, Any]) -> dict[str, Any]:
    """Keep source metadata reproducible without recursively nesting masters."""
    cleaned = dict(metadata)
    params = cleaned.get("params")
    if not isinstance(params, dict):
        return cleaned
    clean_params = dict(params)
    editor = clean_params.get("video_editor")
    if isinstance(editor, dict) and "source_manifest" in editor:
        clean_editor = dict(editor)
        clean_editor.pop("source_manifest", None)
        clean_params["video_editor"] = clean_editor
    cleaned["params"] = clean_params
    return cleaned


def build_source_provenance_manifest(
    clips: list[dict[str, Any]],
    *,
    max_sidecar_bytes: int = SOURCE_SIDECAR_LIMIT_BYTES,
) -> dict[str, Any]:
    """Collect portable source metadata for one assembled editor timeline.

    ``resolved_path`` is accepted only as an already validated API-layer input
    and is never serialized. A missing or malformed sidecar is recorded per
    clip so one legacy source cannot prevent the final video from exporting.
    """
    entries: list[dict[str, Any]] = []
    for index, clip in enumerate(clips):
        resolved = str(clip.get("resolved_path") or "")
        source = str(clip.get("source") or "")
        entry: dict[str, Any] = {
            "index": index,
            "name": str(clip.get("name") or os.path.basename(source) or f"Clip {index + 1}"),
            "source": source,
            "resolved_filename": os.path.basename(resolved) if resolved else None,
        }
        if not resolved:
            entry.update({"sidecar_status": "unavailable", "sidecar_filename": None})
            entries.append(entry)
            continue

        sidecar_path = _source_sidecar_path(resolved)
        entry["sidecar_filename"] = os.path.basename(sidecar_path)
        try:
            size = os.path.getsize(sidecar_path)
            if size > max(1, int(max_sidecar_bytes)):
                entry.update({"sidecar_status": "too_large", "sidecar_bytes": size})
            else:
                with open(sidecar_path, encoding="utf-8") as handle:
                    metadata = json.load(handle)
                if not isinstance(metadata, dict):
                    raise ValueError("source sidecar root is not an object")
                entry.update({
                    "sidecar_status": "embedded",
                    "sidecar_bytes": size,
                    "metadata": _without_nested_source_manifest(metadata),
                })
        except FileNotFoundError:
            entry["sidecar_status"] = "missing"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            entry.update({"sidecar_status": "unreadable", "sidecar_error": str(exc)[:300]})
        entries.append(entry)
    return {"version": 1, "clips": entries}


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


def probe_audio(path: str) -> dict[str, Any]:
    """Return duration for an audio source, rejecting files without audio."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration:stream=codec_type",
            "-of", "json", path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError((result.stderr or "ffprobe could not read this audio file").strip()[-600:])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe returned invalid audio information") from exc
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise ValueError("The selected file does not contain an audio stream")
    duration = float((payload.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("The selected audio has no readable duration")
    return {"duration": round(duration, 4), "has_audio": True}


def _mix_soundtrack(
    video_path: str,
    output_path: str,
    soundtrack: dict[str, Any],
    duration: float,
) -> None:
    """Mix one validated soundtrack over the assembled video's own audio."""
    source = str(soundtrack["resolved_path"])
    trim_start = max(0.0, float(soundtrack.get("trim_start") or 0))
    trim_end = float(soundtrack.get("trim_end") or 0)
    available = max(0.05, trim_end - trim_start) if trim_end > trim_start else duration
    mix_duration = duration if bool(soundtrack.get("loop")) else min(available, duration)
    raw_volume = soundtrack.get("volume")
    volume = max(0.0, min(2.0, float(1 if raw_volume is None else raw_volume)))
    command = ["ffmpeg", "-y", "-i", video_path]
    if bool(soundtrack.get("loop")):
        command.extend(["-stream_loop", "-1"])
    if trim_start:
        command.extend(["-ss", f"{trim_start:.6f}"])
    command.extend([
        "-i", source,
        "-filter_complex",
        (
            f"[1:a:0]atrim=duration={mix_duration:.6f},"
            f"asetpts=PTS-STARTPTS,volume={volume:.4f}[music];"
            "[0:a:0][music]amix=inputs=2:duration=first:dropout_transition=0,"
            f"apad,atrim=duration={duration:.6f}[mixed]"
        ),
        "-map", "0:v:0", "-map", "[mixed]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", output_path,
    ])
    _run(
        command,
        timeout=1800,
        label="Mixing editor soundtrack",
        phase="soundtrack",
        output={"path": os.path.basename(output_path)},
    )


def extract_frame(
    source: str,
    destination: str,
    time_seconds: float,
) -> dict[str, Any]:
    """Extract one accurately-seeked native-resolution PNG from a video."""
    media = probe_media(source)
    fps = max(float(media.get("fps") or 0), 1.0)
    duration = float(media["duration"])
    requested = max(0.0, float(time_seconds))
    # Container duration can extend a fraction beyond the final video PTS.
    # Seeking to duration-1/fps may then return success but write no frame.
    end_margin_frames = 2 if requested >= duration - (1.0 / fps) else 1
    timestamp = max(0.0, min(requested, duration - (end_margin_frames / fps)))

    def capture(at: float) -> None:
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                source,
                "-ss",
                f"{at:.6f}",
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-c:v",
                "png",
                destination,
            ],
            timeout=120,
            label=f"Capturing {os.path.basename(source)} at {at:.3f}s",
        )

    capture(timestamp)
    if not os.path.isfile(destination) or os.path.getsize(destination) <= 0:
        timestamp = max(0.0, duration - (3.0 / fps))
        capture(timestamp)
    if not os.path.isfile(destination) or os.path.getsize(destination) <= 0:
        raise RuntimeError(
            f"FFmpeg did not produce a frame from {os.path.basename(source)} "
            f"near {time_seconds:.3f}s."
        )
    return {
        "time": round(timestamp, 6),
        "width": int(media["width"]),
        "height": int(media["height"]),
    }


def _video_filter(width: int, height: int, fps: int, fit: str) -> str:
    return f"{_layout_filter(width, height, fit)},fps={fps}"


def render_project(
    clips: list[dict[str, Any]],
    output_path: str,
    *,
    width: int,
    height: int,
    fps: int,
    soundtrack: dict[str, Any] | None = None,
    progress: ProgressCallback | None = None,
    abort_callback: AbortCallback | None = None,
) -> dict[str, Any]:
    """Normalise, trim and assemble clips into a shareable H.264 MP4."""
    if not clips:
        raise ValueError("Add at least one video clip")
    if width < 240 or height < 240 or width > 3840 or height > 3840:
        raise ValueError("Output resolution must be between 240 and 3840 pixels")
    if width % 2 or height % 2:
        raise ValueError("Output width and height must be even numbers")
    if fps not in SUPPORTED_FPS:
        raise ValueError("Unsupported frame rate")

    destination = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    total_stages = len(clips) + 1
    with tempfile.TemporaryDirectory(
        prefix=".video_editor_",
        dir=os.path.dirname(destination),
    ) as temp_dir:
        segments: list[str] = []
        clip_frames: list[int] = []
        durations: list[float] = []
        for index, clip in enumerate(clips):
            _check_abort(abort_callback, phase="normalise")
            if progress:
                progress(
                    round((index / total_stages) * 100),
                    f"Preparing clip {index + 1} of {len(clips)}…",
                )
            segment = os.path.join(temp_dir, f"segment_{index:04d}.mp4")
            frames = _normalise_clip(
                str(clip["resolved_path"]),
                segment,
                clip,
                width,
                height,
                fps,
            )
            clip_frames.append(frames)
            durations.append(frames / fps)
            segments.append(segment)

        _check_abort(abort_callback, phase="concat")
        if progress:
            progress(
                round((len(clips) / total_stages) * 100),
                "Joining clips and writing the final MP4…",
            )
        transitions: list[dict[str, Any]] = []
        for index in range(max(0, len(clips) - 1)):
            transition_type = str(clips[index].get("transition") or "none")
            requested_duration = float(clips[index].get("transition_duration") or 0.4)
            actual_duration = max(0.5, min(requested_duration, 5.0)) if is_interstitial_transition(transition_type) else (
                max(
                    MIN_TRIM_SECONDS,
                    min(requested_duration, durations[index] * 0.45, durations[index + 1] * 0.45),
                )
                if transition_type != "none"
                else 0.0
            )
            if transition_type != "none" and not is_interstitial_transition(transition_type):
                fade_frames = plan_transition_frames(
                    actual_duration, fps, clip_frames[index], clip_frames[index + 1],
                )
                actual_duration = fade_frames / fps if fade_frames else 0.0
            transitions.append({
                "type": transition_type,
                "duration": actual_duration,
                "text": normalise_time_card_text(clips[index].get("transition_text")),
                "text_size": max(50.0, min(160.0, float(clips[index].get("transition_text_size") or 100))),
            })

        if any(is_interstitial_transition(item["type"]) for item in transitions):
            if progress:
                progress(88, "Creating time-card transitions…")
            render_segments, render_durations, render_transitions = _materialise_time_cards(
                segments,
                durations,
                transitions,
                temp_dir=temp_dir,
                width=width,
                height=height,
                fps=fps,
            )
        else:
            render_segments, render_durations, render_transitions = segments, durations, transitions

        render_frame_counts = [
            max(1, int(round(float(duration) * fps))) for duration in render_durations
        ]
        expected_frames = _expected_concat_frames(render_frame_counts, render_transitions, fps)
        assembled_path = os.path.join(temp_dir, "assembled.mp4")
        if not any(item["type"] != "none" for item in render_transitions) or len(render_segments) == 1:
            _concat_without_transition(
                render_segments,
                assembled_path,
                fps=fps,
                expected_frames=expected_frames,
                frame_counts=render_frame_counts,
            )
        else:
            _concat_with_transitions(
                render_segments,
                render_durations,
                assembled_path,
                render_transitions,
                fps=fps,
                frame_counts=render_frame_counts,
            )

        staging_path = assembled_path
        duration_seconds = expected_frames / fps
        if soundtrack:
            _check_abort(abort_callback, phase="soundtrack")
            if progress:
                progress(96, "Mixing external soundtrack…")
            mixed_path = os.path.join(temp_dir, "final.mp4")
            _mix_soundtrack(assembled_path, mixed_path, soundtrack, duration_seconds)
            staging_path = mixed_path

        if progress:
            progress(98, "Validating exported frames and audio…")
        accounting = _validate_export_artifact(
            staging_path,
            expected_frames=expected_frames,
            fps=fps,
            expect_audio=True,
            phase="validate",
        )
        _check_abort(abort_callback, phase="validate")
        _promote_output(staging_path, destination)

    if progress:
        progress(100, "Video export complete")
    return {
        "duration": round(duration_seconds, 3),
        "frames": expected_frames,
        "fps": fps,
        "clip_count": len(clips),
        "transitions": transitions,
        "audio_seconds": accounting.get("audio_seconds"),
    }


def _comic_preview_video_filter(
    *,
    duration: float,
    width: int,
    height: int,
    fps: int,
    motion: str,
) -> str:
    """Build a restrained FFmpeg filter that never crops comic artwork."""
    frames = max(2, round(duration * fps))
    progress = f"on/{max(frames - 1, 1)}"
    if motion == "pull-out":
        zoom = f"1.04-0.04*{progress}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan-left":
        zoom = "1.04"
        x = f"(iw-iw/zoom)*(1-{progress})"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan-right":
        zoom = "1.04"
        x = f"(iw-iw/zoom)*{progress}"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "none":
        zoom = "1"
        x = "0"
        y = "0"
    else:
        zoom = f"1+0.04*{progress}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
        "setsar=1,format=yuv420p"
    )


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
    """Turn one lettered comic panel into a silent storyboard-preview shot."""
    video_filter = _comic_preview_video_filter(
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        motion=motion,
    )
    frames = max(2, round(duration * fps))
    span = _seconds_for_ffmpeg(frames, fps)
    _run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", source,
            "-f", "lavfi", "-t", span,
            "-i", "anullsrc=r=48000:cl=stereo",
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", video_filter,
            "-frames:v", str(frames),
            "-fps_mode", "cfr", "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k", destination,
        ],
        timeout=max(180, int(frames / fps * 30) + 30),
        label=f"Animating {os.path.basename(source)}",
        phase="animatic",
        output={"path": os.path.basename(source), "frames": frames, "fps": fps},
    )


def render_comic_animatic(
    panels: list[dict[str, Any]],
    output_path: str,
    *,
    width: int,
    height: int,
    fps: int = 30,
    transition: str = "none",
    transition_duration: float = 0.35,
    progress: ProgressCallback | None = None,
    abort_callback: AbortCallback | None = None,
) -> dict[str, Any]:
    """Render ordered, already-lettered comic panels as a cinematic animatic."""
    if not panels:
        raise ValueError("The comic has no panels to animate")
    if width < 240 or height < 240 or width > 3840 or height > 3840 or width % 2 or height % 2:
        raise ValueError("Invalid animatic resolution")
    if fps not in SUPPORTED_FPS:
        raise ValueError("Unsupported animatic frame rate")
    destination = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".comic_animatic_",
        dir=os.path.dirname(destination),
    ) as temp_dir:
        segments: list[str] = []
        durations: list[float] = []
        frame_counts: list[int] = []
        for index, panel in enumerate(panels):
            _check_abort(abort_callback, phase="animatic")
            if progress:
                progress(round(index / (len(panels) + 1) * 100), f"Animating panel {index + 1} of {len(panels)}…")
            duration = max(0.8, min(float(panel.get("duration") or 3.0), 20.0))
            frames = max(2, round(duration * fps))
            panel_path = os.path.join(temp_dir, f"panel_{index:04d}.mp4")
            _render_still_segment(
                str(panel["resolved_path"]), panel_path, duration=duration,
                width=width, height=height, fps=fps,
                motion=str(panel.get("motion") or "none"),
            )
            segments.append(panel_path)
            durations.append(frames / fps)
            frame_counts.append(frames)
        transitions = []
        for index in range(max(0, len(segments) - 1)):
            if transition == "none":
                fade = 0.0
            else:
                fade_frames = plan_transition_frames(
                    transition_duration, fps, frame_counts[index], frame_counts[index + 1],
                )
                fade = fade_frames / fps if fade_frames else 0.0
            transitions.append({"type": transition, "duration": fade})
        assembled_path = os.path.join(temp_dir, "assembled.mp4")
        expected_frames = _expected_concat_frames(frame_counts, transitions, fps)
        if len(segments) == 1 or transition == "none":
            _concat_without_transition(
                segments,
                assembled_path,
                fps=fps,
                expected_frames=expected_frames,
                frame_counts=frame_counts,
            )
        else:
            _concat_with_transitions(
                segments,
                durations,
                assembled_path,
                transitions,
                fps=fps,
                frame_counts=frame_counts,
            )
        accounting = _validate_export_artifact(
            assembled_path,
            expected_frames=expected_frames,
            fps=fps,
            expect_audio=True,
            phase="validate",
        )
        _check_abort(abort_callback, phase="validate")
        _promote_output(assembled_path, destination)
    if progress:
        progress(100, "Comic animatic complete")
    return {
        "duration": round(expected_frames / fps, 3),
        "frames": expected_frames,
        "fps": fps,
        "clip_count": len(segments),
        "transitions": transitions,
        "audio_seconds": accounting.get("audio_seconds"),
    }

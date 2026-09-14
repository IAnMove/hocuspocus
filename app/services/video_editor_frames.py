"""Frame-accurate FFmpeg assembly helpers for the Video Editor.

Keep integer frame counts as the source of truth. Container duration rounded
to four decimals must not drive ``-t`` or concat; that dropped the last frame
of a 193-frame 30fps clip (historical 589-from-590 export).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from fractions import Fraction
from typing import Any

ProgressCallback = Callable[[int, str], None]
AbortCallback = Callable[[], bool]

MIN_TRIM_SECONDS = 0.05
SUPPORTED_FPS = (24, 25, 30, 50, 60)
_AUDIO_PAD_TOLERANCE_SECONDS = 0.25


class VideoEditorError(RuntimeError):
    """Assembly failure that names the phase and the output facts we have."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        output: dict[str, Any] | None = None,
    ) -> None:
        self.phase = str(phase)
        self.output = dict(output or {})
        detail = f"[{self.phase}] {message}"
        if self.output:
            facts = ", ".join(f"{key}={value}" for key, value in self.output.items())
            detail = f"{detail} ({facts})"
        super().__init__(detail)


class VideoEditorCancelled(VideoEditorError):
    """Raised when an export stops before promoting a new artifact."""


def _seconds_for_ffmpeg(frames: int, fps: int) -> str:
    """Format a rational frame span for FFmpeg time options."""
    return f"{int(frames) / int(fps):.10f}"


def _rate_fraction(value: Any) -> Fraction:
    text = str(value or "0/1").strip()
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            return Fraction(int(numerator), max(int(denominator), 1))
        return Fraction(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return Fraction(0)


def plan_clip_frames(
    *,
    source_frames: int,
    source_fps: Fraction,
    output_fps: int,
    trim_start: float = 0.0,
    trim_end: float | None = None,
) -> tuple[int, int, int]:
    """Return ``(start_frame, end_frame, output_frames)`` in half-open source frames.

    ``end_frame`` is exclusive. When the trim covers the whole source and the
    rates match, ``output_frames == source_frames``.
    """
    frames = max(0, int(source_frames))
    rate = source_fps if isinstance(source_fps, Fraction) else _rate_fraction(source_fps)
    if frames < 1 or rate <= 0:
        raise VideoEditorError(
            "Source video has no countable frames",
            phase="probe",
            output={"source_frames": frames, "source_fps": str(rate)},
        )
    min_source = max(1, int(round(MIN_TRIM_SECONDS * float(rate))))
    start = int(round(max(0.0, float(trim_start)) * float(rate)))
    start = max(0, min(start, max(0, frames - min_source)))
    if trim_end is None:
        end = frames
    else:
        end = int(round(max(0.0, float(trim_end)) * float(rate)))
        end = max(start + min_source, min(end, frames))
        end = min(end, frames)
        if end <= start:
            end = min(frames, start + 1)
    span = max(1, end - start)
    if rate == Fraction(int(output_fps), 1):
        output_frames = span
    else:
        output_frames = max(1, int(round(span * int(output_fps) / rate)))
    return start, end, output_frames


def plan_transition_frames(
    duration: float,
    fps: int,
    left_frames: int,
    right_frames: int,
) -> int:
    """Snap an overlapping transition to whole frames, capped at 45% of each side."""
    max_overlap = min(max(0, int(left_frames) - 1), max(0, int(right_frames) - 1))
    if max_overlap < 1:
        return 0
    requested = max(MIN_TRIM_SECONDS, float(duration))
    capped_seconds = min(requested, (min(left_frames, right_frames) * 0.45) / fps)
    overlap = int(round(capped_seconds * fps))
    return max(1, min(overlap, max_overlap))


def count_decoded_video_frames(path: str, *, timeout: int = 120) -> int:
    """Count decoded video frames; container duration is not used."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames,nb_frames",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise VideoEditorError(
            (result.stderr or "ffprobe could not count frames").strip()[-600:],
            phase="probe",
            output={"path": os.path.basename(path)},
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VideoEditorError(
            "ffprobe returned invalid frame information",
            phase="probe",
            output={"path": os.path.basename(path)},
        ) from exc
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    stream = streams[0] if streams else {}
    for key in ("nb_read_frames", "nb_frames"):
        raw = stream.get(key)
        if raw in (None, "", "N/A"):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    raise VideoEditorError(
        "Could not count decoded video frames",
        phase="probe",
        output={"path": os.path.basename(path)},
    )


def probe_audio_timing(path: str, *, timeout: int = 60) -> dict[str, Any] | None:
    """Audio stream duration and sample rate from the stream, not the container."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "format=duration:stream=codec_type,duration,sample_rate,nb_frames",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not audio:
        return None
    try:
        duration = float(audio.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        try:
            duration = float((payload.get("format") or {}).get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
    try:
        sample_rate = int(audio.get("sample_rate") or 0)
    except (TypeError, ValueError):
        sample_rate = 0
    if duration <= 0 and sample_rate <= 0:
        return None
    return {
        "duration": duration,
        "sample_rate": sample_rate,
        "has_audio": True,
    }


def probe_assembly_source(path: str) -> dict[str, Any]:
    """Frame-accurate source facts for export. UI probe stays on ``probe_media``."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,width,height,r_frame_rate,avg_frame_rate,nb_frames",
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
        raise VideoEditorError(
            (result.stderr or "ffprobe could not read this media file").strip()[-600:],
            phase="probe",
            output={"path": os.path.basename(path)},
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VideoEditorError(
            "ffprobe returned invalid media information",
            phase="probe",
            output={"path": os.path.basename(path)},
        ) from exc
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not video:
        raise VideoEditorError(
            "The selected file does not contain a video stream",
            phase="probe",
            output={"path": os.path.basename(path)},
        )
    rate = _rate_fraction(video.get("avg_frame_rate"))
    if rate <= 0:
        rate = _rate_fraction(video.get("r_frame_rate"))
    if rate <= 0:
        raise VideoEditorError(
            "The selected video has no readable frame rate",
            phase="probe",
            output={"path": os.path.basename(path)},
        )
    nb_frames = 0
    raw_frames = video.get("nb_frames")
    if raw_frames not in (None, "", "N/A"):
        try:
            nb_frames = int(raw_frames)
        except (TypeError, ValueError):
            nb_frames = 0
    if nb_frames < 1:
        nb_frames = count_decoded_video_frames(path)
    return {
        "nb_frames": nb_frames,
        "fps": rate,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
        "duration": float(nb_frames / rate) if rate else 0.0,
    }


def _check_abort(abort_callback: AbortCallback | None, *, phase: str) -> None:
    if abort_callback is not None and abort_callback():
        raise VideoEditorCancelled(
            "Export cancelled before the artifact was finalised",
            phase=phase,
        )


def _promote_output(staging_path: str, output_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    os.replace(staging_path, output_path)


def _validate_export_artifact(
    path: str,
    *,
    expected_frames: int,
    fps: int,
    expect_audio: bool = True,
    phase: str = "validate",
) -> dict[str, Any]:
    facts = {
        "path": os.path.basename(path),
        "expected_frames": int(expected_frames),
        "fps": int(fps),
    }
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise VideoEditorError(
            "FFmpeg produced no output file",
            phase=phase,
            output=facts,
        )
    frames = count_decoded_video_frames(path)
    facts["frames"] = frames
    if frames != int(expected_frames):
        raise VideoEditorError(
            f"Assembled video has {frames} decoded frames, expected {expected_frames}",
            phase=phase,
            output=facts,
        )
    audio = probe_audio_timing(path)
    facts["has_audio"] = bool(audio)
    video_seconds = int(expected_frames) / int(fps)
    facts["video_seconds"] = video_seconds
    if expect_audio:
        if not audio:
            raise VideoEditorError(
                "Assembled video has no audio stream to compare",
                phase=phase,
                output=facts,
            )
        audio_seconds = float(audio["duration"] or 0)
        facts["audio_seconds"] = audio_seconds
        if audio_seconds + max(1.0 / fps, 0.05) < video_seconds:
            raise VideoEditorError(
                "Assembled audio is shorter than the video span",
                phase=phase,
                output=facts,
            )
        if audio_seconds > video_seconds + _AUDIO_PAD_TOLERANCE_SECONDS:
            raise VideoEditorError(
                "Assembled audio is much longer than the video span",
                phase=phase,
                output=facts,
            )
    return facts


def _run(
    command: list[str],
    *,
    timeout: int,
    label: str,
    phase: str = "ffmpeg",
    output: dict[str, Any] | None = None,
) -> None:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VideoEditorError(
            f"{label} timed out after {timeout}s",
            phase=phase,
            output=output,
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown FFmpeg error").strip()
        raise VideoEditorError(
            f"{label} failed: {detail[-1200:]}",
            phase=phase,
            output=output,
        )


def _layout_filter(width: int, height: int, fit: str) -> str:
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
    return f"{sizing},setsar=1,format=yuv420p"


def _normalise_clip(
    source: str,
    destination: str,
    clip: dict[str, Any],
    width: int,
    height: int,
    fps: int,
) -> int:
    media = probe_assembly_source(source)
    trim_end_raw = clip.get("trim_end")
    try:
        trim_end = float(trim_end_raw) if trim_end_raw not in (None, "", 0, 0.0) else None
    except (TypeError, ValueError):
        trim_end = None
    start_frame, end_frame, output_frames = plan_clip_frames(
        source_frames=int(media["nb_frames"]),
        source_fps=media["fps"],
        output_fps=fps,
        trim_start=float(clip.get("trim_start") or 0),
        trim_end=trim_end,
    )
    volume = 0.0 if clip.get("muted") else max(0.0, min(float(clip.get("volume", 1)), 2.0))
    fit = "fill" if clip.get("fit") == "fill" else "fit"
    video_span = _seconds_for_ffmpeg(output_frames, fps)
    source_rate = float(media["fps"])
    audio_start = start_frame / source_rate
    audio_end = end_frame / source_rate
    video_graph = (
        f"{_layout_filter(width, height, fit)},"
        f"trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS,"
        f"fps={fps},tpad=stop_mode=clone:stop=2,"
        f"trim=end_frame={output_frames},setpts=N/{fps}/TB"
    )
    audio_graph = (
        f"atrim=start={audio_start:.10f}:end={audio_end:.10f},asetpts=PTS-STARTPTS,"
        f"aresample=48000:async=1:first_pts=0,volume={volume:.4f},"
        f"apad,atrim=duration={video_span}"
    )
    command = ["ffmpeg", "-y", "-i", source]
    facts = {
        "path": os.path.basename(source),
        "start_frame": start_frame,
        "end_frame": end_frame,
        "output_frames": output_frames,
        "fps": fps,
    }
    if media["has_audio"]:
        command.extend(
            [
                "-filter_complex",
                f"[0:v:0]{video_graph}[vout];[0:a:0]{audio_graph}[aout]",
                "-map",
                "[vout]",
                "-map",
                "[aout]",
            ]
        )
    else:
        command.extend(
            [
                "-f",
                "lavfi",
                "-t",
                video_span,
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-filter_complex",
                (
                    f"[0:v:0]{video_graph}[vout];"
                    f"[1:a:0]volume={volume:.4f},atrim=duration={video_span},"
                    "asetpts=PTS-STARTPTS[aout]"
                ),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
            ]
        )
    command.extend(
        [
            "-frames:v",
            str(output_frames),
            "-fps_mode",
            "cfr",
            "-r",
            str(fps),
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
            "-muxpreload",
            "0",
            "-muxdelay",
            "0",
            destination,
        ]
    )
    _run(
        command,
        timeout=max(300, int(output_frames / fps * 20) + 30),
        label=f"Preparing {os.path.basename(source)}",
        phase="normalise",
        output=facts,
    )
    return output_frames


def _concat_without_transition(
    segments: list[str],
    output_path: str,
    *,
    fps: int | None = None,
    expected_frames: int | None = None,
    frame_counts: list[int] | None = None,
) -> None:
    if len(segments) == 1:
        shutil.copy2(segments[0], output_path)
        return

    # Packet-copy concat keeps AAC priming/padding at each cut and shifts speech
    # against the frame-counted picture. Decode each segment onto the same clock.
    counts = list(frame_counts) if frame_counts is not None else [
        count_decoded_video_frames(segment) for segment in segments
    ]
    output_fps = int(fps or probe_assembly_source(segments[0])["fps"])
    _concat_with_transitions(
        segments, [count / output_fps for count in counts], output_path,
        [{"type": "none", "duration": 0} for _ in segments[1:]],
        fps=output_fps, frame_counts=counts,
    )


def _concat_with_transitions(
    segments: list[str],
    durations: list[float],
    output_path: str,
    transitions: list[dict[str, Any]],
    *,
    fps: int | None = None,
    frame_counts: list[int] | None = None,
) -> None:
    command = ["ffmpeg", "-y", "-filter_complex_threads", "1"]
    for segment in segments:
        # Many short shots must not allocate one full decoder thread pool each.
        command.extend(["-threads", "1", "-i", segment])

    output_fps = int(fps or 30)
    counts = list(frame_counts) if frame_counts is not None else [
        max(1, int(round(float(duration) * output_fps))) for duration in durations
    ]
    filters: list[str] = []
    for index, count in enumerate(counts):
        filters.append(
            f"[{index}:v]fps={output_fps},setpts=N/{output_fps}/TB,"
            f"tpad=stop_mode=clone:stop=2,trim=end_frame={count},"
            f"setpts=N/{output_fps}/TB[v{index}s]"
        )
        filters.append(
            f"[{index}:a]aresample=48000,apad,"
            f"atrim=end_sample={round(count * 48000 / output_fps)},"
            f"asetpts=N/SR/TB[a{index}s]"
        )
    video_label = "v0s"
    audio_label = "a0s"
    running_frames = counts[0]
    for index in range(1, len(segments)):
        out_video = f"v{index}"
        out_audio = f"a{index}"
        transition = transitions[index - 1]
        transition_type = str(transition.get("type") or "none")
        fade_duration = float(transition.get("duration") or 0)
        if transition_type == "none" or fade_duration <= 0:
            # concat resets the timebase to AV_TIME_BASE (1/1000000). Restore
            # 1/fps so a later xfade does not reject the graph.
            filters.append(
                f"[{video_label}][v{index}s]concat=n=2:v=1:a=0,"
                f"settb=1/{output_fps},setpts=N/{output_fps}/TB[{out_video}]"
            )
            filters.append(
                f"[{audio_label}][a{index}s]concat=n=2:v=0:a=1,"
                f"aresample=48000,asetpts=PTS-STARTPTS[{out_audio}]"
            )
            running_frames += counts[index]
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
            fade_frames = max(1, int(round(fade_duration * output_fps)))
            fade_frames = min(fade_frames, max(1, running_frames - 1), max(1, counts[index] - 1))
            offset = max(0, running_frames - fade_frames)
            fade_seconds = _seconds_for_ffmpeg(fade_frames, output_fps)
            offset_seconds = _seconds_for_ffmpeg(offset, output_fps)
            filters.append(
                f"[{video_label}]settb=1/{output_fps},setpts=N/{output_fps}/TB[v{index}l];"
                f"[v{index}s]settb=1/{output_fps},setpts=N/{output_fps}/TB[v{index}r];"
                f"[v{index}l][v{index}r]xfade=transition={transition_name}:"
                f"duration={fade_seconds}:offset={offset_seconds}[{out_video}]"
            )
            filters.append(
                f"[{audio_label}]aresample=48000,asetpts=PTS-STARTPTS[a{index}l];"
                f"[a{index}s]aresample=48000,asetpts=PTS-STARTPTS[a{index}r];"
                f"[a{index}l][a{index}r]acrossfade=d={fade_seconds}:"
                f"c1=tri:c2=tri[{out_audio}]"
            )
            running_frames += counts[index] - fade_frames
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
            "-frames:v",
            str(running_frames),
            "-fps_mode",
            "cfr",
            "-r",
            str(output_fps),
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
        phase="concat",
        output={"segments": len(segments), "expected_frames": running_frames, "fps": output_fps},
    )


def _expected_concat_frames(
    frame_counts: list[int],
    transitions: list[dict[str, Any]],
    fps: int,
) -> int:
    if not frame_counts:
        return 0
    total = int(frame_counts[0])
    for index, transition in enumerate(transitions):
        incoming = int(frame_counts[index + 1])
        kind = str(transition.get("type") or "none")
        fade = float(transition.get("duration") or 0)
        if kind == "none" or fade <= 0:
            total += incoming
        elif kind in {"later-clock", "later-tropical", "later-cinematic"}:
            total += max(1, int(round(fade * fps))) + incoming
        else:
            total += incoming - max(1, int(round(fade * fps)))
    return total

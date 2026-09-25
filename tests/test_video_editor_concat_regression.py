"""Regression for the historical 193+197+200 → 589-frame Video Editor export.

Evidence E10 (job video-edit-3fb2aa82bd8e on 10aa6f0d) received 590 frames and
wrote 589. On current development the drop is still in ``_normalise_clip``:
``probe_media`` rounds 193/30s to 6.4333, ``-t 6.433300`` plus ``fps=30``
emits 192 frames, concat then yields 589. This module reproduces that case
with synthetic FFmpeg media and requires the export path to keep 590 decoded
frames.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from app.services import video_editor


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)


def _run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError((result.stderr or result.stdout or "")[-1200:])
    return result


def write_color_clip(
    path: Path,
    frames: int,
    *,
    fps: int = 30,
    color: str = "red",
    audio: bool = True,
    width: int = 320,
    height: int = 240,
) -> None:
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:r={fps}",
    ]
    if audio:
        duration = frames / fps
        command += [
            "-f", "lavfi", "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration:.10f}",
        ]
    command += [
        "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    ]
    if audio:
        command += ["-c:a", "aac", "-ar", "48000", "-ac", "2"]
    command.append(str(path))
    _run(command)


def decoded_video_frames(path: Path) -> int:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-map", "0:v:0", "-c:v", "rawvideo", "-f", "null", "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    matches = re.findall(r"frame=\s*(\d+)", result.stderr)
    assert matches, result.stderr[-400:]
    return int(matches[-1])


def ffprobe_video(path: Path) -> dict:
    result = _run([
        "ffprobe", "-v", "error", "-count_frames",
        "-select_streams", "v:0",
        "-show_entries", "format=duration:stream=nb_frames,nb_read_frames,duration,r_frame_rate",
        "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


def test_four_decimal_duration_rounding_is_the_historical_589_trap():
    """Document the rounding that turned 193 frames into 192 before concat."""
    assert round(193 / 30, 4) == 6.4333
    assert round(6.4333 * 30) == 193
    # ``-t`` uses the truncated seconds, not round(duration * fps).
    assert 6.4333 * 30 == pytest.approx(192.999, abs=0.001)
    start, end, output = video_editor.plan_clip_frames(
        source_frames=193,
        source_fps=Fraction(30, 1),
        output_fps=30,
        trim_start=0,
        trim_end=round(193 / 30, 4),
    )
    assert (start, end, output) == (0, 193, 193)


def test_concat_193_197_200_keeps_590_decoded_frames(tmp_path: Path):
    counts = (193, 197, 200)
    colors = ("red", "green", "blue")
    clips = []
    for frames, color in zip(counts, colors):
        path = tmp_path / f"clip_{frames}.mp4"
        write_color_clip(path, frames, color=color, audio=True)
        assert decoded_video_frames(path) == frames
        clips.append({"resolved_path": str(path), "transition": "none"})

    output = tmp_path / "assembled.mp4"
    result = video_editor.render_project(
        clips,
        str(output),
        width=320,
        height=240,
        fps=30,
    )

    assert result["frames"] == 590
    assert result["duration"] == pytest.approx(590 / 30, abs=0.001)
    assert decoded_video_frames(output) == 590
    probed = ffprobe_video(output)
    stream = probed["streams"][0]
    assert int(stream["nb_read_frames"]) == 590
    assert int(stream.get("nb_frames") or stream["nb_read_frames"]) == 590
    audio = video_editor.probe_audio_timing(str(output))
    assert audio is not None
    assert audio["duration"] + (1 / 30) >= 590 / 30


def test_failed_export_does_not_overwrite_previous_output(tmp_path: Path):
    output = tmp_path / "keep.mp4"
    previous = b"PREVIOUS-ARTIFACT"
    output.write_bytes(previous)

    with pytest.raises(video_editor.VideoEditorError) as caught:
        video_editor.render_project(
            [{"resolved_path": str(tmp_path / "missing.mp4"), "transition": "none"}],
            str(output),
            width=320,
            height=240,
            fps=30,
        )

    assert caught.value.phase in {"probe", "normalise"}
    assert "phase" in str(caught.value).lower() or caught.value.phase in str(caught.value)
    assert output.read_bytes() == previous


def test_cancel_leaves_previous_output_and_skips_finalize(tmp_path: Path):
    first = tmp_path / "one.mp4"
    second = tmp_path / "two.mp4"
    write_color_clip(first, 8, color="red")
    write_color_clip(second, 8, color="blue")
    output = tmp_path / "keep.mp4"
    previous = b"PREVIOUS-ARTIFACT"
    output.write_bytes(previous)
    seen: list[str] = []

    def abort() -> bool:
        return len(seen) >= 1

    def progress(_percent: int, message: str) -> None:
        seen.append(message)

    with pytest.raises(video_editor.VideoEditorCancelled) as caught:
        video_editor.render_project(
            [
                {"resolved_path": str(first), "transition": "none"},
                {"resolved_path": str(second), "transition": "none"},
            ],
            str(output),
            width=320,
            height=240,
            fps=30,
            progress=progress,
            abort_callback=abort,
        )

    assert caught.value.phase in {"normalise", "concat", "validate"}
    assert output.read_bytes() == previous
    assert seen

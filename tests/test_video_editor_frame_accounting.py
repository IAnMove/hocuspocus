"""Exact frame/PTS accounting for Video Editor concat, trims, and audio."""

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
            f"sine=frequency=660:sample_rate=48000:duration={duration:.10f}",
        ]
    command += [
        "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    ]
    if audio:
        command += ["-c:a", "aac", "-ar", "48000", "-ac", "2"]
    command.append(str(path))
    _run(command)


def write_sine(path: Path, seconds: float) -> None:
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={seconds:.10f}",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        str(path),
    ])


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


def decoded_audio_samples(path: Path, sample_rate: int = 48000) -> int:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (result.stderr or b"")[-800:]
    return len(result.stdout) // 2


@pytest.mark.parametrize("fps,frames", [(24, 23), (30, 193), (60, 59)])
def test_plan_clip_frames_keeps_a_full_span(fps: int, frames: int):
    start, end, output = video_editor.plan_clip_frames(
        source_frames=frames,
        source_fps=Fraction(fps, 1),
        output_fps=fps,
    )
    assert (start, end, output) == (0, frames, frames)


def test_plan_clip_frames_snaps_non_integer_trims_to_nearest_source_frame():
    start, end, output = video_editor.plan_clip_frames(
        source_frames=30,
        source_fps=Fraction(30, 1),
        output_fps=30,
        trim_start=0.04,
        trim_end=0.54,
    )
    assert (start, end, output) == (1, 16, 15)


def test_probe_media_keeps_the_ui_duration_contract(tmp_path: Path):
    path = tmp_path / "ui-probe.mp4"
    write_color_clip(path, 193, fps=30, color="red")
    media = video_editor.probe_media(str(path))
    assert set(media) >= {
        "duration", "width", "height", "fps", "has_audio", "pixel_format", "has_alpha",
    }
    assert media["duration"] == round(193 / 30, 4)
    assert media["fps"] == 30.0
    assembly = video_editor.probe_assembly_source(str(path))
    assert assembly["nb_frames"] == 193
    assert assembly["fps"] == Fraction(30, 1)


@pytest.mark.parametrize("fps", [24, 30, 60])
def test_render_matches_decoded_frames_at_supported_rates(tmp_path: Path, fps: int):
    counts = (12, 13)
    clips = []
    for index, frames in enumerate(counts):
        path = tmp_path / f"{fps}_{frames}.mp4"
        write_color_clip(path, frames, fps=fps, color=("red", "green")[index], audio=True)
        clips.append({"resolved_path": str(path), "transition": "none"})
    output = tmp_path / f"out_{fps}.mp4"
    result = video_editor.render_project(
        clips, str(output), width=320, height=240, fps=fps,
    )
    expected = sum(counts)
    assert result["frames"] == expected
    assert decoded_video_frames(output) == expected
    assert video_editor.count_decoded_video_frames(str(output)) == expected


def test_non_integer_trim_uses_nearest_frames_not_container_duration(tmp_path: Path):
    source = tmp_path / "trim-src.mp4"
    write_color_clip(source, 30, fps=30, color="blue")
    output = tmp_path / "trimmed.mp4"
    result = video_editor.render_project(
        [{
            "resolved_path": str(source),
            "trim_start": 0.04,
            "trim_end": 0.54,
            "transition": "none",
        }],
        str(output),
        width=320,
        height=240,
        fps=30,
    )
    assert result["frames"] == 15
    assert decoded_video_frames(output) == 15


def test_short_duration_clip_keeps_whole_output_frames(tmp_path: Path):
    source = tmp_path / "short-src.mp4"
    write_color_clip(source, 10, fps=30, color="white")
    output = tmp_path / "short.mp4"
    result = video_editor.render_project(
        [{
            "resolved_path": str(source),
            "trim_start": 0,
            "trim_end": 0.05,
            "transition": "none",
        }],
        str(output),
        width=320,
        height=240,
        fps=30,
    )
    assert result["frames"] == 2
    assert decoded_video_frames(output) == 2


def test_video_without_audio_gets_silence_and_exact_frames(tmp_path: Path):
    first = tmp_path / "silent-a.mp4"
    second = tmp_path / "silent-b.mp4"
    write_color_clip(first, 10, color="red", audio=False)
    write_color_clip(second, 11, color="green", audio=False)
    output = tmp_path / "silent-out.mp4"
    result = video_editor.render_project(
        [
            {"resolved_path": str(first), "transition": "none"},
            {"resolved_path": str(second), "transition": "none"},
        ],
        str(output),
        width=320,
        height=240,
        fps=30,
    )
    assert result["frames"] == 21
    assert decoded_video_frames(output) == 21
    audio = video_editor.probe_audio_timing(str(output))
    assert audio is not None
    assert audio["duration"] + (1 / 30) >= 21 / 30


def test_continuous_audio_sample_count_is_not_container_duration(tmp_path: Path):
    first = tmp_path / "talk-a.mp4"
    second = tmp_path / "talk-b.mp4"
    write_color_clip(first, 16, color="red", audio=True)
    write_color_clip(second, 14, color="blue", audio=True)
    output = tmp_path / "talk-out.mp4"
    result = video_editor.render_project(
        [
            {"resolved_path": str(first), "transition": "none"},
            {"resolved_path": str(second), "transition": "none"},
        ],
        str(output),
        width=320,
        height=240,
        fps=30,
    )
    assert result["frames"] == 30
    samples = decoded_audio_samples(output)
    video_samples = round((30 / 30) * 48000)
    assert samples >= video_samples - 1024
    audio = video_editor.probe_audio_timing(str(output))
    assert audio is not None
    assert audio["duration"] + 0.05 >= 30 / 30
    container = json.loads(_run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(output),
    ]).stdout)
    # Acceptance: compare the audio stream, not container duration alone.
    assert audio["duration"] > 0
    assert float(container["format"]["duration"]) > 0


def test_crossfade_subtracts_whole_overlap_frames(tmp_path: Path):
    first = tmp_path / "xfade-a.mp4"
    second = tmp_path / "xfade-b.mp4"
    write_color_clip(first, 15, color="red")
    write_color_clip(second, 15, color="blue")
    output = tmp_path / "xfade-out.mp4"
    result = video_editor.render_project(
        [
            {
                "resolved_path": str(first),
                "transition": "crossfade",
                "transition_duration": 0.2,
            },
            {"resolved_path": str(second), "transition": "none"},
        ],
        str(output),
        width=320,
        height=240,
        fps=30,
    )
    assert result["frames"] == 24
    assert decoded_video_frames(output) == 24
    assert result["transitions"][0]["duration"] == pytest.approx(0.2)


def test_hard_cut_then_crossfade_keeps_expected_frames(tmp_path: Path):
    """A concat cut must not leave timebase 1/1000000 for the following xfade."""
    clips = []
    for frames, color in ((15, "red"), (15, "green"), (15, "blue")):
        path = tmp_path / f"cut-xfade-{color}.mp4"
        write_color_clip(path, frames, color=color)
        clips.append({
            "resolved_path": str(path),
            "transition": "none" if color != "green" else "crossfade",
            "transition_duration": 0.2,
        })
    output = tmp_path / "cut-then-xfade.mp4"
    result = video_editor.render_project(
        clips, str(output), width=320, height=240, fps=30,
    )
    assert result["frames"] == 39
    assert decoded_video_frames(output) == 39


def test_time_card_then_crossfade_keeps_expected_frames(tmp_path: Path):
    clips = []
    for frames, color, transition in (
        (15, "red", "later-clock"),
        (15, "green", "crossfade"),
        (15, "blue", "none"),
    ):
        path = tmp_path / f"card-xfade-{color}.mp4"
        write_color_clip(path, frames, color=color)
        clips.append({
            "resolved_path": str(path),
            "transition": transition,
            "transition_duration": 1.0 if transition == "later-clock" else 0.2,
            "transition_text": "Luego",
        })
    output = tmp_path / "card-then-xfade.mp4"
    result = video_editor.render_project(
        clips, str(output), width=320, height=240, fps=30,
    )
    assert result["frames"] == 69
    assert decoded_video_frames(output) == 69


def test_soundtrack_keeps_video_frames_and_compares_decoded_audio(tmp_path: Path):
    clip = tmp_path / "picture.mp4"
    score = tmp_path / "score.m4a"
    write_color_clip(clip, 12, color="green", audio=True)
    write_sine(score, 2.0)
    output = tmp_path / "scored.mp4"
    result = video_editor.render_project(
        [{"resolved_path": str(clip), "transition": "none"}],
        str(output),
        width=320,
        height=240,
        fps=30,
        soundtrack={
            "resolved_path": str(score),
            "trim_start": 0,
            "trim_end": 2,
            "volume": 0.5,
            "loop": False,
        },
    )
    assert result["frames"] == 12
    assert decoded_video_frames(output) == 12
    samples = decoded_audio_samples(output)
    assert samples >= round((12 / 30) * 48000) - 1024


def test_export_error_includes_phase_and_output_facts(tmp_path: Path):
    output = tmp_path / "failed.mp4"
    with pytest.raises(video_editor.VideoEditorError) as caught:
        video_editor.render_project(
            [{"resolved_path": str(tmp_path / "nope.mp4"), "transition": "none"}],
            str(output),
            width=320,
            height=240,
            fps=30,
        )
    error = caught.value
    assert error.phase
    assert error.output
    assert error.phase in str(error)
    assert not output.exists() or output.stat().st_size == 0

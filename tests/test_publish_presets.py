"""Platform publish presets: encode args, warnings, and loudness."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from services.publish_presets import collect_warnings, encode_args, integrated_lufs, publish_command, render_publish, measure_loudnorm


def test_encode_args_follow_the_preset():
    x_args = encode_args("x")
    assert x_args[x_args.index("-profile:v") + 1] == "high"
    assert x_args[x_args.index("-b:a") + 1] == "128k"
    assert encode_args("youtube")[encode_args("youtube").index("-b:a") + 1] == "192k"
    assert encode_args("archive")[encode_args("archive").index("-crf") + 1] == "12"
    assert encode_args("shorts")[encode_args("shorts").index("-b:a") + 1] == "128k"


def test_warnings_cover_duration_aspect_and_safe_area():
    long_x = collect_warnings(preset="x", width=1920, height=1080, duration=150)
    assert long_x == [{"code": "duration", "limit": 140, "duration": 150}]
    premium = collect_warnings(preset="x", width=1920, height=1080, duration=150, premium=True)
    assert premium == []
    aspect = collect_warnings(preset="youtube", width=1080, height=1920, duration=10)
    assert aspect[0]["code"] == "aspect" and aspect[0]["expected"] == "16:9"
    shorts = collect_warnings(
        preset="shorts", width=1080, height=1920, duration=30,
        overlays=[{"id": "title", "y": 4, "width": 100}, {"id": "ok", "y": 40, "width": 80}],
    )
    assert shorts == [{"code": "safe_area", "ids": ["title"]}]
    assert collect_warnings(preset="archive", width=640, height=480, duration=9999) == []


def _tone(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24:d=3",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            str(path),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60,
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_two_pass_loudnorm_lands_near_minus_14_lufs(tmp_path: Path):
    source = tmp_path / "tone.mp4"
    destination = tmp_path / "tone_x.mp4"
    _tone(source)
    measured = measure_loudnorm(str(source))
    command = render_publish(str(source), str(destination), "x", loudnorm=measured)
    assert "loudnorm=I=-14:TP=-1" in " ".join(command)
    assert abs(integrated_lufs(str(destination)) - (-14.0)) <= 1.0
    preview = publish_command(str(source), str(destination), "x", loudnorm=measured)
    assert "-profile:v" in preview and "high" in preview

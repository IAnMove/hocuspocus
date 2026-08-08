from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.media_thumbnails import ensure_media_thumbnail, thumbnail_cache_key


def _make_test_image(path: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=royalblue:s=640x360:d=0.1",
            "-frames:v",
            "1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("ffmpeg is unavailable in this test environment")


def _make_test_video(path: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=seagreen:s=320x240:d=0.4:r=10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("ffmpeg cannot create the test video")


def test_image_thumbnail_is_small_and_reused(tmp_path: Path):
    source = tmp_path / "source.png"
    cache = tmp_path / "cache"
    _make_test_image(source)

    first = ensure_media_thumbnail(str(source), str(cache), is_video=False)
    first_mtime = Path(first).stat().st_mtime_ns
    second = ensure_media_thumbnail(str(source), str(cache), is_video=False)

    assert first == second
    assert Path(first).is_file()
    assert Path(first).stat().st_size > 0
    assert Path(first).stat().st_mtime_ns == first_mtime
    assert thumbnail_cache_key(str(source)) in Path(first).name


def test_video_thumbnail_captures_a_static_frame(tmp_path: Path):
    source = tmp_path / "source.mp4"
    _make_test_video(source)

    thumbnail = ensure_media_thumbnail(
        str(source),
        str(tmp_path / "cache"),
        is_video=True,
    )

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            thumbnail,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip() == "384x216"

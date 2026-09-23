"""Gallery listing dimensions and aspect-preserving previews."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest
from PIL import Image

from app.services import media_dimensions
from app.services.media_dimensions import image_header_size, listing_dimensions, parse_resolution
from app.services.media_thumbnails import ensure_fitted_thumbnail
from tests.test_output_completion_time import list_test_outputs


@pytest.mark.parametrize(
    ("value", "expected"),
    [("832x480", (832, 480)), (" 480 × 1600 ", (480, 1600)), ("auto", None), ("0x480", None), (None, None), (720, None)],
)
def test_resolution_strings_parse_only_positive_sizes(value, expected):
    assert parse_resolution(value) == expected


def test_image_header_size_follows_file_versions(tmp_path):
    path = tmp_path / "still.png"
    Image.new("RGB", (300, 900)).save(path)
    assert image_header_size(str(path)) == (300, 900)
    assert image_header_size(str(path)) == (300, 900)
    Image.new("RGB", (1200, 400)).save(path)
    os.utime(path, ns=(10**18, 10**18))
    assert image_header_size(str(path)) == (1200, 400)
    assert image_header_size(str(tmp_path / "missing.png")) is None


def test_listing_prefers_real_image_size_and_uses_sidecars_for_video(tmp_path):
    still = tmp_path / "edit.png"
    Image.new("RGB", (640, 960)).save(still)
    entries = [
        ("edit.png", str(still), ".png", 0.0),
        ("clip.mp4", str(tmp_path / "clip.mp4"), ".mp4", 0.0),
        ("unknown.mp4", str(tmp_path / "unknown.mp4"), ".mp4", 0.0),
        ("song.mp3", str(tmp_path / "song.mp3"), ".mp3", 0.0),
    ]
    sidecars = {
        # Auto-canvas edits record a different requested size than they write.
        "edit.png": {"resolution": "1024x1024"},
        "clip.mp4": {"resolution": "832x480"},
        "unknown.mp4": {"resolution": "auto"},
        "song.mp3": {"resolution": "1x1"},
    }
    assert listing_dimensions(entries, sidecars) == {
        "edit.png": {"width": 640, "height": 960},
        "clip.mp4": {"width": 832, "height": 480},
    }


def test_output_list_exposes_dimensions(tmp_path):
    Image.new("RGB", (480, 1600)).save(tmp_path / "portrait.png")
    (tmp_path / "clip.mp4").write_bytes(b"video")
    (tmp_path / "clip.meta.json").write_text(json.dumps({"params": {"resolution": "1280x720"}}), encoding="utf-8")
    (tmp_path / "song.mp3").write_bytes(b"audio")
    outputs = {item["name"]: item for item in list_test_outputs(tmp_path)}
    assert (outputs["portrait.png"]["width"], outputs["portrait.png"]["height"]) == (480, 1600)
    assert (outputs["clip.mp4"]["width"], outputs["clip.mp4"]["height"]) == (1280, 720)
    assert "width" not in outputs["song.mp3"]


def test_fitted_still_keeps_aspect_and_transparency(tmp_path):
    source = tmp_path / "cutout.png"
    image = Image.new("RGBA", (1500, 500), (0, 0, 0, 0))
    image.paste((200, 40, 40, 255), (500, 100, 1000, 400))
    image.save(source)
    cache = tmp_path / "cache"

    medium = ensure_fitted_thumbnail(str(source), str(cache), is_video=False, size="md")
    small = ensure_fitted_thumbnail(str(source), str(cache), is_video=False, size="sm")
    assert medium.endswith(".webp") and small.endswith(".webp")
    with Image.open(medium) as preview:
        assert preview.size == (640, 213)
        assert preview.mode == "RGBA"
        assert preview.getpixel((5, 5))[3] == 0
    with Image.open(small) as preview:
        assert max(preview.size) == 320
    before = os.path.getmtime(medium)
    assert ensure_fitted_thumbnail(str(source), str(cache), is_video=False, size="md") == medium
    assert os.path.getmtime(medium) == before


def test_fitted_still_never_upscales_and_rejects_unknown_sizes(tmp_path):
    source = tmp_path / "tiny.png"
    Image.new("RGB", (120, 90)).save(source)
    with Image.open(ensure_fitted_thumbnail(str(source), str(tmp_path / "c"), is_video=False, size="md")) as preview:
        assert preview.size == (120, 90)
    with pytest.raises(ValueError):
        ensure_fitted_thumbnail(str(source), str(tmp_path / "c"), is_video=False, size="xl")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for video previews")
def test_fitted_video_frame_keeps_portrait_aspect(tmp_path):
    source = tmp_path / "portrait.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=royalblue:s=360x640:d=0.3",
         "-pix_fmt", "yuv420p", str(source)],
        check=True, capture_output=True,
    )
    preview_path = ensure_fitted_thumbnail(str(source), str(tmp_path / "cache"), is_video=True, size="sm")
    assert preview_path.endswith(".jpg")
    with Image.open(preview_path) as preview:
        assert preview.size == (180, 320)


def test_header_cache_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(media_dimensions, "_CACHE_LIMIT", 2)
    monkeypatch.setattr(media_dimensions, "_header_cache", {})
    for index in range(3):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (10 + index, 10)).save(path)
        assert image_header_size(str(path)) == (10 + index, 10)
    assert len(media_dimensions._header_cache) <= 2

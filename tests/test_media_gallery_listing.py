"""Gallery listing facts (size, colour) and aspect-preserving previews."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections import OrderedDict
from types import SimpleNamespace

import pytest
from PIL import Image

from services import media_dimensions
from services.media_dimensions import (
    FACTS_FILENAME,
    average_color,
    image_header_size,
    listing_dimensions,
    listing_fields,
    parse_resolution,
    probe_video_size,
    prune_thumbnail_cache,
)
from services.media_thumbnails import ensure_fitted_thumbnail
from tests.test_output_completion_time import list_test_outputs

_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def test_listing_only_reads_media_facts_for_the_requested_page(tmp_path, monkeypatch):
    for index in range(12):
        Image.new("RGB", (8, 8)).save(tmp_path / f"image-{index}.png")
    inspected = []
    monkeypatch.setattr(media_dimensions, "listing_fields", lambda kind, path, *args: (
        inspected.append(os.path.basename(path)) or {"width": 8, "height": 8}
    ))
    outputs = list_test_outputs(tmp_path, limit=3, offset=2)
    assert len(outputs) == 3
    assert inspected == [item["name"] for item in outputs]


@pytest.fixture(autouse=True)
def isolated_facts(monkeypatch):
    """Each test gets an empty, unconfigured facts store and no live worker."""
    monkeypatch.setattr(media_dimensions, "_facts", OrderedDict())
    monkeypatch.setattr(media_dimensions, "_queue", OrderedDict())
    monkeypatch.setattr(media_dimensions, "_cache_dir", None)
    monkeypatch.setattr(media_dimensions, "_worker", None)
    monkeypatch.setattr(media_dimensions, "_dirty", False)


def _wait_for(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _near(color, expected, tolerance=4):
    """Average colours pass through lossy previews; compare channel by channel."""
    assert color and color.startswith("#") and len(color) == 7, color
    pairs = zip(bytes.fromhex(color[1:]), bytes.fromhex(expected[1:]))
    return all(abs(a - b) <= tolerance for a, b in pairs)


def _video(path, size="360x640", seconds="0.3"):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=royalblue:s={size}:d={seconds}",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )


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
    (tmp_path / "clip.mp4").write_bytes(b"video")
    (tmp_path / "unknown.mp4").write_bytes(b"video")
    entries = [
        ("edit.png", str(still), ".png", os.path.getmtime(still)),
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
    assert "color" not in outputs["portrait.png"]


def test_facts_persist_across_restarts_without_reading_headers(tmp_path, monkeypatch):
    still = tmp_path / "still.png"
    Image.new("RGB", (300, 900)).save(still)
    cache = tmp_path / "cache"
    cache.mkdir()
    media_dimensions.configure(str(cache))
    assert image_header_size(str(still)) == (300, 900)
    media_dimensions.save_facts(force=True)
    assert json.loads((cache / FACTS_FILENAME).read_text(encoding="utf-8"))

    # A new process: empty memory, the same cache directory, and no PIL.
    monkeypatch.setattr(media_dimensions, "_facts", OrderedDict())
    monkeypatch.setattr(media_dimensions, "_cache_dir", None)
    media_dimensions.configure(str(cache))
    monkeypatch.setattr(Image, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("header re-read")))
    assert image_header_size(str(still)) == (300, 900)


def test_average_color_ignores_transparent_pixels(tmp_path):
    cutout = Image.new("RGBA", (40, 40), (0, 0, 255, 0))
    cutout.paste((200, 20, 20, 255), (10, 10, 30, 30))
    cutout.save(tmp_path / "cutout.png")
    assert _near(average_color(str(tmp_path / "cutout.png")), "#c81414")
    Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(tmp_path / "empty.png")
    assert average_color(str(tmp_path / "empty.png")) == ""
    assert average_color(str(tmp_path / "missing.png")) == ""


def test_probe_honours_rotation(monkeypatch):
    payload = {"streams": [{"width": 1920, "height": 1080, "side_data_list": [{"rotation": -90}]}]}
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout=json.dumps(payload)))
    assert probe_video_size("clip.mp4") == (1080, 1920)
    payload["streams"][0] = {"width": 1280, "height": 720, "tags": {"rotate": "180"}}
    assert probe_video_size("clip.mp4") == (1280, 720)
    payload["streams"] = []
    assert probe_video_size("clip.mp4") is None


@pytest.mark.skipif(not _FFMPEG, reason="ffmpeg and ffprobe are required for the background worker")
def test_worker_probes_videos_and_colours_previews(tmp_path):
    video = tmp_path / "portrait.mp4"
    _video(video)
    still = tmp_path / "red.png"
    Image.new("RGB", (800, 400), (220, 30, 30)).save(still)
    media_dimensions.configure(str(tmp_path / "cache"))

    size = os.path.getsize(video)
    mtime = os.path.getmtime(video)
    # The first listing knows nothing about the video and schedules it.
    assert listing_fields("video", str(video), size, mtime) == {}
    listing_fields("image", str(still), os.path.getsize(still), os.path.getmtime(still))
    assert _wait_for(lambda: listing_fields("video", str(video), size, mtime).get("color")
                     and listing_fields("image", str(still), os.path.getsize(still), os.path.getmtime(still)).get("color"))

    video_fields = listing_fields("video", str(video), size, mtime)
    assert (video_fields["width"], video_fields["height"]) == (360, 640)
    assert video_fields["color"].startswith("#")
    image_fields = listing_fields("image", str(still), os.path.getsize(still), os.path.getmtime(still))
    assert (image_fields["width"], image_fields["height"]) == (800, 400)
    assert _near(image_fields["color"], "#dc1e1e")
    assert _wait_for(lambda: (tmp_path / "cache" / FACTS_FILENAME).exists())


def test_note_preview_records_colour_once(tmp_path):
    still = tmp_path / "green.png"
    Image.new("RGB", (200, 100), (10, 180, 40)).save(still)
    preview = ensure_fitted_thumbnail(str(still), str(tmp_path / "cache"), is_video=False, size="sm")
    media_dimensions.note_preview(str(still), preview)
    fields = listing_fields("image", str(still), os.path.getsize(still), os.path.getmtime(still))
    assert _near(fields["color"], "#0ab428")


def test_prune_removes_least_recently_used_previews(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / FACTS_FILENAME).write_text("{}", encoding="utf-8")
    now = time.time()
    for index in range(10):
        path = cache / f"{index:02d}-fit320.webp"
        path.write_bytes(b"x" * 1000)
        os.utime(path, (now - (10 - index) * 3600, now - (10 - index) * 3600))
    assert prune_thumbnail_cache(str(cache), max_bytes=100_000) == 0
    removed = prune_thumbnail_cache(str(cache), max_bytes=5_000)
    remaining = sorted(path.name for path in cache.iterdir())
    assert removed == 6
    assert remaining == [f"{index:02d}-fit320.webp" for index in range(6, 10)] + [FACTS_FILENAME]


def test_cache_hits_mark_previews_recently_used(tmp_path):
    source = tmp_path / "tiny.png"
    Image.new("RGB", (120, 90)).save(source)
    preview = ensure_fitted_thumbnail(str(source), str(tmp_path / "c"), is_video=False, size="sm")
    old = time.time() - 3 * 86_400
    os.utime(preview, (old, old))
    ensure_fitted_thumbnail(str(source), str(tmp_path / "c"), is_video=False, size="sm")
    assert os.stat(preview).st_atime > old + 86_400


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


@pytest.mark.skipif(not _FFMPEG, reason="ffmpeg is required for video previews")
def test_fitted_video_frame_keeps_portrait_aspect(tmp_path):
    source = tmp_path / "portrait.mp4"
    _video(source)
    preview_path = ensure_fitted_thumbnail(str(source), str(tmp_path / "cache"), is_video=True, size="sm")
    assert preview_path.endswith(".jpg")
    with Image.open(preview_path) as preview:
        assert preview.size == (180, 320)


def test_listing_order_applies_before_paging(tmp_path):
    for index, name in enumerate(["old.png", "mid.png", "new.png"]):
        Image.new("RGB", (8, 8)).save(tmp_path / name)
        os.utime(tmp_path / name, (1_000 + index, 1_000 + index))
    names = lambda **kwargs: [item["name"] for item in list_test_outputs(tmp_path, **kwargs)]
    assert names() == ["new.png", "mid.png", "old.png"]
    assert names(order="oldest") == ["old.png", "mid.png", "new.png"]
    assert names(order="oldest", limit=2, offset=1) == ["mid.png", "new.png"]
    assert names(order="unknown") == ["new.png", "mid.png", "old.png"]
    assert names(order="favorites", favorites={"old.png"}) == ["old.png", "new.png", "mid.png"]

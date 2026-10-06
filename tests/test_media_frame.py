"""media.frame saves one frame of a workspace video (seconds, first or last) as a PNG with provenance."""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import HTTPException
from PIL import Image

from services.production_media_commands import command_catalog
from tests.media_tool_fixtures import Install, frames_video, needs_ffmpeg


def _red(path) -> int:
    with Image.open(path) as image:
        return image.convert("RGB").getpixel((5, 5))[0]


@needs_ffmpeg
@pytest.mark.parametrize("codec", ["ffv1", "x264"])
def test_first_and_last_are_the_real_end_frames(tmp_path, codec):
    install = Install(tmp_path)
    folder = install.folder("ep")
    source = folder / ("clip.mkv" if codec == "ffv1" else "clip.mp4")
    frames_video(source, count=24, codec=codec)
    first = install.call("media.frame", {"workspace": "ep", "source": source.name, "at": "first"})["result"]
    last = install.call("media.frame", {"workspace": "ep", "source": source.name, "at": "last"})["result"]
    assert abs(_red(folder / first["file"]) - 0) <= 3
    assert abs(_red(folder / last["file"]) - 230) <= 3  # frame 23, not 21 or 22
    assert first["time"] == 0 and 0.9 < last["time"] < 1.0
    assert (first["width"], first["height"]) == (64, 48)
    assert last["file"] == "clip-frame-last.png" and "workspace=ep" in last["url"]
    assert last["sha256"] == hashlib.sha256((folder / last["file"]).read_bytes()).hexdigest()


@needs_ffmpeg
def test_seconds_pick_that_frame_and_write_provenance(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    frames_video(folder / "clip.mkv", count=24)
    result = install.call("media.frame", {"workspace": "ep", "source": "/api/v1/file/clip.mkv?workspace=ep", "at": 0.5,
                                          "output_name": "start frame"})["result"]
    assert result["file"] == "start frame.png" and abs(_red(folder / result["file"]) - 120) <= 3
    meta = json.loads((folder / "start frame.meta.json").read_text())
    assert meta["origin"]["tool"] == "media.frame"
    assert meta["lineage"]["parents"][0]["uri"] == "clip.mkv"
    assert meta["params"]["source_name"] == "clip.mkv"
    again = install.call("media.frame", {"workspace": "ep", "source": "clip.mkv", "at": 0.5, "output_name": "start frame.jpg"})
    assert again["result"]["file"] == "start frame(2).png"  # an existing name is never overwritten


@needs_ffmpeg
def test_a_time_past_the_end_and_a_bad_source_are_refused(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    frames_video(folder / "clip.mkv", count=24)
    with pytest.raises(HTTPException) as late:
        install.call("media.frame", {"workspace": "ep", "source": "clip.mkv", "at": 5})
    assert late.value.status_code == 422 and late.value.detail["code"] == "time_past_end"
    with pytest.raises(HTTPException) as outside:
        install.call("media.frame", {"workspace": "ep", "source": "../clip.mkv"})
    assert outside.value.detail["code"] in ("path_not_allowed", "media_not_found")
    with pytest.raises(HTTPException) as named:
        install.call("media.frame", {"workspace": "ep", "source": "clip.mkv", "output_name": "../x"})
    assert named.value.detail["code"] == "invalid_output_name"
    assert sorted(path.name for path in folder.glob("*.png")) == []


@needs_ffmpeg
def test_intent_replays_the_same_frame(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    frames_video(folder / "clip.mkv", count=24)
    first = install.call("media.frame", {"workspace": "ep", "source": "clip.mkv", "at": "last"}, intent_id="f-1")["result"]
    again = install.call("media.frame", {"workspace": "ep", "source": "clip.mkv", "at": "last"}, intent_id="f-1")["result"]
    assert again["file"] == first["file"] and again["replayed"] is True
    assert len(list(folder.glob("*.png"))) == 1


def test_catalog_lists_the_four_tools():
    names = [entry["name"] for entry in command_catalog()]
    assert names == ["media.frame", "media.compose", "audio.trim", "assets.import_from_workspace"]
    frame = command_catalog()[0]["inputSchema"]
    assert frame["required"] == ["version", "input"] and frame["properties"]["input"]["additionalProperties"] is False


@needs_ffmpeg
def test_a_keyed_webm_keeps_its_alpha(tmp_path):
    import subprocess

    import numpy as np
    install = Install(tmp_path)
    folder = install.folder("ep")
    frame = np.zeros((32, 32, 4), dtype=np.uint8)
    frame[8:24, 8:24] = (220, 30, 30, 255)
    encoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "32x32", "-r", "12", "-i", "pipe:0",
         "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(folder / "cut-key.webm")],
        input=frame.tobytes() * 12, capture_output=True, check=False)
    if encoded.returncode != 0:
        pytest.skip("libvpx-vp9 unavailable")
    for at in ("last", 0.25):
        result = install.call("media.frame", {"workspace": "ep", "source": "cut-key.webm", "at": at})["result"]
        with Image.open(folder / result["file"]) as image:
            rgba = image.convert("RGBA")
            assert rgba.getpixel((1, 1))[3] < 30 and rgba.getpixel((16, 16))[3] > 220

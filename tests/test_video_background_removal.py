"""Exercise the real streaming/alpha container path with a tiny injected matte."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.tools import create_tools_router
from shared.tools.background_removal import BackgroundRemovalError
from shared.tools.video_background_removal import remove_video_background_file, stabilize_alpha, video_info


@pytest.fixture
def video(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg is required for the alpha container integration test")
    source = tmp_path / "motion.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=10:duration=0.6",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=0.6", "-c:v", "libx264", "-threads", "1",
                    "-c:a", "aac", "-shortest", str(source)], check=True)
    return source


def matte(image):
    rgba = image.convert("RGBA")
    alpha = Image.new("L", image.size, 255)
    alpha.paste(0, (0, 0, image.width // 3, image.height))
    rgba.putalpha(alpha)
    return rgba


def process(source, **kwargs):
    return remove_video_background_file(str(source), uploads_root=str(source.parent / "uploads"),
        workspace_root=str(source.parent), output_dir=str(source.parent), remove_background=matte, **kwargs)


def test_streamed_webm_retains_alpha_audio_frames_and_source(video):
    original = hashlib.sha256(video.read_bytes()).hexdigest()
    updates = []
    result = process(video, progress=lambda *args: updates.append(args))
    assert result["frames"] == 6
    assert result["fps"] == "10"
    assert result["has_audio"] is True
    assert result["duration"] == .6
    assert result["alpha"]["status"] == "transparent"
    assert hashlib.sha256(video.read_bytes()).hexdigest() == original
    assert updates[-1][2:] == (6, 6)
    output = result["path"]
    # FFmpeg's native VP9 decoder discards auxiliary alpha. Decode with libvpx
    # to verify the actual alpha bytes carried by the WebM container.
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i", output,
                                   "-an", "-f", "rawvideo", "-pix_fmt", "rgba", "pipe:1"])
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(6, 48, 64, 4)
    assert frames[:, :, :12, 3].max() < 5
    assert frames[:, :, 40:, 3].min() > 250
    assert video_info(output)["has_audio"] is True
    assert not list(video.parent.glob(".video-cutout-*"))


def test_cancel_cleans_processes_and_unpublished_output(video):
    updates = []
    with pytest.raises(InterruptedError):
        process(video, progress=lambda *args: updates.append(args), cancelled=lambda: len(updates) >= 2)
    assert not list(video.parent.glob("*.webm"))
    assert not list(video.parent.glob(".video-cutout-*"))
    assert video.is_file()


def test_video_preserves_refined_foreground_colors(video, monkeypatch):
    calls = []
    def refined(image, **kwargs):
        calls.append(kwargs)
        # A distinct foreground color proves the encoder uses the matte result
        # rather than leaking the original background back into boundary RGB.
        return Image.new("RGBA", image.size, (20, 200, 60, 160))
    monkeypatch.setattr("shared.tools.video_background_removal.remove_background_image", refined)
    result = remove_video_background_file(str(video), uploads_root=str(video.parent / "uploads"),
        workspace_root=str(video.parent), output_dir=str(video.parent))
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i", result["path"],
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "pipe:1"])
    pixels = np.frombuffer(raw, dtype=np.uint8).reshape(48, 64, 4)
    assert np.max(np.abs(pixels.astype(int) - [20, 200, 60, 160])) < 6
    assert len(calls) == 6 and all(call["alpha_matting"] for call in calls)


def test_decoder_failure_does_not_publish_a_partial_video(tmp_path):
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not a video")
    with pytest.raises(subprocess.CalledProcessError):
        process(source)
    assert list(tmp_path.iterdir()) == [source]


def test_video_source_cannot_escape_allowed_roots(video, tmp_path):
    with pytest.raises(BackgroundRemovalError, match="not allowed"):
        remove_video_background_file(str(video), uploads_root=str(tmp_path / "other"),
            workspace_root=str(tmp_path / "outside"), output_dir=str(tmp_path / "outside"))


def test_temporal_filter_damps_small_flicker_without_leaving_motion_trails():
    previous = np.full((4, 4, 4), 100, dtype=np.uint8)
    current = previous.copy(); current[:, :, 3] = 120
    assert np.all(stabilize_alpha(current, previous)[:, :, 3] == 116)
    moved = previous.copy(); moved[:, :, 3] = 0
    assert not stabilize_alpha(moved, previous)[:, :, 3].any()
    changed = previous.copy(); changed[:, :, :3] = 150; changed[:, :, 3] = 120
    assert np.all(stabilize_alpha(changed, previous)[:, :, 3] == 120)


def test_route_accepts_exact_video_asset_and_freezes_video_mode(video):
    jobs = []
    asset = {"kind": "video", "locations": [{"workspace_id": "default", "filename": video.name}]}
    app = FastAPI()
    app.include_router(create_tools_router(get_active_workspace=lambda: "default",
        list_workspaces=lambda: [{"name": "default"}], workspace_dir=lambda _: str(video.parent),
        uploads_dir=lambda: str(video.parent / "uploads"), asset_finder=lambda _: asset,
        register_job=lambda j: jobs.append(j) or j, start_remove_background=lambda _: None))
    client = TestClient(app)
    result = client.post("/api/v1/tools/remove-background", json={"asset_id": "asset-motion", "source": video.name,
        "workspace": "default", "temporal_smoothing": False})
    assert result.status_code == 200
    assert result.json()["generation_details"]["generation_mode"] == "video"
    assert jobs[0]["params"]["generation_mode"] == "video"
    assert jobs[0]["params"]["temporal_smoothing"] is False
    assert jobs[0]["params"]["_source_path"] == str(video)
    assert client.post("/api/v1/tools/remove-background", json={"asset_id": "asset-motion", "source": "another.mp4"}).status_code == 409


def test_video_limits_reject_before_decoding(monkeypatch):
    class Probe:
        stdout = json.dumps({"streams": [{"codec_type": "video", "width": 64, "height": 48,
                                         "avg_frame_rate": "24/1", "duration": "61"}]}).encode()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: Probe())
    with pytest.raises(BackgroundRemovalError, match="60 seconds"):
        video_info("too-long.mp4")

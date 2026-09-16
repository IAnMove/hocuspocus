import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from services import world3d_media_cache as cache


def _roots(tmp_path):
    app = tmp_path / "app"
    workspace = app / "outputs"
    workspace.mkdir(parents=True)
    public = tmp_path / "ui/dist/examples"
    public.mkdir(parents=True)
    return app, workspace, public


def test_local_cache_cannot_fetch_remote_or_escape_media_roots(tmp_path):
    app, workspace, public = _roots(tmp_path)
    (public / "valid.mp4").write_bytes(b"video")
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(b"private")
    (public / "link.mp4").symlink_to(secret)
    resolve = lambda url: cache.local_video(url, "default", workspace, app)
    assert resolve("/examples/valid.mp4") == public / "valid.mp4"
    for url in ["https://host/examples/valid.mp4", "//host/examples/valid.mp4", "/examples/../../../secret.mp4", "/examples/link.mp4", "/examples/%2e%2e/%2e%2e/%2e%2e/secret.mp4"]:
        assert resolve(url) is None
    (workspace / "private.mp4").write_bytes(b"private")
    assert resolve("/api/v1/file/private.mp4?workspace=another") is None


def test_export_copy_reuses_cache_and_preserves_authoritative_scene(tmp_path, monkeypatch):
    app, workspace, public = _roots(tmp_path)
    (public / "actor.webm").write_bytes(b"video")
    calls = []

    def encode(source, target, cancelled):
        calls.append(source)
        target.write_bytes(b"cached video")
        return True

    monkeypatch.setattr(cache, "_encode", encode)
    snapshot = {"workspace": "default", "document": {"slots": [{"id": "actor", "screen": {"media": "video", "sourceUrl": "/examples/actor.webm", "transparent": True}}]}}
    before = copy.deepcopy(snapshot)
    options = dict(app_root=app, workspace_root=workspace, cancelled=lambda: False)
    first = cache.prepare_media_snapshot(snapshot, **options)
    second = cache.prepare_media_snapshot(snapshot, **options)
    assert snapshot == before
    assert first == second
    assert len(calls) == 1
    assert first["document"]["slots"][0]["screen"]["transparent"] is True
    assert "/.world3d-media-cache/" in first["document"]["slots"][0]["screen"]["sourceUrl"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg unavailable")
def test_seek_copy_preserves_vp9_alpha_frame_count_and_duration(tmp_path):
    from PIL import Image
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for x in range(16, 32):
        for y in range(32):
            image.putpixel((x, y), (200, 40, 80, 255))
    still = tmp_path / "fixture.png"
    image.save(still)
    source, target = tmp_path / "source.webm", tmp_path / "proxy.webm"
    subprocess.run(["ffmpeg", "-v", "error", "-loop", "1", "-i", str(still), "-frames:v", "4", "-r", "30", "-c:v", "libvpx-vp9", "-lossless", "1", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(source)], check=True)
    assert cache._encode(source, target, lambda: False)
    def decode(path):
        return subprocess.check_output(["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba", "-"])
    original, cached = decode(source), decode(target)
    assert len(cached) == len(original) == 4 * 32 * 32 * 4
    assert cached[3::4] == original[3::4]
    assert {0, 255}.issubset(set(cached[3::4]))
    def duration(path):
        return float(json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]))["format"]["duration"])
    assert abs(duration(source) - duration(target)) < .001

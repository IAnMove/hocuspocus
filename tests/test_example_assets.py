import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.example_assets import create_example_assets_router
from services import example_assets as module


CONTENT = b"optional video bytes"


def store(tmp_path, name="demo/video.mp4", content=CONTENT):
    return module.ExampleAssets(tmp_path / "cache", {
        "revision": "a" * 40,
        "files": {name: {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}},
    })


def client(assets):
    app = FastAPI()
    app.include_router(create_example_assets_router(assets))
    return TestClient(app)


def test_startup_head_and_unknown_paths_do_not_download(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "urlopen", lambda *a, **k: pytest.fail("unexpected network"))
    assets = store(tmp_path)
    with client(assets) as http:
        response = http.head("/examples/demo/video.mp4")
        assert response.status_code == 200
        assert int(response.headers["content-length"]) == len(CONTENT)
        for path in ["missing.mp4", "..%2fprivate.txt", "https:%2f%2fexample.com/file", "demo%5cvideo.mp4"]:
            assert http.get("/examples/" + path).status_code == 404
    assert not assets.cache.exists()


def test_first_use_downloads_once_then_serves_offline_and_ranges(tmp_path, monkeypatch):
    assets = store(tmp_path)
    calls = []

    def download(url, timeout):
        calls.append(url)
        assert timeout == 30
        return io.BytesIO(CONTENT)

    monkeypatch.setattr(module, "urlopen", download)
    with client(assets) as http:
        response = http.get("/examples/demo/video.mp4")
        assert response.status_code == 200
        assert response.content == CONTENT
        assert response.headers["content-type"] == "video/mp4"
        assert calls == ["https://raw.githubusercontent.com/IAnMove/hocuspocus/" + "a" * 40 + "/ui/public/examples/demo/video.mp4"]
        monkeypatch.setattr(module, "urlopen", lambda *a, **k: pytest.fail("cache must work offline"))
        assert http.get("/examples/demo/video.mp4").content == CONTENT
        response = http.get("/examples/demo/video.mp4", headers={"Range": "bytes=0-7"})
        assert response.status_code == 206
        assert response.content == CONTENT[:8]
    # Also works after restart (no in-memory verification state).
    assert store(tmp_path).resolve("demo/video.mp4").read_bytes() == CONTENT


@pytest.mark.parametrize("received", [b"short", b"x" * len(CONTENT), CONTENT + b"extra"])
def test_invalid_download_is_never_published_and_can_be_retried(tmp_path, monkeypatch, received):
    assets = store(tmp_path)
    monkeypatch.setattr(module, "urlopen", lambda *a, **k: io.BytesIO(received))
    with client(assets) as http:
        response = http.get("/examples/demo/video.mp4")
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert list(assets.cache.iterdir()) == []
        monkeypatch.setattr(module, "urlopen", lambda *a, **k: io.BytesIO(CONTENT))
        assert http.get("/examples/demo/video.mp4").content == CONTENT


def test_network_failure_is_retryable(tmp_path, monkeypatch):
    def offline(*args, **kwargs):
        raise OSError("offline")
    monkeypatch.setattr(module, "urlopen", offline)
    with client(store(tmp_path)) as http:
        response = http.get("/examples/demo/video.mp4")
        assert response.status_code == 503
        assert "internet" in response.json()["detail"]


def test_corrupted_cached_file_is_not_served(tmp_path, monkeypatch):
    assets = store(tmp_path)
    monkeypatch.setattr(module, "urlopen", lambda *a, **k: io.BytesIO(CONTENT))
    target = assets.resolve("demo/video.mp4")
    assert assets.cached("demo/video.mp4") == target
    target.write_bytes(b"x" * len(CONTENT))
    assert assets.cached("demo/video.mp4") is None
    assert assets.resolve("demo/video.mp4").read_bytes() == CONTENT


def test_concurrent_requests_share_one_download(tmp_path, monkeypatch):
    assets = store(tmp_path)
    calls = []
    def download(*args, **kwargs):
        calls.append(1)
        return io.BytesIO(CONTENT)
    monkeypatch.setattr(module, "urlopen", download)
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(assets.resolve, ["demo/video.mp4"] * 8))
    assert len(set(paths)) == 1
    assert calls == [1]
    assert not list(assets.cache.glob("*.partial"))


def test_gallery_redirect_preserves_relative_media_urls(tmp_path, monkeypatch):
    assets = store(tmp_path, "demo/index.html", b"<html>gallery</html>")
    monkeypatch.setattr(module, "urlopen", lambda *a, **k: io.BytesIO(b"<html>gallery</html>"))
    with client(assets) as http:
        response = http.get("/examples/demo", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/examples/demo/"
        response = http.get("/examples/demo/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")


def test_manifest_is_pinned_and_example_media_is_not_bundled():
    manifest = json.loads(module.MANIFEST_PATH.read_text())
    assert len(manifest["revision"]) == 40
    assert int(manifest["revision"], 16)
    assert sum(entry["size"] for entry in manifest["files"].values()) > 1024**3
    for name, entry in manifest["files"].items():
        assert not name.startswith("/") and ".." not in name.split("/") and "\\" not in name
        assert len(entry["sha256"]) == 64 and int(entry["sha256"], 16)
        assert entry["size"] > 0
    assert not (module.APP_ROOT.parent / "ui/public/examples").exists()

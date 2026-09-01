from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.assets import create_assets_router
from services.asset_manifest import build_asset_manifest, write_asset_manifest


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, Path]]:
    roots = {
        "default": tmp_path / "outputs",
        "film": tmp_path / "outputs" / "film",
        "__uploads__": tmp_path / "uploads",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    app.include_router(create_assets_router(
        list_workspaces=lambda: [{"name": "default"}, {"name": "film"}],
        workspace_dir=lambda name: str(roots[name]),
        uploads_dir=lambda: str(roots["__uploads__"]),
    ))
    return TestClient(app), roots


def test_global_route_lists_workspaces_and_uploads_with_safe_urls(tmp_path: Path):
    client, roots = _client(tmp_path)
    (roots["default"] / "image.png").write_bytes(b"image")
    (roots["film"] / "clip.mp4").write_bytes(b"video")
    (roots["__uploads__"] / "song.wav").write_bytes(b"audio")

    response = client.get("/api/v1/assets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    by_name = {item["filename"]: item for item in body["assets"]}
    assert by_name["clip.mp4"]["url"].endswith("?workspace=film")
    assert by_name["song.wav"]["url"] == "/api/v1/uploads/song.wav"
    assert str(tmp_path) not in response.text


def test_route_filters_and_returns_full_manifest_by_id(tmp_path: Path):
    client, roots = _client(tmp_path)
    output = roots["film"] / "metal.mp4"
    output.write_bytes(b"video")
    write_asset_manifest(
        output,
        build_asset_manifest(
            output, asset_id="asset_metal", tool="story-music-video",
            prompts={"effective": "heavy metal server choir"},
        ),
    )

    listing = client.get("/api/v1/assets", params={
        "workspace": "film", "kind": "video", "search": "server",
    }).json()
    assert listing["total"] == 1
    assert "manifest" not in listing["assets"][0]
    detail = client.get("/api/v1/assets/asset_metal")
    assert detail.status_code == 200
    assert detail.json()["manifest"]["generation"]["prompts"]["effective"] == "heavy metal server choir"


def test_route_rejects_unknown_filters_and_missing_assets(tmp_path: Path):
    client, _roots = _client(tmp_path)
    assert client.get("/api/v1/assets", params={"kind": "magic"}).status_code == 400
    assert client.get("/api/v1/assets", params={"workspace": "missing"}).status_code == 404
    assert client.get("/api/v1/assets/nope").status_code == 404

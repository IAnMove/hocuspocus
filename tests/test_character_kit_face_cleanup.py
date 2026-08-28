from pathlib import Path

import pytest
from PIL import Image

from services.character_kit_face_cleanup import (
    CharacterKitFaceCleanupError,
    clean_character_kit_overlay,
    crop_to_alpha,
    resolve_character_kit_image,
)


def opaque_square(path: Path, size=32):
    image = Image.new("RGBA", (size, size), (180, 80, 40, 255))
    image.save(path)


def fake_matte(image: Image.Image) -> Image.Image:
    out = image.convert("RGBA")
    pixels = out.load()
    for y in range(out.height):
        for x in range(out.width):
            if x < 4 or y < 4 or x >= out.width - 4 or y >= out.height - 4:
                pixels[x, y] = (0, 0, 0, 0)
    return out


def test_resolver_rejects_paths_outside_uploads_and_workspace(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs"
    uploads.mkdir(); workspace.mkdir()
    outside = tmp_path / "secret.png"
    opaque_square(outside)
    with pytest.raises(CharacterKitFaceCleanupError, match="not allowed|not found"):
        resolve_character_kit_image(str(outside), uploads_root=str(uploads), workspace_root=str(workspace))


def test_cleanup_writes_a_new_cropped_png_and_keeps_the_original(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs"
    uploads.mkdir(); workspace.mkdir()
    original = workspace / "mouth-wide.png"
    opaque_square(original, 40)
    result = clean_character_kit_overlay(
        "mouth-wide.png",
        uploads_root=str(uploads),
        workspace_root=str(workspace),
        remove_background=fake_matte,
        padding=2,
    )
    assert original.exists()
    cleaned = Path(result["path"])
    assert cleaned.exists()
    assert cleaned.name.startswith("mouth-wide.cleanup-")
    assert cleaned != original
    assert result["alpha"]["status"] == "transparent"
    assert result["width"] < 40
    assert result["height"] < 40
    assert result["source"].startswith("/api/v1/file/")


def test_crop_to_alpha_rejects_fully_transparent_images():
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    with pytest.raises(CharacterKitFaceCleanupError, match="empty overlay"):
        crop_to_alpha(image)


def test_resolver_accepts_file_api_urls_inside_workspace(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs"
    uploads.mkdir(); workspace.mkdir()
    original = workspace / "brin-mouth-wide-v1.png"
    opaque_square(original)
    resolved = resolve_character_kit_image(
        "/api/v1/file/brin-mouth-wide-v1.png",
        uploads_root=str(uploads),
        workspace_root=str(workspace),
    )
    assert resolved == str(original.resolve())


def test_cleanup_rejects_path_traversal(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs"
    uploads.mkdir(); workspace.mkdir()
    secret = tmp_path / "secret.png"
    opaque_square(secret)
    with pytest.raises(CharacterKitFaceCleanupError, match="not allowed|not found"):
        clean_character_kit_overlay(
            str(secret),
            uploads_root=str(uploads),
            workspace_root=str(workspace),
            remove_background=fake_matte,
        )


def test_cleanup_router_returns_pending_png_without_overwriting(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.character_kit_face import create_character_kit_face_router
    from services import character_kit_face_cleanup as svc

    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs"
    uploads.mkdir(); workspace.mkdir()
    original = workspace / "luma-mouth-closed.png"
    opaque_square(original, 36)
    previous = svc._rembg_remove
    svc._rembg_remove = fake_matte
    try:
        app = FastAPI()
        app.include_router(create_character_kit_face_router(
            workspace_dir=lambda _workspace: str(workspace),
            uploads_root=lambda: str(uploads),
        ))
        response = TestClient(app).post("/api/v1/character-kits/face-rig/cleanup", json={
            "workspace": "default",
            "source": "/api/v1/file/luma-mouth-closed.png",
            "padding": 2,
        })
    finally:
        svc._rembg_remove = previous
    assert response.status_code == 200
    payload = response.json()
    assert original.exists()
    assert payload["original"] == "luma-mouth-closed.png"
    assert payload["source"].startswith("/api/v1/file/")
    assert payload["alpha"]["status"] == "transparent"
    assert payload["filename"].startswith("luma-mouth-closed.cleanup-")
    assert payload["method"] == "rembg-u2net"
    assert payload["model"] == "u2net"

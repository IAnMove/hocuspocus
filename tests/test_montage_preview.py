"""Montage contact sheet. Synthetic clips stay in tmp and are never committed."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image

from services.montage_documents import MontageStore
from services.montage_preview import (
    OPERATION,
    UNPAINTABLE,
    command_catalog,
    command_handlers,
    preview_montage,
)

FFMPEG = shutil.which("ffmpeg")


def _store(tmp_path: Path) -> tuple[MontageStore, Path]:
    root = tmp_path / "workspaces"

    def workspace_dir(name: str) -> str:
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    return MontageStore(workspace_dir), root


def _montage(clips: list[dict]) -> dict:
    return {"version": 1, "name": "Cut", "width": 240, "height": 240, "fps": 24, "clips": clips}


def _lavfi(path: Path, color: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         f"color=c={color}:s=64x64:r=24:d=0.4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path)],
        check=True, timeout=60,
    )


def _png(color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (8, 8), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _scene() -> dict:
    return {
        "version": 1, "name": "sky", "width": 240, "height": 240, "fps": 24, "duration": 1,
        "layers": [{"id": "sky", "type": "effect"}],
    }


def test_catalog_caps_eight_instants_and_does_not_ask_for_png_bytes():
    item = command_catalog()[0]
    assert item["name"] == OPERATION and item["mutation"] is False
    props = item["inputSchema"]["properties"]["input"]["properties"]
    assert props["count"]["maximum"] == 8 and props["times"]["maxItems"] == 8
    assert item["inputSchema"]["properties"]["input"]["required"] == ["workspace", "file"]
    assert "png_base64" not in json.dumps(item)


def test_count_above_eight_is_rejected(tmp_path):
    store, _root = _store(tmp_path)
    with pytest.raises(Exception) as caught:
        preview_montage(store, {"version": 1, "input": {"workspace": "demo", "file": "Cut.montage.json", "count": 9}})
    assert getattr(caught.value, "code", None) == "montage_preview_bad_count"


def test_unpaintable_scene_is_skipped_with_a_stable_code(tmp_path):
    store, root = _store(tmp_path)
    folder = root / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "broken.scene.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
    saved = store.save("demo", _montage([{
        "id": "scene", "source": "missing.mp4", "trimStart": 0, "trimEnd": 1,
        "origin": {"kind": "scene2d", "scene": "broken.scene.json"},
    }]))
    handler = command_handlers(store)[OPERATION]
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handler({"version": 1, "input": {"workspace": "demo", "file": saved["file"], "count": 1}}))
    assert caught.value.detail["code"] == "montage_preview_empty"
    assert caught.value.detail["warnings"][0]["code"] == UNPAINTABLE
    assert caught.value.detail["warnings"][0]["clip"] == "scene"


def test_scene_document_reuses_the_video2d_painter(tmp_path, monkeypatch):
    seen = {}

    def fake_paint(document, times, size):
        seen["document"] = document
        seen["times"] = list(times)
        seen["size"] = size
        return _png((20, 40, 60))

    monkeypatch.setattr("services.montage_preview.paint_contact_sheet", fake_paint)
    store, root = _store(tmp_path)
    folder = root / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sky.scene.json").write_text(json.dumps(_scene()), encoding="utf-8")
    saved = store.save("demo", _montage([{
        "id": "scene", "source": "missing.mp4", "trimStart": 0, "trimEnd": 1,
        "origin": {"kind": "scene2d", "scene": "sky.scene.json"},
    }]))
    payload = {"version": 1, "input": {"workspace": "demo", "file": saved["file"], "count": 1}}
    first = preview_montage(store, payload)
    second = preview_montage(store, payload)
    assert seen["document"]["layers"][0]["id"] == "sky"
    assert seen["times"] == [0.5]
    body = first["result"]
    assert set(body) == {"file", "url", "sha256", "times"}
    assert body["sha256"] == second["result"]["sha256"]
    assert body["url"] == second["result"]["url"]
    sheet = (folder / body["file"]).read_bytes()
    assert sheet.startswith(b"\x89PNG") and hashlib.sha256(sheet).hexdigest() == body["sha256"]
    assert "iVBOR" not in json.dumps(first)


def test_launch_runtime_appends_montage_preview():
    source = Path(__file__).resolve().parents[1].joinpath("app/_launch_runtime.py").read_text(encoding="utf-8")
    assert "**_montage_preview_handlers" in source
    assert "*montage_preview_catalog()" in source


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is missing; the real montage contact-sheet paint was not run")
def test_two_synthetic_clips_repeat_the_same_sheet_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.montage_preview.paint_contact_sheet",
        lambda *_args, **_kwargs: pytest.fail("plain clips must use ffmpeg, not the scene painter"),
    )
    store, root = _store(tmp_path)
    folder = root / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    _lavfi(folder / "a.mp4", "red")
    _lavfi(folder / "b.mp4", "blue")
    saved = store.save("demo", _montage([
        {"id": "a", "source": "a.mp4"},
        {"id": "b", "source": "b.mp4"},
    ]))
    payload = {"version": 1, "input": {"workspace": "demo", "file": saved["file"], "count": 2}}
    handler = command_handlers(store)[OPERATION]
    first = asyncio.run(handler(payload))
    second = asyncio.run(handler(payload))
    body = first["result"]
    assert set(body) == {"file", "url", "sha256", "times"}
    assert body["url"].startswith("/api/v1/file/") and "workspace=demo" in body["url"]
    assert len(body["times"]) == 2
    assert body["sha256"] == second["result"]["sha256"]
    assert body["file"] == second["result"]["file"]
    encoded = json.dumps(first)
    assert "png_base64" not in encoded and "iVBOR" not in encoded
    sheet_path = folder / body["file"]
    raw = sheet_path.read_bytes()
    assert raw.startswith(b"\x89PNG") and hashlib.sha256(raw).hexdigest() == body["sha256"]
    with Image.open(io.BytesIO(raw)) as image:
        colors = image.convert("RGB").getcolors(maxcolors=256 * 256)
    assert colors is not None and len(colors) >= 2

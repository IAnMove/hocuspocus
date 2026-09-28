"""assets.upload returns a canonical URL without POST /api/v1/upload."""

from __future__ import annotations

import asyncio
import base64
import struct
import zlib
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.asset_catalog import find_asset
from services.assets_upload import MAX_ASSETS_UPLOAD_BYTES, command_catalog, command_handlers
from services.studio_image_resources import StudioImageResources
from services.studio_image_spec import _validate_reference
from services.studio_speech_resources import StudioSpeechResources


def tiny_png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")


def _layout(tmp_path: Path):
    workspace = tmp_path / "outputs" / "clip"
    uploads = tmp_path / "uploads"
    workspace.mkdir(parents=True)
    uploads.mkdir()

    def workspace_dir(name: str) -> str:
        if name != "clip":
            raise ValueError("invalid workspace")
        return str(workspace)

    def uploads_dir() -> str:
        return str(uploads)

    return command_handlers(workspace_dir, uploads_dir), workspace, uploads


def _request(intent_id: str, payload: dict) -> dict:
    return {"version": 1, "intent_id": intent_id, "input": payload}


def _call(handlers, intent_id: str, payload: dict) -> dict:
    return asyncio.run(handlers["assets.upload"](_request(intent_id, payload)))


def _resources(workspace: Path, uploads: Path):
    def workspace_dir(name: str) -> str:
        if name != "clip":
            raise ValueError(name)
        return str(workspace)

    def list_workspaces():
        return [{"name": "clip"}]

    common = dict(
        workspace_dir=workspace_dir,
        uploads_dir=lambda: str(uploads),
        list_workspaces=list_workspaces,
        lora_search_dirs=lambda _model: [],
        lora_compatible=lambda *_args, **_kwargs: True,
    )
    return StudioImageResources(**common), StudioSpeechResources(**common)


def test_round_trip_tiny_png_url_is_accepted_by_image_and_audio_fields(tmp_path):
    handlers, workspace, uploads = _layout(tmp_path)
    png = tiny_png()
    encoded = base64.b64encode(png).decode("ascii")
    first = _call(handlers, "intent-png", {"workspace": "clip", "filename": "dot.png", "data_base64": encoded})
    again = _call(handlers, "intent-png", {"workspace": "clip", "filename": "dot.png", "data_base64": encoded})

    assert first["status"] == "completed"
    assert first["operation"] == "assets.upload"
    assert again["result"] == first["result"]
    result = first["result"]
    assert set(result) == {"asset_id", "url"}
    assert result["url"].startswith("/api/v1/file/")
    assert "workspace=clip" in result["url"]
    assert _validate_reference(result["url"]) == result["url"]
    assert _validate_reference(result["asset_id"]) == result["asset_id"]
    assert list(workspace.glob("*.png")) and len(list(workspace.glob("*.png"))) == 1

    images, speech = _resources(workspace, uploads)
    prepared, _resources_found = images.prepare_media({
        "image_refs": [result["url"]],
        "image_start": result["url"],
        "image_end": result["url"],
    })
    assert Path(prepared["image_refs"][0]).read_bytes() == png
    assert Path(prepared["image_start"]).read_bytes() == png
    assert Path(prepared["image_end"]).read_bytes() == png
    # audio_guide uses the same canonical-URL gate and resolver as the image fields.
    audio_path, _origin = speech._media(result["url"])
    assert Path(audio_path).read_bytes() == png

    catalog = find_asset(
        [
            {"workspace_id": "clip", "path": str(workspace)},
            {"workspace_id": "__uploads__", "path": str(uploads)},
        ],
        result["asset_id"],
    )
    assert catalog is not None
    assert catalog["filename"] == Path(prepared["image_start"]).name
    assert list(uploads.iterdir()) == []


def test_existing_workspace_file_round_trips_without_a_copy(tmp_path):
    handlers, workspace, uploads = _layout(tmp_path)
    png = tiny_png()
    source = workspace / "already.png"
    source.write_bytes(png)
    result = _call(handlers, "intent-source", {"workspace": "clip", "source": str(source)})["result"]

    assert _validate_reference(result["url"]) == result["url"]
    images, speech = _resources(workspace, uploads)
    prepared, _found = images.prepare_media({
        "image_refs": [result["url"]],
        "image_start": result["url"],
        "image_end": result["url"],
    })
    assert Path(prepared["image_start"]).read_bytes() == png
    assert Path(speech._media(result["url"])[0]).read_bytes() == png
    assert sorted(path.name for path in workspace.glob("*.png")) == ["already.png"]


def test_oversized_payload_is_rejected_with_a_stable_code(tmp_path):
    handlers, workspace, _uploads = _layout(tmp_path)
    payload = base64.b64encode(b"\x00" * (MAX_ASSETS_UPLOAD_BYTES + 1)).decode("ascii")
    with pytest.raises(HTTPException) as caught:
        _call(handlers, "intent-large", {"workspace": "clip", "filename": "big.png", "data_base64": payload})
    assert caught.value.status_code == 413
    assert caught.value.detail["code"] == "payload_too_large"
    assert list(workspace.glob("*.png")) == []


def test_path_that_escapes_the_workspace_is_rejected(tmp_path):
    handlers, workspace, _uploads = _layout(tmp_path)
    outside = tmp_path / "secret.png"
    outside.write_bytes(tiny_png())
    escaped = workspace / ".." / ".." / outside.name
    with pytest.raises(HTTPException) as caught:
        _call(handlers, "intent-escape", {"workspace": "clip", "source": str(escaped)})
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "path_not_allowed"
    assert list(workspace.glob("*.png")) == []


def test_catalog_publishes_versioned_upload_schema():
    operation = command_catalog()[0]
    assert operation["name"] == "assets.upload"
    assert operation["version"] == 1
    assert operation["mutation"] is True
    schema = operation["inputSchema"]
    assert schema["properties"]["version"]["const"] == 1
    assert schema["required"] == ["version", "intent_id", "input"]
    branches = schema["properties"]["input"]["oneOf"]
    assert {"workspace", "filename", "data_base64"} in {frozenset(branch["required"]) for branch in branches}
    assert {"workspace", "source"} in {frozenset(branch["required"]) for branch in branches}

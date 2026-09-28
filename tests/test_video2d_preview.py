"""Contact-sheet preview for scenes.video2d.preview. No MP4 and no scene save."""

from __future__ import annotations

import base64
import hashlib
import struct
from pathlib import Path

import pytest

import time

from services import video2d_preview
from services.video2d_preview import (
    OPERATION,
    PreviewError,
    bind_preview_origin,
    command_catalog,
    execute,
    painter_block_reason,
)

SHEET = Path("/tmp/m5-video2d-contact-sheet.png")


def _document(**overrides):
    document = {
        "version": 1,
        "name": "preview",
        "width": 64,
        "height": 36,
        "fps": 24,
        "duration": 2,
        "layers": [{
            "id": "sky",
            "name": "Sky",
            "type": "effect",
            "source": "",
            "visible": True,
            "z": 0,
            "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
            "animation": {
                "start": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
                "end": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
                "duration": 2,
                "curve": "linear",
            },
            "atmosphere": {"kind": "dust", "density": 8, "speed": 0.4, "size": 1, "wind": 2, "color": "#fde68a"},
        }],
    }
    document.update(overrides)
    return document


def _command(document=None, times=None):
    return {
        "version": 1,
        "operation": OPERATION,
        "input": {"document": document or _document(), "times": [0, 1] if times is None else times},
    }


def _block_paint(monkeypatch):
    monkeypatch.setattr("services.video2d_preview.paint_contact_sheet", lambda *args: pytest.fail(str(args)))


def _png(result) -> bytes:
    raw = base64.b64decode(result["result"]["png_base64"])
    assert hashlib.sha256(raw).hexdigest() == result["result"]["sha256"]
    return raw


def _png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_catalog_is_a_read_only_preview():
    published = command_catalog()
    assert [item["name"] for item in published] == [OPERATION]
    assert published[0]["mutation"] is False
    assert published[0]["inputSchema"]["properties"]["input"]["properties"]["times"]["maxItems"] == 8


def test_too_many_times_uses_a_stable_code(monkeypatch):
    _block_paint(monkeypatch)
    with pytest.raises(PreviewError) as caught:
        execute(_command(times=[0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6]))
    assert caught.value.code == "preview_too_many_times"


def test_time_past_duration_uses_a_stable_code(monkeypatch):
    _block_paint(monkeypatch)
    with pytest.raises(PreviewError) as caught:
        execute(_command(times=[2.01]))
    assert caught.value.code == "preview_time_out_of_range"


def test_remote_layer_source_is_rejected_before_paint():
    bind_preview_origin("")
    document = _document(layers=[{
        "id": "hero",
        "name": "Hero",
        "type": "image",
        "source": "https://example.invalid/hero.png",
        "visible": True,
        "z": 0,
        "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
        "animation": {
            "start": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
            "end": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
            "duration": 2,
            "curve": "linear",
        },
    }])
    with pytest.raises(PreviewError) as caught:
        execute(_command(document=document, times=[0]))
    assert caught.value.code == "preview_missing_ref"


def test_workspace_media_uses_the_live_app_origin(monkeypatch):
    seen = {}

    def fake_run(payload, timeout):
        seen["payload"] = payload
        seen["timeout"] = timeout
        return b"\x89PNG\r\n\x1a\n" + b"not-a-real-png"

    monkeypatch.setattr("services.video2d_preview.painter_block_reason", lambda: None)
    monkeypatch.setattr("services.video2d_preview._run_node", fake_run)
    monkeypatch.setattr("services.video2d_preview._paint_on_lane", lambda document, times, size: video2d_preview._serve_and_paint(document, times, size, time.monotonic() + 5))
    bind_preview_origin("http://127.0.0.1:7860")
    document = _document(layers=[{
        "id": "hero",
        "name": "Hero",
        "type": "image",
        "source": "/api/v1/file/hero.png?workspace=default",
        "visible": True,
        "z": 0,
        "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
        "animation": {
            "start": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
            "end": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
            "duration": 2,
            "curve": "linear",
        },
    }])
    result = execute(_command(document=document, times=[0]))
    assert seen["payload"]["base"] == "http://127.0.0.1:7860"
    assert seen["payload"]["document"]["layers"][0]["source"] == "/api/v1/file/hero.png?workspace=default"
    assert result["status"] == "completed"
    bind_preview_origin("")


def test_workspace_media_without_app_origin_fails_before_paint():
    bind_preview_origin("")
    document = _document(layers=[{
        "id": "hero",
        "name": "Hero",
        "type": "image",
        "source": "/api/v1/file/hero.png?workspace=default",
        "visible": True,
        "z": 0,
        "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
        "animation": {
            "start": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
            "end": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
            "duration": 2,
            "curve": "linear",
        },
    }])
    with pytest.raises(PreviewError) as caught:
        execute(_command(document=document, times=[0]))
    assert caught.value.code == "preview_painter_unavailable"


def test_contact_sheet_bytes_are_stable_for_a_portrait_document():
    reason = painter_block_reason()
    if reason:
        pytest.skip(reason)
    document = _document(name="portrait", width=90, height=160)
    command = _command(document=document, times=[0, 1])
    first = execute(command)
    second = execute(command)
    left = _png(first)
    right = _png(second)
    assert left == right
    assert hashlib.sha256(left).hexdigest() == first["result"]["sha256"]
    assert first["result"]["frameCount"] == 2
    assert first["result"]["width"] == 90
    assert first["result"]["height"] == 160
    assert first["result"]["columns"] == 2
    assert _png_size(left) == (180, 160)
    assert set(first["result"]) == {
        "mime", "sha256", "png_base64", "times", "width", "height", "columns", "frameCount",
    }
    SHEET.write_bytes(left)

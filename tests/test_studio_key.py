"""studio.key turns green into transparency without returning pixels."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from services.studio_key import (
    TEMPORAL_WEIGHTS,
    AlphaWindow,
    command_catalog,
    command_handlers,
    existing_isnet,
    green_rgba,
    smooth_alpha,
)


def _png(width: int, height: int, rgb: bytes) -> bytes:
    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _layout(tmp_path: Path):
    workspace = tmp_path / "outputs" / "clip"
    uploads = tmp_path / "uploads"
    workspace.mkdir(parents=True)
    uploads.mkdir()

    def workspace_dir(name: str) -> str:
        if name != "clip":
            raise ValueError(name)
        return str(workspace)

    return workspace, uploads, command_handlers(workspace_dir, lambda: str(uploads), find_model=lambda: None)


def _call(handlers, payload: dict) -> dict:
    return asyncio.run(handlers["studio.key"]({"version": 1, "input": payload}))


def _plate() -> bytes:
    # One green screen pixel and one red foreground pixel. No committed image.
    return _png(2, 1, bytes([0, 255, 0, 255, 0, 0]))


def test_green_pixel_becomes_transparent_and_red_stays(tmp_path):
    workspace, _uploads, handlers = _layout(tmp_path)
    source = workspace / "plate.png"
    source.write_bytes(_plate())
    body = _call(handlers, {
        "workspace": "clip",
        "source": "/api/v1/file/plate.png?workspace=clip",
    })

    assert body["operation"] == "studio.key"
    result = body["result"]
    assert set(result) == {"file", "url", "sha256", "frames", "report"}
    assert result["frames"] == 1
    assert result["file"].endswith(".png")
    assert result["url"].startswith("/api/v1/file/")
    assert "workspace=clip" in result["url"]
    output = workspace / result["file"]
    assert output.is_file()
    assert result["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert source.read_bytes() == _plate()

    with Image.open(output) as keyed:
        pixels = list(keyed.convert("RGBA").getdata())
    green, red = pixels
    assert green[3] == 0
    assert red[:3] == (255, 0, 0)
    assert red[3] == 255


def test_despill_lowers_green_spill_without_keying_the_pixel():
    rgba = green_rgba(np.array([[[180, 220, 40]]], dtype=np.uint8))
    pixel = [int(channel) for channel in rgba[0, 0]]
    assert pixel[0] == 180
    assert pixel[2] == 40
    assert pixel[1] < 220
    assert pixel[3] > 0


def test_temporal_weights_stay_at_015_070_015():
    assert TEMPORAL_WEIGHTS == (0.15, 0.7, 0.15)
    frames = [
        np.array([0.0], dtype=np.float64),
        np.array([100.0], dtype=np.float64),
        np.array([40.0], dtype=np.float64),
        np.array([0.0], dtype=np.float64),
    ]
    smoothed = smooth_alpha(frames)
    assert float(smoothed[0][0]) == 0.0
    assert float(smoothed[-1][0]) == 0.0
    assert float(smoothed[1][0]) == 0.15 * 0 + 0.7 * 100 + 0.15 * 40
    assert float(smoothed[2][0]) == 0.15 * 100 + 0.7 * 40 + 0.15 * 0

    window = AlphaWindow()
    emitted = []
    for value in (0, 100, 40, 0):
        frame = np.zeros((1, 1, 4), dtype=np.uint8)
        frame[0, 0, 3] = value
        emitted.extend(window.push(frame))
    emitted.extend(window.finish())
    alphas = [int(frame[0, 0, 3]) for frame in emitted]
    assert alphas[0] == 0
    assert alphas[-1] == 0
    assert alphas[1] == int(round(0.15 * 0 + 0.7 * 100 + 0.15 * 40))
    assert alphas[2] == int(round(0.15 * 100 + 0.7 * 40 + 0.15 * 0))


def test_isnet_anime_without_a_model_uses_a_stable_code(tmp_path):
    workspace, _uploads, handlers = _layout(tmp_path)
    (workspace / "plate.png").write_bytes(_plate())
    with pytest.raises(HTTPException) as caught:
        _call(handlers, {
            "workspace": "clip",
            "source": "/api/v1/file/plate.png?workspace=clip",
            "mode": "isnet-anime",
        })
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "model_not_installed"
    assert list(workspace.glob("*-key*")) == []
    assert existing_isnet([str(tmp_path)]) is None
    marker = tmp_path / "isnet-anime.onnx"
    marker.write_bytes(b"installed")
    assert existing_isnet([str(tmp_path)]) == str(marker)


def test_catalog_is_versioned_green_or_isnet():
    operation = command_catalog()[0]
    assert operation["name"] == "studio.key"
    assert operation["version"] == 1
    schema = operation["inputSchema"]
    assert schema["properties"]["version"]["const"] == 1
    assert schema["required"] == ["version", "input"]
    payload = schema["properties"]["input"]
    assert payload["required"] == ["workspace", "source"]
    assert payload["properties"]["mode"]["enum"] == ["green", "blue", "magenta", "isnet-anime"]
    assert "intent_id" in schema["properties"]
    assert "0.15" in operation["description"]
    assert "model_not_installed" in operation["description"]


def test_video_key_returns_a_webm_not_pixels(tmp_path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg required")
    workspace, _uploads, handlers = _layout(tmp_path)
    raw = tmp_path / "frames.raw"
    red = bytes([255, 0, 0])
    green = bytes([0, 255, 0])
    raw.write_bytes((red + green + green + green) * 3)
    source = workspace / "plate.mkv"
    encoded = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", "2x2", "-r", "1", "-i", str(raw), "-c:v", "ffv1", "-pix_fmt", "bgr0",
            str(source),
        ],
        capture_output=True, check=False,
    )
    if encoded.returncode != 0 or not source.is_file():
        pytest.skip("ffv1 encode unavailable")
    before = source.read_bytes()
    result = _call(handlers, {"workspace": "clip", "source": str(source), "mode": "green"})["result"]
    assert set(result) == {"file", "url", "sha256", "frames", "report"}
    assert result["frames"] == 3
    assert result["file"].endswith(".webm")
    output = workspace / result["file"]
    assert output.is_file() and output.stat().st_size > 0
    assert result["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert "workspace=clip" in result["url"]
    assert source.read_bytes() == before


@pytest.mark.parametrize("screen, backdrop", [("magenta", (255, 0, 255)), ("blue", (0, 0, 255))])
def test_blue_and_magenta_screens_keep_a_green_subject(tmp_path, screen, backdrop):
    # A green prop on a green screen would vanish; the other screens keep it.
    workspace, _uploads, handlers = _layout(tmp_path)
    (workspace / "prop.png").write_bytes(_png(2, 1, bytes([*backdrop, 30, 200, 60])))
    result = _call(handlers, {"workspace": "clip", "source": "prop.png", "mode": screen})["result"]
    with Image.open(workspace / result["file"]) as keyed:
        screen_pixel, subject = list(keyed.convert("RGBA").getdata())
    assert screen_pixel[3] == 0
    assert subject[3] == 255 and subject[1] > 150


def test_same_intent_replays_without_keying_again(tmp_path):
    workspace, _uploads, handlers = _layout(tmp_path)
    (workspace / "plate.png").write_bytes(_plate())
    command = {"version": 1, "intent_id": "key-plate-1", "input": {"workspace": "clip", "source": "plate.png"}}
    first = asyncio.run(handlers["studio.key"](command))["result"]
    again = asyncio.run(handlers["studio.key"](command))["result"]
    assert again["file"] == first["file"] and again["replayed"] is True
    assert len(list(workspace.glob("plate-key*.png"))) == 1
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(handlers["studio.key"]({**command, "input": {**command["input"], "mode": "magenta"}}))
    assert conflict.value.status_code == 409


def _weak_screen(width: int = 40, height: int = 40, screen=(48, 155, 80), figure=(128, 128, 128)) -> np.ndarray:
    """A generated 'green screen' that is only 0.29 green, with a grey square in the middle and a darker corner."""
    rgb = np.empty((height, width, 3), dtype=np.uint8)
    rgb[:] = screen
    rgb[:6, :6] = (40, 120, 66)  # a vignetted corner, only 0.21 green
    rgb[12:28, 12:28] = figure
    rgb[11, 12:28] = [(a + b) // 2 for a, b in zip(screen, figure)]  # one mixed edge row
    return rgb


def test_weak_screen_leaves_no_haze_and_reports_the_residual(tmp_path):
    workspace, _uploads, handlers = _layout(tmp_path)
    Image.fromarray(_weak_screen()).save(workspace / "pose.png")
    result = _call(handlers, {"workspace": "clip", "source": "pose.png"})["result"]
    report = result["report"]
    assert report["adaptive"] is True and report["despill"] is True and report["haze"] is False
    assert report["screenColor"] == "#309b50" and 0.25 < report["screenStrength"] < 0.32
    assert report["semiTransparentShare"] <= 0.02
    with Image.open(workspace / result["file"]) as keyed:
        rgba = np.asarray(keyed.convert("RGBA"))
    assert int(rgba[..., 3][:6, :6].max()) == 0  # the darker corner is cleared from the border
    assert int(rgba[30:, :, 3].max()) == 0 and int(rgba[20, 20, 3]) == 255
    edge = [int(channel) for channel in rgba[11, 20]]
    assert 0 < edge[3] < 255 and edge[1] <= max(edge[0], edge[2]) * 1.02 + 6  # the mixed row is grey, not green


def test_fixed_key_on_a_weak_screen_reports_the_haze(tmp_path):
    workspace, _uploads, handlers = _layout(tmp_path)
    Image.fromarray(_weak_screen()).save(workspace / "pose.png")
    result = _call(handlers, {"workspace": "clip", "source": "pose.png", "adaptive": False})["result"]
    report = result["report"]
    assert report["adaptive"] is False and report["haze"] is True and report["semiTransparentShare"] > 0.5
    assert "another mode" in report["note"]


def test_a_strong_screen_keys_as_the_fixed_key_did(tmp_path):
    workspace, _uploads, handlers = _layout(tmp_path)
    rgb = np.zeros((20, 20, 3), dtype=np.uint8)
    rgb[:] = (0, 255, 0)
    rgb[5:15, 5:15] = (180, 220, 40)
    Image.fromarray(rgb).save(workspace / "plate.png")
    adaptive = _call(handlers, {"workspace": "clip", "source": "plate.png"})["result"]
    with Image.open(workspace / adaptive["file"]) as keyed:
        rgba, fixed = np.asarray(keyed.convert("RGBA")), green_rgba(rgb)
    assert np.array_equal(rgba[..., 3], fixed[..., 3])  # same matte
    red, green, blue = (int(channel) for channel in rgba[10, 10, :3])
    assert green <= max(red, blue) * 1.02 + 6  # the semi-transparent figure has no green cast
    assert adaptive["report"]["screenStrength"] == 1.0


def test_border_without_a_screen_falls_back_to_the_fixed_key(tmp_path):
    workspace, _uploads, handlers = _layout(tmp_path)
    rgb = np.zeros((20, 20, 3), dtype=np.uint8)
    rgb[:] = (120, 90, 60)
    rgb[8:12, 8:12] = (0, 255, 0)
    Image.fromarray(rgb).save(workspace / "photo.png")
    report = _call(handlers, {"workspace": "clip", "source": "photo.png"})["result"]["report"]
    assert report["screenColor"] is None and "fixed key" in report["note"]


def test_key_options_must_be_booleans(tmp_path):
    workspace, _uploads, handlers = _layout(tmp_path)
    (workspace / "plate.png").write_bytes(_plate())
    with pytest.raises(HTTPException) as error:
        _call(handlers, {"workspace": "clip", "source": "plate.png", "despill": "yes"})
    assert error.value.status_code == 422
    properties = command_catalog()[0]["inputSchema"]["properties"]["input"]["properties"]
    assert properties["adaptive"]["type"] == "boolean" and properties["despill"]["type"] == "boolean"

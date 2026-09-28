"""Scene asset facts: cached probes, real PNG alpha, and workspace confinement."""
from __future__ import annotations

import asyncio
import json
import os
import struct
import zlib
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.scene_asset_facts import (
    MAX_NAMES,
    SceneAssetFactsError,
    assemble_asset,
    aspect_ratio,
    command_catalog,
    command_handlers,
    declared_from_metadata,
    duration_from_probe,
    facts_sidecar_path,
    inspect_scene_assets,
    measure_media,
)


def _png(path: Path, *, color_type: int, pixel: bytes) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, color_type, 0, 0, 0)
    raw = b"\x00" + pixel
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


def _inspect(root: Path, names: list[str], **kwargs):
    return inspect_scene_assets("demo", names, workspace_dir=lambda _name: str(root), **kwargs)


def test_cache_hit_skips_probe_until_the_file_changes(tmp_path: Path):
    root = _workspace(tmp_path)
    image = root / "hero.png"
    _png(image, color_type=2, pixel=b"\xff\x00\x00")
    calls: list[str] = []

    def measure(path: str) -> dict:
        calls.append(path)
        return measure_media(path)

    first = _inspect(root, ["hero.png"], measure=measure)
    second = _inspect(root, ["hero.png"], measure=measure)
    assert len(calls) == 1
    assert second == first
    sidecar = json.loads(Path(facts_sidecar_path(str(image))).read_text(encoding="utf-8"))
    assert sidecar["size"] == image.stat().st_size
    assert sidecar["mtime_ns"] == image.stat().st_mtime_ns
    assert sidecar["measured"]["type"] == "image"
    os.utime(image, (image.stat().st_atime, image.stat().st_mtime + 10))
    _inspect(root, ["hero.png"], measure=measure)
    assert len(calls) == 2


def test_png_alpha_comes_from_the_format(tmp_path: Path):
    root = _workspace(tmp_path)
    _png(root / "hero.png", color_type=6, pixel=b"\x00\x00\x00\x80")
    _png(root / "plate.png", color_type=2, pixel=b"\xff\x00\x00")
    assets = {item["name"]: item for item in _inspect(root, ["hero.png", "plate.png"])["assets"]}
    assert assets["hero.png"]["type"] == "image"
    assert assets["hero.png"]["alpha"] is True
    assert assets["hero.png"]["width"] == 1
    assert assets["hero.png"]["height"] == 1
    assert assets["hero.png"]["aspect"] == "1:1"
    assert assets["plate.png"]["alpha"] is False
    assert "duration" not in assets["hero.png"]
    assert "suggestedRole" not in assets["hero.png"]
    assert "seamlessHorizontal" not in assets["hero.png"]
    assert assets["hero.png"]["thumbnailUrl"].startswith("/api/v1/outputs/thumbnail/hero.png?")
    assert "workspace=demo" in assets["hero.png"]["thumbnailUrl"]


def test_names_that_escape_the_workspace_are_rejected(tmp_path: Path):
    root = _workspace(tmp_path)
    outside = tmp_path / "secret.png"
    _png(outside, color_type=2, pixel=b"\x00\xff\x00")
    secret = outside.read_bytes()
    link = root / "link.png"
    link.symlink_to(outside)
    for name in ("../secret.png", "nested/../../secret.png", outside.as_posix(), "/etc/passwd", "link.png"):
        with pytest.raises(SceneAssetFactsError) as caught:
            _inspect(root, [name])
        assert caught.value.status == 400
        assert caught.value.code == "path_not_allowed"
    assert outside.read_bytes() == secret
    assert list(root.iterdir()) == [link]


def test_unknown_file_is_404(tmp_path: Path):
    root = _workspace(tmp_path)
    with pytest.raises(SceneAssetFactsError) as caught:
        _inspect(root, ["missing.png"])
    assert caught.value.status == 404
    assert caught.value.code == "file_not_found"


def test_role_and_seam_come_only_from_recorded_metadata(tmp_path: Path):
    root = _workspace(tmp_path)
    _png(root / "hero.png", color_type=6, pixel=b"\xff\x00\x00\xff")
    meta_path = root / "hero.meta.json"
    meta_path.write_text(json.dumps({
        "params": {"prompt": "a plate with an overlay cutout", "role": "hero", "seamlessHorizontal": False},
    }), encoding="utf-8")
    plain = _inspect(root, ["hero.png"])["assets"][0]
    assert "suggestedRole" not in plain
    assert "seamlessHorizontal" not in plain
    meta_path.write_text(json.dumps({
        "params": {
            "prompt": "a plate with an overlay cutout",
            "suggestedRole": "cutout",
            "seamlessHorizontal": True,
        },
    }), encoding="utf-8")
    calls: list[str] = []

    def measure(path: str) -> dict:
        calls.append(path)
        raise AssertionError("fresh sidecar must not probe again")

    recorded = _inspect(root, ["hero.png"], measure=measure)["assets"][0]
    assert calls == []
    assert recorded["suggestedRole"] == "cutout"
    assert recorded["seamlessHorizontal"] is True
    saved = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved["params"]["prompt"] == "a plate with an overlay cutout"
    cached = json.loads(Path(facts_sidecar_path(str(root / "hero.png"))).read_text(encoding="utf-8"))
    assert "suggestedRole" not in cached["measured"]


def test_declared_metadata_ignores_prose_and_accepts_catalog_labels():
    assert declared_from_metadata({"params": {"prompt": "plate overlay cutout", "style": "anime"}}) == {}
    assert declared_from_metadata({"params": {"style": "cutout"}}) == {"suggestedRole": "cutout"}
    assert declared_from_metadata({"params": {"kind": "overlay"}}) == {"suggestedRole": "overlay"}
    assert declared_from_metadata({"generation": {"parameters": {"role": "plate"}}}) == {"suggestedRole": "plate"}
    assert declared_from_metadata({"technical": {"seamless_horizontal": True}}) == {"seamlessHorizontal": True}
    assert declared_from_metadata({"params": {"kind": "image", "role": "background", "seamlessHorizontal": "true"}}) == {}


def test_assemble_asset_uses_synthesized_probe_fields():
    video = assemble_asset(
        "clip.mp4",
        kind="video",
        measured={"type": "video", "width": 1920, "height": 1080, "aspect": "16:9", "duration": 2.5, "alpha": True},
        declared={},
        thumbnail_url="/api/v1/outputs/thumbnail/clip.mp4?v=1-2&workspace=demo",
    )
    assert video["width"] == 1920
    assert video["height"] == 1080
    assert video["aspect"] == "16:9"
    assert video["duration"] == 2.5
    assert "alpha" not in video
    assert "suggestedRole" not in video
    assert "seamlessHorizontal" not in video
    audio = assemble_asset(
        "song.wav",
        kind="audio",
        measured={"type": "audio", "duration": 3, "width": 10, "height": 10},
        declared={"suggestedRole": "plate"},
        thumbnail_url="http://example.invalid/thumb.jpg",
    )
    assert audio == {"name": "song.wav", "type": "audio", "duration": 3.0, "suggestedRole": "plate"}
    assert aspect_ratio(1920, 1080) == "16:9"
    assert duration_from_probe({"format": {"duration": "1.5"}}) == 1.5
    assert duration_from_probe({"format": {"duration": "0"}}) is None
    assert duration_from_probe({}) is None


def test_limits_names_before_touching_the_workspace():
    def fail(_name: str) -> str:
        raise AssertionError("workspace should not be resolved")

    with pytest.raises(SceneAssetFactsError) as caught:
        inspect_scene_assets("demo", [f"{index}.png" for index in range(MAX_NAMES + 1)], workspace_dir=fail)
    assert caught.value.code == "too_many_names"
    with pytest.raises(SceneAssetFactsError) as caught:
        inspect_scene_assets("../demo", ["hero.png"], workspace_dir=fail)
    assert caught.value.code == "invalid_workspace"


def test_command_schema_limits_names_and_handler_reports_stable_codes(tmp_path: Path):
    catalog = command_catalog()
    assert [item["name"] for item in catalog] == ["scenes.assets.inspect"]
    assert catalog[0]["mutation"] is False
    names = catalog[0]["inputSchema"]["properties"]["input"]["properties"]["names"]
    assert names["maxItems"] == 20
    assert names["minItems"] == 1
    root = _workspace(tmp_path)
    handlers = command_handlers(lambda _name: str(root))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["scenes.assets.inspect"]({
            "version": 1, "input": {"workspace": "demo", "names": ["../secret.png"]},
        }))
    assert caught.value.status_code == 400
    assert caught.value.detail == {"code": "path_not_allowed", "message": "Media path is not allowed"}

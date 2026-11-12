"""media.compose draws image layers over a base image, a video frame or a blank canvas."""
from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from tests.media_tool_fixtures import Install, frames_video, needs_ffmpeg


def _cutout(path, size=(20, 40), color=(255, 0, 0), feet_gap=10) -> None:
    """A figure on transparency whose lowest opaque row is ``feet_gap`` px above the image bottom."""
    rgba = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    rgba[: size[1] - feet_gap] = (*color, 255)
    Image.fromarray(rgba).save(path)


def _pixels(path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"))


def test_layers_land_by_centre_scale_and_bottom_anchor(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    Image.new("RGB", (200, 100), (0, 0, 255)).save(folder / "plate.png")
    _cutout(folder / "hero.png")
    result = install.call("media.compose", {"workspace": "ep", "base": "plate.png", "output_name": "start", "layers": [
        {"file": "hero.png", "x": 25, "y": 50},
        {"file": "hero.png", "x": 75, "y": 90, "scale": 0.8, "anchor": "bottom"},
    ]})["result"]
    assert result["file"] == "start.png" and (result["width"], result["height"]) == (200, 100) and result["layers"] == 2
    image = _pixels(folder / result["file"])
    assert tuple(image[50, 50, :3]) == (255, 0, 0)  # native 20x40 centred on (50, 50): rows 30-70, opaque to 60
    assert tuple(image[65, 50, :3]) == (0, 0, 255)  # its transparent feet gap shows the plate
    rows = np.where((image[:, 140:160, 0] > 40).any(axis=1))[0]
    assert rows.max() == 89  # the lowest opaque row (its soft resampled edge included) stands on y = 90 %
    assert 80 - 20 - 1 <= rows.max() - rows.min() + 1 <= 80  # scaled to 0.8 of the canvas height minus its gap
    meta = json.loads((folder / "start.meta.json").read_text())
    assert meta["origin"]["tool"] == "media.compose"
    assert [parent["role"] for parent in meta["lineage"]["parents"]] == ["base", "layer", "layer"]


def test_blank_canvas_opacity_flip_rotation_and_jpg(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    half = np.zeros((10, 20, 4), dtype=np.uint8)
    half[:, :10] = (0, 255, 0, 255)  # opaque on its left half only
    Image.fromarray(half).save(folder / "half.png")
    flipped = install.call("media.compose", {"workspace": "ep", "size": [40, 20], "layers": [
        {"file": "half.png", "flip": True, "opacity": 0.5}]})["result"]
    image = _pixels(folder / flipped["file"])
    assert image[10, 25, 3] in range(120, 136) and image[10, 15, 3] == 0  # mirrored to the right half, half alpha
    turned = install.call("media.compose", {"workspace": "ep", "size": [40, 40], "background": "#ffffff", "format": "jpg",
                                            "layers": [{"file": "half.png", "rotation": 90}]})["result"]
    assert turned["file"].endswith(".jpg")
    with Image.open(folder / turned["file"]) as jpg:
        rgb = np.asarray(jpg.convert("RGB")).astype(int)
    assert rgb[14, 20, 1] > 200 and rgb[14, 20, 0] < 60  # clockwise: the left half is now on top
    assert rgb[26, 20].min() > 200  # the bottom stays white


@needs_ffmpeg
def test_a_video_base_uses_its_last_frame(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    frames_video(folder / "clip.mkv", count=24)
    _cutout(folder / "hero.png", size=(8, 8), feet_gap=0)
    result = install.call("media.compose", {"workspace": "ep", "base": "clip.mkv", "base_at": "last",
                                            "layers": [{"file": "hero.png", "x": 10, "y": 10}]})["result"]
    image = _pixels(folder / result["file"])
    assert (result["width"], result["height"]) == (64, 48)
    assert abs(int(image[40, 40, 0]) - 230) <= 3 and tuple(image[5, 6, :3]) == (255, 0, 0)
    assert not list(folder.glob(".frame-*"))


def test_bad_layers_and_canvas_are_refused(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    _cutout(folder / "hero.png")
    cases = [
        ({"size": [40, 20], "base": "hero.png", "layers": [{"file": "hero.png"}]}, "invalid_command"),
        ({"size": [40, 20], "layers": [{"file": "hero.png", "scale": 0.5, "width": 0.5}]}, "invalid_command"),
        ({"size": [40, 20], "layers": [{"file": "hero.png", "opacity": 2}]}, "invalid_command"),
        ({"size": [40, 20], "layers": [{"file": "missing.png"}]}, "media_not_found"),
        ({"size": [40, 20], "layers": [{"file": "hero.png"}] * 17}, "invalid_command"),
        ({"size": [5000, 20], "layers": [{"file": "hero.png"}]}, "invalid_command"),
        ({"size": [40, 20], "background": "red", "layers": [{"file": "hero.png"}]}, "invalid_command"),
    ]
    for payload, code in cases:
        with pytest.raises(HTTPException) as error:
            install.call("media.compose", {"workspace": "ep", **payload})
        assert error.value.detail["code"] == code, payload
    assert not list(folder.glob("compose*"))

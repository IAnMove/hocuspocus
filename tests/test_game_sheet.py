"""Sprite-sheet packing and cell rounding on synthetic frames."""
from pathlib import Path

import numpy as np
from PIL import Image

from services.game_sheet import pack_rows, uniform_cell, write_gif_preview


def _block(width: int, height: int, color: tuple[int, int, int, int]) -> np.ndarray:
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[...,] = color
    return image


def test_uniform_cell_rounds_content_plus_pad_up_to_the_grid():
    wide = np.zeros((6, 10, 4), dtype=np.uint8)
    width, height = uniform_cell([wide], grid=8, pad=1)
    assert (width, height) == (16, 8)
    assert width % 8 == 0 and height % 8 == 0

    bare_w, bare_h = uniform_cell([wide], grid=8, pad=0)
    assert (bare_w, bare_h) == (16, 8)

    exact_w, exact_h = uniform_cell([wide], grid=1, pad=0)
    assert (exact_w, exact_h) == (10, 6)

    odd = np.zeros((7, 17, 4), dtype=np.uint8)
    assert uniform_cell([odd], grid=8, pad=0) == (24, 8)


def test_pack_rows_tags_duration_and_sheet_size():
    fps = 12
    sprite = np.zeros((4, 4, 4), dtype=np.uint8)
    sprite[0, 0] = (255, 0, 0, 255)
    sprite[3, 3] = (0, 0, 255, 255)
    other = _block(4, 4, (0, 255, 0, 255))
    walk = [sprite.copy() for _ in range(3)]
    idle = [other.copy() for _ in range(2)]
    animations = [
        {"name": "walk", "frames": walk, "fps": fps, "loop": True},
        {"name": "idle", "frames": idle, "fps": fps, "loop": False},
    ]
    cell = uniform_cell([sprite, other], grid=1, pad=2)
    assert cell == (8, 8)
    image, atlas = pack_rows(animations, cell)
    assert image.size == (cell[0] * 3, cell[1] * 2)
    tags = atlas["meta"]["frameTags"]
    assert [(tag["name"], tag["from"], tag["to"], tag["direction"]) for tag in tags] == [
        ("walk", 0, 2, "forward"),
        ("idle", 3, 4, "forward"),
    ]
    duration = int(round(1000 / fps))
    assert duration == 83
    for record in atlas["frames"].values():
        assert record["duration"] == duration
        assert record["rotated"] is False
        assert record["trimmed"] is False
    assert atlas["meta"]["loop"] == {"walk": True, "idle": False}
    assert atlas["meta"]["pivot"] == {"x": cell[0] // 2, "y": cell[1] - 1}
    assert atlas["meta"]["size"] == {"w": image.size[0], "h": image.size[1]}
    assert atlas["meta"]["app"] == "HocusPocus"
    assert atlas["meta"]["format"] == "RGBA8888"
    assert atlas["meta"]["mirror"] is True
    assert atlas["frames"]["walk_0"]["frame"] == {"x": 0, "y": 0, "w": 8, "h": 8}
    assert atlas["frames"]["walk_1"]["frame"]["x"] == 8
    assert atlas["frames"]["idle_0"]["frame"] == {"x": 0, "y": 8, "w": 8, "h": 8}
    assert atlas["frames"]["idle_1"]["frame"]["x"] == 8
    pixels = np.asarray(image)
    assert tuple(int(channel) for channel in pixels[2, 2]) == (255, 0, 0, 255)
    assert tuple(int(channel) for channel in pixels[5, 5]) == (0, 0, 255, 255)
    assert int(pixels[0, 0, 3]) == 0


def test_write_gif_preview_scales_nearest_and_loops(tmp_path: Path):
    frames = []
    for color in ((255, 0, 0, 255), (0, 255, 0, 255)):
        image = np.zeros((4, 4, 4), dtype=np.uint8)
        image[0, 0] = color
        frames.append(image)
    path = tmp_path / "preview.gif"
    write_gif_preview(frames, fps=10, scale=2, path=path)
    with Image.open(path) as gif:
        assert gif.n_frames == 2
        assert gif.size == (8, 8)
        assert gif.info.get("duration") == 100
        assert gif.info.get("loop") == 0
        first = gif.convert("RGBA")
        assert first.getpixel((0, 0))[0] > 200
        assert first.getpixel((1, 1))[0] > 200
        assert first.getpixel((2, 2))[3] == 0

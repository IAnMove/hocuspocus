"""Crop, pivot placement and dHash on synthetic sprites."""
import numpy as np
from PIL import Image

from services.game_image_ops import (
    compose_start_frame,
    despill,
    dhash,
    feet_point,
    hamming,
    place_on_cell,
    to_illustration,
)


def test_place_on_cell_lands_the_feet_on_the_pivot():
    sprite = np.zeros((6, 5, 4), dtype=np.uint8)
    sprite[5, 2] = (0, 255, 0, 255)
    canvas = place_on_cell(sprite, (24, 20), (11, 16), (2, 5))
    assert canvas[16, 11, 1] == 255
    assert canvas[16, 11, 3] == 255


def test_feet_point_uses_the_lowest_opaque_row():
    sprite = np.zeros((10, 8, 4), dtype=np.uint8)
    sprite[8, 2:6] = (255, 255, 255, 255)
    sprite[2, 3] = (255, 255, 255, 255)
    point = feet_point(sprite)
    assert point[1] == 8
    assert abs(point[0] - 3.5) <= 1


def test_dhash_matches_a_scaled_copy_and_rejects_a_different_picture():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    pixels = image.load()
    for y in range(16, 48):
        for x in range(16, 48):
            if (x - 32) ** 2 + (y - 32) ** 2 < 16 ** 2:
                pixels[x, y] = (255, 220, 40, 255)
    source = np.asarray(image)
    scaled = np.asarray(image.resize((96, 96), Image.Resampling.NEAREST))
    other = np.zeros_like(source)
    other[4:20, 40:60] = (20, 80, 255, 255)
    assert hamming(dhash(source), dhash(scaled)) <= 4
    assert hamming(dhash(source), dhash(other)) > 12


def _disk(size=64, radius=20, color=(100, 100, 100)):
    yy, xx = np.ogrid[:size, :size]
    image = np.zeros((size, size, 4), dtype=np.uint8)
    image[(yy - size // 2) ** 2 + (xx - size // 2) ** 2 < radius ** 2] = (*color, 255)
    return image


def test_to_illustration_edges_are_not_brighter_than_the_source():
    color = (40, 160, 90)
    for height in (11, 21, 37):
        result = to_illustration(_disk(color=color), height, "magenta").astype(np.int32)
        visible = result[..., 3] > 0
        partial = visible & (result[..., 3] < 255)
        assert partial.any()
        for channel, limit in enumerate(color):
            assert int(result[..., channel][visible].max()) <= limit


def test_magenta_despill_keeps_red_and_blue_figures():
    pixels = np.zeros((1, 3, 4), dtype=np.uint8)
    pixels[0, 0] = (200, 30, 30, 128)
    pixels[0, 1] = (30, 30, 200, 128)
    pixels[0, 2] = (200, 30, 180, 0)
    result = despill(pixels, "magenta").astype(np.int32)
    assert tuple(result[0, 0, :3]) == (200, 30, 30)
    assert tuple(result[0, 1, :3]) == (30, 30, 200)
    red_drop = 200 - int(result[0, 2, 0])
    blue_drop = 180 - int(result[0, 2, 2])
    assert red_drop == blue_drop == 150
    assert int(result[0, 2, 1]) == 30


def test_compose_start_frame_blends_the_edge_over_the_screen():
    base = np.zeros((64, 64, 4), dtype=np.uint8)
    base[16:56, 24:40] = (0, 255, 0, 255)
    frame = compose_start_frame(base, (64, 64), "magenta").astype(np.int32)
    assert set(np.unique(frame[..., 3]).tolist()) == {255}
    assert np.array_equal(frame[..., 0], frame[..., 2])
    assert int(np.abs(frame[..., 0] + frame[..., 1] - 255).max()) <= 1
    mixed = (frame[..., 1] > 0) & (frame[..., 1] < 255)
    assert mixed.any()


def test_feet_point_ignores_faint_ringing_under_the_feet():
    sprite = np.zeros((10, 6, 4), dtype=np.uint8)
    sprite[2:7, 1:5] = (255, 255, 255, 255)
    sprite[8, :] = (255, 255, 255, 3)
    assert feet_point(sprite)[1] == 6


def test_dhash_ignores_rgb_hidden_under_transparent_pixels():
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[4:12, 4:12] = (255, 255, 255, 255)
    noisy = sprite.copy()
    hidden = noisy[..., 3] == 0
    noisy[hidden, :3] = np.random.default_rng(3).integers(0, 256, (int(hidden.sum()), 3), dtype=np.uint8)
    assert dhash(noisy) == dhash(sprite)

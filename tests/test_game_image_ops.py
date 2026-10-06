"""Crop, pivot placement and dHash on synthetic sprites."""
import numpy as np
from PIL import Image

from services.game_image_ops import dhash, feet_point, hamming, place_on_cell


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

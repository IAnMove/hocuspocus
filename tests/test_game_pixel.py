"""Deterministic pixel post-process on synthetic images."""
import numpy as np

from services.game_pixel import median_cut, pixel_metrics, to_pixel


def _block(color, alpha=255, size=8):
    image = np.zeros((size, size, 4), dtype=np.uint8)
    image[2:-2, 2:-2] = (*color, alpha)
    return image


def test_to_pixel_stays_on_palette_and_binarizes_alpha():
    image = _block((180, 40, 40))
    image[2, 2, 3] = 100
    image[3, 3, 3] = 200
    palette = ["#ff0000", "#000000"]
    result = to_pixel(image, 1, palette, "none", False)
    opaque = result[..., 3] == 255
    assert set(np.unique(result[..., 3])).issubset({0, 255})
    colors = {tuple(int(channel) for channel in pixel) for pixel in result[opaque][..., :3]}
    assert colors
    assert colors.issubset({(255, 0, 0), (0, 0, 0)})
    assert pixel_metrics(result, palette)["offPalettePct"] == 0.0


def test_isolated_pixel_disappears():
    image = np.zeros((8, 8, 4), dtype=np.uint8)
    image[4, 4] = (255, 0, 0, 255)
    result = to_pixel(image, 1, ["#ff0000"], "none", False)
    assert result[4, 4, 3] == 0
    assert int(result[..., 3].sum()) == 0


def test_outline_rings_the_figure_and_leaves_the_interior():
    image = np.zeros((11, 11, 4), dtype=np.uint8)
    image[3:8, 3:8] = (255, 0, 0, 255)
    result = to_pixel(image, 1, ["#ff0000", "#101010"], "dark-1px", False)
    assert tuple(result[5, 5, :3]) == (255, 0, 0)
    assert result[2, 5, 3] == 255
    assert tuple(result[2, 5, :3]) == (16, 16, 16)
    assert tuple(result[5, 5, :3]) != (16, 16, 16)


def test_median_cut_is_deterministic():
    rng = np.random.default_rng(4)
    image = np.zeros((16, 16, 4), dtype=np.uint8)
    image[..., :3] = rng.integers(0, 255, (16, 16, 3), dtype=np.uint8)
    image[..., 3] = 255
    assert median_cut(image, 6) == median_cut(image, 6)
    assert len(median_cut(image, 6)) == 6

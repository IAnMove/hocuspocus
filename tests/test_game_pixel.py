"""Deterministic pixel post-process on synthetic images."""
import numpy as np

from services import game_pixel
from services.game_pixel import median_cut, nearest_palette, oklab, pixel_metrics, to_pixel


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


def _ramp(width=32, height=8):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[..., 0] = np.linspace(0, 255, width).astype(np.uint8)[None, :]
    image[..., 3] = 255
    return image


def test_black_outline_is_black_not_the_first_palette_color():
    image = np.zeros((11, 11, 4), dtype=np.uint8)
    image[3:8, 3:8] = (255, 0, 0, 255)
    result = to_pixel(image, 1, ["#ff0000", "#101010"], "black-1px", False)
    assert tuple(int(channel) for channel in result[2, 5]) == (0, 0, 0, 255)
    assert tuple(int(channel) for channel in result[5, 5]) == (255, 0, 0, 255)


def test_dither_patterns_a_ramp_and_stays_on_the_palette():
    palette = ["#000000", "#ff0000"]
    plain = to_pixel(_ramp(), 1, palette, "none", False)
    dithered = to_pixel(_ramp(), 1, palette, "none", True)
    assert np.array_equal(dithered, to_pixel(_ramp(), 1, palette, "none", True))
    assert int((plain != dithered).any(axis=2).sum()) > 0
    colors = {tuple(int(channel) for channel in pixel) for pixel in dithered.reshape(-1, 4)}
    assert colors == {(0, 0, 0, 255), (255, 0, 0, 255)}
    middle = dithered[:, 12:20, 0]
    assert 0 < int((middle == 255).sum()) < middle.size


def test_dither_leaves_the_outline_alone_and_zeroes_transparent_rgb():
    image = np.zeros((16, 16, 4), dtype=np.uint8)
    image[4:12, 4:12] = (128, 128, 128, 255)
    palette = ["#ffffff", "#808080", "#202020"]
    for dither in (False, True):
        result = to_pixel(image, 1, palette, "dark-1px", dither)
        ring = result[3, 4:12]
        assert all(tuple(int(channel) for channel in pixel) == (32, 32, 32, 255) for pixel in ring)
        assert tuple(int(channel) for channel in result[0, 0]) == (0, 0, 0, 0)


def test_transparent_pixels_do_not_keep_the_first_palette_color():
    image = np.zeros((8, 8, 4), dtype=np.uint8)
    image[2:6, 2:6] = (255, 0, 0, 255)
    result = to_pixel(image, 1, ["#00ff00", "#ff0000"], "none", False)
    transparent = result[..., 3] == 0
    assert transparent.any()
    assert int(result[transparent][:, :3].astype(np.int32).max()) == 0


def test_chunked_palette_distance_matches_one_pass(monkeypatch):
    rng = np.random.default_rng(7)
    image = rng.integers(0, 256, (23, 19, 4), dtype=np.uint8)
    palette = ["#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff"]
    palette_lab = oklab(game_pixel._parse_palette(palette).reshape(-1, 1, 3)).reshape(-1, 3)
    flat = oklab(image[..., :3]).reshape(-1, 3)
    reference = np.linalg.norm(flat[:, None, :] - palette_lab[None, :, :], axis=2)
    whole_metrics = pixel_metrics(image, palette)
    monkeypatch.setattr(game_pixel, "_CHUNK", 7)
    assert pixel_metrics(image, palette) == whole_metrics
    assert np.array_equal(nearest_palette(image[..., :3], palette_lab).ravel(), reference.argmin(axis=1))
    opaque = (image[..., 3] >= 128).ravel()
    expected = float((reference.min(axis=1)[opaque] * 100.0 > 10.0).mean() * 100.0)
    assert whole_metrics["offPalettePct"] == expected

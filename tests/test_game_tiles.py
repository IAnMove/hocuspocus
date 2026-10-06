"""Seam metric, half-roll and 9-slice on synthetic textures."""
import numpy as np

from services.game_tiles import nine_slice_margins, roll_half, seam_error, unroll


def test_periodic_texture_is_acceptable_and_a_broken_edge_is_not():
    ramp = np.concatenate([np.arange(0, 16), np.arange(15, -1, -1)]).astype(np.uint8)
    periodic = np.zeros((32, 32, 3), dtype=np.uint8)
    periodic[..., 0] = ramp[None, :] * 8
    periodic[..., 1] = ramp[:, None] * 8
    periodic[..., 2] = 90
    assert seam_error(periodic) < 1.1

    broken = np.full((32, 32, 3), 128, dtype=np.uint8)
    broken[:, 0] = 0
    broken[:, -1] = 255
    assert seam_error(broken) > 3


def test_roll_half_then_unroll_is_identity():
    image = np.arange(16 * 18 * 3, dtype=np.uint8).reshape(16, 18, 3)
    rolled = roll_half(image)
    assert not np.array_equal(rolled, image)
    assert np.array_equal(unroll(rolled), image)


def test_unroll_inverts_roll_half_at_odd_sizes():
    image = np.arange(5 * 7 * 3, dtype=np.uint8).reshape(5, 7, 3)
    for axes in ((0, 1), (0,), (1,)):
        rolled = roll_half(image, axes)
        assert not np.array_equal(rolled, image)
        assert np.array_equal(unroll(rolled, axes), image)


def test_nine_slice_finds_a_six_pixel_border():
    panel = np.zeros((40, 48, 4), dtype=np.uint8)
    panel[..., :3] = (20, 30, 40)
    panel[6:-6, 6:-6, :3] = (220, 210, 200)
    panel[..., 3] = 255
    margins = nine_slice_margins(panel)
    for side in ("left", "right", "top", "bottom"):
        assert abs(margins[side] - 6) <= 1

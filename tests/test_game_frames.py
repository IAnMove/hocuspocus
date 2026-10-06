"""Cycle finding, drift removal and VFX alpha on synthetic frames."""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from services.game_frames import (
    drift_correct,
    extract_frames,
    find_cycle,
    key_frames,
    sample_frames,
    select_range,
    vfx_alpha,
)
from services.game_image_ops import feet_point


def _moving_disk(index: int, period: int = 10, noise: int = 2) -> np.ndarray:
    frame = np.zeros((64, 64, 4), dtype=np.uint8)
    shift = (index % period) * 4
    cy, cx, radius = 32, 10 + shift, 6
    yy, xx = np.ogrid[:64, :64]
    mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= radius ** 2
    frame[mask, 0] = 240
    frame[mask, 1] = 180
    frame[mask, 2] = 40
    frame[mask, 3] = 255
    rng = np.random.default_rng(1000 + index)
    delta = rng.integers(-noise, noise + 1, size=frame[..., :3].shape, dtype=np.int16)
    frame[..., :3] = np.clip(frame[..., :3].astype(np.int16) + delta, 0, 255).astype(np.uint8)
    return frame


def _square_frame(x: int, y: int) -> np.ndarray:
    frame = np.zeros((80, 96, 4), dtype=np.uint8)
    frame[y:y + 8, x:x + 8] = (255, 255, 255, 255)
    return frame


def test_find_cycle_recovers_a_ten_frame_loop():
    frames = [_moving_disk(index) for index in range(30)]
    start, period, error = find_cycle(frames, fps=10, min_s=0.4)
    assert start == 0
    assert abs(period - 10) <= 1
    assert error < 0.6


def test_find_cycle_accepts_a_loop_that_closes_on_the_last_frame():
    frames = [_moving_disk(index) for index in range(11)]
    start, period, error = find_cycle(frames, fps=10, min_s=0.4)
    assert (start, period) == (0, 10)
    assert error < 0.6


def test_find_cycle_without_a_loop_spans_every_frame():
    single = [_moving_disk(0)]
    start, span, error = find_cycle(single, fps=10)
    assert (start, span, error) == (0, 1, 1.0)
    assert len(sample_frames(single, start, span, 1)) == 1

    drifting = [_moving_disk(index, period=100) for index in range(6)]
    start, span, error = find_cycle(drifting, fps=10, min_s=0.2)
    assert (start, span, error) == (0, 6, 1.0)
    picked = sample_frames(drifting, start, span, 6)
    assert picked[-1] is drifting[-1]


def test_drift_correct_removes_linear_x_and_keeps_the_jump():
    frames = []
    for index in range(10):
        x = 8 + 3 * index
        y = int(round(18 + (index - 4.5) ** 2))
        frames.append(_square_frame(x, y))
    before_y = [feet_point(frame)[1] for frame in frames]
    before_x = [feet_point(frame)[0] for frame in frames]
    corrected = drift_correct(frames, keep_vertical=True)
    after_x = [feet_point(frame)[0] for frame in corrected]
    after_y = [feet_point(frame)[1] for frame in corrected]
    before_range = max(before_y) - min(before_y)
    after_range = max(after_y) - min(after_y)
    assert max(before_x) - min(before_x) >= 25
    assert max(after_x) - min(after_x) <= 2
    assert before_range > 10
    assert abs(after_range - before_range) <= 2
    for before, after in zip(frames, corrected):
        assert np.array_equal(before[..., 3].any(axis=1), after[..., 3].any(axis=1))


def test_vfx_alpha_keys_black_and_drops_empty_ends():
    black = np.zeros((8, 8, 3), dtype=np.uint8)
    middle = np.zeros((8, 8, 3), dtype=np.uint8)
    middle[3, 4] = (255, 255, 255)
    middle[1, 1] = (100, 0, 0)
    result = vfx_alpha([black, middle, black])
    assert len(result) == 1
    frame = result[0]
    assert frame.shape == (8, 8, 4)
    assert frame[0, 0, 3] == 0
    assert tuple(int(channel) for channel in frame[3, 4]) == (255, 255, 255, 255)
    assert tuple(int(channel) for channel in frame[1, 1]) == (255, 0, 0, 100)


def test_sample_frames_uses_even_intervals_on_a_half_open_span():
    frames = list(range(20))
    assert sample_frames(frames, 0, 10, 5) == [0, 2, 4, 6, 8]


def test_select_range_picks_the_lookalike_in_the_tail():
    base = _square_frame(8, 40)
    frames = [
        _square_frame(40, 10),
        _square_frame(30, 20),
        _square_frame(20, 30),
        _square_frame(8, 40),
        _square_frame(50, 12),
    ]
    chosen = select_range(frames, base, around_s=0.2, fps=10)
    assert np.array_equal(chosen, frames[3])


def test_key_frames_removes_magenta_and_keeps_the_figure(tmp_path: Path):
    image = Image.new("RGB", (16, 16), (255, 0, 255))
    pixels = image.load()
    for y in range(4, 12):
        for x in range(4, 12):
            pixels[x, y] = (200, 30, 30)
    path = tmp_path / "sprite.png"
    image.save(path)
    keyed = key_frames([path], "magenta")
    assert len(keyed) == 1
    assert keyed[0].shape[2] == 4
    assert keyed[0][0, 0, 3] == 0
    assert keyed[0][8, 8, 3] > 128
    assert keyed[0][8, 8, 0] > 128


def test_extract_frames_names_ffmpeg_when_it_is_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        extract_frames(tmp_path / "missing.mp4", 0, 1, tmp_path / "out")


def test_extract_frames_pulls_about_ten_pngs(tmp_path: Path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is missing")
    video = tmp_path / "clip.mp4"
    created = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10", "-t", "1", str(video)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr[-500:]
    paths = extract_frames(video, 0, 1, tmp_path / "frames")
    assert 8 <= len(paths) <= 12
    assert [path.name for path in paths] == [f"{index:04d}.png" for index in range(1, len(paths) + 1)]
    assert all(path.suffix == ".png" and path.is_file() for path in paths)

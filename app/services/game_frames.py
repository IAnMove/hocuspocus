"""Cut a keyed clip into a sprite cycle: extract, key, loop, and settle the feet.

CPU only. Frame grabs go through ffmpeg. Screen removal uses the public
``key_screen`` and ``clean_alpha`` helpers. Nothing here imports a private
``_`` function.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from services.game_image_ops import clean_alpha, feet_point, key_screen


# Accepted cycles are strictly under 0.6. 1.0 means "no period found".
_HIGH_LOOP_ERROR = 1.0
_THUMB_WIDTH = 64
_LUMA = (0.299, 0.587, 0.114)


def extract_frames(video, start_s, end_s, out_dir) -> list[Path]:
    """Write ``ffmpeg -y -ss {start} -t {duration} -i {video} -vsync 0 {out}/%04d.png``.

    ``duration`` is ``end_s - start_s``. A missing ffmpeg, or a failed command,
    raises ``RuntimeError`` and the message names ffmpeg. Paths come back in order.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not available; install ffmpeg to extract frames")
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    _clear_numbered_pngs(folder)
    duration = float(end_s) - float(start_s)
    pattern = folder / "%04d.png"
    command = [
        "ffmpeg", "-y",
        "-ss", str(start_s),
        "-t", str(duration),
        "-i", str(video),
        "-vsync", "0",
        str(pattern),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, errors="replace")
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not available; install ffmpeg to extract frames") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {result.returncode}"
        raise RuntimeError(f"ffmpeg failed to extract frames: {tail}")
    return _numbered_pngs(folder)


def key_frames(paths, screen) -> list[np.ndarray]:
    """Load each PNG as RGB, key ``screen``, then clean the matte. RGBA uint8."""
    keyed = []
    for path in paths:
        keyed.append(clean_alpha(key_screen(_load_rgb(path), screen)))
    return keyed


def find_cycle(frames, fps, min_s: float = 0.4) -> tuple[int, int, float]:
    """Return ``(0, period, loopError)`` for the first return to frame 0.

    Thumbnails are 64px wide. RGB is premultiplied by alpha/255, then turned
    into luminance. ``loopError`` is ``D(period) / median(D)``. With no
    qualifying minimum, the span is the whole clip (``len(frames)``, so
    ``sample_frames`` reaches the last frame) and the error is high.
    """
    count = len(frames)
    if count < 2:
        return (0, count, _HIGH_LOOP_ERROR)
    distances = _distance_from_first(frames)
    median = float(np.median(distances))
    if median <= 0:
        return (0, count, _HIGH_LOOP_ERROR)
    period = _first_period(distances, float(min_s) * float(fps), 0.6 * median)
    if period is None:
        return (0, count, _HIGH_LOOP_ERROR)
    return (0, int(period), float(distances[period] / median))


def sample_frames(frames, start, length, n) -> list:
    """Pick ``n`` frames at even intervals across ``[start, start + length)``."""
    count = len(frames)
    samples = int(n)
    if samples <= 0 or count == 0 or float(length) <= 0:
        return []
    step = float(length) / float(samples)
    origin = float(start)
    picked = []
    for index in range(samples):
        slot = int(origin + index * step)
        picked.append(frames[_clamp_index(slot, count)])
    return picked


def drift_correct(frames, keep_vertical: bool = True):
    """Subtract a straight-line fit of the feet-x centroids. Shift by whole pixels.

    The centroid is the horizontal mean of the bottom 15% of opaque pixels,
    the same measure as ``feet_point``. Only x moves, so y is always kept and
    a jump's height stays. ``keep_vertical`` is accepted for the brief's
    signature and has no other effect.
    """
    shifts = _drift_shifts(frames)
    return [_shift_x(frame, dx) for frame, dx in zip(frames, shifts)]


def select_range(frames, base, around_s, fps):
    """Return the frame in the tail window closest to ``base``.

    The window is the last ``round(around_s * fps)`` frames (the end of a
    segment). An empty window searches every frame. Distance is the mean
    absolute difference of 64px grayscale thumbnails.
    """
    if len(frames) == 0:
        raise ValueError("select_range requires frames")
    window = _tail_frames(frames, around_s, fps)
    base_gray = _gray_thumb(base)
    best = window[0]
    best_score = _mean_abs(base_gray, _gray_thumb(best))
    for frame in window[1:]:
        score = _mean_abs(base_gray, _gray_thumb(frame))
        if score < best_score:
            best = frame
            best_score = score
    return best


def vfx_alpha(rgb_frames) -> list[np.ndarray]:
    """Key additive VFX on black: alpha is ``max(r, g, b)``, then unpremultiply.

    Leading and trailing frames whose mean energy (mean of the max channel)
    is 0 are dropped. Interior black frames stay. RGBA uint8.
    """
    start, end = _content_span(rgb_frames)
    return [_unpremultiply(frame) for frame in rgb_frames[start:end]]


def _clear_numbered_pngs(folder: Path) -> None:
    for path in folder.glob("[0-9][0-9][0-9][0-9].png"):
        path.unlink()


def _numbered_pngs(folder: Path) -> list[Path]:
    start = 0 if (folder / "0000.png").is_file() else 1
    paths: list[Path] = []
    index = start
    while True:
        path = folder / f"{index:04d}.png"
        if not path.is_file():
            return paths
        paths.append(path)
        index += 1


def _load_rgb(path) -> np.ndarray:
    with Image.open(path) as image:
        return np.array(image.convert("RGB"))


def _as_rgba_frame(frame) -> np.ndarray:
    if isinstance(frame, Image.Image):
        return np.asarray(frame.convert("RGBA"))
    image = np.asarray(frame)
    if image.ndim == 3 and image.shape[2] == 4:
        return np.ascontiguousarray(image, dtype=np.uint8)
    if image.ndim == 3 and image.shape[2] == 3:
        color = np.ascontiguousarray(image, dtype=np.uint8)
        alpha = np.full(color.shape[:2] + (1,), 255, dtype=np.uint8)
        return np.concatenate([color, alpha], axis=2)
    gray = np.ascontiguousarray(image, dtype=np.uint8)
    rgb = np.repeat(gray[..., None], 3, axis=2)
    alpha = np.full(rgb.shape[:2] + (1,), 255, dtype=np.uint8)
    return np.concatenate([rgb, alpha], axis=2)


def _gray_thumb(frame, width: int = _THUMB_WIDTH) -> np.ndarray:
    """64px-wide thumbnail: premultiply RGB by alpha/255, then luminance."""
    rgba = _as_rgba_frame(frame)
    src_h, src_w = rgba.shape[:2]
    thumb_w = max(1, int(width))
    thumb_h = max(1, int(round(src_h * (thumb_w / max(src_w, 1)))))
    if src_w != thumb_w or src_h != thumb_h:
        rgba = np.asarray(
            Image.fromarray(rgba).resize((thumb_w, thumb_h), Image.Resampling.NEAREST),
            dtype=np.uint8,
        )
    image = rgba.astype(np.float32)
    alpha = image[..., 3] / 255.0
    red, green, blue = image[..., 0], image[..., 1], image[..., 2]
    luma = _LUMA[0] * red + _LUMA[1] * green + _LUMA[2] * blue
    return luma * alpha


def _resize_gray(gray: np.ndarray, width: int, height: int) -> np.ndarray:
    image = Image.fromarray(np.clip(np.rint(gray), 0, 255).astype(np.uint8))
    resized = image.resize((int(width), max(1, int(height))), Image.Resampling.NEAREST)
    return np.asarray(resized, dtype=np.float32)


def _mean_abs(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        right = _resize_gray(right, left.shape[1], left.shape[0])
    return float(np.mean(np.abs(left.astype(np.float32) - right.astype(np.float32))))


def _distance_from_first(frames) -> np.ndarray:
    thumbs = [_gray_thumb(frame) for frame in frames]
    base = thumbs[0]
    distances = np.empty(len(thumbs), dtype=np.float64)
    for index, thumb in enumerate(thumbs):
        distances[index] = _mean_abs(base, thumb)
    return distances


def _is_local_min(distances: np.ndarray, index: int) -> bool:
    """``D(i)`` is no larger than its neighbors. The last index only has a left neighbor."""
    value = float(distances[index])
    if value > float(distances[index - 1]):
        return False
    return index == len(distances) - 1 or value <= float(distances[index + 1])


def _first_period(distances: np.ndarray, min_index: float, limit: float) -> int | None:
    """First local minimum at ``i >= min_index`` with ``D(i) < limit``.

    The last index counts, so a clip that closes exactly on its final frame
    (``n * period + 1`` frames) is accepted.
    """
    for index in range(1, len(distances)):
        if index >= min_index and float(distances[index]) < limit and _is_local_min(distances, index):
            return index
    return None


def _clamp_index(slot: int, count: int) -> int:
    if slot < 0:
        return 0
    if slot >= count:
        return count - 1
    return slot


def _slope(values: np.ndarray) -> float:
    count = int(values.shape[0])
    if count < 2:
        return 0.0
    index = np.arange(count, dtype=np.float64)
    centered = index - index.mean()
    denom = float(np.dot(centered, centered))
    if denom == 0.0:
        return 0.0
    return float(np.dot(centered, values - float(values.mean())) / denom)


def _drift_shifts(frames) -> list[int]:
    count = len(frames)
    if count < 2:
        return [0] * count
    xs = np.asarray([float(feet_point(frame)[0]) for frame in frames], dtype=np.float64)
    slope = _slope(xs)
    return [int(np.rint(-slope * index)) for index in range(count)]


def _shift_x(frame, dx: int) -> np.ndarray:
    image = np.asarray(frame)
    shifted = np.zeros_like(image)
    width = int(image.shape[1]) if image.ndim >= 2 else 0
    if dx == 0 or width == 0:
        return np.array(image, copy=True)
    if abs(dx) >= width:
        return shifted
    if dx > 0:
        shifted[:, dx:] = image[:, :-dx]
    else:
        shifted[:, :dx] = image[:, -dx:]
    return shifted


def _tail_frames(frames, around_s, fps):
    count = int(round(float(around_s) * float(fps)))
    if count <= 0:
        return list(frames)
    return list(frames[-count:])


def _mean_energy(frame) -> float:
    color = np.asarray(frame)[..., :3]
    if color.size == 0:
        return 0.0
    return float(np.mean(np.max(color, axis=-1)))


def _content_span(frames) -> tuple[int, int]:
    start = 0
    end = len(frames)
    while start < end and _mean_energy(frames[start]) <= 0.0:
        start += 1
    while end > start and _mean_energy(frames[end - 1]) <= 0.0:
        end -= 1
    return start, end


def _unpremultiply(rgb) -> np.ndarray:
    color = np.asarray(rgb)[..., :3].astype(np.float32)
    alpha = np.max(color, axis=2)
    scale = np.ones(alpha.shape, dtype=np.float32)
    visible = alpha > 0
    scale[visible] = 255.0 / alpha[visible]
    straight = np.clip(np.rint(color * scale[..., None]), 0, 255)
    output = np.empty(color.shape[:2] + (4,), dtype=np.uint8)
    output[..., :3] = straight.astype(np.uint8)
    output[..., 3] = np.clip(np.rint(alpha), 0, 255).astype(np.uint8)
    return output

"""Stream video frames through the shared matte model into an alpha WebM.

No frame directory is materialized: only one current and one previous frame
are retained. The queued Tools worker owns admission, progress and cancellation.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import uuid
from fractions import Fraction
from pathlib import Path
from collections.abc import Callable

import numpy as np
from PIL import Image

from services.character_kit_face_cleanup import _contained
from services.rembg_adapter import DEFAULT_MODEL, remove_background_image
from .background_removal import BackgroundRemovalError, _destination_root
from .background_removal_request import UPSCALE_VIDEO_EXTENSIONS

MAX_SECONDS = 60
MAX_FRAMES = 1800
MAX_EDGE = 1920


def video_info(source: str) -> dict:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", source,
    ], capture_output=True, check=True, timeout=30)
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise BackgroundRemovalError("Source has no video stream")
    try:
        fps = Fraction(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0")
        duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
        width, height = int(video["width"]), int(video["height"])
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        raise BackgroundRemovalError("Video dimensions, duration or frame rate are unavailable") from exc
    if not math.isfinite(duration) or duration <= 0 or duration > MAX_SECONDS + .001:
        raise BackgroundRemovalError("Video background removal accepts clips up to 60 seconds")
    if not 0 < fps <= 60 or duration * float(fps) > MAX_FRAMES + .1:
        raise BackgroundRemovalError("Video background removal accepts up to 60 fps and 1800 frames")
    if min(width, height) <= 0 or width * height > 33_177_600:
        raise BackgroundRemovalError("Video dimensions are unsupported")
    # ffmpeg autorotates display-oriented sources before scaling. Handle phone
    # video rotation so the output retains its portrait orientation.
    rotation = float(video.get("tags", {}).get("rotate", 0))
    for side in video.get("side_data_list", []):
        if "rotation" in side:
            rotation = float(side["rotation"])
    if round(rotation) % 180:
        width, height = height, width
    ratio = min(1, MAX_EDGE / max(width, height))
    return {"width": max(2, int(width * ratio) // 2 * 2),
            "height": max(2, int(height * ratio) // 2 * 2),
            "fps": str(fps), "duration": duration,
            "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


def stabilize_alpha(rgba: np.ndarray, previous: np.ndarray | None) -> np.ndarray:
    """Dampen small matte fluctuations only where the underlying pixels agree.

    Large motion/edge changes use the current matte immediately, avoiding the
    trails that a global temporal average leaves behind moving hands and wheels.
    """
    if previous is None:
        return rgba
    current = rgba.astype(np.int16)
    old = previous.astype(np.int16)
    alpha = current[:, :, 3]
    stable = (np.mean(np.abs(current[:, :, :3] - old[:, :, :3]), axis=2) < 8)
    stable &= (np.abs(alpha - old[:, :, 3]) < 48) & (alpha > 3) & (alpha < 252)
    rgba[:, :, 3] = np.where(stable, (alpha * 4 + old[:, :, 3]) // 5, alpha).astype(np.uint8)
    return rgba


def _stop(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    for pipe in (process.stdin, process.stdout):
        if pipe:
            try:
                pipe.close()
            except OSError:
                pass


def remove_video_background_file(
    source: str, *, uploads_root: str, workspace_root: str, output_dir: str,
    destination_workspace_root: str | None = None, model: str = DEFAULT_MODEL,
    temporal_smoothing: bool = True,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[str, int, int, int], None] = lambda *args: None,
    remove_background: Callable[[Image.Image], Image.Image] | None = None,
) -> dict:
    original = os.path.realpath(os.path.abspath(source))
    roots = [os.path.realpath(os.path.abspath(p)) for p in (uploads_root, workspace_root) if p]
    if (Path(original).suffix.lower() not in UPSCALE_VIDEO_EXTENSIONS
            or not os.path.isfile(original) or not any(_contained(original, root) for root in roots)):
        raise BackgroundRemovalError("Video source path is not allowed")
    destination = _destination_root(output_dir, uploads_root=uploads_root,
                                    workspace_root=destination_workspace_root or workspace_root)
    if cancelled():
        raise InterruptedError("Background removal cancelled")
    info = video_info(original)
    width, height, fps = info["width"], info["height"], info["fps"]
    total = min(MAX_FRAMES, math.ceil(info["duration"] * float(Fraction(fps))))
    matte = remove_background or (lambda frame: remove_background_image(
        frame, model=model, alpha_matting=True, bgcolor=None))
    os.makedirs(destination, exist_ok=True)
    filename = f"{Path(original).stem}.no-background-{uuid.uuid4().hex[:8]}.webm"
    output = os.path.join(destination, filename)
    decoder = encoder = None
    previous = None
    count = 0
    alpha_min, alpha_max = 255, 0
    with tempfile.TemporaryDirectory(prefix=".video-cutout-", dir=destination) as scratch:
        raw_video = os.path.join(scratch, "transparent.webm")
        completed = os.path.join(scratch, "complete.webm")
        with tempfile.TemporaryFile() as decode_log, tempfile.TemporaryFile() as encode_log:
            try:
                decoder = subprocess.Popen([
                    "ffmpeg", "-v", "error", "-nostdin", "-threads", "2", "-i", original,
                    "-map", "0:v:0", "-an", "-vf", f"fps={fps},scale={width}:{height},setsar=1",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
                ], stdout=subprocess.PIPE, stderr=decode_log)
                encoder = subprocess.Popen([
                    "ffmpeg", "-v", "error", "-nostdin", "-f", "rawvideo", "-pix_fmt", "rgba",
                    "-s", f"{width}x{height}", "-r", fps, "-i", "pipe:0", "-an",
                    "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20",
                    "-deadline", "realtime", "-cpu-used", "5", "-row-mt", "1", "-threads", "2",
                    "-auto-alt-ref", "0", "-f", "webm", raw_video,
                ], stdin=subprocess.PIPE, stderr=encode_log)
                while True:
                    if cancelled():
                        raise InterruptedError("Background removal cancelled")
                    frame = decoder.stdout.read(width * height * 3)
                    if not frame:
                        break
                    if len(frame) != width * height * 3:
                        raise BackgroundRemovalError("Video decoder returned an incomplete frame")
                    if count >= MAX_FRAMES:
                        raise BackgroundRemovalError("Video exceeds the 1800 frame limit")
                    image = Image.frombytes("RGB", (width, height), frame)
                    cutout = matte(image)
                    if not isinstance(cutout, Image.Image) or cutout.size != image.size:
                        raise BackgroundRemovalError("Matte must preserve the source frame dimensions")
                    rgba = np.array(cutout.convert("RGBA"))
                    # Matting also estimates foreground color at the boundary.
                    # Replacing it with source RGB reintroduces the removed
                    # background as a light/dark fringe on other scenes.
                    if temporal_smoothing:
                        rgba = stabilize_alpha(rgba, previous)
                        previous = rgba
                    alpha_min = min(alpha_min, int(rgba[:, :, 3].min()))
                    alpha_max = max(alpha_max, int(rgba[:, :, 3].max()))
                    if cancelled():
                        raise InterruptedError("Background removal cancelled")
                    encoder.stdin.write(rgba.tobytes())
                    count += 1
                    progress(f"Removing video background · {count}/{total} frames", min(94, 5 + count * 89 // max(1, total)), count, total)
                encoder.stdin.close()
                for process, log in ((decoder, decode_log), (encoder, encode_log)):
                    if process.wait(timeout=60):
                        log.seek(0)
                        raise BackgroundRemovalError(log.read(4000).decode(errors="replace") or "Video processing failed")
                if not count:
                    raise BackgroundRemovalError("Video has no decodable frames")
                if cancelled():
                    raise InterruptedError("Background removal cancelled")
                progress("Saving transparent WebM…", 96, count, count)
                duration = count / float(Fraction(fps))
                if info["has_audio"]:
                    subprocess.run([
                        "ffmpeg", "-v", "error", "-nostdin", "-i", raw_video, "-i", original,
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "libopus",
                        "-b:a", "128k", "-t", f"{duration:.9f}", "-f", "webm", completed,
                    ], capture_output=True, check=True, timeout=60)
                else:
                    os.replace(raw_video, completed)
                if cancelled():
                    raise InterruptedError("Background removal cancelled")
                os.replace(completed, output)
            finally:
                _stop(decoder)
                _stop(encoder)
    return {"path": output, "filename": filename, "original": os.path.basename(original),
            "source": f"/api/v1/file/{filename}", "width": width, "height": height,
            "fps": fps, "duration": duration, "frames": count, "has_audio": info["has_audio"],
            "alpha": {"status": "transparent" if alpha_min < 255 else "opaque", "min": alpha_min, "max": alpha_max},
            "method": "rembg-u2net-video", "model": model,
            "temporal_smoothing": temporal_smoothing}

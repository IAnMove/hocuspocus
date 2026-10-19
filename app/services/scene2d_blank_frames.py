"""Stop a Video 2D export whose frames came back fully transparent.

A canvas that is lost in the headless browser reads back as RGBA zeros, and ffmpeg turns that into a black
frame without any error. A painted frame always starts with an opaque background, so a frame whose alpha is
zero everywhere is never real; a fade to black is opaque black and passes.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

# An all-zero RGBA PNG deflates to about 1/1000 of its raw size. Only files below 1/50 are opened, so a
# normal export reads the size of each frame and decodes none.
SMALL_FRAME_RATIO = 50


def is_blank_frame(path: Path) -> bool:
    """True when the PNG has an alpha channel and every alpha value is zero."""
    with Image.open(path) as image:
        if "A" not in image.getbands():
            return False
        width, height = image.size
        if path.stat().st_size > width * height * 4 // SMALL_FRAME_RATIO:
            return False
        return image.getchannel("A").getbbox() is None


def assert_no_blank_frames(frames: list[Path], fps: int) -> None:
    """Raise before encoding when any rendered frame is fully transparent."""
    blank = [index for index, path in enumerate(frames) if is_blank_frame(path)]
    if not blank:
        return
    first = blank[0]
    raise RuntimeError(
        f"Video 2D export rendered {len(blank)} blank (fully transparent) frame(s) out of {len(frames)}, "
        f"the first at {first / int(fps):.3f} s (frame {first + 1}). The headless canvas was probably lost. "
        "Export stopped instead of encoding black frames; export again.")

"""Keep native 3D cuts on the montage's one shared frame clock."""
from __future__ import annotations

import math


def align_native_cuts(segments, fps=24):
    if not any(shot.get("kind") == "scene3d" for shot, _, _ in segments):
        return segments
    # Round absolute boundaries, not each duration: independent rounding
    # moves every later scene relative to the continuous soundtrack.
    aligned = []
    for shot, start, end in segments:
        first = math.floor(start * fps + 0.5)
        last = math.floor(end * fps + 0.5)
        if last > first:
            aligned.append((shot, first / fps, last / fps))
    return aligned

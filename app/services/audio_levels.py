"""Loudness of audio files, so a mix can balance sources that were mastered very differently.

Local speech comes out between -18 and -29 LUFS, generated music and sound
effects between -11 and -32: the same ``volume`` meant a whisper for one file
and a blast for another. Lines are levelled to ``DIALOGUE_LUFS``; music and
effects keep their ``volume`` as "relative to the dialogue" by scaling it with
their own measured loudness.
"""
from __future__ import annotations

import os
import re
import subprocess

DIALOGUE_LUFS = -16.0
_INTEGRATED = re.compile(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", re.MULTILINE)


def integrated_lufs(path: str) -> float | None:
    """Integrated loudness (EBU R128); None for silence, very short clips or an unreadable file."""
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                                capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    found = _INTEGRATED.findall(result.stderr or "")
    value = float(found[-1]) if found else None
    return value if value is not None and value > -60 else None


def gain_to(path: str, target: float = DIALOGUE_LUFS, *, low: float = 0.1, high: float = 4.0) -> float:
    """Linear gain that brings a file to ``target``; 1.0 when it cannot be measured."""
    measured = integrated_lufs(path)
    return 1.0 if measured is None else max(low, min(high, 10 ** ((target - measured) / 20)))


def level_file(path: str, target: float = DIALOGUE_LUFS, tolerance_db: float = 0.5) -> float:
    """Rewrite a file at ``target`` loudness (peaks limited); returns the gain in dB, 0 when already there."""
    measured = integrated_lufs(path)
    if measured is None or abs(target - measured) <= tolerance_db:
        return 0.0
    gain = max(-20.0, min(20.0, target - measured))
    stem, extension = os.path.splitext(path)
    temporary = f"{stem}.level{extension}"
    result = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-af", f"volume={gain:.2f}dB,alimiter=limit=0.95:level=disabled",
                             temporary], capture_output=True, text=True, timeout=120, check=False)
    if result.returncode != 0 or not os.path.isfile(temporary):
        if os.path.isfile(temporary):
            os.remove(temporary)
        return 0.0
    os.replace(temporary, path)
    return round(gain, 2)

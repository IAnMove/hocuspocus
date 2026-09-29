"""Contact sheets and composite references the production makes with ffmpeg.

``frames_sheet`` puts every start frame on one labelled sheet, made before any clip is shot, so a person or an
agent can see duplicated characters or a wrong look while a wrong frame still costs nothing (a clip is minutes of GPU).
``compose_group`` puts the reference sheets of several characters side by side in one picture: an image model that
runs out of memory with three references takes one group reference.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

CELL_W, CELL_H = 426, 240
COLUMNS = 4
GROUP_W, GROUP_H = 1280, 704


def _label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)[:24]


def frames_sheet_command(root: Path, frames: dict[str, str], out: str) -> list[str] | None:
    """ffmpeg arguments for the labelled sheet; None when there is nothing to show."""
    items = [(key, name) for key, name in frames.items() if isinstance(name, str) and (root / name).is_file()][:24]
    if not items:
        return None
    args = ["ffmpeg", "-v", "error", "-y"]
    for _key, name in items:
        args += ["-i", str(root / name)]
    scaled = "".join(
        f"[{i}]scale={CELL_W}:{CELL_H}:force_original_aspect_ratio=decrease,pad={CELL_W}:{CELL_H}:(ow-iw)/2:(oh-ih)/2,"
        f"drawtext=text={_label(key)}:x=6:y=6:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6[s{i}];"
        for i, (key, _name) in enumerate(items))
    layout = "|".join(f"{(i % COLUMNS) * CELL_W}_{(i // COLUMNS) * CELL_H}" for i in range(len(items)))
    stack = "".join(f"[s{i}]" for i in range(len(items))) + f"xstack=inputs={len(items)}:layout={layout}"
    return args + ["-filter_complex", scaled + stack, "-frames:v", "1", str(root / out)]


def make_frames_sheet(root: Path, frames: dict[str, str], out: str) -> str | None:
    command = frames_sheet_command(root, frames, out)
    if command is None:
        return None
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return out if (root / out).is_file() else None


def group_command(paths: list[Path], out: Path) -> list[str]:
    """Each sheet letterboxed into its own column of one GROUP_W x GROUP_H picture (nothing is cropped)."""
    width = GROUP_W // len(paths)
    args = ["ffmpeg", "-v", "error", "-y"]
    for path in paths:
        args += ["-i", str(path)]
    cells = "".join(f"[{i}]scale={width}:{GROUP_H}:force_original_aspect_ratio=decrease,pad={width}:{GROUP_H}:(ow-iw)/2:(oh-ih)/2:color=0x808080[c{i}];"
                    for i in range(len(paths)))
    joined = "".join(f"[c{i}]" for i in range(len(paths))) + f"hstack={len(paths)},pad={GROUP_W}:{GROUP_H}:0:0:color=0x808080"
    return args + ["-filter_complex", cells + joined, str(out)]


def compose_group(paths: list[Path], out: Path) -> bool:
    if not paths or not all(path.is_file() for path in paths):
        return False
    try:
        subprocess.run(group_command(paths, out), check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.is_file()

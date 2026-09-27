"""Series episode assembly adapters for the core/remote profile.

NVIDIA joins approved clips with WanGP's FFmpeg helper. Core keeps the same
HTTP contract and concatenates with FFmpeg, without Torch.

Do not use the concat demuxer (``-f concat``) with ``-c copy``: mismatched
codecs, timebases or audio layouts make ffmpeg report success while dropping
later clips. The NVIDIA helper documents that failure mode and uses the concat
filter instead.
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Callable

from services import core_editor, core_workspace as core
from services.mix_concat import (
    _run_ffmpeg_command,
    build_hard_concat_filter,
    concat_with_tail_hold_and_crossfade,
    probe_audio_flags,
    probe_duration_seconds,
    should_use_hold_crossfade,
)


def asset_local_path(workspace: str, asset: dict[str, Any]) -> str:
    uri = str(asset.get("uri") or "")
    if uri.startswith("https://"):
        raise ValueError(
            f"Remote Series asset {asset.get('id')} must be imported into the workspace before assembly"
        )
    folder = os.path.realpath(core.workspace_dir(workspace))
    relative = uri[len("outputs/"):] if uri.startswith("outputs/") else uri
    candidate = os.path.realpath(os.path.join(folder, relative))
    if candidate != folder and not candidate.startswith(folder + os.sep):
        raise ValueError(f"Series asset {asset.get('id')} leaves its workspace")
    if not os.path.isfile(candidate):
        raise ValueError(f"Series reference file is missing: {uri}")
    return candidate


def available_filename(directory: str, name: str) -> str:
    _filename, destination = core_editor.unique_output_name(directory, name)
    return destination


def _ffmpeg_bin() -> str | None:
    return os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")


def _hard_concat_filter(
    files: list[str],
    output_path: str,
    *,
    abort_callback: Callable[[], bool] | None = None,
) -> bool:
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        return False
    audio_flags = probe_audio_flags(files, ffmpeg)
    silent_durations = None
    if audio_flags and any(audio_flags) and not all(audio_flags):
        silent_durations = [probe_duration_seconds(path, ffmpeg) or 1.0 for path in files]
    filter_str, maps_audio = build_hard_concat_filter(
        len(files),
        audio_flags=audio_flags if any(audio_flags) else None,
        silent_durations=silent_durations,
    )
    cmd = [ffmpeg, "-y"]
    for path in files:
        cmd += ["-i", path.replace("\\", "/")]
    cmd += ["-filter_complex", filter_str, "-map", "[outv]"]
    if maps_audio:
        cmd += ["-map", "[outa]", "-c:a", "aac"]
    cmd += [
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        os.path.abspath(output_path).replace("\\", "/"),
    ]
    return _run_ffmpeg_command(cmd, output_path, abort_callback=abort_callback)


def concatenate_clips(
    paths: list[str],
    output_path: str,
    *,
    abort_callback: Callable[[], bool] | None = None,
) -> bool:
    if abort_callback and abort_callback():
        return False
    files = [str(path) for path in paths]
    if not files or any(
        not path or not os.path.isfile(path) or os.path.getsize(path) == 0
        for path in files
    ):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    if len(files) == 1:
        shutil.copyfile(files[0], output_path)
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    if should_use_hold_crossfade(len(files)):
        if concat_with_tail_hold_and_crossfade(
            files, output_path, abort_callback=abort_callback,
        ):
            return True
        if abort_callback and abort_callback():
            return False
    return _hard_concat_filter(files, output_path, abort_callback=abort_callback)

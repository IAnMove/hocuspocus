"""Join a long run of clips in blocks, so memory does not grow with the number of clips.

One ffmpeg filter graph that joins N clips keeps a decoder and its buffered frames for each of them: about 75 MB a
1080p clip, so the 90 shots of one Series episode (a 62 GB machine, the server and the join in one cgroup) were killed
by the OOM killer. Past ``ASSEMBLY_BLOCK_CLIPS`` clips the run is cut into balanced blocks. Each block is joined by the
filter that joins the whole run, from the same plan, and the blocks are joined by that filter again:

* the whole run is planned once (``series_transitions.plan_clips``), so every clip keeps the held tail, the dissolve or
  the fade it has in a single pass; a block's last clip before a cut keeps its hold, and one before a dissolve or a fade
  does not;
* a block is then one clip of the join above it, as long as the plan says (never re-probed: container durations carry
  encoder tails and frame rounding) and with the join its first clip had, so the seam is the single pass's own xfade,
  acrossfade or fade at the same time, and the final length, frame count and sound position are the single pass's;
* the sound of a block is PCM and its picture x264 at crf 12, so the extra generation costs no AAC priming (which is
  what drifts a join) and no visible loss.

Hard cuts (``build_hard_concat_filter``) go through ``hard_join_in_blocks``: the same blocks, joined by whatever the
caller joined the whole run with (WanGP's helper, with its driving soundtrack, or the core one).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Sequence
from typing import Any

from . import mix_concat
from .mix_concat import (
    FADE_SEC,
    HOLD_TAIL_SEC,
    _run_ffmpeg_command,
    build_hard_concat_filter,
    probe_audio_flags,
    probe_duration_seconds,
)
from .series_transitions import chain_filter, merged, plan_clips, rebased

BLOCK_VIDEO_ARGS = ["-c:v", "libx264", "-crf", "12", "-preset", "veryfast"]
BLOCK_AUDIO_ARGS = ["-c:a", "pcm_s16le"]
BLOCK_SUFFIX = ".mov"
Aborted = Callable[[], bool] | None


def block_slices(count: int, limit: int | None = None) -> list[tuple[int, int]]:
    """``count`` items in the fewest consecutive blocks of at most ``limit``, as even as can be (90 -> 6 of 15)."""
    limit = max(2, int(limit or mix_concat.ASSEMBLY_BLOCK_CLIPS))
    blocks = -(-int(count) // limit)
    size, extra = divmod(int(count), blocks)
    slices, start = [], 0
    for index in range(blocks):
        end = start + size + (1 if index < extra else 0)
        slices.append((start, end))
        start = end
    return slices


def _command(ffmpeg_bin: str, inputs: Sequence[str], graph: str, video: str, audio: str | None,
             codec_args: Sequence[str], audio_args: Sequence[str], output_path: str,
             tail: Sequence[str] = ()) -> list[str]:
    cmd = [ffmpeg_bin, "-y"]
    for path in inputs:
        cmd += ["-i", path.replace("\\", "/")]
    cmd += ["-filter_complex", graph, "-map", f"[{video}]"]
    if audio:
        cmd += ["-map", f"[{audio}]", *audio_args]
    cmd += [*codec_args, "-pix_fmt", "yuv420p", *tail, os.path.abspath(output_path).replace("\\", "/")]
    return cmd


def _workdir(output_path: str) -> str:
    return tempfile.mkdtemp(prefix=".hocuspocus-join-", dir=os.path.dirname(os.path.abspath(output_path)) or None)


def join_in_blocks(
    files: Sequence[str],
    output_path: str,
    durations: Sequence[float],
    transitions: Sequence[Any] | None,
    *,
    audio_flags: Sequence[bool],
    hold_sec: float = HOLD_TAIL_SEC,
    fade_sec: float = FADE_SEC,
    video_args: Sequence[str],
    ffmpeg_bin: str = "ffmpeg",
    abort_callback: Aborted = None,
    limit: int | None = None,
) -> bool:
    """The join ``build_hold_crossfade_filter`` / ``series_transitions.filter_for`` would make of ``files``, in blocks.

    ``video_args`` are the final file's codec arguments (the join's own quality); blocks are intermediates.
    """
    limit = max(2, int(limit or mix_concat.ASSEMBLY_BLOCK_CLIPS))
    clips = plan_clips(durations, transitions, hold_sec, fade_sec)
    mix = any(audio_flags)
    flags: list[bool] | None = [bool(flag) for flag in audio_flags] if mix else None
    units: list | None = list(zip([str(path) for path in files], clips))
    workdir = _workdir(output_path)
    try:
        level = 0
        while len(units) > limit:
            level += 1
            units, flags = _encode_blocks(units, flags, workdir, level, hold_sec, ffmpeg_bin, abort_callback, limit)
            if units is None:
                return False
        graph, video, audio = chain_filter([clip for _path, clip in units], flags, hold_sec)
        cmd = _command(ffmpeg_bin, [path for path, _clip in units], graph, video, audio if mix else None,
                       video_args, ["-c:a", "aac"], output_path, ["-movflags", "+faststart"])
        print(f"[MixConcat] final join of {len(units)} blocks ({len(files)} clips) -> {os.path.basename(output_path)}")
        return _run_ffmpeg_command(cmd, output_path, abort_callback=abort_callback)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _encode_blocks(units, flags, workdir, level, hold_sec, ffmpeg_bin, abort_callback, limit):
    """One level: every block of ``units`` joined into a file. Returns the blocks as units (and their sound flags)."""
    blocks = []
    for number, (start, end) in enumerate(block_slices(len(units), limit)):
        if abort_callback is not None and abort_callback():
            return None, flags
        group = units[start:end]
        graph, video, audio = chain_filter(
            rebased([clip for _path, clip in group]), flags[start:end] if flags is not None else None, hold_sec,
        )
        out = os.path.join(workdir, f"block-{level}-{number:03d}{BLOCK_SUFFIX}")
        cmd = _command(ffmpeg_bin, [path for path, _clip in group], graph, video, audio, BLOCK_VIDEO_ARGS,
                       BLOCK_AUDIO_ARGS, out)
        print(f"[MixConcat] block {number + 1}: clips {start + 1}-{end} of {len(units)} (level {level})")
        if not _run_ffmpeg_command(cmd, out, abort_callback=abort_callback):
            return None, flags
        blocks.append((out, merged([clip for _path, clip in group])))
    return blocks, ([True] * len(blocks) if flags is not None else None)


def hard_join_in_blocks(
    files: Sequence[str],
    output_path: str,
    final: Callable[[list[str]], bool],
    *,
    with_clip_audio: bool,
    ffmpeg_bin: str = "ffmpeg",
    abort_callback: Aborted = None,
    limit: int | None = None,
) -> bool:
    """Hard-cut ``files`` in blocks, then ``final(block files)``: the caller's own join of the blocks (it may join
    again in blocks when there are still more than ``limit``). ``with_clip_audio`` False makes silent blocks, for a
    join whose sound is a driving soundtrack laid by ``final``."""
    workdir = _workdir(output_path)
    try:
        blocks = []
        for number, (start, end) in enumerate(block_slices(len(files), limit)):
            if abort_callback is not None and abort_callback():
                return False
            group = [str(path) for path in files[start:end]]
            out = os.path.join(workdir, f"block-{number:03d}{BLOCK_SUFFIX}")
            if not _hard_block(group, out, with_clip_audio, ffmpeg_bin, abort_callback):
                return False
            blocks.append(out)
        print(f"[MixConcat] hard cuts: {len(files)} clips in {len(blocks)} blocks")
        return final(blocks)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _hard_block(group: list[str], out: str, with_clip_audio: bool, ffmpeg_bin: str, abort_callback: Aborted) -> bool:
    flags = probe_audio_flags(group, ffmpeg_bin) if with_clip_audio else []
    silent = None
    if flags and any(flags) and not all(flags):
        silent = [probe_duration_seconds(path, ffmpeg_bin) or 1.0 for path in group]
    graph, maps_audio = build_hard_concat_filter(
        len(group), audio_flags=flags if flags and any(flags) else None, silent_durations=silent,
    )
    cmd = _command(ffmpeg_bin, group, graph, "outv", "outa" if maps_audio else None, BLOCK_VIDEO_ARGS,
                   BLOCK_AUDIO_ARGS, out)
    return _run_ffmpeg_command(cmd, out, abort_callback=abort_callback)

"""Join generated clips with a short freeze-tail and a standard crossfade.

H3 shots end on the last generated frame. Hard-concat then feels like a slap.
Extending the *generation* by 0.5s is the wrong lever: the lattice is 17n+5
and extra authored time often becomes invented speech. Instead we clone the
last frame for ``HOLD_TAIL_SEC`` and dissolve ``FADE_SEC`` into the next shot,
mostly over that freeze so the acted part stays intact.
"""
from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from typing import Sequence

HOLD_TAIL_SEC = 0.5
FADE_SEC = 0.4


def should_use_hold_crossfade(
    clip_count: int,
    *,
    has_driving_audio: bool = False,
    pad_audio: bool = False,
    audio_duration_sec: float | None = None,
) -> bool:
    """Soft joins add hold+crossfade time and must not change a locked timeline.

    Recast / Repaint / Outpaint pass ``audio_duration_sec`` (and often
    ``pad_audio``) so the assembled shot count stays exact. Those callers
    then reject any frame-count drift and delete the mix. Free-form Director
    and Series joins omit that lock and still get the freeze-tail dissolve.
    """
    if int(clip_count) < 2:
        return False
    if has_driving_audio:
        return False
    if pad_audio:
        return False
    if audio_duration_sec is not None:
        return False
    return True


def hold_crossfade_output_seconds(
    durations: Sequence[float],
    *,
    hold_sec: float = HOLD_TAIL_SEC,
    fade_sec: float = FADE_SEC,
) -> float:
    """Timeline length after freeze-tails and overlapping dissolves."""
    if len(durations) < 2:
        return float(durations[0]) if durations else 0.0
    fade = float(fade_sec)
    hold = float(hold_sec)
    padded = [max(0.1, float(duration)) + hold for duration in durations]
    elapsed = padded[0]
    for index in range(1, len(padded)):
        pair_fade = min(fade, hold, padded[index - 1] * 0.4, padded[index] * 0.4)
        elapsed = elapsed + padded[index] - pair_fade
    return elapsed


def _remove_if_exists(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _run_ffmpeg_command(
    cmd: list[str],
    output_path: str,
    *,
    abort_callback: Callable[[], bool] | None = None,
    timeout: float = 3600,
) -> bool:
    process = None
    try:
        if abort_callback is None:
            completed = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            if completed.returncode != 0:
                err = (completed.stderr or "")[-800:]
                print(f"[MixConcat] ffmpeg error: {err}")
                _remove_if_exists(output_path)
                return False
            return os.path.isfile(output_path) and os.path.getsize(output_path) > 0

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.monotonic() + timeout
        while True:
            try:
                _stdout, stderr = process.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if abort_callback():
                    print("[MixConcat] concatenation cancelled")
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    _remove_if_exists(output_path)
                    return False
                if time.monotonic() >= deadline:
                    process.kill()
                    process.communicate()
                    _remove_if_exists(output_path)
                    return False
        if process.returncode != 0:
            err = (stderr or "")[-800:]
            print(f"[MixConcat] ffmpeg error: {err}")
            _remove_if_exists(output_path)
            return False
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[MixConcat] ffmpeg failed: {exc}")
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.communicate()
            except Exception:
                pass
        _remove_if_exists(output_path)
        return False


def probe_duration_seconds(path: str, ffmpeg_bin: str = "ffmpeg") -> float | None:
    ffprobe_bin = ffmpeg_bin.replace("ffmpeg", "ffprobe")
    try:
        result = subprocess.run(
            [
                ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", path,
            ],
            capture_output=True, text=True, timeout=15,
        )
        value = float((result.stdout or "").strip())
        if value > 0:
            return value
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def probe_has_audio(path: str, ffmpeg_bin: str = "ffmpeg") -> bool:
    """True when *path* has at least one audio stream.

    Fail open on a flaky probe so a later dialogue clip is not dropped
    just because ffprobe could not inspect this file. If ffprobe itself
    is missing, fall back to ffmpeg stderr (``Audio:``) before assuming
    a stream is present.
    """
    ffprobe_bin = ffmpeg_bin.replace("ffmpeg", "ffprobe")
    try:
        probe = subprocess.run(
            [
                ffprobe_bin, "-i", path, "-show_streams",
                "-select_streams", "a", "-loglevel", "error",
            ],
            capture_output=True, text=True, timeout=10,
        )
        stdout = probe.stdout or ""
        return "codec_type=audio" in stdout or bool(stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        try:
            probe = subprocess.run(
                [ffmpeg_bin, "-i", path, "-f", "null", "-"],
                capture_output=True, text=True, timeout=10,
            )
            return "Audio:" in (probe.stderr or "")
        except (OSError, subprocess.TimeoutExpired):
            return True


def probe_audio_flags(
    paths: Sequence[str],
    ffmpeg_bin: str = "ffmpeg",
) -> list[bool]:
    """Per-clip audio presence. Do not trust only the first file."""
    return [probe_has_audio(path, ffmpeg_bin) for path in paths]


def _audio_pad_filter(index: int, padded_duration: float, hold: float, has_stream: bool) -> str:
    """Keep acrossfade legal when some clips are video-only.

    Missing streams get synthesized stereo silence at 48 kHz so later
    dialogue is not discarded and ffmpeg does not fail on ``[n:a]``.
    """
    if has_stream:
        return (
            f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad=pad_dur={hold:.3f}[a{index}]"
        )
    return (
        f"anullsrc=channel_layout=stereo:sample_rate=48000:d={padded_duration:.3f},"
        f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
    )


def build_hold_crossfade_filter(
    durations: Sequence[float],
    *,
    hold_sec: float = HOLD_TAIL_SEC,
    fade_sec: float = FADE_SEC,
    with_audio: bool = True,
    has_audio: Sequence[bool] | None = None,
) -> tuple[str, str, str | None]:
    """Return ffmpeg filter_complex, video label, optional audio label."""
    count = len(durations)
    if count < 2:
        raise ValueError("need at least two clip durations")
    if has_audio is not None and len(has_audio) != count:
        raise ValueError("has_audio length must match durations")
    fade = float(fade_sec)
    hold = float(hold_sec)
    parts: list[str] = []
    padded = [max(0.1, float(duration)) + hold for duration in durations]
    audio_flags = [True] * count if with_audio and has_audio is None else (
        [bool(flag) for flag in has_audio] if with_audio and has_audio is not None else None
    )
    if audio_flags is not None and not any(audio_flags):
        audio_flags = None
    mix_audio = audio_flags is not None
    use_silence_pads = bool(
        audio_flags is not None
        and has_audio is not None
        and not all(audio_flags)
    )
    for index in range(count):
        parts.append(
            f"[{index}:v]tpad=stop_mode=clone:stop_duration={hold:.3f}[v{index}]"
        )
        if mix_audio:
            if use_silence_pads and audio_flags is not None:
                parts.append(
                    _audio_pad_filter(index, padded[index], hold, audio_flags[index])
                )
            else:
                parts.append(f"[{index}:a]apad=pad_dur={hold:.3f}[a{index}]")

    video_label = "v0"
    audio_label = "a0" if mix_audio else None
    elapsed = padded[0]
    for index in range(1, count):
        pair_fade = min(fade, hold, padded[index - 1] * 0.4, padded[index] * 0.4)
        offset = max(0.05, elapsed - pair_fade)
        next_video = f"vx{index}"
        parts.append(
            f"[{video_label}][v{index}]xfade=transition=fade:duration={pair_fade:.3f}"
            f":offset={offset:.3f}[{next_video}]"
        )
        video_label = next_video
        if mix_audio:
            next_audio = f"ax{index}"
            parts.append(
                f"[{audio_label}][a{index}]acrossfade=d={pair_fade:.3f}[{next_audio}]"
            )
            audio_label = next_audio
        elapsed = elapsed + padded[index] - pair_fade
    return ";".join(parts), video_label, audio_label


def concat_with_tail_hold_and_crossfade(
    clip_paths: Sequence[str],
    output_path: str,
    *,
    hold_sec: float = HOLD_TAIL_SEC,
    fade_sec: float = FADE_SEC,
    abort_callback: Callable[[], bool] | None = None,
) -> bool:
    """Re-encode clips with a 0.5s freeze tail and ~0.4s crossfade."""
    ffmpeg_bin = os.environ.get("FFMPEG_BINARY", "ffmpeg")
    valid = [os.path.abspath(path) for path in clip_paths if os.path.isfile(path)]
    if len(valid) < 2:
        return False
    durations = [probe_duration_seconds(path, ffmpeg_bin) for path in valid]
    if any(duration is None for duration in durations):
        return False
    audio_flags = probe_audio_flags(valid, ffmpeg_bin)
    with_audio = any(audio_flags)
    filter_str, video_label, audio_label = build_hold_crossfade_filter(
        [float(value) for value in durations if value is not None],
        hold_sec=hold_sec,
        fade_sec=fade_sec,
        with_audio=with_audio,
        has_audio=audio_flags if with_audio else None,
    )
    cmd = [ffmpeg_bin, "-y"]
    for path in valid:
        cmd += ["-i", path.replace("\\", "/")]
    cmd += ["-filter_complex", filter_str, "-map", f"[{video_label}]"]
    if with_audio and audio_label:
        cmd += ["-map", f"[{audio_label}]", "-c:a", "aac"]
    cmd += [
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        os.path.abspath(output_path).replace("\\", "/"),
    ]
    print(
        f"[MixConcat] hold={hold_sec:.2f}s fade={fade_sec:.2f}s "
        f"clips={len(valid)} -> {os.path.basename(output_path)}"
    )
    return _run_ffmpeg_command(
        cmd,
        output_path,
        abort_callback=abort_callback,
    )


def build_hard_concat_filter(
    clip_count: int,
    *,
    audio_flags: Sequence[bool] | None = None,
    silent_durations: Sequence[float] | None = None,
) -> tuple[str, bool]:
    """Return ``(filter_complex, maps_embedded_audio)`` for a hard concat.

    Recast / Repaint / Outpaint skip the hold-crossfade and land here, as
    does the soft-join fallback. If only some clips have audio, missing
    streams become stereo silence so ``concat=a=1`` stays legal and later
    dialogue is not discarded.
    """
    count = int(clip_count)
    if count < 1:
        raise ValueError("need at least one clip")
    flags = (
        [bool(flag) for flag in audio_flags]
        if audio_flags is not None
        else None
    )
    if flags is not None and len(flags) != count:
        raise ValueError("audio_flags length must match clip_count")
    mix_audio = bool(flags and any(flags))
    if not mix_audio:
        inputs = "".join(f"[{index}:v]" for index in range(count))
        return f"{inputs}concat=n={count}:v=1:a=0[outv]", False
    if flags is not None and all(flags):
        inputs = "".join(f"[{index}:v][{index}:a]" for index in range(count))
        return f"{inputs}concat=n={count}:v=1:a=1[outv][outa]", True

    durations = [max(0.1, float(value)) for value in (silent_durations or [])]
    if len(durations) != count:
        raise ValueError("silent_durations length must match clip_count")
    parts: list[str] = []
    mapped: list[str] = []
    for index, has_stream in enumerate(flags or []):
        if has_stream:
            parts.append(
                f"[{index}:a]aresample=48000,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
            )
        else:
            parts.append(
                f"anullsrc=channel_layout=stereo:sample_rate=48000"
                f":d={durations[index]:.3f},"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
            )
        mapped.append(f"[{index}:v][a{index}]")
    filter_str = (
        ";".join(parts)
        + ";"
        + "".join(mapped)
        + f"concat=n={count}:v=1:a=1[outv][outa]"
    )
    return filter_str, True

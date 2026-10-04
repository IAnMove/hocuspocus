"""Finish a joined Series episode: even loudness and subtitles.

Each shot mixes its own audio and the join only concatenates, so a five-minute
episode came out near -19 LUFS and without subtitles, although every 2D take's
scene document holds the exact text and timing of its lines (``dialogueBeats``).

1. Subtitles: ``<episode>.srt`` and ``<episode>.vtt`` from the beats of each
   approved take, placed with the clip offsets the join used (freeze tail plus
   dissolve, or a hard cut when the join fell back to one).
2. Loudness: two ffmpeg ``loudnorm`` passes apply one linear gain to -16 LUFS
   integrated, under a -1 dBTP ceiling after AAC. Video is stream-copied.
3. Thumbnail: ``<episode>.thumb.jpg``, a frame of the first shot after the
   opening one (a series opens on its title card), for lists and publishing.

Neither step fails the assembly. A step that cannot run says why.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from services.media_dimensions import probe_video_size
from services.mix_concat import (
    _run_ffmpeg_command,
    hold_crossfade_offsets,
    hold_crossfade_output_seconds,
    probe_duration_seconds,
    probe_has_audio,
)

TARGET_LUFS = -16.0
# Aim below the -1 dBTP delivery ceiling: AAC encoding overshoots the limiter by about 0.5 dB.
TRUE_PEAK_DB = -1.5
# Wide enough that loudnorm keeps the gain linear instead of compressing.
LOUDNESS_RANGE = 20.0
LINE_CHARACTERS = 42
CUE_CHARACTERS = LINE_CHARACTERS * 2
SUBTITLE_SUFFIXES = (".srt", ".vtt")
THUMBNAIL_SUFFIX = ".thumb.jpg"


def ffmpeg_binary() -> str | None:
    return os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")


# Timeline -------------------------------------------------------------------

def join_offsets(durations: Sequence[float], joined_duration: float | None) -> tuple[list[float], str]:
    """Clip starts for the join that produced ``joined_duration``: ``dissolve`` or ``cut``."""
    cut, elapsed = [], 0.0
    for duration in durations:
        cut.append(elapsed)
        elapsed += float(duration)
    if len(durations) < 2:
        return cut, "cut"
    dissolve_total = hold_crossfade_output_seconds(durations)
    if joined_duration is None or abs(joined_duration - dissolve_total) <= abs(joined_duration - elapsed):
        return hold_crossfade_offsets(durations), "dissolve"
    return cut, "cut"


def _chunks(text: str) -> list[str]:
    """Split one line into cues of at most two subtitle lines, at word boundaries."""
    words, chunks, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > CUE_CHARACTERS:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _wrap(text: str) -> str:
    """At most two lines, broken at the space nearest the middle."""
    if len(text) <= LINE_CHARACTERS:
        return text
    middle = len(text) // 2
    spaces = [index for index, char in enumerate(text) if char == " "]
    if not spaces:
        return text
    split = min(spaces, key=lambda index: abs(index - middle))
    return f"{text[:split]}\n{text[split + 1:]}"


def _beat_cues(beat: Any, offset: float, duration: float) -> list[dict[str, Any]]:
    if not isinstance(beat, dict):
        return []
    text = " ".join(str(beat.get("text") or "").split())
    try:
        start, end = max(0.0, float(beat["start"])), min(float(duration), float(beat["end"]))
    except (KeyError, TypeError, ValueError):
        return []
    if not text or end <= start:
        return []
    chunks = _chunks(text)
    total = sum(len(chunk) for chunk in chunks)
    cues, cursor = [], start
    for chunk in chunks:
        length = (end - start) * len(chunk) / total
        cues.append({"start": offset + cursor, "end": offset + cursor + length, "text": _wrap(chunk)})
        cursor += length
    return cues


def episode_cues(clips: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """``clips``: ``{offset, duration, beats}`` per shot → cues on the episode timeline."""
    cues = [cue for clip in clips for beat in clip.get("beats") or []
            for cue in _beat_cues(beat, float(clip["offset"]), float(clip["duration"]))]
    return sorted(cues, key=lambda cue: (cue["start"], cue["end"]))


def _timestamp(seconds: float, separator: str) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    whole, fraction = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d}{separator}{fraction:03d}"


def srt_text(cues: Sequence[dict[str, Any]]) -> str:
    return "\n".join(
        f"{index}\n{_timestamp(cue['start'], ',')} --> {_timestamp(cue['end'], ',')}\n{cue['text']}\n"
        for index, cue in enumerate(cues, start=1)
    )


def vtt_text(cues: Sequence[dict[str, Any]]) -> str:
    body = "\n".join(
        f"{_timestamp(cue['start'], '.')} --> {_timestamp(cue['end'], '.')}\n{cue['text']}\n" for cue in cues
    )
    return f"WEBVTT\n\n{body}"


def scene_beats(workspace_dir: str, scene_filename: Any) -> list[dict[str, Any]]:
    """Dialogue beats of a take's scene document (or the take's own beats, given as a list); nothing for a missing or foreign file."""
    if isinstance(scene_filename, list):
        return [beat for beat in scene_filename if isinstance(beat, dict)]
    if not isinstance(scene_filename, str) or not scene_filename:
        return []
    root = Path(workspace_dir).resolve()
    path = (root / scene_filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    beats = document.get("dialogueBeats") if isinstance(document, dict) else None
    return [beat for beat in beats if isinstance(beat, dict)] if isinstance(beats, list) else []


def write_episode_subtitles(
    output_path: str, clip_paths: Sequence[str], scene_filenames: Sequence[Any], *, workspace_dir: str,
    ffmpeg: str,
) -> dict[str, Any]:
    durations = [probe_duration_seconds(path, ffmpeg) for path in clip_paths]
    if any(duration is None for duration in durations):
        return {"written": False, "reason": "A clip duration could not be read"}
    offsets, join = join_offsets(durations, probe_duration_seconds(output_path, ffmpeg))
    clips = [{"offset": offset, "duration": duration, "beats": scene_beats(workspace_dir, name)}
             for offset, duration, name in zip(offsets, durations, scene_filenames)]
    cues = episode_cues(clips)
    if not cues:
        return {"written": False, "reason": "No approved take has dialogue beats in its scene document"}
    stem = os.path.splitext(output_path)[0]
    Path(f"{stem}.srt").write_text(srt_text(cues), encoding="utf-8")
    Path(f"{stem}.vtt").write_text(vtt_text(cues), encoding="utf-8")
    return {
        "written": True, "srt": os.path.basename(f"{stem}.srt"), "vtt": os.path.basename(f"{stem}.vtt"),
        "cueCount": len(cues), "shotsWithDialogue": sum(1 for clip in clips if clip["beats"]), "join": join,
    }


# Loudness -------------------------------------------------------------------

def _loudnorm(measured: dict[str, Any] | None = None) -> str:
    base = f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_DB}:LRA={LOUDNESS_RANGE}"
    if not measured:
        return f"{base}:print_format=json"
    return (f"{base}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true:print_format=json")


def _loudnorm_report(stderr: str) -> dict[str, Any] | None:
    found = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr or "")
    if not found:
        return None
    try:
        return json.loads(found[-1])
    except ValueError:
        return None


def measure_loudness(path: str, ffmpeg: str, timeout: float = 1800) -> dict[str, Any] | None:
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0", "-af", _loudnorm(), "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _loudnorm_report(completed.stderr) if completed.returncode == 0 else None


def _summary(report: dict[str, Any], prefix: str) -> dict[str, float]:
    return {"lufs": float(report[f"{prefix}_i"]), "truePeakDb": float(report[f"{prefix}_tp"]),
            "rangeLu": float(report[f"{prefix}_lra"])}


def normalize_loudness(path: str, *, ffmpeg: str, abort_callback: Callable[[], bool] | None = None) -> dict[str, Any]:
    if not probe_has_audio(path, ffmpeg):
        return {"applied": False, "reason": "The episode has no audio"}
    measured = measure_loudness(path, ffmpeg)
    if not measured:
        return {"applied": False, "reason": "ffmpeg could not measure the loudness"}
    try:
        before = _summary(measured, "input")
    except (KeyError, TypeError, ValueError):
        return {"applied": False, "reason": "ffmpeg returned an unreadable loudness report"}
    if before["lufs"] < -70:
        return {"applied": False, "reason": "The episode audio is silent", "before": before}
    temporary = f"{os.path.splitext(path)[0]}.loudnorm-tmp.mp4"
    command = [
        ffmpeg, "-y", "-hide_banner", "-i", path, "-map", "0:v?", "-map", "0:a:0", "-c:v", "copy",
        "-af", _loudnorm(measured), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
        temporary,
    ]
    if not _run_ffmpeg_command(command, temporary, abort_callback=abort_callback):
        return {"applied": False, "reason": "ffmpeg could not apply the gain", "before": before}
    after = measure_loudness(temporary, ffmpeg)
    os.replace(temporary, path)
    result = {"applied": True, "targetLufs": TARGET_LUFS, "truePeakTargetDb": TRUE_PEAK_DB, "before": before}
    if after:
        result["after"] = _summary(after, "input")
    return result


# Burned-in subtitles ---------------------------------------------------------

def _subtitles_filter(path: str, style: str) -> str:
    """ffmpeg escapes twice: inside an option value, then for the filter graph."""
    def value(text: str) -> str:
        return text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    described = f"subtitles=filename={value(path)}:force_style={value(style)}"
    return "".join(f"\\{char}" if char in "\\'[],;" else char for char in described)


def subtitle_style(size: tuple[int, int] | None) -> str:
    """libass sizes SRT text against a 288-line script, so a tall frame needs a smaller font in those units.
    Vertical video (TikTok, Reels) keeps captions above the app's bottom buttons."""
    font, margin = (11, 62) if size and size[1] > size[0] else (20, 28)
    return (f"FontName=DejaVu Sans,FontSize={font},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,"
            f"Outline=2,Shadow=0,MarginV={margin}")


def burn_subtitles(output_path: str, srt_name: str, *, ffmpeg: str,
                   abort_callback: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Write ``<episode>_subtitled.mp4`` with the subtitles drawn on the picture; the clean file stays."""
    source = os.path.abspath(output_path)
    target = f"{os.path.splitext(source)[0]}_subtitled.mp4"
    srt = os.path.join(os.path.dirname(source), srt_name).replace("\\", "/")
    style = subtitle_style(probe_video_size(source))
    command = [
        ffmpeg, "-y", "-hide_banner", "-i", source,
        "-vf", _subtitles_filter(srt, style),
        "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "copy",
        "-movflags", "+faststart", target,
    ]
    # Never chdir in the server: the escaped absolute path keeps drive colons out of the filter syntax.
    done = _run_ffmpeg_command(command, target, abort_callback=abort_callback)
    if not done:
        return {"burned": False, "reason": "ffmpeg could not draw the subtitles"}
    return {"burned": True, "file": os.path.basename(target)}


# All steps -------------------------------------------------------------------

def thumbnail_time(durations: Sequence[float], joined: float) -> float:
    """Into the second shot when the first is a short opening, else a third of the way in."""
    if len(durations) >= 2 and durations[0] < joined / 2:
        offsets, _join = join_offsets(durations, joined)
        return round(min(joined - 0.05, offsets[1] + min(1.0, durations[1] / 2)), 3)
    return round(joined / 3, 3)


def write_episode_thumbnail(output_path: str, clip_paths: Sequence[str], *, ffmpeg: str) -> dict[str, Any]:
    joined = probe_duration_seconds(output_path, ffmpeg)
    if not joined:
        return {"written": False, "reason": "The episode duration could not be read"}
    durations = [probe_duration_seconds(path, ffmpeg) for path in clip_paths]
    at = thumbnail_time([] if any(value is None for value in durations) else durations, joined)
    target = os.path.splitext(output_path)[0] + THUMBNAIL_SUFFIX
    result = subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", output_path, "-frames:v", "1",
                             "-vf", "scale=1280:-2", "-q:v", "3", target], capture_output=True, text=True, timeout=120, check=False)
    if result.returncode or not os.path.isfile(target):
        return {"written": False, "reason": (result.stderr or "ffmpeg wrote no frame").strip()[-300:]}
    return {"written": True, "file": os.path.basename(target), "time": at}


def finish_episode(
    output_path: str, clip_paths: Sequence[str], scene_filenames: Sequence[Any], *, workspace_dir: str,
    abort_callback: Callable[[], bool] | None = None, burn: bool = False,
) -> dict[str, Any]:
    ffmpeg = ffmpeg_binary()
    if not ffmpeg:
        reason = {"reason": "ffmpeg is not installed"}
        return {"subtitles": {"written": False, **reason}, "loudness": {"applied": False, **reason}}
    finished: dict[str, Any] = {}
    for key, step in (
        ("subtitles", lambda: write_episode_subtitles(
            output_path, clip_paths, scene_filenames, workspace_dir=workspace_dir, ffmpeg=ffmpeg)),
        ("loudness", lambda: normalize_loudness(output_path, ffmpeg=ffmpeg, abort_callback=abort_callback)),
    ):
        try:
            finished[key] = step()
        except Exception as error:  # A finishing step never costs the joined episode.
            finished[key] = {"applied" if key == "loudness" else "written": False, "reason": str(error)}
    subtitles = finished["subtitles"]
    if burn and subtitles.get("written"):
        try:
            subtitles.update(burn_subtitles(output_path, subtitles["srt"], ffmpeg=ffmpeg, abort_callback=abort_callback))
        except Exception as error:
            subtitles.update({"burned": False, "reason": str(error)})
    try:
        finished["thumbnail"] = write_episode_thumbnail(output_path, clip_paths, ffmpeg=ffmpeg)
    except Exception as error:  # Nor does the thumbnail.
        finished["thumbnail"] = {"written": False, "reason": str(error)}
    return finished


def finishing_note(finished: dict[str, Any]) -> str:
    loudness, subtitles = finished.get("loudness") or {}, finished.get("subtitles") or {}
    if loudness.get("applied"):
        sound = f"Loudness {loudness['before']['lufs']:.1f} → {TARGET_LUFS:.0f} LUFS."
    else:
        sound = f"Loudness unchanged: {loudness.get('reason', 'not measured')}."
    if subtitles.get("written"):
        text = f"{subtitles['cueCount']} subtitle cues."
    else:
        text = f"No subtitles: {subtitles.get('reason', 'not written')}."
    return f"{sound} {text}"


def remove_episode_subtitles(output_path: str) -> None:
    stem = os.path.splitext(output_path)[0]
    for suffix in (*SUBTITLE_SUFFIXES, "_subtitled.mp4", THUMBNAIL_SUFFIX):
        try:
            os.remove(f"{stem}{suffix}")
        except OSError:
            pass

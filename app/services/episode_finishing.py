"""Finish a joined Series episode: even loudness, subtitles, ambience and score.

Each shot mixes its own audio and the join only concatenates, so a five-minute
episode came out near -19 LUFS and without subtitles, although every 2D take's
scene document holds the exact text and timing of its lines (``dialogueBeats``).

1. Subtitles: ``<episode>.srt`` and ``<episode>.vtt`` from the beats of each
   approved take, placed with the clip offsets the join used (freeze tail plus
   dissolve, or a hard cut when the join fell back to one).
2. Ambience: with ``soundDesign.ambienceMode: "episode"``, one continuous
   bed per run of shots in a location, laid under the joined audio at the
   clips' real places on the timeline (``series_ambience``).
3. Score: the episode's music cues (``episode.score``), lowered while the
   lines the subtitles come from are spoken and silent under a shot with its
   own music (``series_score``).
4. Loudness: two ffmpeg ``loudnorm`` passes apply one linear gain to -16 LUFS
   integrated, under a -1 dBTP ceiling after AAC. Video is stream-copied.
5. Thumbnail: ``<episode>.thumb.jpg``, a frame of the first shot after the
   opening one (a series opens on its title card), for lists and publishing.

No step fails the assembly. A step that cannot run says why.
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

from services import series_ambience, series_hearing, series_score
from services.audio_levels import gain_to
from services.audio_mix import track_source
from services.media_dimensions import probe_video_size
from services.episode_av_sync import check_sync, sync_note
from services.mix_concat import (
    HOLD_TAIL_SEC,
    _run_ffmpeg_command,
    hold_crossfade_offsets,
    hold_crossfade_output_seconds,
    probe_duration_seconds,
    probe_has_audio,
)
from services.series_transitions import any_active, placed_offsets, placed_spans

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

def join_offsets(durations: Sequence[float], joined_duration: float | None,
                 transitions: Sequence[Any] | None = None) -> tuple[list[float], str]:
    """Clip starts for the join that produced ``joined_duration``: ``dissolve`` or ``cut``, or ``transition`` when a
    shot fades or dissolves in (``series_transitions``, whose cuts are that same dissolve)."""
    if any_active(transitions):
        return placed_offsets(durations, transitions), "transition"
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


def join_spans(durations: Sequence[float], joined_duration: float | None,
               transitions: Sequence[Any] | None = None) -> tuple[list[tuple[float, float]], str]:
    """Where each clip plays on the joined timeline, ``(start, end)``: a dissolve overlaps a clip's held tail with
    the next clip's start."""
    if any_active(transitions):
        return placed_spans(durations, transitions), "transition"
    offsets, join = join_offsets(durations, joined_duration)
    lengths = [max(0.1, float(duration)) + HOLD_TAIL_SEC if join == "dissolve" else float(duration) for duration in durations]
    return [(offset, offset + length) for offset, length in zip(offsets, lengths)], join


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


UNTIMED_MARGIN = 0.25


def spread_beats(beats: Sequence[Any], duration: float) -> list[dict[str, Any]]:
    """Beats without start/end (an H3 or imported take) share the clip by text length, inside a small margin."""
    texts = [" ".join(str(beat.get("text") or "").split()) for beat in beats if isinstance(beat, dict)]
    texts = [text for text in texts if text]
    total = sum(len(text) for text in texts)
    if not texts or duration <= 2 * UNTIMED_MARGIN or total == 0:
        return []
    span, cursor, timed = duration - 2 * UNTIMED_MARGIN, UNTIMED_MARGIN, []
    for text in texts:
        length = span * len(text) / total
        timed.append({"text": text, "start": round(cursor, 3), "end": round(cursor + length, 3)})
        cursor += length
    return timed


def _timed(beats: Sequence[Any], duration: float) -> list[Any]:
    if beats and all(isinstance(beat, dict) and beat.get("start") is None and beat.get("end") is None for beat in beats):
        return spread_beats(beats, duration)
    return list(beats)


def episode_cues(clips: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """``clips``: ``{offset, duration, beats}`` per shot → cues on the episode timeline."""
    cues = [cue for clip in clips for beat in _timed(clip.get("beats") or [], float(clip["duration"]))
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
    ffmpeg: str, transitions: Sequence[Any] | None = None,
) -> dict[str, Any]:
    durations = [probe_duration_seconds(path, ffmpeg) for path in clip_paths]
    if any(duration is None for duration in durations):
        return {"written": False, "reason": "A clip duration could not be read"}
    offsets, join = join_offsets(durations, probe_duration_seconds(output_path, ffmpeg), transitions)
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


# Ambience and score ---------------------------------------------------------

def _timeline(output_path: str, clip_paths: Sequence[str], ffmpeg: str,
              transitions: Sequence[Any] | None = None) -> tuple[list[float], float, list[tuple[float, float]], str] | None:
    """Each clip's length, the joined length, where each clip plays and the join; None when a length cannot be read."""
    durations = [probe_duration_seconds(path, ffmpeg) for path in clip_paths]
    joined = probe_duration_seconds(output_path, ffmpeg)
    if any(duration is None for duration in durations) or not joined:
        return None
    spans, join = join_spans(durations, joined, transitions)
    return durations, joined, spans, join


def _sources(workspace_dir: str, names: set[str], ffmpeg: str) -> tuple[dict[str, str], dict[str, float | None], list[str]]:
    """The workspace files behind ``names``, their lengths, and the names with no readable file."""
    resolved = {name: track_source(workspace_dir, name) for name in names}
    sources = {name: str(path) for name, path in resolved.items() if path is not None and path.is_file()}
    seconds = {name: probe_duration_seconds(path, ffmpeg) for name, path in sources.items()}
    return sources, seconds, sorted(name for name in resolved if not seconds.get(name))


def speech_spans(spans: Sequence[tuple[float, float]], durations: Sequence[float], lines: Sequence[Any], *,
                 workspace_dir: str) -> list[tuple[float, float]]:
    """When someone speaks on the joined timeline: the subtitle cues' times, from each take's recorded lines."""
    clips = [{"offset": span[0], "duration": duration, "beats": scene_beats(workspace_dir, name)}
             for span, duration, name in zip(spans, durations, lines)]
    return [(cue["start"], cue["end"]) for cue in episode_cues(clips)]


def lay_ambience(
    output_path: str, clip_paths: Sequence[str], ambience: Sequence[dict[str, Any]], *, workspace_dir: str, ffmpeg: str,
    abort_callback: Callable[[], bool] | None = None, level: Callable[[str], float] = gain_to,
    lines: Sequence[Any] | None = None, transitions: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Episode-mode beds (``ambience``: each clip's location and entry) under the joined audio, before the loudness.
    Entries with ``duckDb`` dip under the clips' recorded ``lines`` (``finish_episode``'s scene documents)."""
    timeline = _timeline(output_path, clip_paths, ffmpeg, transitions)
    if timeline is None:
        return {"applied": False, "reason": "The clip durations could not be read"}
    durations, joined, spans, join = timeline
    sources, seconds, missing = _sources(workspace_dir, {item["file"] for item in ambience if item.get("file")}, ffmpeg)
    # A missing file leaves its run silent, and the beds around it fade out instead of crossfading into it.
    shots = [item if item.get("file") not in missing else {"locationId": item.get("locationId")} for item in ambience]
    beds = series_ambience.plan_beds(shots, spans, seconds)
    report: dict[str, Any] = {"mode": "episode", **({"missing": missing} if missing else {})}
    if not beds:
        reason = (f"Ambience files not found in the workspace: {', '.join(missing)}" if missing
                  else "No shot's location has an ambience in soundDesign.ambienceByLocation")
        return {"applied": False, "reason": reason, **report}
    duck = max((float(item.get("duckDb") or 0) for item in ambience if item.get("file")), default=0.0)
    dips = series_score.merge_spans(speech_spans(spans, durations, lines, workspace_dir=workspace_dir)) if duck and lines else []
    envelopes = [series_score.envelope(series_score.bed_dips(bed, dips, duck_db=duck)) for bed in beds] if dips else None
    gains = {name: level(sources[name]) for name in {bed.file for bed in beds}}
    laid = series_ambience.mix_beds(
        output_path, beds, [sources[bed.file] for bed in beds], [gains[bed.file] for bed in beds], ffmpeg=ffmpeg,
        has_audio=probe_has_audio(output_path, ffmpeg), duration=joined, abort_callback=abort_callback, envelopes=envelopes)
    if not laid:
        return {"applied": False, "reason": "ffmpeg could not mix the ambience beds", **report}
    ducking = {"duckDb": duck, "dips": len(dips)} if duck else {}
    return {"applied": True, "join": join, "beds": [bed.report() for bed in beds], **ducking, **report}


def _score_factors(beds, cues, dips, silences):
    """Each cue's ducking and silence envelope on its planned bed."""
    return [series_score.bed_dips(bed, dips if cue.get("duck", True) else [], silences)
            for bed, cue in zip(beds, cues)]


def _score_cue_reports(beds, cues, factors) -> list[dict[str, Any]]:
    """Report the score that was laid, including each cue's ducking and silences."""
    return [{**bed.report(), "duck": bool(cue.get("duck", True)),
             "dips": sum(1 for item in items if item.depth < 1), "silences": sum(1 for item in items if item.depth >= 1)}
            for bed, cue, items in zip(beds, cues, factors)]


def lay_score(
    output_path: str, clip_paths: Sequence[str], lines: Sequence[Any], score: dict[str, Any], *, workspace_dir: str,
    ffmpeg: str, abort_callback: Callable[[], bool] | None = None, level: Callable[[str], float] = gain_to,
    transitions: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """The episode's score (``series_score.clip_score``) under the joined audio, before the loudness: each cue dips
    under the clips' recorded ``lines`` and is silent under a clip with its own music."""
    skipped = list(score.get("skipped") or [])
    report: dict[str, Any] = {"skipped": skipped} if skipped else {}
    cues = [cue for cue in score.get("cues") or [] if isinstance(cue, dict) and cue.get("file")]
    if not cues:
        return {"applied": False, "reason": "No score cue covers shots the episode has", **report}
    timeline = _timeline(output_path, clip_paths, ffmpeg, transitions)
    if timeline is None:
        return {"applied": False, "reason": "The clip durations could not be read", **report}
    durations, joined, spans, join = timeline
    sources, seconds, missing = _sources(workspace_dir, {cue["file"] for cue in cues}, ffmpeg)
    if missing:
        report["missing"] = missing
    cues = [cue for cue in cues if cue["file"] not in missing]
    if not cues:
        return {"applied": False, "reason": f"Score files not found in the workspace: {', '.join(missing)}", **report}
    beds = series_score.plan_cues(cues, spans, seconds)
    dips = series_score.merge_spans(speech_spans(spans, durations, lines, workspace_dir=workspace_dir))
    music = list(score.get("music") or [])
    silences = series_score.merge_spans([span for span, own in zip(spans, music) if own])
    factors = _score_factors(beds, cues, dips, silences)
    gains = {name: level(sources[name]) for name in {bed.file for bed in beds}}
    laid = series_ambience.mix_beds(
        output_path, beds, [sources[bed.file] for bed in beds], [gains[bed.file] for bed in beds], ffmpeg=ffmpeg,
        has_audio=probe_has_audio(output_path, ffmpeg), duration=joined, abort_callback=abort_callback,
        envelopes=[series_score.envelope(items) for items in factors], label="score")
    if not laid:
        return {"applied": False, "reason": "ffmpeg could not mix the score", **report}
    laid_cues = _score_cue_reports(beds, cues, factors)
    return {"applied": True, "join": join, "cues": laid_cues, **report}


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

def thumbnail_time(durations: Sequence[float], joined: float, transitions: Sequence[Any] | None = None) -> float:
    """Into the second shot when the first is a short opening, else a third of the way in."""
    if len(durations) >= 2 and durations[0] < joined / 2:
        offsets, _join = join_offsets(durations, joined, transitions)
        return round(min(joined - 0.05, offsets[1] + min(1.0, durations[1] / 2)), 3)
    return round(joined / 3, 3)


def write_episode_thumbnail(output_path: str, clip_paths: Sequence[str], *, ffmpeg: str,
                            transitions: Sequence[Any] | None = None) -> dict[str, Any]:
    joined = probe_duration_seconds(output_path, ffmpeg)
    if not joined:
        return {"written": False, "reason": "The episode duration could not be read"}
    durations = [probe_duration_seconds(path, ffmpeg) for path in clip_paths]
    at = thumbnail_time([] if any(value is None for value in durations) else durations, joined, transitions)
    target = os.path.splitext(output_path)[0] + THUMBNAIL_SUFFIX
    result = subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", output_path, "-frames:v", "1",
                             "-vf", "scale=1280:-2", "-q:v", "3", target], capture_output=True, text=True, timeout=120, check=False)
    if result.returncode or not os.path.isfile(target):
        return {"written": False, "reason": (result.stderr or "ffmpeg wrote no frame").strip()[-300:]}
    return {"written": True, "file": os.path.basename(target), "time": at}


def _color_hearing(output_path: str, clip_paths: Sequence[str], hearing: Sequence[str], ffmpeg: str,
                   abort_callback: Callable[[], bool] | None, transitions: Sequence[Any] | None = None) -> dict[str, Any]:
    """Subjective hearing on the joined timeline (where the transitions put each clip), after the ambience and the
    score and before the loudness."""
    timeline = _timeline(output_path, clip_paths, ffmpeg, transitions)
    if timeline is None:
        return {"applied": False, "reason": "The clip durations could not be read"}
    return series_hearing.color_episode(output_path, timeline[2], hearing, ffmpeg=ffmpeg, abort_callback=abort_callback)


def finish_episode(
    output_path: str, clip_paths: Sequence[str], scene_filenames: Sequence[Any], *, workspace_dir: str,
    abort_callback: Callable[[], bool] | None = None, burn: bool = False,
    ambience: Sequence[dict[str, Any]] | None = None, score: dict[str, Any] | None = None,
    transitions: Sequence[Any] | None = None,
    hearing: Sequence[str] | None = None,
) -> dict[str, Any]:
    """``ambience`` (``series_ambience.clip_ambience``) lays episode-mode beds and ``score``
    (``series_score.clip_score``) the episode's music, both before the loudness pass."""
    ffmpeg = ffmpeg_binary()
    if not ffmpeg:
        reason = {"reason": "ffmpeg is not installed"}
        finished = {"subtitles": {"written": False, **reason}, "loudness": {"applied": False, **reason}}
        return {**finished, **{key: {"applied": False, **reason} for key, value in (("ambience", ambience), ("score", score))
                               if value is not None}}
    steps: list[tuple[str, Callable[[], dict[str, Any]]]] = [("subtitles", lambda: write_episode_subtitles(
        output_path, clip_paths, scene_filenames, workspace_dir=workspace_dir, ffmpeg=ffmpeg, transitions=transitions))]
    if ambience is not None:
        steps.append(("ambience", lambda: lay_ambience(
            output_path, clip_paths, ambience, workspace_dir=workspace_dir, ffmpeg=ffmpeg, abort_callback=abort_callback,
            lines=scene_filenames, transitions=transitions)))
    if score is not None:
        steps.append(("score", lambda: lay_score(
            output_path, clip_paths, scene_filenames, score, workspace_dir=workspace_dir, ffmpeg=ffmpeg,
            abort_callback=abort_callback, transitions=transitions)))
    if series_hearing.active(hearing):
        steps.append(("hearing", lambda: _color_hearing(output_path, clip_paths, hearing, ffmpeg, abort_callback, transitions)))
    steps.append(("loudness", lambda: normalize_loudness(output_path, ffmpeg=ffmpeg, abort_callback=abort_callback)))
    steps.append(("sync", lambda: check_episode_sync(output_path, clip_paths, ffmpeg=ffmpeg, transitions=transitions)))
    finished: dict[str, Any] = {}
    for key, step in steps:
        try:
            finished[key] = step()
        except Exception as error:  # A finishing step never costs the joined episode.
            finished[key] = {"written" if key == "subtitles" else ("checked" if key == "sync" else "applied"): False,
                             "reason": str(error)}
    subtitles = finished["subtitles"]
    if burn and subtitles.get("written"):
        try:
            subtitles.update(burn_subtitles(output_path, subtitles["srt"], ffmpeg=ffmpeg, abort_callback=abort_callback))
        except Exception as error:
            subtitles.update({"burned": False, "reason": str(error)})
    try:
        finished["thumbnail"] = write_episode_thumbnail(output_path, clip_paths, ffmpeg=ffmpeg, transitions=transitions)
    except Exception as error:  # Nor does the thumbnail.
        finished["thumbnail"] = {"written": False, "reason": str(error)}
    return finished


def check_episode_sync(output_path: str, clip_paths: Sequence[str], *, ffmpeg: str,
                       transitions: Sequence[Any] | None = None) -> dict[str, Any]:
    """Every take's sound against where the join put its pictures in the finished episode (``episode_av_sync``)."""
    timeline = _timeline(output_path, clip_paths, ffmpeg, transitions)
    if timeline is None:
        return {"checked": False, "reason": "The clip durations could not be read"}
    _durations, _joined, spans, _join = timeline
    return check_sync(output_path, clip_paths, [start for start, _end in spans], ffmpeg=ffmpeg)


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
    notes = [sound, text]
    for key, items, name in (("ambience", "beds", "ambience bed"), ("score", "cues", "score cue")):
        laid = finished.get(key)
        if laid is None:
            continue
        if laid.get("applied"):
            count = len(laid.get(items) or [])
            notes.append(f"{count} {name}{'' if count == 1 else 's'}.")
        else:
            notes.append(f"No {name}s: {laid.get('reason', 'not laid')}.")
    if finished.get("sync") is not None:
        notes.append(sync_note(finished["sync"]))
    return " ".join(notes)


def remove_episode_subtitles(output_path: str) -> None:
    stem = os.path.splitext(output_path)[0]
    for suffix in (*SUBTITLE_SUFFIXES, "_subtitled.mp4", THUMBNAIL_SUFFIX):
        try:
            os.remove(f"{stem}{suffix}")
        except OSError:
            pass

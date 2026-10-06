"""Generated and imported takes at the episode cut: the shot's sound on them, and one frame format for every clip.

A MiniMax H3 clip or an imported video is a take the native render never
touches, so its shot's ``layout2d.sfx`` and ``music`` used to be muxed onto it
with ffmpeg before the import, and a 1280x704 30 fps clip in a 1920x1080 24 fps
episode made the join fail. At assembly now:

* a ``generated_video`` / ``imported_video`` shot's ``sfx`` (at ``at`` + ``offset``
  seconds; line and entrance anchors have nothing to follow in a video take and
  start at 0) and ``music`` are mixed onto its take, volumes relative to the
  dialogue as in a rendered shot, over the clip's own audio
  (``layout2d.clipAudio``: ``"keep"``, the default, or ``"drop"``;
  ``clipVolume`` 0-2, default 1). Changing them only needs a recut;
* a video shot's ``foley`` (made by ``series.episode.render_native`` from the
  take's picture, ``series_video_foley``) is laid under it at its volume; when
  it has not been made yet the cut goes without it and says so;
* every clip whose frame size, frame rate or pixel aspect differ from the
  episode's (1920x1080 or 1080x1920 at 24 fps) is conformed: ``cover``
  (scale and centre-crop) when its shape is within 6 % of the frame's, else
  ``contain`` (fit with bars); ``layout2d.clipFit`` forces either.

The takes themselves are never changed: the conformed copies live in a
temporary folder for the join and its finishing, and are removed after it.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from services.audio_levels import gain_to
from services.audio_mix import AUDIO_FILTER_TAIL, track_source
from services.series_shot_extras import CLIP_AUDIO, CLIP_FIT, cue_time, normalize_clip_fields
from services.series_shot_plan import FPS, frame_size
from services.series_sound_cuts import materialize_cuts, track_cut
from services.series_video_foley import VIDEO_METHODS, shot_foley, sound_name
COVER_TOLERANCE = 0.06
MAX_GAIN = 2.0


def episode_frame(series: dict[str, Any]) -> dict[str, int]:
    width, height = frame_size(series)
    return {"width": width, "height": height, "fps": FPS}


def _sound_plan(shot: dict[str, Any], episode_id: str) -> dict[str, Any] | None:
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    sound = {key: layout[key] for key in ("sfx", "music", "clipAudio", "clipVolume") if layout.get(key) not in (None, [], {})}
    foley = shot_foley(shot)
    if foley:
        sound["foley"] = {**foley, "episodeId": episode_id, "shotId": shot.get("id")}
    if sound.get("clipAudio") == "keep":
        sound.pop("clipAudio")
    if sound.get("clipVolume") == 1.0:
        sound.pop("clipVolume")
    return sound or None


def plan_take_sound(series: dict[str, Any], episode: dict[str, Any], clips: list[dict[str, Any]]) -> dict[str, int]:
    """Mark each clip of a video shot with its shot's sound and fit (kept on the job for a resume); returns the frame."""
    shots = {str(shot.get("id")): shot for shot in episode.get("shots") or [] if isinstance(shot, dict)}
    for clip in clips:
        shot = shots.get(str(clip.get("shotId"))) or {}
        if shot.get("productionMethod") not in VIDEO_METHODS:
            continue
        sound = _sound_plan(shot, str(episode.get("id") or ""))
        if sound:
            clip["takeSound"] = sound
        fit = (shot.get("layout2d") or {}).get("clipFit") if isinstance(shot.get("layout2d"), dict) else None
        if fit in CLIP_FIT:
            clip["clipFit"] = fit
    return episode_frame(series)


def _rate(value: Any) -> float:
    try:
        top, _, bottom = str(value or "").partition("/")
        return float(top) / float(bottom or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _aspect(value: Any) -> float:
    top, _, bottom = str(value or "").partition(":")
    try:
        ratio = float(top) / float(bottom)
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0
    return ratio if ratio > 0 else 1.0


def probe_clip(path: str) -> dict[str, Any]:
    """Size, pixel aspect, frame rate, duration and whether it has sound."""
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                            capture_output=True, text=True, timeout=60, check=False)
    data = json.loads(result.stdout or "{}") if result.returncode == 0 else {}
    streams = data.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError(f"{os.path.basename(path)} has no video stream")
    duration = float(video.get("duration") or (data.get("format") or {}).get("duration") or 0)
    return {"width": int(video.get("width") or 0), "height": int(video.get("height") or 0),
            "sar": _aspect(video.get("sample_aspect_ratio")), "fps": _rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
            "duration": duration, "audio": any(item.get("codec_type") == "audio" for item in streams)}


def needs_conform(info: dict[str, Any], frame: dict[str, int]) -> bool:
    return (info["width"], info["height"]) != (frame["width"], frame["height"]) or abs(info["fps"] - frame["fps"]) > 0.01 \
        or abs(info["sar"] - 1.0) > 0.001


def fit_mode(info: dict[str, Any], frame: dict[str, int], forced: str | None = None) -> str:
    if forced in CLIP_FIT:
        return forced
    shape = info["width"] * info["sar"] / max(1, info["height"])
    target = frame["width"] / frame["height"]
    return "cover" if abs(shape / target - 1.0) <= COVER_TOLERANCE else "contain"


def video_filter(info: dict[str, Any], frame: dict[str, int], fit: str) -> str:
    width, height = frame["width"], frame["height"]
    square = "scale=trunc(iw*sar/2)*2:ih," if abs(info["sar"] - 1.0) > 0.001 else ""
    if fit == "cover":
        sized = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    else:
        sized = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    return f"{square}{sized},setsar=1,fps={frame['fps']},format=yuv420p"


def sound_tracks(sound: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    """The shot's effects and music as mixer tracks: effects at their second (plus offset), music from its start."""
    tracks = []
    for index, cue in enumerate(sound.get("sfx") or []):
        if isinstance(cue, dict) and cue.get("file"):
            plain = {key: value for key, value in cue.items() if key not in ("line", "anchor", "cast")}
            tracks.append({"id": f"sfx-{index}", "filename": cue["file"], "kind": "sfx", "startTime": cue_time(plain, [], duration),
                           "volume": float(cue.get("volume", 0.8)), **track_cut(cue)})
    music = sound.get("music")
    if isinstance(music, dict) and music.get("file"):
        tracks.append({"id": "music", "filename": music["file"], "kind": "music", "startTime": float(music.get("start") or 0),
                       "volume": float(music.get("volume", 0.5))})
    return tracks


def _audio_graph(info: dict[str, Any], sound: dict[str, Any], sources: list[tuple[Path, float, float]], duration: float) -> tuple[str, int]:
    """The filter graph that mixes the clip's own sound (input 0) and the sources (inputs 1..n) into [mix]."""
    parts, labels = [], []
    if info["audio"] and sound.get("clipAudio") != "drop":
        parts.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo,volume={float(sound.get('clipVolume', 1.0)):.4f}[c0]")
        labels.append("[c0]")
    for index, (_path, start, volume) in enumerate(sources, start=1):
        delay = int(round(start * 1000))
        parts.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,volume={volume:.4f},adelay={delay}|{delay}[s{index}]")
        labels.append(f"[s{index}]")
    if not labels:
        parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{duration:.4f}[mix]")
        return ";".join(parts), 0
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,{AUDIO_FILTER_TAIL},apad,atrim=0:{duration:.4f}[mix]")
    return ";".join(parts), len(labels)


def _foley_source(root: str, clip: str, foley: dict[str, Any], gain: Callable[[str], float]) -> tuple[Path, float, float] | None:
    """The foley made for this take and prompt, at its volume relative to the dialogue; None until it is made."""
    path = Path(root) / sound_name(clip, str(foley.get("episodeId")), str(foley.get("shotId")), foley)
    return (path, 0.0, round(min(MAX_GAIN, float(foley["volume"]) * gain(str(path))), 4)) if path.is_file() else None


def _sources(root: str, sound: dict[str, Any], duration: float, gain: Callable[[str], float]) -> list[tuple[Path, float, float]]:
    tracks = sound_tracks(sound, duration)
    materialize_cuts(root, tracks)
    found = []
    for track in tracks:
        path = track_source(root, track["filename"])
        if path is None or not path.is_file():
            raise ValueError(f"Shot sound file {track['filename']} is not in the workspace")
        if track["startTime"] < duration:
            found.append((path, track["startTime"], round(min(MAX_GAIN, track["volume"] * gain(str(path))), 4)))
    return found


def _clip_command(path: str, target: str, sources: list[tuple[Path, float, float]], graph: str, duration: float,
                  video: str | None) -> list[str]:
    """ffmpeg for one prepared clip: ``video`` is the conform filter (None copies the picture)."""
    command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", path]
    for source, _start, _volume in sources:
        command += ["-i", str(source)]
    if video is None:
        command += ["-filter_complex", graph, "-map", "0:v:0", "-map", "[mix]", "-c:v", "copy"]
    else:
        command += ["-filter_complex", f"[0:v]{video}[v];{graph}", "-map", "[v]", "-map", "[mix]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    return command + ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{duration:.4f}", "-movflags", "+faststart", target]


def _clip_report(info: dict[str, Any], sound: dict[str, Any], sources: list, foley: Any, mode: str | None) -> dict[str, Any]:
    report: dict[str, Any] = {"conformed": mode is not None}
    if mode is not None:
        report.update({"from": f"{info['width']}x{info['height']}@{info['fps']:.3g}", "fit": mode})
    if sound:
        report.update(sounds=len(sources), clipAudio="drop" if sound.get("clipAudio") == "drop" else "keep")
    if sound.get("foley"):
        report["foley"] = bool(foley)
        if not foley:
            report["warning"] = "foley not made yet: render the shot (series.shot.update render, or render_native with its id)"
    return report


def render_clip(path: str, target: str, info: dict[str, Any], frame: dict[str, int], *, root: str,
                sound: dict[str, Any] | None = None, fit: str | None = None, gain: Callable[[str], float] = gain_to) -> dict[str, Any]:
    """One clip as the cut needs it: conformed when its format differs, with its shot's sound when it has some."""
    sound = sound or {}
    sources = _sources(root, sound, info["duration"], gain) if sound else []
    foley = _foley_source(root, path, sound["foley"], gain) if sound.get("foley") else None
    sources += [foley] if foley else []
    mode = fit_mode(info, frame, fit) if needs_conform(info, frame) else None
    graph, mixed = _audio_graph(info, sound, sources, info["duration"])
    video = video_filter(info, frame, mode) if mode else None
    result = subprocess.run(_clip_command(path, target, sources, graph, info["duration"], video),
                            capture_output=True, text=True, timeout=1800, check=False)
    if result.returncode != 0 or not os.path.isfile(target):
        raise RuntimeError(("Preparing a take for the cut failed: " + (result.stderr or "")).strip()[-600:])
    return {**_clip_report(info, sound, sources, foley, mode), "mixedInputs": mixed}


def prepare_clips(paths: list[str], clips: list[dict[str, Any]], frame: dict[str, int] | None, root: str, folder: str, *,
                  probe: Callable[[str], dict[str, Any]] = probe_clip, gain: Callable[[str], float] = gain_to,
                  cancelled: Callable[[], bool] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    """The paths to join: each clip as it is, or a conformed copy with its shot's sound in ``folder``; and a report."""
    if not frame:
        return list(paths), []
    prepared, report = [], []
    for index, (path, clip) in enumerate(zip(paths, clips)):
        if cancelled and cancelled():
            raise RuntimeError("Series assembly cancelled")
        sound = clip.get("takeSound") if isinstance(clip.get("takeSound"), dict) else None
        try:
            info = probe(path)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            # Not readable here: the join itself says what is wrong with it.
            prepared.append(path)
            if sound:
                report.append({"shotId": clip.get("shotId"), "conformed": False, "warning": f"sound left out: {error}"[:200]})
            continue
        if not sound and not needs_conform(info, frame):
            prepared.append(path)
            continue
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, f"{index:03d}-{str(clip.get('shotId') or 'clip')[:60]}.mp4")
        done = render_clip(path, target, info, frame, root=root, sound=sound, fit=clip.get("clipFit"), gain=gain)
        prepared.append(target)
        report.append({"shotId": clip.get("shotId"), **done})
    return prepared, report


def prepared_metadata(report: list[dict[str, Any]]) -> dict[str, Any]:
    """What the cut's asset records about the clips it conformed or gave their shot's sound (nothing when none)."""
    return {"preparedClips": report} if report else {}


def prepared_note(report: list[dict[str, Any]]) -> str:
    """One sentence for the assembly message: how many clips were conformed and how many takes got their shot's sound."""
    conformed = sum(1 for item in report if item.get("conformed"))
    sounded = sum(1 for item in report if "sounds" in item)
    parts = [f"{conformed} clip{'' if conformed == 1 else 's'} conformed to the episode frame" if conformed else "",
             f"{sounded} video take{'' if sounded == 1 else 's'} with {'its' if sounded == 1 else 'their'} shot's sound" if sounded else ""]
    text = " and ".join(part for part in parts if part)
    return f"{text[0].upper()}{text[1:]}." if text else ""


__all__ = ["CLIP_AUDIO", "CLIP_FIT", "VIDEO_METHODS", "episode_frame", "fit_mode", "needs_conform", "normalize_clip_fields",
           "plan_take_sound", "prepare_clips", "prepared_metadata", "prepared_note", "probe_clip", "render_clip", "sound_tracks", "video_filter"]

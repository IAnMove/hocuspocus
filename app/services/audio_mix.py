"""The one ffmpeg mixer under a rendered scene: Video 2D and Video 3D, with the same limiter and ducking.

Three mixers used to exist (recording, 2D, 3D) with different defaults; the 3D
one had no limiter, so overlapping voices or a loud effect clipped. Every mix
now ends in ``alimiter`` before the AAC encoder.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

LIMIT = 0.97
AUDIO_FILTER_TAIL = f"alimiter=limit={LIMIT}:attack=5:release=50"
# Same envelope as Video 3D dialogue ducking (ui/src/features/scene3d/speech/audio.ts).
DUCK_ATTACK, DUCK_RELEASE, DUCK_MARGIN = 0.12, 0.4, 0.08


def audio_seconds(path: Path) -> float:
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=30, check=False)
    try:
        return float(probe.stdout.strip())
    except ValueError:
        return 0.0


def track_source(workspace_root: Path | str, filename: object) -> Path | None:
    """The file a scene track names, anywhere inside the workspace (``music/theme.wav`` included); None outside it."""
    name = str(filename or "").strip().replace("\\", "/")
    if not name or name.startswith("/") or ".." in name.split("/"):
        return None
    root = Path(workspace_root).resolve()
    candidate = (root / name).resolve()
    return candidate if root in candidate.parents else None


def duck_db(document: dict) -> float:
    """``audioMix.duckDb``: how far music and effects dip while someone speaks (0 = off)."""
    value = (document.get("audioMix") or {}).get("duckDb") if isinstance(document.get("audioMix"), dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 30 else 0.0


def duck_expression(windows: list[tuple[float, float]], depth_db: float) -> str | None:
    """A volume expression of output time: 1, down by ``depth_db`` inside each speech window, with short ramps."""
    if not windows or depth_db <= 0:
        return None
    depth = 1 - 10 ** (-depth_db / 20)
    terms = [f"min(clip((t-{start - DUCK_MARGIN:.3f})/{DUCK_ATTACK},0,1),clip(({end + DUCK_RELEASE:.3f}-t)/{DUCK_RELEASE},0,1))"
             for start, end in windows]
    combined = terms[0]
    for term in terms[1:]:
        combined = f"max({combined},{term})"
    return f"1-{depth:.4f}*{combined}"


def _usable_tracks(tracks: list[dict], workspace_root: Path, duration: float) -> list[tuple[Path, float, float, bool]]:
    usable = []
    for track in tracks:
        source = track_source(workspace_root, track.get("filename"))
        start = float(track.get("startTime") or 0)
        if source is not None and source.is_file() and 0 <= start < duration:
            usable.append((source, start, max(0.0, min(2.0, float(track.get("volume", 1) or 0))), track.get("kind") == "speech"))
    return usable


def mux_wav_audio(video: Path, wav: Path, duration: float, *, label: str = "Audio mix") -> Path:
    """Put a page's WAV mix under the silent render: limited, AAC 192k, video copied, exactly ``duration`` long."""
    mixed = video.with_name("fx-mixed.mp4")
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(wav), "-filter_complex",
               f"[1:a]aresample=48000,aformat=channel_layouts=stereo,{AUDIO_FILTER_TAIL},apad,atrim=0:{duration:.4f}[mix]",
               "-map", "0:v:0", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-t", f"{duration:.4f}", "-movflags", "+faststart", str(mixed)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
    if result.returncode != 0 or not mixed.is_file():
        raise RuntimeError((f"{label} failed: " + (result.stderr or "")).strip()[-800:])
    return mixed


def mix_audio_tracks(video: Path, tracks: list[dict], workspace_root: Path, duration: float,
                     extras: list[Path] | None = None, duck: float = 0.0) -> Path:
    """Mix scene audio tracks (startTime, volume) and optional extra WAVs under the silent render.

    With ``duck`` (dB), every track that is not speech, and the extras, dips under the speech tracks.
    """
    usable = [(extra, 0.0, 1.0, False) for extra in extras or [] if extra.is_file()] + _usable_tracks(tracks, workspace_root, duration)
    if not usable:
        return video
    windows = [(start, start + audio_seconds(source)) for source, start, _, speech in usable if speech] if duck else []
    envelope = duck_expression(windows, duck)
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(video)]
    parts, labels = [], []
    for index, (source, start, volume, speech) in enumerate(usable, start=1):
        command += ["-i", str(source)]
        delay = int(round(start * 1000))
        ducked = f",volume='{envelope}':eval=frame" if envelope and not speech else ""
        parts.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,volume={volume:.4f},adelay={delay}|{delay}{ducked}[a{index}]")
        labels.append(f"[a{index}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,{AUDIO_FILTER_TAIL},apad,atrim=0:{duration:.4f}[mix]")
    mixed = video.with_name("mixed.mp4")
    command += ["-filter_complex", ";".join(parts), "-map", "0:v:0", "-map", "[mix]", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-t", f"{duration:.4f}", "-movflags", "+faststart", str(mixed)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
    if result.returncode != 0 or not mixed.is_file():
        raise RuntimeError(("Audio track mix failed: " + (result.stderr or "")).strip()[-800:])
    return mixed


__all__ = ["AUDIO_FILTER_TAIL", "LIMIT", "audio_seconds", "duck_db", "duck_expression", "mix_audio_tracks", "mux_wav_audio",
           "track_source"]

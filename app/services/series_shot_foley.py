"""Foley made from a shot's own picture: ``shot.foley = {prompt, volume}``.

A shot's ``sfx`` are files placed by hand at a second or on a line. Foley is
generated for the finished picture instead: after the native render exports a
shot, ``generation.sfx`` (MMAudio, video-guided) watches the export and makes
sound that follows its motion (an airship creaking, swords, an explosion), and
the render mixes it under the take's own lines, music and effects before the
take is imported:

* ``prompt``: what to hear, in a few words ("wooden airship creaking, wind, cannon shots");
* ``volume``: above 0 and up to 2, relative to the dialogue (default 0.5), scaled by the
  generated sound's own loudness like a shot's music and effects.

The block lives on the shot, not in ``scene3d``: every rendered shot, 2D or 3D,
has a picture to follow. Foley is an extra: when MMAudio fails, is not
installed or takes too long, the take is imported without it and the render
item carries a warning.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

from services.audio_mix import AUDIO_FILTER_TAIL, audio_seconds

MODEL = "mmaudio_v2"
DEFAULT_VOLUME = 0.5
MAX_VOLUME = 2.0
MAX_PROMPT = 500
# The take already has its lines and music: the foley is everything else.
NEGATIVE_PROMPT = "speech, voices, talking, singing, music"


def normalize_foley(value: Any) -> dict[str, Any] | None:
    """``{prompt, volume}`` with the default volume, or None for no foley; a malformed block is refused."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("shot.foley must be an object {prompt, volume}")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("shot.foley.prompt must describe the sound to generate")
    if len(prompt.strip()) > MAX_PROMPT:
        raise ValueError(f"shot.foley.prompt must be at most {MAX_PROMPT} characters")
    volume = value.get("volume", DEFAULT_VOLUME)
    if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 < volume <= MAX_VOLUME:
        raise ValueError(f"shot.foley.volume must be above 0 and at most {MAX_VOLUME:g} (relative to the dialogue)")
    return {"prompt": prompt.strip(), "volume": float(volume)}


def file_digest(path: str) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def foley_keys(export_digest: str, foley: dict[str, Any]) -> tuple[str, str]:
    """(sound, take): the generated sound depends on the picture and the prompt; the mixed take on the volume too."""
    sound = f"{export_digest}\n{foley['prompt']}"
    return (hashlib.sha1(sound.encode()).hexdigest()[:12],
            hashlib.sha1(f"{sound}\n{foley['volume']:g}".encode()).hexdigest()[:12])


def foley_seed(shot_id: str, prompt: str) -> int:
    """The same shot and prompt ask MMAudio with the same seed."""
    return int(hashlib.sha1(f"{shot_id}\n{prompt}".encode()).hexdigest()[:6], 16)


def sfx_params(workspace: str, video: str, foley: dict[str, Any], seed: int, seconds: float) -> dict[str, Any]:
    """``generation.sfx`` v2 params: MMAudio follows the exported video (``seconds`` is its length; the tool measures
    the guide again and uses that)."""
    return {"model_type": MODEL, "prompt": foley["prompt"], "MMAudio_neg_prompt": NEGATIVE_PROMPT,
            "duration_seconds": float(seconds), "seed": seed,
            "video_guide": f"/api/v1/file/{quote(video)}?workspace={quote(workspace)}"}


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _ffmpeg(command: list[str], temporary: str, target: str, label: str) -> None:
    """Run ffmpeg into ``temporary`` and move it to ``target``, so a cut-off run never leaves a cached file."""
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
    if result.returncode != 0 or not os.path.isfile(temporary):
        _remove(temporary)
        raise RuntimeError((f"{label} failed: " + (result.stderr or "")).strip()[-600:])
    os.replace(temporary, target)


def extract_audio(source: str, target: str) -> None:
    """The sound track of a generated clip as a stereo 48 kHz WAV; the clip's picture is a copy of the take's."""
    temporary = f"{os.path.splitext(target)[0]}.part.wav"
    _ffmpeg(["ffmpeg", "-v", "error", "-y", "-i", source, "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "48000", temporary],
            temporary, target, "Foley audio extraction")


def has_audio(path: str) -> bool:
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30, check=False)
    return bool(probe.stdout.strip())


def mix_under(take: str, foley: str, target: str, gain: float) -> None:
    """``foley`` at ``gain`` under the take's own sound, limited like every scene mix; the picture is stream-copied
    and the result is exactly as long as the take."""
    seconds = audio_seconds(Path(take))
    if seconds <= 0:
        raise RuntimeError("The take has no readable duration")
    under = f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={gain:.4f}"
    if has_audio(take):
        graph = (f"[0:a]aresample=48000,aformat=channel_layouts=stereo[take];{under}[foley];"
                 f"[take][foley]amix=inputs=2:duration=longest:normalize=0,")
    else:
        graph = f"{under},"
    graph += f"{AUDIO_FILTER_TAIL},apad,atrim=0:{seconds:.4f}[mix]"
    temporary = f"{os.path.splitext(target)[0]}.part.mp4"
    _ffmpeg(["ffmpeg", "-v", "error", "-y", "-i", take, "-i", foley, "-filter_complex", graph, "-map", "0:v:0", "-map", "[mix]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{seconds:.4f}", "-movflags", "+faststart", temporary],
            temporary, target, "Foley mix")


__all__ = ["DEFAULT_VOLUME", "MAX_VOLUME", "MODEL", "NEGATIVE_PROMPT", "extract_audio", "file_digest", "foley_keys", "foley_seed",
           "has_audio", "mix_under", "normalize_foley", "sfx_params"]

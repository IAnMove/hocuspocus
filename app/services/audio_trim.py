"""``audio.trim``: an exact cut of a workspace audio file into a new audio asset.

Unlike ``audio.shorten`` (which snaps every edge to an onset and joins
ranges), this cuts exactly ``start`` .. ``start + length`` (or ``end``),
sample-accurately with ``atrim``, keeps the source's sample rate and channels
and adds short fades (5 ms by default) so the cut does not click. One
footstep out of an eight-second footsteps file, a sting out of a theme.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from services.production_media_common import (
    OUTPUT_NAME, SOURCE, WORKSPACE, MediaToolError, media_url, number, operation_schema, output_destination,
    publish_sidecar, read_input, resolve_source, sha256_file, source_ref, uploads_root,
    workspace_folder,
)

OPERATION = "audio.trim"
MAX_SECONDS = 3600.0
DEFAULT_FADE = 0.005
_KEYS = frozenset({"workspace", "source", "start", "length", "end", "fade_in", "fade_out", "output_name", "format"})
_PCM_KEEP = {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le", "pcm_u8"}


def catalog() -> dict[str, Any]:
    seconds = {"type": "number", "minimum": 0, "maximum": MAX_SECONDS}
    fade = {"type": "number", "minimum": 0, "maximum": 10, "description": f"Seconds (default {DEFAULT_FADE})."}
    return operation_schema(OPERATION, (
        "Cut an exact segment of a workspace audio file (or a video's audio) into a new audio file in the workspace, "
        "instead of cutting it with ffmpeg outside HocusPocus: start seconds and length seconds (or end). The cut is "
        "sample-exact (no snapping to onsets, unlike audio.shorten), keeps the source's sample rate and channels, "
        "and fades in and out over fade_in / fade_out seconds (default 0.005) so it does not click. A length past "
        "the end of the file stops at the end (clipped true). format wav (default) or keep (the source's own "
        "format, for an audio source). Writes a provenance sidecar naming the source and the cut. Returns file, url, "
        "seconds, start, sample_rate, channels, sha256. Use the result as an sfx file, e.g. one footstep with "
        "repeat: steps."
    ), {
        "workspace": WORKSPACE, "source": SOURCE, "start": {**seconds, "description": "Source in-point, seconds."},
        "length": {"type": "number", "exclusiveMinimum": 0, "maximum": MAX_SECONDS, "description": "Seconds kept."},
        "end": {**seconds, "description": "Source out-point, seconds (instead of length)."},
        "fade_in": fade, "fade_out": fade, "output_name": OUTPUT_NAME,
        "format": {"type": "string", "enum": ["wav", "keep"]},
    }, ["workspace", "source", "start"])


def _ffprobe_audio(source: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=codec_name,sample_rate,channels:format=duration", "-of", "json", source],
            capture_output=True, text=True, timeout=60, check=False)
        return json.loads(result.stdout or "{}") if result.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise MediaToolError("trim_failed", "ffprobe could not read the audio.") from exc


def probe_audio_stream(source: str) -> dict[str, Any]:
    """Codec, sample rate, channels and duration of the first audio stream."""
    data = _ffprobe_audio(source)
    streams = data.get("streams") or []
    if not streams:
        raise MediaToolError("unsupported_media", "The source has no audio stream.")
    stream = streams[0]
    try:
        info = {"codec": str(stream.get("codec_name") or ""), "sample_rate": int(stream.get("sample_rate") or 0),
                "channels": int(stream.get("channels") or 0),
                "duration": float((data.get("format") or {}).get("duration") or 0)}
    except (TypeError, ValueError) as exc:
        raise MediaToolError("trim_failed", "ffprobe could not read the audio.") from exc
    if min(info["sample_rate"], info["channels"], info["duration"]) <= 0:
        raise MediaToolError("unsupported_media", "The source audio has no readable rate, channels or duration.")
    return info


def _window(payload: dict, duration: float) -> tuple[float, float, bool]:
    """(start, length, clipped) inside the source."""
    if ("length" in payload) == ("end" in payload):
        raise MediaToolError("invalid_command", "Give length or end, not both.")
    start = number(payload, "start", 0, MAX_SECONDS)
    if start >= duration:
        raise MediaToolError("start_past_end", f"start is past the end of the audio ({duration:.3f} s).")
    if "end" in payload:
        end = number(payload, "end", 0, MAX_SECONDS)
        if end <= start:
            raise MediaToolError("invalid_command", "end must be after start.")
        length = end - start
    else:
        length = number(payload, "length", 1e-3, MAX_SECONDS)
    clipped = start + length > duration + 1e-6
    return start, min(length, duration - start), clipped


def _filters(start: float, length: float, fade_in: float, fade_out: float) -> str:
    parts = [f"atrim=start={start:.6f}:duration={length:.6f}", "asetpts=PTS-STARTPTS"]
    fade_in, fade_out = min(fade_in, length / 2), min(fade_out, length / 2)
    if fade_in > 0:
        parts.append(f"afade=t=in:st=0:d={fade_in:.6f}")
    if fade_out > 0:
        parts.append(f"afade=t=out:st={max(0.0, length - fade_out):.6f}:d={fade_out:.6f}")
    return ",".join(parts)


def _codec(fmt: str, info: dict[str, Any]) -> list[str]:
    if fmt == "keep":
        return []  # the encoder ffmpeg picks for the source's extension
    return ["-c:a", info["codec"] if info["codec"] in _PCM_KEEP else "pcm_s16le"]


def _extension(fmt: str, source: str) -> str:
    if fmt == "wav":
        return ".wav"
    from services.media_paths import _KIND_EXTENSIONS
    extension = os.path.splitext(source)[1].lower()
    if extension not in _KIND_EXTENSIONS["audio"]:
        raise MediaToolError("invalid_command", "format keep needs an audio source; use wav for a video's audio.")
    return extension


def cut(source: str, destination: str, window: tuple[float, float], fades: tuple[float, float], info: dict, fmt: str) -> None:
    command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", source, "-map", "0:a:0", "-vn", "-sn", "-dn",
               "-map_metadata", "-1", "-af", _filters(*window, *fades), "-ar", str(info["sample_rate"]),
               "-ac", str(info["channels"]), *_codec(fmt, info), destination]
    try:
        result = subprocess.run(command, capture_output=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaToolError("trim_failed", "ffmpeg could not cut the audio.") from exc
    if result.returncode != 0 or not os.path.isfile(destination) or os.path.getsize(destination) <= 0:
        raise MediaToolError("trim_failed", "ffmpeg could not cut the audio.")


def run(arguments: Any, *, workspace_dir, uploads_dir) -> dict[str, Any]:
    payload = read_input(arguments, _KEYS, ("workspace", "source", "start"))
    workspace = payload["workspace"]
    folder, uploads = workspace_folder(workspace_dir, workspace), uploads_root(uploads_dir)
    source = resolve_source(payload["source"], workspace, folder, uploads, ("audio", "video"))
    fmt = payload.get("format", "wav")
    if fmt not in ("wav", "keep"):
        raise MediaToolError("invalid_command", "format must be wav or keep.")
    info = probe_audio_stream(source)
    start, length, clipped = _window(payload, info["duration"])
    fades = (number(payload, "fade_in", 0, 10, DEFAULT_FADE), number(payload, "fade_out", 0, 10, DEFAULT_FADE))
    stem = os.path.splitext(os.path.basename(source))[0][:80]
    default = f"{stem}-trim-{start:.2f}-{length:.2f}".replace(".", "_")
    with output_destination(folder, payload.get("output_name"), default, _extension(fmt, source)) as destination:
        cut(source, destination, (start, length), fades, info, fmt)
        made = probe_audio_stream(destination)
        params = {"start": round(start, 6), "length": round(length, 6), "fade_in": fades[0], "fade_out": fades[1],
                  "source_name": os.path.basename(source)}
        sidecar = publish_sidecar(destination, workspace, OPERATION, "audio", params, [source_ref(source, workspace)])
        return {"file": os.path.basename(destination), "url": media_url(destination, workspace, uploads, folder),
                "seconds": round(made["duration"], 4), "start": round(start, 6), "sample_rate": made["sample_rate"],
                "channels": made["channels"], "clipped": clipped, "sha256": sha256_file(destination), "sidecar": sidecar}

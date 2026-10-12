"""``media.frame``: save one frame of a workspace video as a PNG image asset.

``at`` is seconds, ``"first"`` or ``"last"``. The last frame is the real final
picture of the stream (decoded up to the end), not a frame a fixed margin
before the container's duration. Videos with alpha (VP9 webm from
``studio.key``) keep their transparency.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any

from services.production_media_common import (
    OUTPUT_NAME, SOURCE, WORKSPACE, MediaToolError, media_url, operation_schema, output_destination, publish_sidecar,
    read_input, remove_quietly, resolve_source, sha256_file, source_ref, uploads_root, workspace_folder,
)

OPERATION = "media.frame"
_KEYS = frozenset({"workspace", "source", "at", "output_name"})


def catalog() -> dict[str, Any]:
    return operation_schema(OPERATION, (
        "Save one frame of a workspace video as a PNG image in the workspace (instead of extracting frames with "
        "ffmpeg outside HocusPocus): at is seconds, \"first\" or \"last\" (the real final frame, e.g. the start "
        "frame for the next image-to-video shot). Keeps the video's resolution and its alpha (a keyed webm). "
        "Writes a provenance sidecar naming the source video and time. Returns file, url, width, height, time, "
        "sha256. output_name names the PNG (an existing name gets name(2).png)."
    ), {
        "workspace": WORKSPACE, "source": SOURCE,
        "at": {"anyOf": [{"type": "number", "minimum": 0, "maximum": 36000}, {"type": "string", "enum": ["first", "last"]}],
               "description": "Seconds from the start, or first / last. Default first."},
        "output_name": OUTPUT_NAME,
    }, ["workspace", "source"])


def _ffprobe(args: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(["ffprobe", "-v", "error", *args, "-of", "json"], capture_output=True, text=True,
                                timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaToolError("frame_failed", "ffprobe could not read the video.") from exc
    if result.returncode != 0:
        raise MediaToolError("frame_failed", "ffprobe could not read the video.")
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaToolError("frame_failed", "ffprobe could not read the video.") from exc


def probe(source: str) -> dict[str, Any]:
    """Size, rate, duration, codec and alpha of the first video stream."""
    from services.video_editor import probe_media
    try:
        media = probe_media(source)
    except ValueError as exc:
        raise MediaToolError("unsupported_media", str(exc)) from exc
    streams = _ffprobe(["-select_streams", "v:0", "-show_entries", "stream=codec_name", source]).get("streams") or [{}]
    return {**media, "codec": str(streams[0].get("codec_name") or "")}


def last_frame_time(source: str, duration: float) -> float:
    """The presentation time of the stream's final frame (read from the last two seconds)."""
    start = max(0.0, duration - 2.0)
    frames = _ffprobe(["-select_streams", "v:0", "-read_intervals", f"{start:.3f}%", "-show_entries",
                       "frame=pts_time,best_effort_timestamp_time", source]).get("frames") or []
    times = [float(value) for frame in frames
             for value in [frame.get("pts_time") or frame.get("best_effort_timestamp_time")] if value not in (None, "N/A")]
    return round(max(times), 6) if times else round(max(0.0, duration), 6)


def _decoder(media: dict[str, Any]) -> list[str]:
    """ffmpeg's native VP9 decoder drops alpha; libvpx keeps it."""
    if media.get("has_alpha") and media.get("codec") in ("vp9", "vp8"):
        return ["-c:v", "libvpx-vp9" if media["codec"] == "vp9" else "libvpx"]
    return []


def _ffmpeg(args: list[str]) -> None:
    try:
        result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", *args], capture_output=True, timeout=300,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaToolError("frame_failed", "ffmpeg could not read a frame.") from exc
    if result.returncode != 0:
        raise MediaToolError("frame_failed", "ffmpeg could not read a frame.")


def _capture_last(source: str, destination: str, media: dict[str, Any]) -> None:
    """Decode the last seconds and keep overwriting one PNG: what remains is the final frame."""
    back = max(1.0, 4.0 / max(float(media.get("fps") or 1.0), 1.0))
    _ffmpeg([*_decoder(media), "-sseof", f"-{back:.3f}", "-i", source, "-map", "0:v:0", "-update", "1",
             "-c:v", "png", "-pix_fmt", "rgba" if media.get("has_alpha") else "rgb24", destination])


def _capture_at(source: str, destination: str, seconds: float, media: dict[str, Any]) -> float:
    if not _decoder(media):
        from services.video_editor import extract_frame
        try:
            return float(extract_frame(source, destination, seconds)["time"])
        except (RuntimeError, ValueError) as exc:
            raise MediaToolError("frame_failed", "ffmpeg could not read a frame.") from exc
    fps = max(float(media.get("fps") or 0), 1.0)
    at = max(0.0, min(seconds, float(media["duration"]) - 2.0 / fps))
    _ffmpeg([*_decoder(media), "-i", source, "-ss", f"{at:.6f}", "-map", "0:v:0", "-frames:v", "1",
             "-c:v", "png", "-pix_fmt", "rgba", destination])
    return round(at, 6)


def _requested(payload: dict[str, Any]) -> float | str:
    at = payload.get("at", "first")
    if at in ("first", "last"):
        return at
    if isinstance(at, bool) or not isinstance(at, (int, float)) or not 0 <= float(at) <= 36000:
        raise MediaToolError("invalid_command", "at must be seconds (0 or more), \"first\" or \"last\".")
    return float(at)


def capture(source: str, destination: str, at: float | str) -> dict[str, Any]:
    """Write one frame of ``source`` to ``destination`` (PNG). Returns time, width and height."""
    media = probe(source)
    duration = float(media["duration"])
    if isinstance(at, float) and at > duration + 1e-3:
        raise MediaToolError("time_past_end", f"at is past the end of the video ({duration:.3f} s); use \"last\".")
    if at == "last":
        _capture_last(source, destination, media)
        time = last_frame_time(source, duration)
    else:
        time = _capture_at(source, destination, 0.0 if at == "first" else at, media)
    if not os.path.isfile(destination) or os.path.getsize(destination) <= 0:
        raise MediaToolError("frame_failed", "ffmpeg did not write a frame.")
    return {"time": time, "width": int(media["width"]), "height": int(media["height"])}


def capture_to_temp(source: str, at: float | str, folder: str) -> str:
    """One frame in a hidden temporary PNG in ``folder`` (for media.compose's base); the caller removes it."""
    handle, path = tempfile.mkstemp(prefix=".frame-", suffix=".png", dir=folder)
    os.close(handle)
    try:
        capture(source, path, at)
    except Exception:
        remove_quietly(path)
        raise
    return path


def requested_time(value: Any) -> float | str:
    return _requested({"at": value} if value is not None else {})


def run(arguments: Any, *, workspace_dir, uploads_dir) -> dict[str, Any]:
    payload = read_input(arguments, _KEYS, ("workspace", "source"))
    workspace = payload["workspace"]
    folder, uploads = workspace_folder(workspace_dir, workspace), uploads_root(uploads_dir)
    source = resolve_source(payload["source"], workspace, folder, uploads, ("video",))
    at = _requested(payload)
    label = at if isinstance(at, str) else f"{at:.2f}s".replace(".", "_")
    stem = os.path.splitext(os.path.basename(source))[0][:80]
    with output_destination(folder, payload.get("output_name"), f"{stem}-frame-{label}", ".png") as destination:
        found = capture(source, destination, at)
        sidecar = publish_sidecar(destination, workspace, OPERATION, "image",
                                  {"time": found["time"], "at": at, "source_name": os.path.basename(source)},
                                  [source_ref(source, workspace)])
        return {"file": os.path.basename(destination), "url": media_url(destination, workspace, uploads, folder),
                **found, "sha256": sha256_file(destination), "sidecar": sidecar}

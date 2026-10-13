"""What POST /api/v1/upload reports about an uploaded video: its frame rate, frame count, duration and audio.

``routers.uploads`` takes one of these as its ``probe_video_metadata``: the full
server probes with its own decoder, the core server (no Torch, no PyAV) asks ffprobe.
Both return the same fields, and the router ignores a probe that raises.
"""
from __future__ import annotations

from typing import Any


def probe_with_decoder(filepath: str) -> dict[str, Any]:
    """The full server's probe: its video decoder for the stream, PyAV for the audio."""
    result: dict[str, Any] = {}
    from shared.utils.video_decode import probe_video_stream_metadata
    _metadata = probe_video_stream_metadata(filepath)
    if _metadata is not None:
        _fps = float(_metadata.get("fps_float") or _metadata.get("fps") or 0)
        _frame_count = int(_metadata.get("frame_count") or 0)
        _duration = float(_metadata.get("duration") or 0)
    else:
        from shared.utils.utils import get_video_info
        _fps, _w, _h, _frame_count = get_video_info(filepath)
        _duration = float(_frame_count or 0) / float(_fps) if _fps else 0
    if _fps:
        result["fps"] = float(_fps)
        result["frame_count"] = int(_frame_count or 0)
        result["duration_seconds"] = round(_duration or (float(_frame_count or 0) / float(_fps)), 3)
    try:
        import av as _av

        with _av.open(filepath) as _container:
            result["has_audio"] = bool(_container.streams.audio)
    except Exception:
        result["has_audio"] = False
    return result


def probe_with_ffprobe(filepath: str) -> dict[str, Any]:
    """The core server's probe: ffprobe through the video editor's media probe."""
    from services.video_editor import probe_media

    facts = probe_media(filepath)
    result: dict[str, Any] = {}
    fps = float(facts.get("fps") or 0)
    duration = float(facts.get("duration") or 0)
    if fps:
        result["fps"] = fps
        result["frame_count"] = int(round(duration * fps))
        result["duration_seconds"] = round(duration, 3)
    result["has_audio"] = bool(facts.get("has_audio"))
    return result

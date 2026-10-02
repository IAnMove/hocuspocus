"""Clip inventory. Index plus asset hash selects a clip. Names do not.

Duration is max(time) - min(time). A zero-duration clip is a pose. The
default motion skips it. Playback subtracts time_start and keeps duration.
"""

from __future__ import annotations

from services.humanoid_rig.gltf_accessors import AccessorError, read_accessor


class ClipSelectError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def list_clips(document: dict, buffers: list[bytes] | None = None) -> list[dict]:
    clips = []
    for index, animation in enumerate(document.get("animations") or []):
        if not isinstance(animation, dict):
            continue
        clips.append(_summarize(document, animation, index, buffers or []))
    return clips


def select_clip(document: dict, animation_index: int, *, asset_hash: str | None = None) -> dict:
    """Select by index. Duplicate names are not a selector. A bad index fails."""
    clips = document.get("animations") or []
    if not isinstance(animation_index, int) or isinstance(animation_index, bool):
        raise ClipSelectError("invalid_animation_index")
    if animation_index < 0 or animation_index >= len(clips):
        raise ClipSelectError("invalid_animation_index")
    if not isinstance(clips[animation_index], dict):
        raise ClipSelectError("invalid_animation_index")
    summary = _summarize(document, clips[animation_index], animation_index, [])
    summary["asset_hash"] = asset_hash
    summary["selector"] = "animation_index"
    return summary


def select_by_name(clips: list[dict], name: str) -> dict:
    matches = [clip for clip in clips if clip.get("name") == name]
    if len(matches) != 1:
        raise ClipSelectError("duplicate_or_missing_name")
    return matches[0]


def default_motion_index(clips: list[dict]) -> int | None:
    """First clip with a positive duration. A leading static pose is not used."""
    for clip in clips:
        duration = clip.get("duration")
        if duration is None:
            continue
        if float(duration) > 0.0:
            return int(clip["index"])
    return None


def playback_time(clip: dict, clock: float) -> float:
    """Map a zero-based playback clock onto the clip without changing duration."""
    start = float(clip.get("time_start") or 0.0)
    duration = float(clip.get("duration") or 0.0)
    if clock < 0.0 or clock > duration:
        raise ClipSelectError("clock_outside_duration")
    return start + clock


def _summarize(document: dict, animation: dict, index: int, buffers: list[bytes]) -> dict:
    start, end, interpolations, channels, error = _span(document, animation, buffers)
    if error:
        duration = None
        static_pose = False
    elif start is None or end is None:
        duration = 0.0
        static_pose = True
    else:
        duration = float(end) - float(start)
        static_pose = duration == 0.0
    return {
        "index": index,
        "name": animation.get("name") or "",
        "duration": duration,
        "time_start": 0.0 if start is None else float(start),
        "interpolations": sorted(interpolations),
        "channel_count": channels,
        "static_pose": static_pose,
        "unreadable": bool(error),
        "error": error,
    }


def _span(document, animation, buffers: list[bytes]):
    start = None
    end = None
    kinds: set[str] = set()
    count = 0
    error = None
    samplers = animation.get("samplers") or []
    for channel in animation.get("channels") or []:
        count += 1
        sampler = _sampler(samplers, channel)
        if sampler is None:
            continue
        kinds.add(sampler.get("interpolation") or "LINEAR")
        low, high, problem = _sampler_times(document, sampler, buffers)
        if problem and error is None:
            error = problem
        if low is None:
            continue
        start = low if start is None else min(start, low)
        end = high if end is None else max(end, high)
    return start, end, kinds, count, error


def _sampler(samplers, channel) -> dict | None:
    index = channel.get("sampler")
    if not isinstance(index, int) or index < 0 or index >= len(samplers):
        return None
    sampler = samplers[index]
    return sampler if isinstance(sampler, dict) else None


def _sampler_times(document, sampler, buffers: list[bytes]):
    index = sampler.get("input")
    if not isinstance(index, int) or isinstance(index, bool):
        return None, None, None
    accessors = document.get("accessors") or []
    accessor = accessors[index] if 0 <= index < len(accessors) else None
    if isinstance(accessor, dict) and "min" in accessor and "max" in accessor:
        return float(accessor["min"][0]), float(accessor["max"][0]), None
    if not buffers:
        return None, None, None
    try:
        times = read_accessor(document, index, buffers)
    except AccessorError as exc:
        return None, None, exc.reason
    if len(times) == 0:
        return None, None, "empty_channel"
    return float(times.min()), float(times.max()), None

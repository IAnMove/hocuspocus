"""Per-shot joins for a Series episode (``shot.transitionIn``).

``cut`` and a missing field leave the montage on the freeze-tail dissolve
(``mix_concat``): the filter list is that helper's, so an episode that never
names a transition is unchanged. ``dissolve`` overlaps picture and sound and
shortens the cut. ``fade_black`` and ``dip_white`` fade the outgoing end and
the incoming start and do not overlap, so the episode keeps the sum of the
shot lengths (#903). The first shot's ``transitionIn`` has nothing to join
from and is ignored.
"""
from __future__ import annotations

from typing import Any, Sequence

from services.mix_concat import (
    FADE_SEC,
    HOLD_TAIL_SEC,
    _audio_pad_filter,
    build_hold_crossfade_filter,
    hold_crossfade_output_seconds,
)

KINDS = ("cut", "fade_black", "dissolve", "dip_white")
_ACTIVE = frozenset({"fade_black", "dissolve", "dip_white"})
_TAIL = 0.05


def normalize_transition(value: Any) -> dict[str, Any] | None:
    """A stored ``{kind, seconds}``, or None for a cut, null or a missing field."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("transitionIn must be an object with kind and seconds")
    kind = value.get("kind", "cut")
    if kind == "cut":
        return None
    if kind not in _ACTIVE:
        raise ValueError("transitionIn.kind must be cut, fade_black, dissolve or dip_white")
    return {"kind": kind, "seconds": _seconds(value.get("seconds"))}


def _seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("transitionIn.seconds must be a number from 0.2 to 2")
    seconds = float(value)
    if seconds < 0.2 or seconds > 2:
        raise ValueError("transitionIn.seconds must be a number from 0.2 to 2")
    return round(seconds, 3)


def _kind(item: Any) -> str:
    if not isinstance(item, dict):
        return "cut"
    kind = item.get("kind") or "cut"
    return kind if kind in _ACTIVE else "cut"


def _at(transitions: Sequence[Any] | None, index: int) -> Any:
    if not transitions or index >= len(transitions):
        return None
    return transitions[index]


def any_active(transitions: Sequence[Any] | None) -> bool:
    """True when a shot after the first asks for a fade or a dissolve."""
    return any(_kind(item) in _ACTIVE for item in list(transitions or [])[1:])


def _fit(seconds: float, left: float, right: float) -> float:
    """A fade may not eat either clip; leave about a frame of picture."""
    room = min(float(left), float(right)) - _TAIL
    if room <= 0:
        return 0.0
    return min(float(seconds), room)


def _walk(durations: Sequence[float], transitions: Sequence[Any] | None):
    """Each clip as ``(length, kind, overlap)``. Overlap is how early a dissolve starts."""
    previous = 0.0
    for index, duration in enumerate(durations):
        length = float(duration)
        kind, overlap = "cut", 0.0
        if index:
            kind = _kind(_at(transitions, index))
            if kind == "dissolve":
                overlap = _fit(_seconds_of(_at(transitions, index)), previous, length)
                if overlap <= 0:
                    kind = "cut"
        yield length, kind, overlap
        previous = length


def _seconds_of(item: Any) -> float:
    try:
        return float(item.get("seconds"))
    except (AttributeError, TypeError, ValueError):
        return 0.5


def output_seconds(durations: Sequence[float], transitions: Sequence[Any] | None = None) -> float:
    """Joined length. No active transition keeps the freeze-tail dissolve's length."""
    if not durations:
        return 0.0
    if not any_active(transitions):
        return hold_crossfade_output_seconds(durations)
    total = 0.0
    for length, kind, overlap in _walk(durations, transitions):
        total += length - (overlap if kind == "dissolve" else 0.0)
    return total


def placed_offsets(durations: Sequence[float], transitions: Sequence[Any] | None = None) -> list[float]:
    """Where each clip's first frame starts once a fade or dissolve is in the join."""
    offsets, elapsed = [], 0.0
    for length, kind, overlap in _walk(durations, transitions):
        start = elapsed - overlap
        offsets.append(start)
        elapsed = start + length
    return offsets


def placed_spans(durations: Sequence[float], transitions: Sequence[Any] | None = None) -> list[tuple[float, float]]:
    """``(start, end)`` of each clip on that timeline. A dissolve overlaps the next clip."""
    offsets = placed_offsets(durations, transitions)
    return [(start, start + float(duration)) for start, duration in zip(offsets, durations)]


def join_arguments(transitions: Sequence[Any] | None, *, abort_callback=None, supports_abort: bool = False) -> dict[str, Any]:
    """Keyword arguments for ``concatenate_clips``. Omit ``transitions`` unless one is active, so a
    join with none is the same call as before."""
    kwargs: dict[str, Any] = {}
    if supports_abort:
        kwargs["abort_callback"] = abort_callback
    if any_active(transitions):
        kwargs["transitions"] = list(transitions or [])
    return kwargs


def _flags(count: int, with_audio: bool, has_audio: Sequence[bool] | None) -> list[bool] | None:
    if not with_audio:
        return None
    if has_audio is None:
        return [True] * count
    if len(has_audio) != count:
        raise ValueError("has_audio length must match durations")
    flags = [bool(flag) for flag in has_audio]
    return flags if any(flags) else None


def _video(index: int, duration: float) -> str:
    return (f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS,trim=end={duration:.6f},"
            f"setpts=PTS-STARTPTS[v{index}]")


def filter_for(
    durations: Sequence[float],
    *,
    transitions: Sequence[Any] | None = None,
    hold_sec: float = HOLD_TAIL_SEC,
    fade_sec: float = FADE_SEC,
    with_audio: bool = True,
    has_audio: Sequence[bool] | None = None,
) -> tuple[str, str, str | None]:
    """The filter list, its video label and its audio label.

    With no active transition this is ``build_hold_crossfade_filter``, byte for byte.
    """
    if not any_active(transitions):
        return build_hold_crossfade_filter(
            durations, hold_sec=hold_sec, fade_sec=fade_sec, with_audio=with_audio, has_audio=has_audio,
        )
    return _active_filter(durations, transitions, with_audio=with_audio, has_audio=has_audio)


def _active_filter(durations, transitions, *, with_audio: bool, has_audio) -> tuple[str, str, str | None]:
    count = len(durations)
    if count < 2:
        raise ValueError("need at least two clip durations")
    flags = _flags(count, with_audio, has_audio)
    lengths = [max(0.1, float(duration)) for duration in durations]
    plan = list(_walk(lengths, transitions))
    parts = [_prepared(index, length, flags) for index, length in enumerate(lengths)]
    video, audio, elapsed = "v0", ("a0" if flags is not None else None), lengths[0]
    for index in range(1, count):
        _length, kind, overlap = plan[index]
        video, audio, elapsed, extra = _join(
            video, audio, elapsed, index, lengths[index], kind, overlap, _at(transitions, index), flags is not None,
        )
        parts.append(extra)
    return ";".join(parts), video, audio


def _prepared(index: int, length: float, flags: list[bool] | None) -> str:
    video = _video(index, length)
    if flags is None:
        return video
    return video + ";" + _audio_pad_filter(index, length, flags[index])


def _join(video, audio, elapsed, index, length, kind, overlap, item, mix: bool):
    if kind == "dissolve" and overlap > 0:
        return _dissolve(video, audio, elapsed, index, length, overlap, mix)
    if kind in ("fade_black", "dip_white"):
        seconds = _fit(_seconds_of(item), elapsed, length)
        if seconds > 0:
            color = "white" if kind == "dip_white" else "black"
            return _dip(video, audio, elapsed, index, length, seconds, color, mix)
    return _cut(video, audio, elapsed, index, length, mix)


def _cut(video, audio, elapsed, index, length, mix: bool):
    video_label, audio_label = f"vx{index}", f"ax{index}"
    if mix:
        return video_label, audio_label, elapsed + length, (
            f"[{video}][{audio}][v{index}][a{index}]concat=n=2:v=1:a=1[{video_label}][{audio_label}]"
        )
    return video_label, None, elapsed + length, f"[{video}][v{index}]concat=n=2:v=1:a=0[{video_label}]"


def _dissolve(video, audio, elapsed, index, length, seconds, mix: bool):
    video_label, audio_label = f"vx{index}", f"ax{index}"
    offset = max(0.0, elapsed - seconds)
    parts = [
        f"[{video}]settb=AVTB,setpts=PTS-STARTPTS[vb{index}]",
        f"[vb{index}][v{index}]xfade=transition=fade:duration={seconds:.3f}:offset={offset:.3f}[{video_label}]",
    ]
    if mix:
        parts.append(f"[{audio}][a{index}]acrossfade=d={seconds:.6f}[{audio_label}]")
        return video_label, audio_label, elapsed + length - seconds, ";".join(parts)
    return video_label, None, elapsed + length - seconds, ";".join(parts)


def _dip(video, audio, elapsed, index, length, seconds, color: str, mix: bool):
    video_label, audio_label = f"vx{index}", f"ax{index}"
    start = max(0.0, elapsed - seconds)
    parts = [
        f"[{video}]fade=t=out:st={start:.3f}:d={seconds:.3f}:color={color}[vf{index}]",
        f"[v{index}]fade=t=in:st=0:d={seconds:.3f}:color={color}[vi{index}]",
    ]
    if mix:
        parts.append(f"[{audio}]afade=t=out:st={start:.3f}:d={seconds:.3f}[af{index}]")
        parts.append(f"[a{index}]afade=t=in:st=0:d={seconds:.3f}[ai{index}]")
        parts.append(
            f"[vf{index}][af{index}][vi{index}][ai{index}]concat=n=2:v=1:a=1[{video_label}][{audio_label}]"
        )
        return video_label, audio_label, elapsed + length, ";".join(parts)
    parts.append(f"[vf{index}][vi{index}]concat=n=2:v=1:a=0[{video_label}]")
    return video_label, None, elapsed + length, ";".join(parts)

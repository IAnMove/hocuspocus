"""Per-shot joins for a Series episode (``shot.transitionIn``).

``cut`` and a missing field are the freeze-tail dissolve (``mix_concat``): the
outgoing clip holds its last frame and dissolves into the next. That stays so
beside a join that names a transition, and an episode that never names one gets
that helper's filter list. ``dissolve`` overlaps picture and sound and shortens
the cut. ``fade_black`` and ``dip_white`` fade the outgoing end and the incoming
start and do not overlap. A clip that one of these three follows ends on its own
last frame, without the held tail; the episode's last clip keeps it, as in a
join without transitions (#903). The first shot's ``transitionIn`` has nothing
to join from and is ignored.
"""
from __future__ import annotations

from typing import Any, NamedTuple, Sequence

from services.mix_concat import (
    FADE_SEC,
    HOLD_TAIL_SEC,
    _audio_pad_filter,
    build_hold_crossfade_filter,
    held_video_filter,
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


class _Clip(NamedTuple):
    length: float   # the clip's own pictures
    played: float   # with its held tail, when a cut follows it or it ends the episode
    kind: str       # how it joins from the clip before
    seconds: float  # that join's dissolve (a cut's is mix_concat's) or fade
    start: float    # where its first frame is on the joined timeline


def _kinds(lengths: Sequence[float], transitions: Sequence[Any] | None) -> list[tuple[str, float]]:
    """Each clip's join from the one before as ``(kind, seconds asked)``. A dissolve with no room is a cut."""
    kinds = [("cut", 0.0)]
    for index in range(1, len(lengths)):
        item = _at(transitions, index)
        kind = _kind(item)
        if kind == "dissolve":
            overlap = _fit(_seconds_of(item), lengths[index - 1], lengths[index])
            kinds.append(("dissolve", overlap) if overlap > 0 else ("cut", 0.0))
        else:
            kinds.append((kind, _seconds_of(item)))
    return kinds


def _plan(durations: Sequence[float], transitions: Sequence[Any] | None,
          hold_sec: float = HOLD_TAIL_SEC, fade_sec: float = FADE_SEC) -> tuple[list[_Clip], float]:
    """Every clip on the joined timeline, and its length. The filter and the finishing steps both read this."""
    lengths = [max(0.1, float(duration)) for duration in durations]
    kinds = _kinds(lengths, transitions)
    count = len(lengths)
    played = [length + (float(hold_sec) if count > 1 and (index + 1 == count or kinds[index + 1][0] == "cut") else 0.0)
              for index, length in enumerate(lengths)]
    clips, elapsed = [], played[0] if count else 0.0
    for index, (length, (kind, seconds)) in enumerate(zip(lengths, kinds)):
        if not index:
            clips.append(_Clip(length, played[0], kind, 0.0, 0.0))
            continue
        if kind == "cut":
            # mix_concat's pair fade and offset, so a cut is the join an episode without transitions has.
            seconds = min(float(fade_sec), float(hold_sec), played[index - 1] * 0.4, played[index] * 0.4)
            start = max(0.05, elapsed - seconds)
        elif kind == "dissolve":
            start = elapsed - seconds
        else:
            seconds, start = _fit(seconds, elapsed, length), elapsed
        clips.append(_Clip(length, played[index], kind, seconds, start))
        elapsed += played[index] - (seconds if kind in ("cut", "dissolve") else 0.0)
    return clips, elapsed


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
    return _plan(durations, transitions)[1]


def placed_offsets(durations: Sequence[float], transitions: Sequence[Any] | None = None) -> list[float]:
    """Where each clip's first frame starts once a fade or dissolve is in the join."""
    return [clip.start for clip in _plan(durations, transitions)[0]]


def placed_spans(durations: Sequence[float], transitions: Sequence[Any] | None = None) -> list[tuple[float, float]]:
    """``(start, end)`` of each clip on that timeline, with its held tail. A cut or a dissolve overlaps the next
    clip."""
    return [(clip.start, clip.start + clip.played) for clip in _plan(durations, transitions)[0]]


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
    return _active_filter(durations, transitions, hold_sec=hold_sec, fade_sec=fade_sec,
                          with_audio=with_audio, has_audio=has_audio)


def _active_filter(durations, transitions, *, hold_sec: float, fade_sec: float, with_audio: bool,
                   has_audio) -> tuple[str, str, str | None]:
    count = len(durations)
    if count < 2:
        raise ValueError("need at least two clip durations")
    flags = _flags(count, with_audio, has_audio)
    clips, _length = _plan(durations, transitions, hold_sec, fade_sec)
    parts = [_prepared(index, clip, hold_sec, flags) for index, clip in enumerate(clips)]
    video, audio = "v0", ("a0" if flags is not None else None)
    for index in range(1, count):
        video, audio, extra = _join(video, audio, index, clips[index], flags is not None)
        parts.append(extra)
    return ";".join(parts), video, audio


def _prepared(index: int, clip: _Clip, hold_sec: float, flags: list[bool] | None) -> str:
    video = held_video_filter(index, clip.played, hold_sec) if clip.played > clip.length else _video(index, clip.length)
    if flags is None:
        return video
    return video + ";" + _audio_pad_filter(index, clip.played, flags[index])


def _join(video, audio, index: int, clip: _Clip, mix: bool):
    if clip.kind in ("cut", "dissolve"):
        return _dissolve(video, audio, index, clip.start, clip.seconds, mix)
    if clip.seconds > 0:
        color = "white" if clip.kind == "dip_white" else "black"
        return _dip(video, audio, index, clip.start, clip.seconds, color, mix)
    return _concat(video, audio, index, mix)


def _concat(video, audio, index, mix: bool):
    video_label, audio_label = f"vx{index}", f"ax{index}"
    if mix:
        return video_label, audio_label, (
            f"[{video}][{audio}][v{index}][a{index}]concat=n=2:v=1:a=1[{video_label}][{audio_label}]"
        )
    return video_label, None, f"[{video}][v{index}]concat=n=2:v=1:a=0[{video_label}]"


def _dissolve(video, audio, index, offset, seconds, mix: bool):
    """The incoming clip from ``offset``, over the last ``seconds`` of the outgoing one (its held tail for a cut)."""
    video_label, audio_label = f"vx{index}", f"ax{index}"
    parts = [
        f"[{video}]settb=AVTB,setpts=PTS-STARTPTS[vb{index}]",
        f"[vb{index}][v{index}]xfade=transition=fade:duration={seconds:.3f}:offset={offset:.3f}[{video_label}]",
    ]
    if mix:
        parts.append(f"[{audio}][a{index}]acrossfade=d={seconds:.6f}[{audio_label}]")
        return video_label, audio_label, ";".join(parts)
    return video_label, None, ";".join(parts)


def _dip(video, audio, index, elapsed, seconds, color: str, mix: bool):
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
        return video_label, audio_label, ";".join(parts)
    parts.append(f"[vf{index}][vi{index}]concat=n=2:v=1:a=0[{video_label}]")
    return video_label, None, ";".join(parts)

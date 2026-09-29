"""When a music-video shot stops spending lip-sync takes.

Stop rule: once a shot has a kept ``best_r``, the next measured ``best_r``
must be strictly greater or that shot stops. The first measured ``r`` does
not stop it. A verdict other than ``retake`` still stops, and so does this
run's ``max_takes``. A failed output has no ``best_r`` and does not trip
the flat-r stop.

Automatic shooting also stops at ``RECORDED_CAP`` (4) recorded takes. A key
listed in ``retake`` may be shot again; the same ``best_r`` rule still
applies. ``state["clip_seconds"]`` stores generation seconds per shot. The
backoff after a fully failed round is not included.
"""
from __future__ import annotations

RECORDED_CAP = 4


def recorded_takes(state: dict, key: str) -> int:
    """Takes already on the shot: ``clip_takes`` when the key is set, else the log."""
    tried = state.get("clip_takes") or {}
    if key in tried:
        return int(tried[key])
    prefix = f"clip {key} take "
    return sum(1 for line in state.get("log") or [] if isinstance(line, str) and line.startswith(prefix))


def pending_windows(windows: list[dict], state: dict, retake: tuple[str, ...] | list[str]) -> list[dict]:
    """H3 shots that still need a clip, skipping automatic shots already at the cap."""
    frames = state.get("frames") or {}
    clips = state.get("clips") or {}
    listed = set(retake)
    pending: list[dict] = []
    for window in windows:
        key = window.get("key")
        if window.get("kind") != "h3" or key not in frames:
            continue
        if key in listed or (key not in clips and recorded_takes(state, key) < RECORDED_CAP):
            pending.append(window)
    return pending


def take_settled(qa: dict, previous_r: float | None) -> bool:
    """True when this take should be the last one for the shot."""
    if qa.get("verdict") != "retake":
        return True
    score = qa.get("best_r")
    if previous_r is None or score is None:
        return False
    return float(score) <= float(previous_r)


def another_take(settled: bool, tried: int, budget: int, explicit: bool) -> bool:
    """Whether this run should queue the shot for another take."""
    if settled or tried >= budget:
        return False
    return explicit or tried < RECORDED_CAP


def note_seconds(state: dict, windows: list[dict], elapsed: float) -> None:
    """Add this round's generation seconds onto each shot that was in it."""
    seconds = state.setdefault("clip_seconds", {})
    for window in windows:
        key = window["key"]
        seconds[key] = round(float(seconds.get(key) or 0) + float(elapsed), 3)

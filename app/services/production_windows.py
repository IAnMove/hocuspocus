"""Shot windows and scene cuts. ``music_production`` re-exports both names."""
from __future__ import annotations

from typing import Callable

from services.production_frame_clock import align_native_cuts
from services.production_shot_plan import is_auto_pad, place_pads


def _host():
    import services.music_production as host
    return host


def shot_windows(spec: dict, score: dict) -> list[dict]:
    lines = score.get("lines") or []
    try:
        duration = float(score.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    out = []
    for index, shot in enumerate(spec["shots"]):
        if is_auto_pad(shot):
            continue
        line = lines[shot["line"]] if isinstance(shot.get("line"), int) and 0 <= shot["line"] < len(lines) else None
        if "t0" in shot:
            t0 = float(shot["t0"])
        elif line:
            t0 = line["t0"] - 0.25
        elif isinstance(shot.get("after"), int) and 0 <= shot["after"] < len(lines):
            t0 = lines[shot["after"]]["t1"] + 0.3
        else:
            t0 = 0.0
        # an `after` card uses last.t1 + 0.3; when the last lyric ends at the song
        # end that start is past duration and segments() drops it (b - a <= 0).
        if duration > 0 and t0 >= duration:
            t0 = max(0.0, duration - 4.0)
        if line:
            last = lines[min(len(lines) - 1, shot["line"] + shot.get("span", 1) - 1)]
            t1 = last["t1"] + 0.2
        elif "t1" in shot:
            try:
                t1 = float(shot["t1"])
            except (TypeError, ValueError):
                t1 = t0 + 4
        else:
            t1 = t0 + 4                       # untitled cards; a trailer bakes t1 so a held beat is not 4 s
        out.append({**shot, "i": index, "t0": round(max(0.0, t0), 3), "t1": round(t1, 3)})
    try:
        bpm = float(score.get("bpm") or 120) or 120.0
    except (TypeError, ValueError):
        bpm = 120.0
    shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
    if spec.get("auto_pads") or any(is_auto_pad(shot) for shot in shots):
        return place_pads(out, spec, duration, bpm)
    return out


def segments(windows: list[dict], score: dict, clip_ok: Callable[[str], bool], fill: list[dict]) -> list[tuple[dict, float, float]]:
    """Scene cuts; an h3 shot longer than its clip is cut at the clip end and the rest filled on bar lines."""
    cuts = [w["t0"] for w in windows] + [float(score["duration"])]
    cuts[0] = 0.0
    bar = 4 * float(score.get("beat") or 0.5)
    out, used = [], 0
    for n, shot in enumerate(windows):
        a, b = cuts[n], cuts[n + 1]
        if shot["kind"] == "h3" and clip_ok(shot["key"]) and fill:
            length = _host().h3_frames_for(shot["t1"] - shot["t0"]) / 24 - max(0.0, a - shot["t0"])
            if b - a > length + 0.3:
                out.append((shot, a, a + length))
                t, k = a + length, 0
                while t < b - 0.05:
                    item = fill[used % len(fill)]
                    used += 1
                    end = min(b, t + 2 * bar)
                    out.append(({**item, "key": f"{shot['key']}_fill{k}"}, t, end))
                    t, k = end, k + 1
                continue
        if b - a > 0.05:
            out.append((shot, a, b))
    return align_native_cuts(out)

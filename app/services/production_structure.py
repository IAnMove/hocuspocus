"""Two ways to compile a production: a clip and a trailer.

A music video follows a song: verses and choruses, motifs that come back, a singer when one is worth showing.
A trailer does not: it presents, builds tension, escalates, reveals and closes, and it is made as much of silence,
hits and risers as of pictures. Forcing both through the same verse/chorus alternation makes every result look alike.

``spec.structure`` is ``"clip"`` (the default: nothing changes) or ``"trailer"``. With ``shots: "auto"`` a trailer is
planned on time, not on lyric lines: five beats that share the duration (presentation 14 %, tension 28 %,
escalation 30 %, reveal 16 %, close 12 %) snapped to bars, long held shots in the quiet beats, quick cuts that
accelerate in the escalation, one hit for the reveal. The GPU makes the big shots; the quick cuts of the escalation
re-frame clips that already exist (``kind: "clip"`` with a different camera each), so a trailer is not thirty clips.
Sound is designed in production_trailer_audio (silence before the reveal, riser, impact).
"""
from __future__ import annotations

from typing import Any

from services.production_treatment import TRAILER_BEATS, moments_of, require_treatment

STRUCTURES = ("clip", "trailer")
BEAT_SHARE = {"presentation": 0.14, "tension": 0.28, "escalation": 0.30, "reveal": 0.16, "close": 0.12}
MIN_H3_S = 4.0            # a generated shot shorter than this wastes most of the 5 s a clip costs
_CUT_RATIO = 0.88         # each escalation cut is this much shorter than the one before
_CAMERAS = ("camera-whip-pan", "camera-push-in", "camera-pan-right", "camera-crane-up", "camera-pull-out", "camera-pan-left")
_ACTIONS = {
    "presentation": "Slow establishing shot of the world, calm and inviting: {phrase}. Slow push in.",
    "tension": "Quiet and tense, something is about to happen: {phrase}. Slow, controlled camera.",
    "reveal": "The reveal: {phrase}. Maximum scale, light and motion, the camera pulls back.",
    "close": "The aftermath, calm and still: {phrase}. The camera holds and slowly retreats.",
}


def require_structure(spec: dict) -> dict:
    structure = spec.get("structure")
    if structure is not None and structure not in STRUCTURES:
        from services.music_production import ProductionError
        raise ProductionError("invalid_spec", f"structure must be one of {', '.join(STRUCTURES)}")
    return spec


def require_direction(spec: dict) -> dict:
    """validate_spec hook: structure and treatment, both optional, both checked."""
    return require_treatment(require_structure(spec))


# ---------------------------------------------------------------- the beats
def beat_plan(duration: float, bpm: float) -> list[dict]:
    """The five beats as [start, end) in seconds; inner boundaries snap to a bar so a cut lands on the music."""
    bar = 240.0 / (bpm if bpm and bpm > 0 else 120.0)
    duration = float(duration)
    n = len(TRAILER_BEATS)
    # A full bar between beats only when the song can hold one bar per beat. A 16 s
    # trailer at 60 BPM is 4 bars: forcing +bar / duration-bar then clamps reveal to 0.
    step = bar if duration + 1e-9 >= n * bar else max(0.05, duration / (2 * n))
    edges = [0.0]
    cursor = 0.0
    remaining = n - 1
    for name in TRAILER_BEATS[:-1]:
        remaining -= 1
        cursor += duration * BEAT_SHARE[name]
        snapped = round(cursor / bar) * bar if 0 < bar < duration / 10 else cursor
        low = edges[-1] + step
        high = duration - remaining * step
        edges.append(round(min(max(snapped, low), max(low, high)), 3))
    edges.append(round(duration, 3))
    return [{"beat": name, "start": edges[i], "end": edges[i + 1]} for i, name in enumerate(TRAILER_BEATS)]


def cut_lengths(total: float, count: int, ratio: float = _CUT_RATIO) -> list[float]:
    """``count`` cuts that add up to ``total`` and get shorter by ``ratio`` each time."""
    weights = [ratio ** index for index in range(count)]
    scale = total / sum(weights)
    return [round(weight * scale, 3) for weight in weights]


def _even(total: float, count: int) -> list[float]:
    return [round(total / count, 3)] * count


# ---------------------------------------------------------------- the shots
def _phrases(spec: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Event text and moment id per beat, from the treatment's moments that land on a beat."""
    events: dict[str, str] = {}
    ids: dict[str, str] = {}
    for moment in moments_of(spec):
        if isinstance(moment["lines"], str) and moment["lines"] not in events:
            events[moment["lines"]] = moment["event"]
            ids[moment["lines"]] = moment["id"]
    return events, ids


def plan_trailer(spec: dict, look: dict, title: str) -> list[dict]:
    """The shots of a trailer, each with baked ``t0``/``t1`` and its ``beat``. ``look`` is production_shot_plan's look."""
    from services import production_shot_plan as plan

    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    beats = beat_plan(float(song.get("duration") or 60), float(song.get("bpm") or 120))
    events, ids = _phrases(spec)
    shots: list[dict] = []
    big: list[str] = []         # the generated shots the quick cuts re-frame
    for entry in beats:
        for shot in _beat_shots(entry, look, title, spec, events.get(entry["beat"]), big, plan):
            shot["beat"] = entry["beat"]
            if entry["beat"] in ids and not any(s.get("moment") == ids[entry["beat"]] for s in shots):
                shot["moment"] = ids[entry["beat"]]
            shots.append(shot)
    return shots


def _beat_shots(entry: dict, look: dict, title: str, spec: dict, event: str | None, big: list[str], plan: Any) -> list[dict]:
    beat, start, length = entry["beat"], entry["start"], entry["end"] - entry["start"]
    phrase = event or look["phrase"]
    if beat == "escalation":
        return _cuts(start, length, look, big, plan)
    count = 1 if beat != "tension" else max(1, int(length // (MIN_H3_S + 2)))
    lengths = _even(length, count)
    shots = []
    cursor = start
    for index, span in enumerate(lengths):
        key = {"presentation": "open", "tension": f"t{index + 1}", "reveal": "reveal", "close": "close"}[beat]
        shot: dict[str, Any] = {"key": key, "kind": look["kind"], "t0": round(cursor, 3),
                                "t1": round(cursor + span, 3), "sing": False}
        plan._paint(shot, look)
        if shot["kind"] == "h3":
            shot["action"] = _ACTIONS[beat].format(phrase=phrase) + plan._alone(look["cast"])
            big.append(key)
        if beat == "presentation":
            shot["title"] = {"template": "end-card", "fields": {"title": title, "cta": look["cta"]}}
        if beat == "close":
            shot["title"] = {"template": "end-card", "fields": {"title": title, "cta": look["cta"]}}
        shots.append(shot)
        cursor += span
    return shots


def _cuts(start: float, length: float, look: dict, big: list[str], plan: Any) -> list[dict]:
    count = max(3, round(length / 2.5))
    shots = []
    cursor = start
    for index, span in enumerate(cut_lengths(length, count)):
        key = f"e{index + 1}"
        if look["kind"] == "h3" and big:
            shot: dict[str, Any] = {"key": key, "kind": "clip", "clip": big[index % len(big)], "camera": _CAMERAS[index % len(_CAMERAS)]}
        else:
            shot = {"key": key, "kind": look["kind"]}
            plan._paint(shot, look)
            plan._vary(shot, look, 2, index)           # the same picture re-framed: layout, workspace or zoom
        shot.update(t0=round(cursor, 3), t1=round(cursor + span, 3), sing=False)
        shots.append(shot)
        cursor += span
    return shots

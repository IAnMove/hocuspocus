"""Check a production spec before any GPU or MCP work.

``dry_run`` lists shot windows, H3 frame counts, lyric lines no shot covers,
instrumental gaps with no fill, titles over 12 characters, captions over 32,
an estimated minute count, and ``motion`` (seconds and share of the runtime on still
images, the longest hold) with warnings for a static video, a long hold, a still used
three times, ``max_takes`` 1 and fewer than three song seeds. It never calls the client passed as ``mcp``.
``shots: "auto"`` expands through ``services.production_shot_plan.plan_shots``.
"""
from __future__ import annotations

from typing import Any

from services.music_production import h3_frames_for, shot_windows
from services.production_quality import expand_quality, profile_of
from services.production_style_presets import expand_style_preset
from services.song_analysis import lyric_lines

TITLE_LIMIT = 12
CAPTION_LIMIT = 32
_TITLE_FIELDS = ("title", "date", "line")
_CAPTION_FIELDS = ("caption", "sub", "cta")
# Runbook: about 25–35 min for 5 H3 shots. Three song seeds and five shots land near 32.
_MINUTES_PER_SEED = 2
_MINUTES_PER_H3 = 5
_MINUTES_TAIL = 1
# What made the last long videos look thin: 160-178 s songs with 9-10 clips left 43-56 % of the runtime on stills.
LONG_SHOT_S = 10.0
REUSED_STILL = 3
MIN_SONG_SEEDS = 3


def dry_run(spec: Any, mcp: Any = None) -> dict[str, Any]:
    """Report the spec. ``mcp`` is accepted so tests can pass a spy and is never called."""
    _ = mcp
    spec = spec if isinstance(spec, dict) else {}
    spec, expanded, pending = _expand_shots(spec)
    shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
    usable = [shot for shot in shots if isinstance(shot, dict)]
    score = _score(spec)
    windows = shot_windows({**spec, "shots": usable}, score) if expanded else []
    rows = _rows(windows)
    texts = [line["text"] for line in score["lines"]]
    missing = _uncovered(texts, usable)
    gaps = _gaps(windows, float(score["duration"]), spec.get("fill") or [])
    motion = _motion(windows, float(score["duration"]))
    titles = _spec_title(spec) + _field_hits(usable, _TITLE_FIELDS, TITLE_LIMIT)
    captions = _song_caption(spec) + _field_hits(usable, _CAPTION_FIELDS, CAPTION_LIMIT) + _lyric_captions(texts)
    return {
        "dry_run": True,
        "running": False,
        "expanded": expanded,
        "shots": spec.get("shots") if not expanded else "expanded",
        "windows": rows,
        "h3_frames": sum(row["frames"] for row in rows if "frames" in row),
        "lines_without_shot": missing,
        "gaps": gaps,
        "long_titles": titles,
        "long_captions": captions,
        "minutes": _minutes(spec, sum(1 for row in rows if row.get("kind") == "h3")),
        "motion": motion,
        "warnings": pending + _warnings(missing, gaps, titles, captions) + _quality_warnings(spec, usable, motion),
    }


def _expand_shots(spec: dict) -> tuple[dict, bool, list[dict]]:
    """Expand ``shots: "auto"``. ImportError leaves the value unexpanded."""
    if spec.get("shots") != "auto":
        return spec, isinstance(spec.get("shots"), list), []
    try:
        from services.production_shot_plan import plan_shots
    except ImportError:
        return spec, False, [{"code": "shots_auto_unavailable"}]
    planned = plan_shots(expand_quality(expand_style_preset(spec)))
    if isinstance(planned, list):
        planned = {**spec, "shots": planned}
    if not isinstance(planned, dict):
        return spec, False, [{"code": "shots_auto_unavailable"}]
    merged = {**spec, **planned}
    return merged, isinstance(merged.get("shots"), list), []


def _score(spec: dict) -> dict[str, Any]:
    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    duration = max(0.0, float(song.get("duration") or 0))
    bpm = float(song.get("bpm") or 120) or 120.0
    return {"duration": duration, "beat": 60.0 / bpm, "bpm": bpm,
            "lines": _place(lyric_lines(str(song.get("lyrics") or "")), duration)}


def _place(texts: list[str], duration: float) -> list[dict]:
    if not texts or duration <= 0:
        return []
    slot = duration / len(texts)
    placed = []
    for index, text in enumerate(texts):
        t0 = round(index * slot, 3)
        placed.append({"t0": t0, "t1": round(min(duration, t0 + slot * 0.85), 3), "text": text})
    return placed


def _rows(windows: list[dict]) -> list[dict]:
    rows = []
    for shot in windows:
        row = {"key": shot.get("key"), "kind": shot.get("kind"), "t0": shot["t0"], "t1": shot["t1"]}
        if shot.get("kind") == "h3":
            row["frames"] = h3_frames_for(max(0.0, shot["t1"] - shot["t0"]))
        rows.append(row)
    return rows


def _covered(shots: list[dict]) -> set[int]:
    covered: set[int] = set()
    for shot in shots:
        if not isinstance(shot.get("line"), int):
            continue
        span = shot.get("span", 1)
        width = span if isinstance(span, int) and span > 0 else 1
        covered.update(range(shot["line"], shot["line"] + width))
    return covered


def _uncovered(texts: list[str], shots: list[dict]) -> list[dict]:
    covered = _covered(shots)
    return [{"index": index, "text": text} for index, text in enumerate(texts) if index not in covered]


def _gaps(windows: list[dict], duration: float, fill: Any) -> list[dict]:
    """Tails an H3 clip cannot cover when the spec has no fill. Stills have no clip limit."""
    if fill:
        return []
    if not windows:
        return [{"t0": 0.0, "t1": round(duration, 3)}] if duration > 0 else []
    cuts = [shot["t0"] for shot in windows]
    cuts[0] = 0.0
    cuts.append(float(duration))
    gaps = []
    for index, shot in enumerate(windows):
        if shot.get("kind") != "h3":
            continue
        start, end = cuts[index], cuts[index + 1]
        clip = h3_frames_for(max(0.0, shot["t1"] - shot["t0"])) / 24 - max(0.0, start - shot["t0"])
        if end - start > clip + 0.3:
            gaps.append({"key": shot.get("key"), "t0": round(start + max(clip, 0.0), 3), "t1": round(end, 3)})
    return gaps


def _motion(windows: list[dict], duration: float) -> dict[str, Any]:
    """How long the picture stands still. A still image (Ken Burns at best) is static; clips and the native desktop move."""
    if not windows or duration <= 0:
        return {"static_s": 0.0, "static_ratio": 0.0, "longest_shot_s": 0.0, "avg_shot_s": 0.0}
    starts = [float(shot["t0"]) for shot in windows]
    starts[0] = 0.0
    holds = [(shot, end - start) for shot, start, end in zip(windows, starts, [*starts[1:], duration])]
    static = sum(hold for shot, hold in holds if shot.get("kind") == "still")
    longest = max(holds, key=lambda item: item[1])
    return {"static_s": round(static, 1), "static_ratio": round(static / duration, 2), "longest_shot_s": round(longest[1], 1),
            "longest_shot": longest[0].get("key"), "avg_shot_s": round(duration / len(holds), 1)}


def _quality_warnings(spec: dict, shots: list[dict], motion: dict) -> list[dict]:
    """Choices that leave the result thin, reported before any GPU work."""
    profile = profile_of(spec)
    return [*_static_warnings(motion, profile), *_pace_warnings(spec, shots, profile), *_reused_stills(shots), *_setup_warnings(spec, shots, profile)]


def _static_warnings(motion: dict, profile: dict) -> list[dict]:
    found = []
    if motion.get("static_ratio", 0) > profile["static"]:
        found.append({"code": "too_static", "ratio": motion["static_ratio"], "limit": profile["static"],
                      "hint": "add H3 shots or shorten the still scenes"})
    if motion.get("longest_shot_s", 0) > LONG_SHOT_S:
        found.append({"code": "long_shot", "key": motion.get("longest_shot"), "seconds": motion["longest_shot_s"], "limit": LONG_SHOT_S})
    return found


def _pace_warnings(spec: dict, shots: list[dict], profile: dict) -> list[dict]:
    minutes = float((spec.get("song") or {}).get("duration") or 0) / 60
    clips = sum(1 for shot in shots if shot.get("kind") in ("h3", "scene3d"))
    if minutes <= 0 or clips / minutes >= profile["clips_per_minute"]:
        return []
    return [{"code": "few_clips", "per_minute": round(clips / minutes, 1), "minimum": profile["clips_per_minute"],
             "hint": "more H3 or scene3d shots, or a shorter song, or quality: draft"}]


def _reused_stills(shots: list[dict]) -> list[dict]:
    uses: dict[str, int] = {}
    for shot in shots:
        if shot.get("kind") == "still" and isinstance(shot.get("still"), str):
            uses[shot["still"]] = uses.get(shot["still"], 0) + 1
    return [{"code": "still_reused", "still": name, "shots": count} for name, count in uses.items() if count >= REUSED_STILL]


def _setup_warnings(spec: dict, shots: list[dict], profile: dict) -> list[dict]:
    found = []
    if any(shot.get("kind") == "h3" for shot in shots) and int(spec.get("max_takes") or 3) < min(2, profile["max_takes"]):
        found.append({"code": "single_take", "hint": "max_takes 1 keeps the first clip whatever it looks like"})
    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    seeds = song.get("seeds")
    if not song.get("file") and isinstance(seeds, list) and 0 < len(seeds) < min(MIN_SONG_SEEDS, profile["seeds"]):
        found.append({"code": "few_song_seeds", "seeds": len(seeds), "hint": "the best of three candidates is picked by lyric recall"})
    return found


def _over(value: Any, limit: int) -> bool:
    return isinstance(value, str) and len(value) > limit


def _spec_title(spec: dict) -> list[dict]:
    title = spec.get("title")
    if not _over(title, TITLE_LIMIT):
        return []
    return [{"field": "title", "text": title, "length": len(title)}]


def _song_caption(spec: dict) -> list[dict]:
    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    caption = song.get("caption")
    if not _over(caption, CAPTION_LIMIT):
        return []
    return [{"field": "caption", "text": caption, "length": len(caption)}]


def _field_hits(shots: list[dict], names: tuple[str, ...], limit: int) -> list[dict]:
    hits = []
    for shot in shots:
        title = shot.get("title")
        if isinstance(title, str) and "title" in names and _over(title, limit):
            hits.append({"key": shot.get("key"), "field": "title", "text": title, "length": len(title)})
        fields = title.get("fields") if isinstance(title, dict) else {}
        if not isinstance(fields, dict):
            continue
        for name in names:
            value = fields.get(name)
            if _over(value, limit):
                hits.append({"key": shot.get("key"), "field": name, "text": value, "length": len(value)})
    return hits


def _lyric_captions(texts: list[str]) -> list[dict]:
    return [{"index": index, "field": "line", "text": text, "length": len(text)}
            for index, text in enumerate(texts) if len(text) > CAPTION_LIMIT]


def _warnings(missing: list[dict], gaps: list[dict], titles: list[dict], captions: list[dict]) -> list[dict]:
    found: list[dict] = []
    found.extend({"code": "line_without_shot", **item} for item in missing)
    found.extend({"code": "gap_without_fill", **item} for item in gaps)
    found.extend({"code": "title_too_long", **item} for item in titles)
    found.extend({"code": "caption_too_long", **item} for item in captions)
    return found


def _minutes(spec: dict, h3_count: int) -> float:
    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    if song.get("file"):
        seeds = 0
    else:
        raw = song.get("seeds")
        seeds = len(raw) if isinstance(raw, list) and raw else 3
    estimate = _MINUTES_PER_SEED * seeds + _MINUTES_PER_H3 * h3_count + _MINUTES_TAIL
    return float(round(estimate, 1))

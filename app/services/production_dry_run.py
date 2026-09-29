"""Check a production spec before any GPU or MCP work.

``dry_run`` lists shot windows, H3 frame counts, lyric lines no shot covers,
instrumental gaps with no fill, titles over 12 characters, captions over 32,
and an estimated minute count. It never calls the client passed as ``mcp``.
``shots: "auto"`` expands through ``services.production_shot_plan.plan_shots``
when that module exists. This branch does not include the planner.
"""
from __future__ import annotations

from typing import Any

from services.music_production import h3_frames_for, shot_windows
from services.song_analysis import lyric_lines

TITLE_LIMIT = 12
CAPTION_LIMIT = 32
_TITLE_FIELDS = ("title", "date", "cta", "line")
_CAPTION_FIELDS = ("caption", "sub")
# Runbook: about 25–35 min for 5 H3 shots. Three song seeds and five shots land near 32.
_MINUTES_PER_SEED = 2
_MINUTES_PER_H3 = 5
_MINUTES_TAIL = 1


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
        "warnings": pending + _warnings(missing, gaps, titles, captions),
    }


def _expand_shots(spec: dict) -> tuple[dict, bool, list[dict]]:
    """Expand ``shots: "auto"``. ImportError leaves the value unexpanded."""
    if spec.get("shots") != "auto":
        return spec, isinstance(spec.get("shots"), list), []
    try:
        from services.production_shot_plan import plan_shots
    except ImportError:
        return spec, False, [{"code": "shots_auto_unavailable"}]
    planned = plan_shots(spec)
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

"""Build a shot list when ``spec["shots"]`` is the string ``"auto"``.

Sung lines sit on a bar grid: one bar of intro, then one bar per lyric line
(bar = 4 * 60 / bpm). A shot that does not name a lyric line covers four
seconds in ``shot_windows``. Pad shots are not baked into the spec: the
planner only writes content shots plus a ``fill`` template. ``shot_windows``
places pads on the score so the time from one start to the next, and from
the last start to the end of the song, is never longer than two bars.
"""
from __future__ import annotations

import re
from typing import Any

_FRAME = "Medium close-up of the singer from the cast sheet, facing the camera, lips parted"
_ACTIONS = {
    "verse": "(S1) The singer sings the verse to the camera, swaying gently.",
    "chorus": "(S1) The singer sings the chorus to the camera with a bigger gesture.",
}
_HEADER = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_PAD_KEY = re.compile(r"^fill\d+$")


def plan_shots(spec: Any) -> dict:
    """Return a copy whose ``shots`` is a list. Non-auto specs are unchanged."""
    if not isinstance(spec, dict) or spec.get("shots") != "auto":
        return spec
    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    sections = _sections(str(song.get("lyrics") or ""))
    kind, still = _content_kind(spec)
    actions = spec.get("section_actions") if isinstance(spec.get("section_actions"), dict) else {}
    shots = _ordered_shots(spec, sections, _cast_ids(spec), kind, still, actions)
    planned = dict(spec)
    planned["shots"] = shots
    planned["auto_pads"] = True
    if not planned.get("fill"):
        planned["fill"] = [_fill_template(kind, still)]
    return planned


def is_auto_pad(shot: Any) -> bool:
    """Planner pads: ``pad: True``, or a ``fillN`` key with only a baked ``t0``."""
    if not isinstance(shot, dict):
        return False
    if shot.get("pad") is True:
        return True
    key = shot.get("key")
    if not isinstance(key, str) or not _PAD_KEY.fullmatch(key):
        return False
    return "line" not in shot and "after" not in shot


def place_pads(windows: list[dict], spec: dict, duration: float, bpm: float) -> list[dict]:
    """Insert pad shots so consecutive starts (and the tail) stay within two bars."""
    content = [window for window in windows if not is_auto_pad(window)]
    content = _sorted_windows(content)
    if duration <= 0:
        return content
    starts = [float(window["t0"]) for window in content]
    room = max(0, 60 - len(content))
    tempo = bpm if bpm > 0 else 120.0
    kind, still = _content_kind(spec)
    extras = _extra_starts(starts, duration, 240.0 / tempo, room)
    if not extras:
        return content
    base = max((int(window.get("i") or 0) for window in content), default=-1) + 1
    template = _pad_template(spec, kind, still)
    pads = []
    for index, t0 in enumerate(extras):
        shot = {**template, "key": f"fill{index}", "pad": True, "t0": t0}
        pads.append({**shot, "i": base + index, "t0": round(float(t0), 3), "t1": round(float(t0) + 4, 3)})
    return _sorted_windows(content + pads)


def _pad_template(spec: dict, kind: str, still: str | None) -> dict:
    fill = spec.get("fill")
    if isinstance(fill, list) and fill and isinstance(fill[0], dict):
        template = dict(fill[0])
        if template.get("kind") in ("h3", "still", "clip", "screen"):
            return template
    shot: dict[str, Any] = {"kind": kind}
    _paint(shot, kind, still)
    return shot


def _sorted_windows(windows: list[dict]) -> list[dict]:
    return sorted(windows, key=lambda window: (float(window["t0"]), int(window.get("i") or 0)))


def _sections(lyrics: str) -> list[dict]:
    sections: list[dict] = []
    current = None
    index = 0
    for raw in lyrics.splitlines():
        header = _HEADER.match(raw)
        if header:
            current = {"role": _role(header.group(1)), "start": index, "count": 0}
            sections.append(current)
            continue
        if not re.sub(r"\[[^\]]*\]", "", raw).strip():
            continue
        if current is None:
            current = {"role": "verse", "start": index, "count": 0}
            sections.append(current)
        current["count"] += 1
        index += 1
    return sections


def _role(name: str) -> str:
    words = name.replace("-", " ").lower().split()
    head = words[0] if words else ""
    if head.startswith("intro"):
        return "intro"
    if head.startswith("outro") or head in {"end", "ending"}:
        return "outro"
    if any(word.startswith("chorus") or word in {"hook", "refrain"} for word in words):
        return "chorus"
    return "verse"


def _cast_ids(spec: dict) -> list[str]:
    cast = spec.get("cast") or []
    return [item["id"] for item in cast if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]]


def _content_kind(spec: dict) -> tuple[str, str | None]:
    stills = spec.get("stills")
    if isinstance(stills, dict) and stills:
        return "still", next(iter(stills))
    return "screen", None


def _action(actions: dict, role: str) -> str:
    phrase = actions.get(role)
    if isinstance(phrase, str) and phrase.strip():
        return phrase.strip()
    return _ACTIONS.get(role, _ACTIONS["verse"])


def _ordered_shots(spec: dict, sections: list[dict], cast: list[str], kind: str, still: str | None, actions: dict) -> list[dict]:
    title = str(spec.get("title") or "Untitled")
    shots: list[dict] = []
    numbers = {"v": 0, "s": 0, "c": 0}
    if not any(section["role"] == "intro" for section in sections):
        shots.append(_card("intro", title, kind, still, t0=0))
    for section in sections:
        shots.extend(_one_section(section, title, cast, kind, still, actions, numbers))
    if any(section["role"] == "outro" for section in sections):
        return shots
    last = sum(section["count"] for section in sections) - 1
    card = _card("outro", title, kind, still)
    if last >= 0:
        card["after"] = last
    else:
        card["t0"] = 0
    shots.append(card)
    return shots


def _one_section(section: dict, title: str, cast: list[str], kind: str, still: str | None, actions: dict, numbers: dict) -> list[dict]:
    role, start, count = section["role"], section["start"], section["count"]
    if role == "intro":
        return [_intro_card(title, kind, still, start, count)]
    if role == "outro":
        return [_outro_card(title, kind, still, start, count)]
    action = _action(actions, role)
    if role == "chorus":
        return _chorus_shots(start, count, cast, action, numbers)
    return _verse_shots(start, count, cast, action, kind, still, numbers)


def _intro_card(title: str, kind: str, still: str | None, start: int, count: int) -> dict:
    shot = _card("intro", title, kind, still, t0=0)
    if count:
        shot["line"] = start
        shot["span"] = count
    return shot


def _outro_card(title: str, kind: str, still: str | None, start: int, count: int) -> dict:
    shot = _card("outro", title, kind, still)
    if count:
        shot["line"] = start
        shot["span"] = count
    elif start:
        shot["after"] = start - 1
    else:
        shot["t0"] = 0
    return shot


def _verse_shots(start: int, count: int, cast: list[str], action: str, kind: str, still: str | None, numbers: dict) -> list[dict]:
    shots = []
    for offset in range(count):
        if offset % 2 == 0:
            shots.append(_sung(_next(numbers, "v"), start + offset, 1, cast, action))
        else:
            shots.append(_content(_next(numbers, "s"), start + offset, kind, still))
    return shots


def _chorus_shots(start: int, count: int, cast: list[str], action: str, numbers: dict) -> list[dict]:
    shots = []
    offset = 0
    while offset < count:
        span = 2 if offset + 1 < count else 1
        shots.append(_sung(_next(numbers, "c"), start + offset, span, cast, action))
        offset += span
    return shots


def _sung(key: str, line: int, span: int, cast: list[str], action: str) -> dict:
    return {"key": key, "kind": "h3", "line": line, "span": span, "sing": True, "cast": list(cast), "frame": _FRAME, "action": action}


def _content(key: str, line: int, kind: str, still: str | None) -> dict:
    shot: dict[str, Any] = {"key": key, "kind": kind, "line": line}
    _paint(shot, kind, still)
    return shot


def _card(key: str, title: str, kind: str, still: str | None, t0: float | None = None) -> dict:
    shot: dict[str, Any] = {
        "key": key, "kind": kind,
        "title": {"template": "end-card", "fields": {"title": title, "cta": "watch"}},
    }
    if t0 is not None:
        shot["t0"] = t0
    _paint(shot, kind, still)
    return shot


def _paint(shot: dict, kind: str, still: str | None) -> None:
    if kind == "still":
        shot["still"] = still
        shot["zoom"] = [1.0, 1.08]
    else:
        shot["desktop"] = {"layout": "single", "apps": "mixed"}


def _fill_template(kind: str, still: str | None) -> dict:
    shot: dict[str, Any] = {"kind": kind}
    _paint(shot, kind, still)
    return shot


def _next(numbers: dict, prefix: str) -> str:
    key = f"{prefix}{numbers.get(prefix, 0)}"
    numbers[prefix] = numbers.get(prefix, 0) + 1
    return key


def _extra_starts(starts: list[float], duration: float, bar: float, room: int) -> list[float]:
    points = sorted({round(point, 3) for point in (0.0, *starts, duration)})
    limit = 2 * bar
    step = min(4.0, limit)
    extra: list[float] = []
    for left, right in zip(points, points[1:]):
        cursor = left
        while right - cursor > limit + 1e-6 and len(extra) < room:
            cursor = round(cursor + step, 3)
            if cursor >= right - 1e-6:
                break
            extra.append(cursor)
    return extra

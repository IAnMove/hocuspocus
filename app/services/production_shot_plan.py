"""Build a shot list when ``spec["shots"]`` is the string ``"auto"``.

What the non-sung shots are follows the look, not a fixed default: uploaded
``stills`` become still shots, ``style.content == "screen"`` (or a ``style.theme``)
becomes the native tiling desktop, and anything else is a short H3 clip of the
protagonist. ``style.singer == false`` (the ``omarchy-desktop`` preset) puts no
sung H3 shot on screen at all.

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
_BROLL_FRAME = "Wide cinematic shot of the protagonist from the reference sheet in the scene: {phrase}"
_BROLL_ACTION = "The protagonist acts out the scene: {phrase}. Clear movement, slow camera."
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
    actions = spec.get("section_actions") if isinstance(spec.get("section_actions"), dict) else {}
    look = _look(spec, actions)
    shots = _ordered_shots(spec, sections, _cast_ids(spec), look, actions)
    planned = dict(spec)
    planned["shots"] = shots
    planned["auto_pads"] = True
    if not planned.get("fill"):
        planned["fill"] = [_fill_template(look, shots)]
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
    look = _look(spec, {})
    extras = _extra_starts(starts, duration, 240.0 / tempo, room)
    if not extras:
        return content
    base = max((int(window.get("i") or 0) for window in content), default=-1) + 1
    template = _pad_template(spec, look, content)
    pads = []
    for index, t0 in enumerate(extras):
        shot = {**template, "key": f"fill{index}", "pad": True, "t0": t0}
        pads.append({**shot, "i": base + index, "t0": round(float(t0), 3), "t1": round(float(t0) + 4, 3)})
    return _sorted_windows(content + pads)


def _pad_template(spec: dict, look: dict, content: list[dict]) -> dict:
    fill = spec.get("fill")
    if isinstance(fill, list) and fill and isinstance(fill[0], dict):
        template = dict(fill[0])
        if template.get("kind") in ("h3", "still", "clip", "screen"):
            return template
    return _fill_template(look, content)


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


def _look(spec: dict, actions: dict) -> dict:
    """What the non-sung shots are, and whether anyone sings on screen."""
    style = spec.get("style") if isinstance(spec.get("style"), dict) else {}
    stills = spec.get("stills")
    if isinstance(stills, dict) and stills:
        kind, still = "still", next(iter(stills))
    elif style.get("content") == "screen" or style.get("theme"):
        kind, still = "screen", None
    else:
        kind, still = "h3", None
    phrase = actions.get("verse") if isinstance(actions.get("verse"), str) and actions["verse"].strip() else str(spec.get("title") or "the song")
    return {"kind": kind, "still": still, "cast": _cast_ids(spec), "phrase": phrase.strip(),
            "sings": style.get("singer") is not False,
            "cta": str(spec.get("cta") or "watch").strip()[:32] or "watch"}


def _action(actions: dict, role: str) -> str:
    phrase = actions.get(role)
    if isinstance(phrase, str) and phrase.strip():
        return phrase.strip()
    return _ACTIONS.get(role, _ACTIONS["verse"])


def _ordered_shots(spec: dict, sections: list[dict], cast: list[str], look: dict, actions: dict) -> list[dict]:
    title = str(spec.get("title") or "Untitled")
    shots: list[dict] = []
    numbers = {"v": 0, "s": 0, "c": 0}
    if not any(section["role"] == "intro" for section in sections):
        shots.append(_card("intro", title, look, t0=0))
    for section in sections:
        shots.extend(_one_section(section, title, cast, look, actions, numbers))
    if any(section["role"] == "outro" for section in sections):
        return shots
    last = sum(section["count"] for section in sections) - 1
    card = _card("outro", title, look)
    if last >= 0:
        card["after"] = last
    else:
        card["t0"] = 0
    shots.append(card)
    return shots


def _one_section(section: dict, title: str, cast: list[str], look: dict, actions: dict, numbers: dict) -> list[dict]:
    role, start, count = section["role"], section["start"], section["count"]
    if role == "intro":
        return [_intro_card(title, look, start, count)]
    if role == "outro":
        return [_outro_card(title, look, start, count)]
    action = _action(actions, role)
    if role == "chorus":
        return _chorus_shots(start, count, cast, action, look, numbers)
    return _verse_shots(start, count, cast, action, look, numbers)


def _intro_card(title: str, look: dict, start: int, count: int) -> dict:
    shot = _card("intro", title, look, t0=0)
    if count:
        shot["line"] = start
        shot["span"] = count
    return shot


def _outro_card(title: str, look: dict, start: int, count: int) -> dict:
    shot = _card("outro", title, look)
    if count:
        shot["line"] = start
        shot["span"] = count
    elif start:
        shot["after"] = start - 1
    else:
        shot["t0"] = 0
    return shot


def _verse_shots(start: int, count: int, cast: list[str], action: str, look: dict, numbers: dict) -> list[dict]:
    shots = []
    for offset in range(count):
        if offset % 2 == 0 and look["sings"]:
            shots.append(_sung(_next(numbers, "v"), start + offset, 1, cast, action))
        else:
            shots.append(_content(_next(numbers, "s"), start + offset, look))
    return shots


def _chorus_shots(start: int, count: int, cast: list[str], action: str, look: dict, numbers: dict) -> list[dict]:
    shots = []
    offset = 0
    while offset < count:
        span = 2 if offset + 1 < count else 1
        if look["sings"]:
            shots.append(_sung(_next(numbers, "c"), start + offset, span, cast, action))
        else:
            shot = _content(_next(numbers, "c"), start + offset, look)
            shot["span"] = span
            shots.append(shot)
        offset += span
    return shots


ALONE = " Only this character appears; no other characters, creatures or animals."


def _alone(cast: list[str]) -> str:
    """A video model invents extra characters when an action does not say who is alone in the frame."""
    return ALONE if len(cast) == 1 else ""


def _sung(key: str, line: int, span: int, cast: list[str], action: str) -> dict:
    return {"key": key, "kind": "h3", "line": line, "span": span, "sing": True, "cast": list(cast), "frame": _FRAME,
            "action": action + _alone(cast)}


def _content(key: str, line: int, look: dict) -> dict:
    shot: dict[str, Any] = {"key": key, "kind": look["kind"], "line": line}
    _paint(shot, look)
    return shot


def _card(key: str, title: str, look: dict, t0: float | None = None) -> dict:
    shot: dict[str, Any] = {
        "key": key, "kind": look["kind"],
        "title": {"template": "end-card", "fields": {"title": title, "cta": look["cta"]}},
    }
    if t0 is not None:
        shot["t0"] = t0
    _paint(shot, look)
    return shot


def _paint(shot: dict, look: dict) -> None:
    kind = look["kind"]
    if kind == "still":
        shot["still"] = look["still"]
        shot["zoom"] = [1.0, 1.08]
    elif kind == "screen":
        shot["desktop"] = {"layout": "single", "apps": "mixed"}
    else:
        shot.update(cast=list(look["cast"]), frame=_BROLL_FRAME.format(phrase=look["phrase"]),
                    action=_BROLL_ACTION.format(phrase=look["phrase"]) + _alone(look["cast"]))


def _fill_template(look: dict, shots: list[dict]) -> dict:
    """Pads are the look's own kind; in H3 mode they reuse a clip that is already planned."""
    if look["kind"] != "h3":
        shot: dict[str, Any] = {"kind": look["kind"]}
        _paint(shot, look)
        return shot
    source = next((item["key"] for item in shots if item.get("kind") == "h3" and item.get("key") not in ("intro", "outro")),
                  next((item["key"] for item in shots if item.get("kind") == "h3"), "intro"))
    return {"kind": "clip", "clip": source}


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

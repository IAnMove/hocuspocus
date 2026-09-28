"""Title cue builders for scenes.video2d.edit.

Python port of the defaults in ui/src/lib/kineticText/templates.ts.
"""
from __future__ import annotations


def _fail(code: str, message: str) -> None:
    from services.video2d_edit import Video2dEditError
    raise Video2dEditError(code, message)


def _cue(cue_id: str, text: str, frame: dict, extra: dict) -> dict:
    cue = {"id": cue_id, "text": text, "start": frame["start"], "end": frame["start"] + frame["duration"], "preset": "impact", "x": 50, "y": 80, "size": 8, "color": "#fff6e8", "rotation": 0}
    cue.update(extra)
    return cue


def _field(fields: dict, key: str) -> str:
    if key not in fields or fields[key] is None:
        return ""
    value = fields[key]
    if isinstance(value, str):
        text = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(value)
    else:
        _fail("invalid_input", "Title fields must be strings")
    if len(text) > 240:
        _fail("invalid_input", "Title field exceeds 240 characters")
    return text


def _vertical(frame: dict) -> bool:
    return frame["height"] > frame["width"]


def _lower_third(fields: dict, frame: dict) -> list:
    y = 72 if _vertical(frame) else 78
    return [
        _cue("date", _field(fields, "date") or "1991", frame, {"y": y - 8, "size": 14, "font": "display", "weight": 400, "align": "left", "x": 12, "enter": {"preset": "slide-right", "duration": 0.45}, "box": {"kind": "bar", "color": "#e85d4c", "opacity": 1, "padding": 0.2}}),
        _cue("caption", _field(fields, "caption") or "", frame, {"y": y, "size": 5, "font": "condensed", "x": 12, "align": "left", "enter": {"preset": "fade", "duration": 0.4}}),
    ]


def _chorus(fields: dict, frame: dict) -> list:
    return [_cue("chorus", _field(fields, "line") or "", frame, {"font": "marker", "y": 62 if _vertical(frame) else 48, "enter": {"preset": "words", "duration": 1.1}, "loop": "pulse", "box": {"kind": "paper", "color": "#f4e7cf", "opacity": 0.94, "padding": 0.4}, "color": "#2a2118"})]


def _title_card(fields: dict, frame: dict) -> list:
    cues = [_cue("title", _field(fields, "title") or "", frame, {"font": "display", "weight": 400, "size": 16, "y": 46, "enter": {"preset": "blur", "duration": 0.7}, "box": {"kind": "plate", "color": "#07080d", "opacity": 1, "padding": 0}})]
    subtitle = _field(fields, "subtitle")
    if subtitle:
        cues.append(_cue("sub", subtitle, frame, {"y": 62, "size": 5, "font": "serif", "enter": {"preset": "fade", "duration": 0.5}}))
    return cues


def _end_card(fields: dict, frame: dict) -> list:
    return [
        _cue("end", _field(fields, "title") or "", frame, {"font": "display", "weight": 400, "size": 12, "y": 44}),
        _cue("cta", _field(fields, "cta") or "", frame, {"y": 60, "size": 5, "font": "sans"}),
    ]


def _js_number(text: str):
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return 0
    if value != value or abs(value) == float("inf"):
        return 0
    if value == int(value) and abs(value) < 1e15:
        return int(value)
    return value


def _year_counter(fields: dict, frame: dict) -> list:
    cues = [_cue("count", "{value}", frame, {"font": "display", "weight": 400, "size": 18, "y": 42, "counter": {"from": _js_number(_field(fields, "from")), "to": _js_number(_field(fields, "to")), "decimals": 0, "ease": "ease"}})]
    label = _field(fields, "label")
    if label:
        cues.append(_cue("label", label, frame, {"y": 62, "size": 5, "font": "condensed"}))
    return cues


def _quote(fields: dict, frame: dict) -> list:
    width = 78 if _vertical(frame) else 60
    cues = [_cue("quote", "\u201c" + (_field(fields, "quote") or "") + "\u201d", frame, {"font": "serif", "italic": True, "size": 7, "y": 46, "maxWidth": width, "enter": {"preset": "typewriter", "duration": 1.4}})]
    author = _field(fields, "author")
    if author:
        cues.append(_cue("author", author, frame, {"y": 64, "size": 4, "font": "sans"}))
    return cues


def _trailer(fields: dict, frame: dict) -> list:
    lines = [line.strip() for line in (_field(fields, "lines") or "").split("|") if line.strip()][:8]
    if not lines:
        return []
    each = frame["duration"] / len(lines)
    cues = []
    for index, line in enumerate(lines):
        sliced = {**frame, "start": frame["start"] + each * index, "duration": each}
        cues.append(_cue(f"slam-{index + 1}", line, sliced, {"font": "display", "weight": 400, "size": 14, "y": 50, "enter": {"preset": "impact", "duration": 0.18}, "box": {"kind": "plate", "color": "#000000", "opacity": 1, "padding": 0}}))
    return cues


def _chapter(fields: dict, frame: dict) -> list:
    return [
        _cue("kicker", (_field(fields, "kicker") or "").upper(), frame, {"y": 40, "size": 3, "font": "condensed", "uppercase": True, "letterSpacing": 0.2}),
        _cue("chapter", _field(fields, "title") or "", frame, {"y": 50, "size": 12, "font": "display", "weight": 400}),
    ]


def _social(fields: dict, frame: dict) -> list:
    tall = _vertical(frame)
    return [_cue("social", _field(fields, "caption") or "", frame, {"y": 72 if tall else 84, "size": 4.5, "maxWidth": 76 if tall else 70, "font": "sans", "box": {"kind": "pill", "color": "#11131a", "opacity": 0.82, "padding": 0.45, "radius": 0.8}})]


TITLE_BUILDERS = {
    "lower-third-date": _lower_third,
    "chorus-banner": _chorus,
    "title-card": _title_card,
    "end-card": _end_card,
    "year-counter": _year_counter,
    "quote": _quote,
    "trailer-slam": _trailer,
    "chapter": _chapter,
    "social-caption": _social,
}

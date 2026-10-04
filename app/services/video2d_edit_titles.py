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


_RANSOM_FONTS = ("display", "marker", "serif", "condensed")
_RANSOM_PAPER = ("#f4e7cf", "#f6f1e4", "#f3d2b5", "#e7eef8")
_RANSOM_TILT = (-3, 2, -1, 4, -2, 3, 1, -4)
_INK = {"color": "#1c140f", "width": 0}
_NO_SHADOW = {"color": "#1c140f", "blur": 0, "x": 0, "y": 0}
_DYMO_TILT = (-1.5, -1, -0.5, 0, 0.5, 1, 1.5)


def _ransom_words(line: str) -> list[str]:
    return [word for word in line.upper().split() if word][:8]


def _ransom_place(index: int, count: int, tall: bool) -> tuple[float, float]:
    cols = 3 if tall else 4
    row, col = divmod(index, cols)
    row_count = min(cols, count - row * cols)
    rows = (count + cols - 1) // cols
    x = 50 + (col - (row_count - 1) / 2) * (22 if tall else 18)
    y = (46 if tall else 48) + (row - (rows - 1) / 2) * 12
    return x, y


def _ransom_cue(word: str, index: int, count: int, frame: dict, tall: bool) -> dict:
    x, y = _ransom_place(index, count, tall)
    return _cue(f"word-{index + 1}", word, frame, {
        "x": x, "y": y, "size": 7 if tall else 8, "font": _RANSOM_FONTS[index % 4], "weight": 700,
        "align": "center", "uppercase": True, "rotation": _RANSOM_TILT[index % 8], "color": "#1c140f",
        "start": frame["start"] + min(index * 0.12, frame["duration"] * 0.5), "end": frame["start"] + frame["duration"],
        "enter": {"preset": "impact", "duration": 0.2},
        "box": {"kind": "paper", "color": _RANSOM_PAPER[index % 4], "opacity": 1, "padding": 0.28},
        "stroke": dict(_INK), "shadow": dict(_NO_SHADOW),
    })


def _ransom(fields: dict, frame: dict) -> list:
    words = _ransom_words(_field(fields, "line") or "THE BIRD IS FREED")
    tall = _vertical(frame)
    return [_ransom_cue(word, index, len(words), frame, tall) for index, word in enumerate(words)]


def _utf16_unit(char: str) -> int:
    code = ord(char)
    if code <= 0xFFFF:
        return code
    return 0xD800 + ((code - 0x10000) >> 10)


def _dymo_tilt(text: str) -> float:
    total = 0
    for char in text:
        total = (total + _utf16_unit(char)) % 7
    return _DYMO_TILT[total]


def _dymo_dark(background: str) -> bool:
    return background.strip().lower() == "dark"


def _dymo_look(text: str, dark: bool, tall: bool) -> dict:
    return {
        "x": 50, "y": 72 if tall else 78, "size": 4.5 if tall else 5, "font": "mono", "weight": 700,
        "align": "center", "uppercase": True, "letterSpacing": 0.06, "maxWidth": 84 if tall else 78,
        "rotation": _dymo_tilt(text), "color": "#141210" if dark else "#f4efe6",
        "enter": {"preset": "words", "duration": 0.8},
        "box": {"kind": "tape", "color": "#f2b705" if dark else "#141210", "opacity": 1, "padding": 0.55, "radius": 0.18},
        "stroke": {"color": "#141210", "width": 0}, "shadow": {"color": "#141210", "blur": 0, "x": 0, "y": 0},
    }


def _dymo(fields: dict, frame: dict) -> list:
    text = (_field(fields, "line") or "KEEP THE LINE").upper()
    dark = _dymo_dark(_field(fields, "background") or "paper")
    return [_cue("tape", text, frame, _dymo_look(text, dark, _vertical(frame)))]


def _card(fields: dict, frame: dict) -> list:
    tall = _vertical(frame)
    return [_cue("card", _field(fields, "title") or "Musktopia", frame, {
        "x": 50, "y": 44 if tall else 46, "size": 10 if tall else 12, "font": "display", "weight": 400,
        "align": "center", "rotation": -1, "color": "#1a140f", "enter": {"preset": "rise", "duration": 0.45},
        "box": {"kind": "card", "color": "#f7f1e4", "opacity": 1, "padding": 0.62, "radius": 0.08},
        "stroke": dict(_INK), "shadow": dict(_NO_SHADOW),
    })]


_DESKTOP_KEYS = ("theme", "layout", "apps", "switch")
_DESKTOP_NUMBERS = ("focus", "workspace")


def _desktop(fields: dict, frame: dict) -> list:
    """Full-frame tiling-desktop graphic (theme, layout and apps come from scene_graphics.json)."""
    from services.video2d_catalogs import GRAPHICS_CATALOG
    entry = next(item for item in GRAPHICS_CATALOG["entries"] if item["id"] == "tiling")
    allowed = {param["key"]: param for param in entry["params"]}
    params: dict = {}
    for key in _DESKTOP_KEYS:
        value = _field(fields, key)
        if value not in allowed[key]["values"]:
            _fail("invalid_input", f"desktop {key} must be one of {', '.join(allowed[key]['values'])}")
        params[key] = value
    for key in _DESKTOP_NUMBERS:
        try:
            value = int(float(_field(fields, key)))
        except ValueError:
            _fail("invalid_input", f"desktop {key} must be a number")
        if not allowed[key]["min"] <= value <= allowed[key]["max"]:
            _fail("invalid_input", f"desktop {key} is out of range")
        params[key] = value
    return [_cue("desktop", "", frame, {"x": 50, "y": 50, "size": 10, "graphic": {"id": "tiling", "params": params}})]


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
    "ransom": _ransom,
    "dymo": _dymo,
    "card": _card,
    "desktop": _desktop,
}

TITLE_DEFAULTS = {
    "ransom": {"line": "THE BIRD IS FREED"},
    "dymo": {"line": "KEEP THE LINE", "background": "paper"},
    "card": {"title": "Musktopia"},
    "desktop": {"theme": "tokyo-night", "layout": "triple", "apps": "mixed", "focus": "0", "workspace": "1", "switch": "none"},
}


def install_title_defaults() -> None:
    """Register styles on the edit module without editing that file."""
    from services import video2d_edit as edit
    edit._TITLE_DEFAULTS.update(TITLE_DEFAULTS)
    edit._TEXT_BOXES = frozenset([*edit._TEXT_BOXES, "tape", "card"])


install_title_defaults()

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

Every shot takes place in one scene phrase: ``section_actions.scene``, else ``section_actions.verse``, else the
title. Sung shots and H3 content shots each take the next of four framings in turn, so no two start frames share
one text. A sung shot's action is ``section_actions.<role>`` or a plain default; the camera move is the shot's
``camera``, not words in the action. ``plan_report`` is what dry_run shows of all this.
"""
from __future__ import annotations

import re
from typing import Any

from services.production_treatment import VARIATIONS, annotate_moments

# One framing per sung shot, in turn: with one shared frame text, cast and seed every sung start frame was the
# same picture. Each keeps the face large and readable for the lip-sync check.
_FRAMES = (
    "Medium close-up of the singer from the cast sheet, facing the camera, lips parted",
    "Waist-up medium shot of the singer from the cast sheet, three-quarter angle, lips parted",
    "Low-angle medium close-up of the singer from the cast sheet, looking just past the camera, lips parted",
    "Close-up of the singer from the cast sheet in three-quarter profile, lips parted, background in soft focus",
)
# One framing per H3 content shot, in turn, like _FRAMES: one shared text made every content shot the same picture.
_CONTENT_FRAMES = (
    "Wide establishing shot of the protagonist from the reference sheet in the scene: {phrase}",
    "Medium shot of the protagonist from the reference sheet in the middle of the action, in the scene: {phrase}",
    "Detail insert of the protagonist from the reference sheet: a close view of their hands or of what they hold, in the scene: {phrase}",
    "Over-the-shoulder shot from behind the protagonist from the reference sheet, looking into the scene: {phrase}",
)
_CONTENT_ACTION = "The protagonist acts out the scene: {phrase}. Clear movement."
_ACTIONS = {
    "verse": "(S1) The singer sings the verse to the camera, swaying gently.",
    "chorus": "(S1) The singer sings the chorus to the camera with a bigger gesture.",
}
_PAD_CAMERAS = ("camera-push-in", "camera-pan-right", "camera-pull-out", "camera-pan-left")
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
    trailer = spec.get("structure") == "trailer"
    if trailer:
        from services.production_structure import plan_trailer
        shots = _uncover_image_titles(plan_trailer(spec, look, str(spec.get("title") or "Untitled")))
    else:
        shots = annotate_moments(spec, _uncover_image_titles(_ordered_shots(spec, sections, _cast_ids(spec), look, actions)))
    planned = dict(spec)
    planned["shots"] = shots
    planned["auto_pads"] = not trailer          # a trailer's long held shots are deliberate: no pad cuts inside them
    if not planned.get("fill"):
        planned["fill"] = [_fill_template(look, shots)]
    return planned


def check_section_actions(spec: dict) -> None:
    """validate_spec hook: ``section_actions.scene``, when given, is a short phrase."""
    actions = spec.get("section_actions")
    scene = actions.get("scene") if isinstance(actions, dict) else None
    if scene is not None and not (isinstance(scene, str) and 0 < len(scene.strip()) <= 200):
        from services.music_production import ProductionError
        raise ProductionError("invalid_spec", "section_actions.scene is a phrase of 1-200 characters")


def plan_report(spec: Any) -> dict | None:
    """What ``shots: "auto"`` fills in, for dry_run: the scene phrase and where it came from, and the framings and
    actions written into the shots. None when the spec lists its own shots."""
    if not isinstance(spec, dict) or spec.get("shots") != "auto":
        return None
    actions = spec.get("section_actions") if isinstance(spec.get("section_actions"), dict) else {}
    look = _look(spec, actions)
    trailer = spec.get("structure") == "trailer"
    report: dict[str, Any] = {"structure": "trailer" if trailer else "clip", "content": look["kind"], "scene": look["phrase"],
                              "scene_from": next((f"section_actions.{name}" for name in ("scene", "verse") if _given(actions, name)), "title")}
    if look["kind"] == "h3":
        report["content_framings"] = [frame.format(phrase=look["phrase"]) for frame in _CONTENT_FRAMES]
        report["content_action"] = _CONTENT_ACTION.format(phrase=look["phrase"])
    if not trailer and look["sings"]:
        report["sung_framings"] = [f"{frame}, in the scene: {look['phrase']}" for frame in _FRAMES]
        report["sung_actions"] = {role: {"text": _action(actions, role), "from": "section_actions" if _given(actions, role) else "default"}
                                  for role in ("verse", "pre-chorus", "chorus")}
    return report


def _given(actions: dict, name: str) -> bool:
    return isinstance(actions.get(name), str) and bool(actions[name].strip())


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
        if shot.get("kind") in ("clip", "still"):
            shot.setdefault("camera", _PAD_CAMERAS[index % len(_PAD_CAMERAS)])       # the same pad twice is not the same picture
        pads.append({**shot, "i": base + index, "t0": round(float(t0), 3), "t1": round(float(t0) + 4, 3)})
    return _sorted_windows(content + pads)


def _pad_template(spec: dict, look: dict, content: list[dict]) -> dict:
    fill = spec.get("fill")
    if isinstance(fill, list) and fill and isinstance(fill[0], dict):
        template = dict(fill[0])
        if template.get("kind") in ("h3", "still", "clip", "screen", "scene2d"):
            return template
    return _fill_template(look, content)


def _sorted_windows(windows: list[dict]) -> list[dict]:
    return sorted(windows, key=lambda window: (float(window["t0"]), int(window.get("i") or 0)))


def _sections(lyrics: str) -> list[dict]:
    sections: list[dict] = []
    current = None
    index = 0
    seen: dict[str, int] = {}
    for raw in lyrics.splitlines():
        header = _HEADER.match(raw)
        if header:
            role = _role(header.group(1))
            seen[role] = seen.get(role, 0) + 1
            current = {"role": role, "nth": seen[role], "start": index, "count": 0}
            sections.append(current)
            continue
        if not re.sub(r"\[[^\]]*\]", "", raw).strip():
            continue
        if current is None:
            seen["verse"] = seen.get("verse", 0) + 1
            current = {"role": "verse", "nth": seen["verse"], "start": index, "count": 0}
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
    if "pre" in words and any(word.startswith("chorus") for word in words):
        return "pre-chorus"               # a build into the chorus is a verse to shoot, not a second chorus
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
    phrase = next((actions[name] for name in ("scene", "verse") if _given(actions, name)), str(spec.get("title") or "the song"))
    return {"kind": kind, "still": still, "cast": _cast_ids(spec), "phrase": phrase.strip(),
            "sings": style.get("singer") is not False,
            "cta": str(spec.get("cta") or "watch").strip()[:32] or "watch"}


def _action(actions: dict, role: str) -> str:
    phrase = actions.get(role)
    if isinstance(phrase, str) and phrase.strip():
        return phrase.strip()
    return _ACTIONS.get(role, _ACTIONS["verse"])


def _uncover_image_titles(shots: list[dict]) -> list[dict]:
    from services.production_preview import uncover_titles
    return uncover_titles(shots)


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
        return _chorus_shots(start, count, cast, action, look, numbers, section.get("nth", 1))
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
            shots.append(_sung(_next(numbers, "v"), start + offset, 1, cast, action, _frame(look, numbers)))
        else:
            shots.append(_content(_next(numbers, "s"), start + offset, look))
    return shots


def _chorus_shots(start: int, count: int, cast: list[str], action: str, look: dict, numbers: dict, nth: int = 1) -> list[dict]:
    shots = []
    offset = 0
    while offset < count:
        span = 2 if offset + 1 < count else 1
        if look["sings"]:
            shot = _sung(_next(numbers, "c"), start + offset, span, cast, action, _frame(look, numbers))
        else:
            shot = _content(_next(numbers, "c"), start + offset, look)
            shot["span"] = span
        shots.append(_vary(shot, look, nth, len(shots)))
        offset += span
    return shots


_LAYOUTS = ("triple", "quad", "master", "split")
_ZOOMS = ([1.0, 1.08], [1.15, 1.3], [1.3, 1.15])


def _vary(shot: dict, look: dict, nth: int, index: int) -> dict:
    """A chorus that comes back is not the first one again: other framing, a consequence, more of the scene."""
    if nth < 2:
        return shot
    turn = nth - 2 + index
    if shot["kind"] in ("h3", "scene3d") and shot.get("action"):
        shot["action"] = shot["action"].replace(ALONE, "") + " " + VARIATIONS[turn % len(VARIATIONS)] + (ALONE if ALONE in shot["action"] else "")
    elif shot["kind"] == "screen":
        shot["desktop"] = {**shot["desktop"], "layout": _LAYOUTS[turn % len(_LAYOUTS)], "workspace": min(9, nth), "switch": "right"}
    elif shot["kind"] == "still":
        shot["zoom"] = list(_ZOOMS[turn % len(_ZOOMS)])
    return shot


ALONE = " Only this character appears; no other characters, creatures or animals."


def _alone(cast: list[str]) -> str:
    """A video model invents extra characters when an action does not say who is alone in the frame."""
    return ALONE if len(cast) == 1 else ""


def _frame(look: dict, numbers: dict) -> str:
    """The next sung framing, placed in the song's scene."""
    turn = numbers.get("sung", 0)
    numbers["sung"] = turn + 1
    return f"{_FRAMES[turn % len(_FRAMES)]}, in the scene: {look['phrase']}"


def _sung(key: str, line: int, span: int, cast: list[str], action: str, frame: str) -> dict:
    return {"key": key, "kind": "h3", "line": line, "span": span, "sing": True, "cast": list(cast), "frame": frame,
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
        turn = look.get("framed", 0)        # this plan's next content framing; the counter lives in the plan's look
        look["framed"] = turn + 1
        shot.update(cast=list(look["cast"]), frame=_CONTENT_FRAMES[turn % len(_CONTENT_FRAMES)].format(phrase=look["phrase"]),
                    action=_CONTENT_ACTION.format(phrase=look["phrase"]) + _alone(look["cast"]))


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

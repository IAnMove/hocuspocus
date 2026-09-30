"""Scene documents: windows, lyric and title ops, and the fingerprint that skips a re-export."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

import numpy as np

from services.production_shot_plan import is_auto_pad, place_pads
from services.production_state import note_held
from services.video2d_edit import MAX_TEXTS
from services.video2d_edit_titles import TITLE_BUILDERS

# dymo punches its letters out of the tape: on a dark picture they vanish. Dark letters on cream tape read on any picture.
DYMO_READABLE = {"color": "#141210", "box": {"kind": "tape", "color": "#F4EEE2", "opacity": 1, "padding": 0.72, "radius": 0.18}}


def _host():
    import services.music_production as host
    return host


def h3_frames_for(seconds: float) -> int:
    frames = _host().H3_FRAMES
    need = int(np.ceil(seconds * 24))
    return next((frame for frame in frames if frame >= need), frames[-1])


def _duration(score: dict) -> float:
    try:
        return float(score.get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def _bpm(score: dict) -> float:
    try:
        return float(score.get("bpm") or 120) or 120.0
    except (TypeError, ValueError):
        return 120.0


def _line_at(lines: list, index: object) -> dict | None:
    if isinstance(index, int) and 0 <= index < len(lines):
        return lines[index]
    return None


def _window_start(shot: dict, lines: list, duration: float) -> tuple[float, dict | None]:
    line = _line_at(lines, shot.get("line"))
    if "t0" in shot:
        t0 = float(shot["t0"])
    elif line:
        t0 = line["t0"] - 0.25
    elif _line_at(lines, shot.get("after")) and isinstance(shot.get("after"), int):
        t0 = lines[shot["after"]]["t1"] + 0.3
    else:
        t0 = 0.0
    # an `after` card uses last.t1 + 0.3; when the last lyric ends at the song
    # end that start is past duration and segments() drops it (b - a <= 0).
    if duration > 0 and t0 >= duration:
        t0 = max(0.0, duration - 4.0)
    return t0, line


def _window_end(shot: dict, lines: list, line: dict | None, t0: float) -> float:
    if line:
        last = lines[min(len(lines) - 1, shot["line"] + shot.get("span", 1) - 1)]
        return last["t1"] + 0.2
    if "t1" not in shot:
        return t0 + 4                       # untitled cards; a trailer bakes t1 so a held beat is not 4 s
    try:
        return float(shot["t1"])
    except (TypeError, ValueError):
        return t0 + 4


def shot_windows(spec: dict, score: dict) -> list[dict]:
    lines = score.get("lines") or []
    duration = _duration(score)
    out = []
    for index, shot in enumerate(spec["shots"]):
        if is_auto_pad(shot):
            continue
        t0, line = _window_start(shot, lines, duration)
        t1 = _window_end(shot, lines, line, t0)
        out.append({**shot, "i": index, "t0": round(max(0.0, t0), 3), "t1": round(t1, 3)})
    bpm = _bpm(score)
    shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
    if spec.get("auto_pads") or any(is_auto_pad(shot) for shot in shots):
        return place_pads(out, spec, duration, bpm)
    return out


def _fill_tail(shot: dict, a: float, b: float, length: float, fill: list[dict], used: int, bar: float) -> tuple[list, int]:
    out = [(shot, a, a + length)]
    t, k = a + length, 0
    while t < b - 0.05:
        item = fill[used % len(fill)]
        used += 1
        end = min(b, t + 2 * bar)
        out.append(({**item, "key": f"{shot['key']}_fill{k}"}, t, end))
        t, k = end, k + 1
    return out, used


def segments(windows: list[dict], score: dict, clip_ok: Callable[[str], bool], fill: list[dict]) -> list[tuple[dict, float, float]]:
    """Scene cuts; an h3 shot longer than its clip is cut at the clip end and the rest filled on bar lines."""
    cuts = [w["t0"] for w in windows] + [float(score["duration"])]
    cuts[0] = 0.0
    bar = 4 * float(score.get("beat") or 0.5)
    out, used = [], 0
    for n, shot in enumerate(windows):
        a, b = cuts[n], cuts[n + 1]
        if shot["kind"] == "h3" and clip_ok(shot["key"]) and fill:
            length = h3_frames_for(shot["t1"] - shot["t0"]) / 24 - max(0.0, a - shot["t0"])
            if b - a > length + 0.3:
                extra, used = _fill_tail(shot, a, b, length, fill, used, bar)
                out.extend(extra)
                continue
        if b - a > 0.05:
            out.append((shot, a, b))
    return out


def title_span(dur: float) -> tuple[float, float] | None:
    """Inset 0.1 s when the scene is long enough; otherwise fill the scene. None if nothing fits."""
    if dur <= 0:
        return None
    if dur > 0.3:
        start, length = 0.1, round(dur - 0.2, 3)
    else:
        start, length = 0.0, round(dur, 3)
    if length <= 0:
        return None
    return start, length


def lyric_span(line: dict, a: float, b: float, dur: float) -> tuple[float, float] | None:
    """Scene-relative start/duration for a score line, or None if it would be rejected by edit."""
    if line["t1"] <= a or line["t0"] >= b:
        return None
    start = round(max(0.0, line["t0"] - a), 3)
    length = round(min(b, line["t1"] + 0.15) - max(a, line["t0"]), 3)
    if length <= 0 or start + length - dur > 1e-6:
        return None
    return start, length


def seam_look(line: dict, a: float, b: float) -> dict:
    """A line that runs across a cut keeps one continuous caption: no entrance in the scene it continues into, no exit before the cut."""
    look: dict = {}
    if line["t0"] < a - 0.02:
        look["enter"] = {"preset": "none", "duration": 0.05}
    if line["t1"] + 0.15 > b + 0.02:
        look["exit"] = {"preset": "none", "duration": 0.05}
    return look


def title_cue_count(template: str, fields: dict, start: float, length: float) -> int:
    builder = TITLE_BUILDERS.get(template)
    if builder is None:
        return 1
    try:
        return max(1, len(builder(fields, {"start": start, "duration": length, "width": 1920, "height": 1080})))
    except Exception:
        return 1


def scene_fingerprint(shot: dict, style: dict, stills: dict, score: dict, start: float, end: float) -> str:
    """Invalidate a rendered scene when its spec, window, or lyric timing changes on resume."""
    source = {"shot": shot, "style": style, "stills": stills, "lines": score.get("lines") or [],
              "start": round(float(start), 3), "end": round(float(end), 3)}
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()[:16]


def contact_sheet_filter(duration: float) -> str:
    """Sample the whole song into the 24-cell review sheet, including its final card."""
    return f"fps={24 / max(duration, 1):.8f},scale=320:-1,tile=6x4"


def theme_colours(theme: str | None) -> dict:
    if not theme:
        return {}
    themes = _host().OMARCHY_THEMES
    if theme not in themes:
        from services.music_production import ProductionError
        raise ProductionError("invalid_spec", f"unknown theme {theme}")
    return themes[theme]


def theme_lyric_style(theme: str | None) -> dict:
    """Default lyric look for an Omarchy theme: square mono plate in the theme's surface colour."""
    colours = theme_colours(theme)
    if not colours:
        return {}
    return {"color": colours["fg"], "font": "mono", "weight": 700,
            "box": {"kind": "solid", "color": colours["surface"], "opacity": 0.92, "padding": 0.5, "radius": 0}}


def _clip_layers(production: Any, shot: dict, a: float, dur: float, clip: dict) -> list[dict]:
    note_held(production.state, shot["key"], False)
    ops = [{"op": "add_layer", "id": "bg", "source": clip["url"], "type": "video", "preset": shot.get("camera", "camera-locked")}]
    skip = 0.0
    if shot["kind"] == "h3":
        skip = round(max(0.0, a - shot.get("t0", a)) + ((clip.get("qa") or {}).get("suggested_sync_s") or 0), 3)
    # the animation duration is also the video span (sceneTimeline.getSceneLayerTiming): a camera preset's
    # shorter duration would freeze the clip mid-scene, so it always covers the scene (+ the skipped head)
    anim: dict[str, Any] = {"end": {"x": 50, "y": 50, "scale": 1.0, "rotation": 0},
                            "duration": round(dur + skip, 3)}
    if skip > 0:
        anim["trimStart"] = skip
    ops.append({"op": "update_layer", "id": "bg", "patch": {"fill": True, "animation": anim}})
    return ops


def _plate_layers(production: Any, shot: dict, dur: float, style: dict, stills: dict) -> list[dict]:
    if shot["kind"] == "screen":
        desktop = {"theme": style.get("theme") or "tokyo-night", "layout": "triple", "apps": "mixed", "focus": "0", "workspace": "1",
                   "switch": "none", **{k: str(v) for k, v in (shot.get("desktop") or {}).items()}}
        return [{"op": "add_title", "id": "desk", "template": "desktop", "fields": desktop, "start": 0, "duration": dur}]
    zoom = shot.get("zoom") or [1.0, 1.1]
    source = stills.get(shot.get("still"), shot.get("still"))
    if not source and shot["kind"] == "h3" and shot["key"] in production.state.get("frames", {}):
        source = production.upload(production.state["frames"][shot["key"]])[1]      # clip failed: hold its start frame
        note_held(production.state, shot["key"])
    return [{"op": "add_layer", "id": "bg", "source": source, "type": "image", "preset": shot.get("camera", "camera-push-in")},
            {"op": "update_layer", "id": "bg", "patch": {"fill": True, "focus": shot.get("focus", {"x": 50, "y": 50}), "animation": {
                "start": {"x": 50, "y": 50, "scale": zoom[0], "rotation": 0}, "end": {"x": 50, "y": 50, "scale": zoom[1], "rotation": 0}}}}]


def scene_ops(production: Any, shot: dict, a: float, b: float, dur: float, score: dict, clips: dict, style: dict, stills: dict) -> list[dict]:
    ops: list[dict] = []
    clip = clips.get(shot["key"]) or (clips.get(shot.get("clip")) if shot["kind"] == "clip" else None)
    if shot["kind"] == "scene3d" and not clip:
        from services.music_production import ProductionError
        raise ProductionError("scene3d_export_failed", f"scene3d clip missing: {shot['key']}")
    if clip:
        ops.extend(_clip_layers(production, shot, a, dur, clip))
    else:
        ops.extend(_plate_layers(production, shot, dur, style, stills))
    title_rows, used = production._title_ops(shot, dur, style)
    ops.extend(title_rows)
    ops.extend(production._lyric_ops(shot, a, b, dur, score, style, used))
    ops.extend(production._footer_ops(dur, style))
    if style.get("finish"):
        ops.append({"op": "set_finish", **style["finish"]})
    return ops


def title_ops(shot: dict, dur: float, style: dict) -> tuple[list[dict], int]:
    span = title_span(dur)
    if not shot.get("title") or not span:
        return [], 0
    template = shot["title"].get("template", "lower-third-date")
    fields = shot["title"]["fields"]
    ops = [{"op": "add_title", "id": "tt", "template": template, "fields": fields,
            "start": span[0], "duration": span[1]}]
    cues = TITLE_BUILDERS[template](fields, {"start": span[0], "duration": span[1], "width": 1920, "height": 1080})
    for index, cue in enumerate(cues):
        patch = {**(style.get("title_style") or {}), **(shot["title"].get("style") or {}),
                 **((shot["title"].get("cues") or {}).get(cue["id"]) or {})}
        if shot.get("graphic") and index == 0:
            patch["graphic"] = shot["graphic"]
        if patch:
            ops.append({"op": "update_text", "id": f"tt-{cue['id']}", "patch": patch})
    if template == "lower-third-date":   # section label on top; lyrics own the bottom
        ops += [{"op": "update_text", "id": "tt-date", "patch": {"y": 12}},
                {"op": "update_text", "id": "tt-caption", "patch": {"y": 20}}]
    return ops, title_cue_count(template, fields, *span)


def lyric_ops(production: Any, shot: dict, a: float, b: float, dur: float, score: dict, style: dict, used: int) -> list[dict]:
    ops: list[dict] = []
    template = style.get("lyric_template", "social-caption")
    limit = MAX_TEXTS - bool(style.get("footer"))
    for index, line in enumerate(score.get("lines") or []):
        span = lyric_span(line, a, b, dur)
        if span is None:
            continue
        fields = {"line": line["text"]} if template in ("ransom", "dymo") else {"caption": line["text"]}
        cues = title_cue_count(template, fields, *span)
        if used + cues > limit:
            production.log(f"scene {shot.get('key')}: dropped lyrics after {used} text cues")
            break
        used += cues
        ops.append({"op": "add_title", "id": f"ly{index}", "template": template, "fields": fields,
                    "start": span[0], "duration": span[1]})
        own = style.get("lyric_style") or {}
        look = {**theme_lyric_style(style.get("theme")), **(DYMO_READABLE if template == "dymo" and "box" not in own else {}), **own, **seam_look(line, a, b)}
        if look:
            built = TITLE_BUILDERS[template](fields, {"start": span[0], "duration": span[1], "width": 1920, "height": 1080})
            for cue in built:
                ops.append({"op": "update_text", "id": f"ly{index}-{cue['id']}", "patch": look})
    return ops


def footer_ops(dur: float, style: dict) -> list[dict]:
    if not style.get("footer"):
        return []
    colours = theme_colours(style.get("theme"))
    theme_patch = {}
    if colours:
        theme_patch = {"color": colours["fg"], "box": {"kind": "solid", "color": colours["surface"], "opacity": 0.92, "padding": 0.25}}
    return [{"op": "add_title", "id": "footer", "template": "social-caption", "fields": {"caption": str(style["footer"])},
             "start": 0, "duration": dur},
            {"op": "update_text", "id": "footer-social", "patch": {"y": 96, "size": 2, "font": "mono", "maxWidth": 96,
             "color": "#EFE6D2", "box": {"kind": "solid", "color": "#1B1718", "opacity": 0.85, "padding": 0.25},
             **theme_patch, **(style.get("footer_style") or {})}}]

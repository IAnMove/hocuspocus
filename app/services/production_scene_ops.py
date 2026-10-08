"""Title, lyric and footer operations for one Video 2D scene.

``music_production`` keeps ``title_span``, ``lyric_span`` and ``seam_look``. Tests
import those from there. This module is loaded only after that module has finished
importing.
"""
from __future__ import annotations

from typing import Callable

from services.music_production import (
    DYMO_READABLE, lyric_span, seam_look, theme_colours, theme_lyric_style, title_cue_count, title_span,
)
from services.video2d_edit import MAX_TEXTS
from services.video2d_edit_titles import TITLE_BUILDERS


def title_ops(shot: dict, dur: float, style: dict) -> tuple[list[dict], int]:
    span = title_span(dur)
    if not shot.get("title") or not span:
        return [], 0
    template = shot["title"].get("template", "lower-third-date")
    fields = shot["title"]["fields"]
    ops = [{"op": "add_title", "id": "tt", "template": template, "fields": fields, "start": span[0], "duration": span[1]}]
    cues = TITLE_BUILDERS[template](fields, {"start": span[0], "duration": span[1], "width": 1920, "height": 1080})
    for index, cue in enumerate(cues):
        patch = {**(style.get("title_style") or {}), **(shot["title"].get("style") or {}),
                 **((shot["title"].get("cues") or {}).get(cue["id"]) or {})}
        if shot.get("graphic") and index == 0:
            patch["graphic"] = shot["graphic"]
        if patch:
            ops.append({"op": "update_text", "id": f"tt-{cue['id']}", "patch": patch})
    if template == "lower-third-date":
        ops += [{"op": "update_text", "id": "tt-date", "patch": {"y": 12}},
                {"op": "update_text", "id": "tt-caption", "patch": {"y": 20}}]
    return ops, title_cue_count(template, fields, *span)


def lyric_ops(log: Callable[[str], None], shot: dict, a: float, b: float, dur: float, score: dict, style: dict, used: int,
              sections: list[str] | None = None) -> list[dict]:
    """Title cues for the sung lines in this scene. ``sections`` is each score line's song section, for lyric_looks."""
    from services.production_lyric_looks import look_for
    ops: list[dict] = []
    limit = MAX_TEXTS - bool(style.get("footer"))
    sections = sections or []
    for index, line in enumerate(score.get("lines") or []):
        span = lyric_span(line, a, b, dur)
        if span is None:
            continue
        designed = look_for(style, sections[index] if index < len(sections) else "verse")
        template = designed["template"] if designed else style.get("lyric_template", "social-caption")
        fields = {"line": line["text"]} if template in ("ransom", "dymo") else {"caption": line["text"]}
        cues = title_cue_count(template, fields, *span)
        if used + cues > limit:
            log(f"scene {shot.get('key')}: dropped lyrics after {used} text cues")
            break
        used += cues
        ops.append({"op": "add_title", "id": f"ly{index}", "template": template, "fields": fields,
                    "start": span[0], "duration": span[1]})
        look = {**_line_look(designed, template, line, style), **seam_look(line, a, b)}
        if look:
            for cue in TITLE_BUILDERS[template](fields, {"start": span[0], "duration": span[1], "width": 1920, "height": 1080}):
                ops.append({"op": "update_text", "id": f"ly{index}-{cue['id']}", "patch": look})
    return ops


def _line_look(designed: dict | None, template: str, line: dict, style: dict) -> dict:
    """The lyric look for one line: a designed look (its entrance timed to the words), else the theme's; lyric_style on top."""
    from services.production_lyric_looks import synced_enter
    own = style.get("lyric_style") or {}
    if designed:
        synced = synced_enter(designed, line)
        return {**designed["look"], **({"enter": synced} if synced else {}), **own}
    return {**theme_lyric_style(style.get("theme")), **(DYMO_READABLE if template == "dymo" and "box" not in own else {}), **own}


def footer_ops(dur: float, style: dict) -> list[dict]:
    if not style.get("footer"):
        return []
    colours = theme_colours(style.get("theme"))
    return [{"op": "add_title", "id": "footer", "template": "social-caption", "fields": {"caption": str(style["footer"])},
             "start": 0, "duration": dur},
            {"op": "update_text", "id": "footer-social", "patch": {"y": 96, "size": 2, "font": "mono", "maxWidth": 96,
             "color": "#EFE6D2", "box": {"kind": "solid", "color": "#1B1718", "opacity": 0.85, "padding": 0.25},
             **({"color": colours["fg"], "box": {"kind": "solid", "color": colours["surface"], "opacity": 0.92, "padding": 0.25}} if colours else {}),
             **(style.get("footer_style") or {})}}]

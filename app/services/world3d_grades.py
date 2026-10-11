"""Colour grades of a Video 3D document.

A grade is the document ``look`` (tone mapping and exposure), an optional gel over the lamp and screen effects that
already exist (vignette, film grain, vhs, scanlines, light rays). The table is ``app/shared/world3d_modifiers.json``,
shared with ``ui/src/features/scene3d/modifiers.ts``; its screen effects carry ids ``grade-*`` so a later grade
replaces the earlier one and the template's own effects (and a shot's ``shot-*`` ones) stay.
"""
from __future__ import annotations

from services.world3d_modifiers import modifier_tables, tinted

GRADE_FX_PREFIX = "grade-"
GRADE_NAMES = tuple(modifier_tables()["grades"])


def grade_of(name) -> dict:
    grade = modifier_tables()["grades"].get(name) if isinstance(name, str) else None
    if not grade:
        raise ValueError(f"unknown_grade:{name}")
    return grade


def grade_cues(name: str, duration) -> list[dict]:
    """The grade's screen effects over the whole document."""
    return [{"id": f"{GRADE_FX_PREFIX}{cue['kind']}", "kind": cue["kind"], "start": 0, "end": duration, "intensity": cue["intensity"]}
            for cue in grade_of(name)["fx"]]


def apply_grade(document: dict, name: str) -> None:
    """The look, the lamp's gel and the grade's effects. The lamp keeps its ungraded colour (``untinted``) so the next
    grade tints the lamp and not the earlier tint."""
    grade = grade_of(name)
    document["look"] = dict(grade["look"])
    light = dict(document.get("light") or {})
    base = light.pop("untinted", None) or light.get("color")
    if grade.get("tint") and base:
        light["color"], light["untinted"] = tinted(base, grade["tint"]), base
    elif base:
        light["color"] = base
    document["light"] = light
    kept = [cue for cue in document.get("sfx") or [] if not str(cue.get("id", "")).startswith(GRADE_FX_PREFIX)]
    document["sfx"] = kept + grade_cues(name, document.get("duration"))

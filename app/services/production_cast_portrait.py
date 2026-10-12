"""A plain full-body portrait for each cast member.

The cast sheet shows several views on the set, and an image model copies that
as several people. A one-subject portrait is the reference for a shot, and a
group image is built from those portraits rather than from the sheets.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from services.production_image_defaults import image_choice

PHRASE = "single full-body view, plain neutral background, exactly one subject"
PORTRAIT_SIZE = "1024x1536"


def single_prompt(entry: dict, style: str = "") -> str:
    """The portrait prompt: an explicit single_prompt, or the sheet prompt plus the plain-background phrase."""
    own = entry.get("single_prompt")
    if isinstance(own, str) and own.strip():
        text = own.strip()
    else:
        sheet = str(entry.get("sheet_prompt") or "").strip().rstrip(".")
        text = f"{sheet}. {PHRASE}" if sheet else PHRASE
    if style and style not in text:
        text = f"{text} {style}".strip()
    return text


def frame_references(window: dict, cast: dict, singles: dict) -> list[str]:
    """Image refs for a start frame. A portrait replaces its sheet when one exists."""
    ids = [item for item in window.get("cast") or [] if isinstance(item, str) and item in cast]
    return [singles.get(item) or cast[item] for item in ids]


def group_sources(production: Any, members: list) -> list[Path]:
    """Files for a group plate: each member's portrait, or the sheet if the portrait is missing."""
    singles = production.state.get("cast_single") or {}
    cast = production.state.get("cast") or {}
    paths = []
    for member in members:
        url = singles.get(member) or cast.get(member)
        if isinstance(url, str) and url:
            paths.append(production.uploads / Path(url).name)
    return paths


def ensure_portraits(production: Any, spec: dict) -> None:
    """Generate the missing one-subject portraits. A failed portrait does not drop the sheet.

    ``wait`` replaces ``failures``, so a sheet that never arrived keeps the reason
    recorded before this round.
    """
    jobs = _portrait_jobs(production, spec)
    if not jobs:
        return
    kept = dict(getattr(production, "failures", {}) or {})
    singles = production.state.setdefault("cast_single", {})
    for cid, name in production.wait(jobs).items():
        if name:
            singles[cid] = production.upload(name)[1]
            continue
        production.log(f"portrait {cid} failed ({production.failures.get(cid, 'no output')})")
    production.failures = {**kept, **(getattr(production, "failures", {}) or {})}


def _portrait_jobs(production: Any, spec: dict) -> dict:
    singles = production.state.get("cast_single") or {}
    cast = production.state.get("cast") or {}
    settings = spec.get("style") or {}
    style = settings.get("image", "")
    jobs = {}
    for entry in spec.get("cast") or []:
        if not isinstance(entry, dict) or entry.get("group"):
            continue
        cid = entry.get("id")
        if not isinstance(cid, str) or not cid or cid in singles or cid not in cast:
            continue
        jobs[cid] = production.image(
            "cast-single-" + cid, single_prompt(entry, style), None, PORTRAIT_SIZE,
            entry.get("seed", 5), *image_choice(entry, settings),
            production._attempt("cast_single_attempts", cid),
        )
    return jobs

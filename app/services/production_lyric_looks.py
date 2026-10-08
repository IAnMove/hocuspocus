"""Lyric looks: designed type for sung lines, chosen per piece and per song section.

``style.lyric_look`` names one look for the whole song; ``style.lyric_looks`` maps song sections (verse,
chorus, bridge, pre-chorus, intro, outro, default) to looks, so a chorus can land big while the verses stay
quiet. A look (``app/shared/lyric_looks.json``) is a title template plus its type: font, weight, colour,
outline or shadow, a box only where it is part of the design, entrance, loop and place. ``lyric_style``
still overrides single fields on top. With no lyric template, style or look, the finish preset picks the
look that suits it, so a piece no longer falls back to the same flat box.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

SECTIONS = ("default", "intro", "verse", "pre-chorus", "chorus", "bridge", "outro")
_TAG = re.compile(r"^\[([^\]]+)\]$")
_FILE = Path(__file__).resolve().parents[1] / "shared" / "lyric_looks.json"


class LyricLookError(ValueError):
    pass


@lru_cache(maxsize=1)
def looks() -> dict[str, dict]:
    return {entry["id"]: entry for entry in json.loads(_FILE.read_text(encoding="utf-8"))["looks"]}


def check_lyric_looks(style: dict) -> None:
    named = style.get("lyric_look")
    by_section = style.get("lyric_looks")
    if named is not None and named not in looks():
        raise LyricLookError(f"style.lyric_look must be one of {', '.join(looks())}")
    if by_section is None:
        return
    if not isinstance(by_section, dict) or not by_section or set(by_section) - set(SECTIONS):
        raise LyricLookError(f"style.lyric_looks maps sections ({', '.join(SECTIONS)}) to looks")
    unknown = sorted({value for value in by_section.values() if value not in looks()})
    if unknown:
        raise LyricLookError(f"unknown lyric looks {', '.join(map(str, unknown))}; known: {', '.join(looks())}")


def section_of(tag: str) -> str:
    """'[Chorus 2]' -> chorus, '[Pre-Chorus]' -> pre-chorus, '[Verse]' -> verse; anything else is default."""
    words = re.sub(r"[^a-z\- ]", " ", tag.lower()).split()
    name = "-".join(words[:2]) if words[:2] == ["pre", "chorus"] else (words[0] if words else "")
    return name if name in SECTIONS else "default"


def line_sections(lyrics: str) -> list[str]:
    """The song section of each written lyric line, in the order the score numbers them."""
    current, found = "verse", []
    for row in (lyrics or "").split("\n"):
        row = row.strip()
        tag = _TAG.match(row)
        if tag:
            current = section_of(tag.group(1))
        elif row and not re.fullmatch(r"\[[^\]]*\]", row):
            found.append(current)
    return found


def _named(style: dict, section: str) -> str | None:
    by_section = style.get("lyric_looks") or {}
    if section in by_section:
        return by_section[section]
    if section == "pre-chorus" and "verse" in by_section:
        return by_section["verse"]
    if style.get("lyric_look"):
        return style["lyric_look"]
    if by_section.get("default"):
        return by_section["default"]
    if style.get("lyric_template") or style.get("lyric_style") or style.get("theme"):
        return None
    preset = (style.get("finish") or {}).get("preset")
    return next((entry["id"] for entry in looks().values() if preset in entry.get("finish", [])), None)


def look_for(style: dict, section: str) -> dict[str, Any] | None:
    """The look entry for a line of this section, or None to keep the plain template path."""
    name = _named(style, section)
    return looks().get(name) if name else None


def synced_enter(entry: dict[str, Any], line: dict[str, Any]) -> dict[str, Any] | None:
    """A words/letters/typewriter entrance that lasts until the last sung word starts (0.3-3 s)."""
    enter = (entry.get("look") or {}).get("enter")
    if not entry.get("sync") or not enter or not line.get("words"):
        return None
    last = max(float(word.get("t0", line["t0"])) for word in line["words"])
    return {"preset": enter["preset"], "duration": round(min(3.0, max(0.3, last - float(line["t0"]))), 3)}

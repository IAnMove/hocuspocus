"""Character style presets shared by the Character Creator and MCP (``app/shared/character_styles.json``).

A preset holds the prompt fragments that keep a cast consistent (character,
new pose, prop, plain screen background) and the default mouth look for
``characters.rig.flat``. The screen colour is green unless the description
mentions green, then magenta, because keying green removes green clothes.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG = Path(__file__).resolve().parents[1] / "shared" / "character_styles.json"
KINDS = ("character", "pose", "prop")


@lru_cache(maxsize=1)
def style_catalog() -> dict[str, Any]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def character_style(style_id: str) -> dict[str, Any]:
    for style in style_catalog()["styles"]:
        if style["id"] == style_id:
            return style
    raise KeyError(style_id)


def screen_for(description: str) -> str:
    """``magenta`` when the subject has green in it, else ``green``."""
    text = str(description or "").lower()
    return "magenta" if any(re.search(rf"\b{re.escape(word)}", text) for word in style_catalog()["greenWords"]) else "green"


def style_prompt(style_id: str, kind: str, description: str, screen: str | None = None) -> dict[str, str]:
    """Prompt, negative prompt and screen for one generation in this style."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    style = character_style(style_id)
    screen = screen or screen_for(description)
    background = style["background"].replace("{screen}", style_catalog()["screens"][screen])
    prompt = style[kind].replace("{description}", " ".join(str(description or "").split())).strip()
    return {"prompt": f"{prompt} {background}", "negative": style["negative"], "screen": screen}

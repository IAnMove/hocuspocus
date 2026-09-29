"""Turn an eight-field brief into a production spec. Lyrics are the caller's, or a short draft."""
from __future__ import annotations

import re
from typing import Any, Callable

from services.production_shot_plan import plan_shots
from services.production_style_presets import expand_style_preset

_FIELDS = (
    (("tema", "theme"), "tema"),
    (("publico", "audience"), "publico"),
    (("duracion", "duration"), "duracion"),
    (("musica", "music"), "musica"),
    (("estilo", "style"), "estilo"),
    (("protagonista", "protagonist"), "protagonista"),
    (("cta", "cta"), "cta"),
    (("limites", "limits"), "limites"),
)


class PlanError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def plan_brief(brief: Any, lyricist: Callable[[dict], str] | None = None) -> dict:
    """Return a spec with shots expanded. Every required brief field is a non-empty string."""
    fields = _fields(brief)
    lyrics = _lyrics_text(fields, lyricist)
    duration = _duration(fields["duracion"])
    bpm = _bpm(fields["musica"])
    spec = {
        "title": _title(fields["tema"]),
        "song": {"lyrics": lyrics, "caption": _clip(fields["musica"], 32), "duration": duration, "bpm": bpm},
        "style": {"preset": _preset(fields["estilo"])},
        "cast": [{"id": "hero", "sheet_prompt": fields["protagonista"][:400]}],
        "shots": "auto",
        "section_actions": {"verse": _clip(fields["tema"], 32), "chorus": _clip(fields["cta"], 32)},
    }
    from services.music_production import ProductionError
    try:
        expanded = expand_style_preset(spec)
    except ProductionError as error:
        raise PlanError(error.code, str(error)) from error
    return plan_shots(expanded)


def _fields(brief: Any) -> dict[str, str]:
    if not isinstance(brief, dict):
        raise PlanError("invalid_brief", "brief must be an object")
    found = {}
    missing = []
    for names, label in _FIELDS:
        value = next((brief.get(name).strip() for name in names if isinstance(brief.get(name), str) and brief.get(name).strip()), "")
        if not value:
            missing.append(label)
        found[label] = value
    if missing:
        raise PlanError("invalid_brief", "brief needs " + ", ".join(missing))
    lyrics = brief.get("lyrics")
    if isinstance(lyrics, str) and lyrics.strip():
        found["lyrics"] = lyrics.strip()
    return found


def _lyrics_text(fields: dict, lyricist: Callable[[dict], str] | None) -> str:
    if fields.get("lyrics"):
        return fields["lyrics"]
    if lyricist is not None:
        written = lyricist(fields)
        if isinstance(written, str) and written.strip():
            return written.strip()
    return _draft_lyrics(fields["tema"], fields["cta"])


def _draft_lyrics(theme: str, cta: str) -> str:
    verse = "\n".join(_line(theme, index) for index in range(4))
    chorus = "\n".join(_line(cta, index) for index in range(4))
    return f"[Intro]\n[Verse]\n{verse}\n[Chorus]\n{chorus}\n[Outro]\n"


def _line(text: str, index: int) -> str:
    words = re.findall(r"[A-Za-z0-9']+", text) or ["song"]
    return f"{' '.join(words[:4])[:24]} {index + 1}"[:32]


def _title(theme: str) -> str:
    title = ""
    for word in re.findall(r"[A-Za-z0-9']+", theme):
        nxt = word if not title else f"{title} {word}"
        if len(nxt) > 12:
            break
        title = nxt
    return (title or "Video")[:12]


def _clip(text: str, limit: int) -> str:
    words = text.split()
    out = ""
    for word in words:
        nxt = word if not out else f"{out} {word}"
        if len(nxt) > limit:
            break
        out = nxt
    return (out or text)[:limit]


def _duration(text: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return 48.0
    value = float(match.group(1))
    if re.search(r"min", text, re.IGNORECASE):
        value *= 60.0
    return min(180.0, max(16.0, value))


def _bpm(text: str) -> int:
    """Read an explicit BPM. Bare numbers are sample rates (48k) or decades (90s)."""
    match = re.search(r"(?<![A-Za-z0-9])(\d{2,3})\s*bpm\b", text, re.IGNORECASE) or re.search(
        r"\bbpm\s*[=:]?\s*(\d{2,3})\b", text, re.IGNORECASE
    )
    if not match:
        return 120
    bpm = int(match.group(1))
    return bpm if 60 <= bpm <= 200 else 120


def _preset(style: str) -> str:
    text = style.lower()
    if any(word in text for word in ("omarchy", "escritorio", "desktop")):
        return "omarchy-desktop"
    if any(word in text for word in ("riso", "zine", "caricatura", "caricature")):
        return "riso-zine"
    if "noir" in text:
        return "neo-noir-realista"
    return "anime"

"""Turn an eight-field brief into a production spec. Lyrics are the caller's: the plan does not invent them."""
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
    trailer = fields.get("structure") == "trailer"
    lyrics = "" if trailer and not fields.get("lyrics") else _lyrics_text(fields, lyricist)     # a trailer may be instrumental
    duration = _duration(fields["duracion"])
    bpm = _bpm(fields["musica"])
    spec = {
        "title": _title(fields["tema"]),
        "song": {"lyrics": lyrics, "caption": _clip(fields["musica"], 32), "duration": duration, "bpm": bpm},
        "style": {"preset": _preset(fields["estilo"]), **({"footer": fields["footer"]} if fields.get("footer") else {})},
        "cast": [{"id": "hero", "sheet_prompt": fields["protagonista"][:400]}],
        "shots": "auto",
        "cta": _clip(fields["cta"], 32),
        "quality": fields.get("quality") if fields.get("quality") in ("draft", "standard", "max") else "standard",
        **({"structure": "trailer"} if trailer else {}),
        **({"treatment": fields["treatment"]} if fields.get("treatment") else {}),
        "section_actions": {"verse": _clip(fields["tema"], 32), "chorus": _clip(fields["cta"], 32)},
    }
    from services.music_production import ProductionError
    try:
        expanded = expand_style_preset(spec)
    except ProductionError as error:
        raise PlanError(error.code, str(error)) from error
    query = _world3d_query(brief)
    if query:
        return _plan_world3d_shot(expanded, brief, query)
    return plan_shots(expanded)


def _world3d_query(brief: Any) -> str:
    if not isinstance(brief, dict):
        return ""
    for name in ("world3d", "toma"):
        value = brief.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _plan_world3d_shot(spec: dict, brief: dict, query: str) -> dict:
    """Place one real template id. A tied search is refused instead of inventing a shot."""
    from services.world3d_template_catalog import search_templates
    hits = search_templates(query, limit=8)
    if not hits:
        raise PlanError("unknown_template", f"No Video 3D template matches {query}")
    if len(hits) > 1 and hits[0]["score"] == hits[1]["score"]:
        names = ", ".join(str(item["id"]) for item in hits[:8])
        raise PlanError("ambiguous_template", f"Several templates match {query}: {names}")
    chosen = hits[0]
    speed = float(chosen.get("playbackSpeed") or 1)
    native = float(chosen.get("duration") or 6) / speed
    window = min(float(spec["song"]["duration"]), max(1.0, native))
    scene3d: dict[str, Any] = {"template": chosen["id"]}
    subject = _optional_text(brief, ("world3d_subject", "sujeto_3d"))
    if subject:
        scene3d["subject"] = subject
    planned = dict(spec)
    planned["shots"] = [{"key": "world3d", "kind": "scene3d", "t0": 0, "t1": round(window, 3), "scene3d": scene3d}]
    planned["world3d_template"] = chosen["id"]
    return planned


def _optional_text(brief: dict, names: tuple[str, ...]) -> str:
    for name in names:
        value = brief.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _fields(brief: Any) -> dict[str, Any]:
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
    for optional, names in (("lyrics", ("lyrics", "letra")), ("footer", ("footer", "aviso")), ("quality", ("quality", "calidad")),
                               ("structure", ("structure", "estructura"))):
        value = next((brief[name].strip() for name in names if isinstance(brief.get(name), str) and brief[name].strip()), "")
        if value:
            found[optional] = value
    treatment = brief.get("treatment", brief.get("tratamiento"))
    if isinstance(treatment, dict) and treatment:
        found["treatment"] = treatment              # validated by validate_spec: the plan only carries it
    return found


def _lyrics_text(fields: dict, lyricist: Callable[[dict], str] | None) -> str:
    """The caller's words, or a lyricist's. The plan never invents placeholder lines: ACE-Step would sing them."""
    if fields.get("lyrics"):
        return fields["lyrics"]
    if lyricist is not None:
        written = lyricist(fields)
        if isinstance(written, str) and written.strip():
            return written.strip()
    raise PlanError("invalid_brief", "brief needs lyrics: the plan does not write placeholder lines that a singer would perform")


def _title(theme: str) -> str:
    title = ""
    for word in re.findall(r"[\w']+", theme):
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
    """Seconds from "75 s", "1.5 min", "2 minutos" or "1:30". Clamped to 16-180 s; 48 s when there is no number."""
    clock = re.search(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])", text)
    if clock:
        return min(180.0, max(16.0, int(clock.group(1)) * 60.0 + int(clock.group(2))))
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(min|m\b)?", text, re.IGNORECASE)
    if not match:
        return 48.0
    value = float(match.group(1).replace(",", "."))
    if match.group(2):
        value *= 60.0
    return min(180.0, max(16.0, value))


def _bpm(text: str) -> int:
    """Tempo from "124 BPM", "BPM: 95", or "110-125 bpm" (the middle).

    Sample rates (48k, 44.1k, 96k) and decades (2000s) are not tempos.
    """
    span = re.search(r"(\d{2,3})(?:\s*[-–]\s*(\d{2,3}))?\s*bpm\b", text, re.IGNORECASE)
    if span:
        low = int(span.group(1))
        high = int(span.group(2) or low)
        bpm = round((low + high) / 2)
        return bpm if 40 <= bpm <= 220 else 120
    labeled = re.search(r"\bbpm\s*[=:]?\s*(\d{2,3})\b", text, re.IGNORECASE)
    if labeled:
        bpm = int(labeled.group(1))
        return bpm if 60 <= bpm <= 200 else 120
    for found in re.finditer(r"(?<![\d.:])(\d{2,3})(?![\d.:kK])(?!\s*k\b)(?!\s*s\b)(?!s)", text):
        bpm = int(found.group(1))
        if 60 <= bpm <= 200:
            return bpm
    return 120


_LOOKS = (
    ("anime", ("anime", "manga", "cel")),
    ("riso-zine", ("riso", "zine", "caricatura", "caricature")),
    ("neo-noir-realista", ("noir",)),
    ("omarchy-desktop", ("omarchy", "escritorio", "desktop")),
)


def _preset(style: str) -> str:
    """An explicit look word wins over a subject word: "zine riso sobre Omarchy" is a zine, not a desktop."""
    text = style.lower()
    for preset, words in _LOOKS:
        if any(re.search(rf"\b{re.escape(word)}", text) for word in words):
            return preset
    return "anime"

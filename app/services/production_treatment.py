"""Treatment: what happens in the video, not only how it looks.

A spec that says "cinematic, cyberpunk, dramatic light" leaves every decision open. ``spec.treatment`` is the short
account the language model writes before any shot: what changes between the first and the last image, what the
protagonist wants and what stands in the way, the few memorable moments and where they land, and the motifs that come
back. HocusPocus does not judge the idea; it checks that the plan carries it:

* a moment that lands where no shot is (``moment_without_shot``);
* a chorus that comes back with exactly the same shots (``chorus_repeats_identical``): repeating an image is fine,
  repeating it unchanged is what makes a clip feel like a slide show;
* (only at ``quality: "max"``) no treatment at all (``treatment_missing``).

``shots: "auto"`` uses it too: each moment's event is written into the action of the shot that covers it, and a
chorus that returns is varied (wider, closer, a consequence, bigger) in production_shot_plan.
"""
from __future__ import annotations

import json
import re
from typing import Any

MAX_MOMENTS = 12
MAX_MOTIFS = 6
TEXT_LIMIT = 600
EVENT_LIMIT = 300
SAME_SHARE = 0.8        # how alike two choruses must be (share of identical shots) to be reported
TRAILER_BEATS = ("presentation", "tension", "escalation", "reveal", "close")
_HEADER = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_AT = re.compile(r"^(?P<role>[a-z][a-z-]*?)(?P<nth>\d+)?$")
# How a chorus that returns is told apart from the first one; production_shot_plan writes them into the action.
VARIATIONS = (
    "Same place as the first chorus, but wider, with more of the set and more characters visible.",
    "A closer, more energetic angle than before; new lighting, the same place.",
    "A consequence of what has happened: something in the scene is different now.",
    "The biggest version so far: maximum scale, motion and light.",
)


class TreatmentError(ValueError):
    code = "invalid_spec"


# ---------------------------------------------------------------- validation
def _text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TreatmentError(f"treatment.{label} must be a non-empty string")
    if len(value) > limit:
        raise TreatmentError(f"treatment.{label} is over {limit} characters")
    return value.strip()


def validate_treatment(raw: Any) -> dict | None:
    """The treatment as stored, or None when the spec has none. Raises TreatmentError for a malformed one."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TreatmentError("treatment must be an object")
    known = {"arc", "want", "obstacle", "moments", "motifs"}
    if set(raw) - known:
        raise TreatmentError("treatment has unknown fields: " + ", ".join(sorted(set(raw) - known)))
    treatment: dict[str, Any] = {key: _text(raw[key], key, TEXT_LIMIT) for key in ("arc", "want", "obstacle") if raw.get(key) is not None}
    moments = raw.get("moments", [])
    if not isinstance(moments, list) or len(moments) > MAX_MOMENTS:
        raise TreatmentError(f"treatment.moments must be a list of at most {MAX_MOMENTS}")
    treatment["moments"] = [_moment(item, index) for index, item in enumerate(moments)]
    ids = [moment["id"] for moment in treatment["moments"]]
    if len(set(ids)) != len(ids):
        raise TreatmentError("treatment.moments ids must be unique")
    motifs = raw.get("motifs", [])
    if not isinstance(motifs, list) or len(motifs) > MAX_MOTIFS or not all(isinstance(m, str) and 0 < len(m) <= 80 for m in motifs):
        raise TreatmentError(f"treatment.motifs must be up to {MAX_MOTIFS} short strings")
    treatment["motifs"] = list(motifs)
    if not treatment.get("arc") and not treatment["moments"]:
        raise TreatmentError("treatment needs an arc or at least one moment")
    return treatment


def _moment(item: Any, index: int) -> dict:
    if not isinstance(item, dict) or set(item) - {"at", "event", "id"}:
        raise TreatmentError(f"treatment.moments[{index}] needs at and event")
    at = item.get("at")
    if isinstance(at, bool) or not isinstance(at, (str, int)) or (isinstance(at, str) and not at.strip()):
        raise TreatmentError(f"treatment.moments[{index}].at must be a section (chorus2), line:N or a trailer beat")
    identity = str(item.get("id") or f"m{index + 1}")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", identity):
        raise TreatmentError(f"treatment.moments[{index}].id must be letters, digits, - or _")
    return {"id": identity, "at": at if isinstance(at, int) else at.strip().lower(), "event": _text(item.get("event"), f"moments[{index}].event", EVENT_LIMIT)}


# ---------------------------------------------------------------- where a moment lands
def lyric_sections(lyrics: str) -> list[dict]:
    """Sections of a lyric by header: name, role, nth occurrence of that role, first line and line count."""
    sections: list[dict] = []
    current = None
    seen: dict[str, int] = {}
    index = 0
    for raw in (lyrics or "").splitlines():
        header = _HEADER.match(raw)
        if header:
            name = header.group(1).strip().lower().replace(" ", "-")
            role = _role(name)
            seen[role] = seen.get(role, 0) + 1
            current = {"name": name, "role": role, "nth": seen[role], "start": index, "count": 0}
            sections.append(current)
            continue
        if not re.sub(r"\[[^\]]*\]", "", raw).strip():
            continue
        if current is None:
            seen["verse"] = seen.get("verse", 0) + 1
            current = {"name": "verse", "role": "verse", "nth": seen["verse"], "start": index, "count": 0}
            sections.append(current)
        current["count"] += 1
        index += 1
    return sections


def _role(name: str) -> str:
    words = name.split("-")
    if "pre" in words and any(word.startswith("chorus") for word in words):
        return "pre-chorus"
    if any(word.startswith("chorus") or word in {"hook", "refrain"} for word in words):
        return "chorus"
    for role in ("intro", "outro", "bridge", "verse"):
        if words[0].startswith(role):
            return role
    return "end" if words[0] in {"end", "ending"} else words[0]


def resolve_at(at: Any, sections: list[dict], structure: str = "clip") -> tuple[int, int] | str | None:
    """Lines (first, last) a moment lands on; a trailer beat name in trailer mode; None when it matches nothing."""
    if isinstance(at, int):
        return (at, at)
    text = str(at)
    if structure == "trailer" and text in TRAILER_BEATS:
        return text
    if text.startswith("line:") and text[5:].isdigit():
        return (int(text[5:]), int(text[5:]))
    found = _AT.match(text)
    if not found:
        return None
    role, nth = found.group("role"), int(found.group("nth") or 1)
    for section in sections:
        if section["role"] == role and section["nth"] == nth and section["count"]:
            return (section["start"], section["start"] + section["count"] - 1)
    return None


def moments_of(spec: dict) -> list[dict]:
    """The treatment's moments with the lines (or beat) they resolve to. Unresolved ones keep ``lines: None``."""
    try:
        treatment = validate_treatment(spec.get("treatment")) or {}     # the plan runs before validate_spec: accept raw, ignore malformed
    except TreatmentError:
        return []
    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    sections = lyric_sections(str(song.get("lyrics") or ""))
    structure = str(spec.get("structure") or "clip")
    return [{**moment, "lines": resolve_at(moment["at"], sections, structure)} for moment in treatment.get("moments") or []]


def unresolved_moments(spec: dict) -> list[str]:
    return [moment["id"] for moment in moments_of(spec) if moment["lines"] is None]


# ---------------------------------------------------------------- what the plan does with it
def shot_lines(shot: dict) -> tuple[int, int] | None:
    line = shot.get("line")
    if isinstance(line, int):
        span = shot.get("span") if isinstance(shot.get("span"), int) and shot["span"] > 0 else 1
        return (line, line + span - 1)
    return None


def shots_on(shots: list[dict], first: int, last: int) -> list[dict]:
    return [shot for shot in shots if (lines := shot_lines(shot)) and lines[0] <= last and lines[1] >= first]


def annotate_moments(spec: dict, shots: list[dict]) -> list[dict]:
    """Write each moment into the shot that covers its first line: ``moment`` id, and for generated shots its event in
    the action. Returns a new list; shots the moment does not reach are untouched."""
    out = [dict(shot) for shot in shots]
    for moment in moments_of(spec):
        if not isinstance(moment["lines"], tuple):
            continue
        for shot in shots_on(out, *moment["lines"])[:1]:
            shot["moment"] = moment["id"]
            if shot.get("kind") in ("h3", "scene3d") and shot.get("action"):
                shot["action"] = f"{shot['action'].rstrip()} Key moment: {moment['event']}"
    return out


def _plain(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _signature(shot: dict) -> str:
    """What makes two shots the same shot to a viewer: kind, picture, action, framing. A variation phrase is a difference."""
    keyed = {"kind": shot.get("kind"), "frame": _plain(shot.get("frame")), "action": _plain(shot.get("action")), "still": shot.get("still"),
             "clip": shot.get("clip"), "desktop": shot.get("desktop"), "scene3d": shot.get("scene3d"), "zoom": shot.get("zoom"),
             "camera": shot.get("camera")}
    return json.dumps(keyed, sort_keys=True, default=str)


def _occurrences(spec: dict, shots: list[dict], role: str) -> list[tuple[str, list[dict]]]:
    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    found = []
    for section in lyric_sections(str(song.get("lyrics") or "")):
        if section["role"] == role and section["count"]:
            found.append((f"{role}{section['nth']}", shots_on(shots, section["start"], section["start"] + section["count"] - 1)))
    return found


def variation_warnings(spec: dict, shots: list[dict]) -> list[dict]:
    """A chorus that returns with (nearly) the same shots as an earlier one."""
    warnings = []
    seen: list[tuple[str, set[str], list[dict]]] = []
    for name, covered in _occurrences(spec, shots, "chorus"):
        signatures = {_signature(shot) for shot in covered}
        if not signatures:
            continue
        for earlier, before, earlier_shots in seen:
            if len(signatures & before) / max(len(signatures), len(before)) >= SAME_SHARE:
                warnings.append({"code": "chorus_repeats_identical", "sections": [earlier, name],
                                 "shots": [shot.get("key") for shot in [*earlier_shots, *covered]],
                                 "hint": "change the framing, add a consequence or more characters, or a transformation"})
                break
        seen.append((name, signatures, covered))
    return warnings


def moment_warnings(spec: dict, shots: list[dict]) -> list[dict]:
    warnings = []
    for moment in moments_of(spec):
        lines = moment["lines"]
        if lines is None:
            warnings.append({"code": "moment_unresolved", "moment": moment["id"], "at": moment["at"]})
        elif isinstance(lines, tuple) and not shots_on(shots, *lines) and not any(shot.get("moment") == moment["id"] for shot in shots):
            warnings.append({"code": "moment_without_shot", "moment": moment["id"], "at": moment["at"], "lines": list(lines)})
        elif isinstance(lines, str) and not any(shot.get("moment") == moment["id"] or shot.get("beat") == lines for shot in shots):
            warnings.append({"code": "moment_without_shot", "moment": moment["id"], "at": moment["at"]})
    return warnings


def treatment_warnings(spec: dict, shots: list[dict]) -> list[dict]:
    """All the treatment checks for dry_run."""
    if not spec.get("treatment"):
        return [{"code": "treatment_missing", "hint": "say what changes from the first image to the last (spec.treatment)"}] if spec.get("quality") == "max" else []
    try:
        spec = {**spec, "treatment": validate_treatment(spec["treatment"])}
    except TreatmentError as error:                      # dry_run sees the spec before validate_spec does
        return [{"code": "treatment_invalid", "message": str(error)}]
    return [*moment_warnings(spec, shots), *variation_warnings(spec, shots)]


def require_treatment(spec: dict) -> dict:
    """validate_spec hook: the spec with its treatment normalised, or a ProductionError for a malformed one."""
    if "treatment" not in spec:
        return spec
    try:
        treatment = validate_treatment(spec["treatment"])
    except TreatmentError as error:
        from services.music_production import ProductionError
        raise ProductionError(error.code, str(error)) from error
    return {**spec, "treatment": treatment}

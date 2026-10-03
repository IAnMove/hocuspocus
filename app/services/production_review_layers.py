"""Three review layers for production.status.

execution: the final file exists and can be opened.
technical: the code checks, plus a smoothness watch or fail.
artistic: never an automatic ok. It lists the contact sheet, the animatic,
and the start frames, and stays pending for a person.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def pending_review() -> dict[str, Any]:
    """What status returns before a run is finished. Nothing is invented."""
    return {
        "review": {
            "execution": {"verdict": "unreliable"},
            "technical": {"verdict": "unreliable", "failures": [], "unknown": ["appearance_changed"]},
            "artistic": {"verdict": "pending", "evidence": _empty_evidence()},
        },
        "retake_keys": [],
    }


def apply(packed: dict, state: Any, execution: str, root: str | None = None) -> dict:
    """Wrap the code-check pack. A smoothness failure does not add retake keys."""
    flat = packed.get("review") if isinstance(packed.get("review"), dict) else {}
    smooth = _smooth(state)
    technical: dict[str, Any] = {
        "verdict": _combine(flat.get("verdict"), smooth),
        "failures": list(flat.get("failures") or []),
        "unknown": list(flat.get("unknown") or []),
    }
    if smooth and technical["verdict"] in {"watch", "fail"}:
        technical["smoothness"] = smooth
    packed["review"] = {
        "execution": {"verdict": execution},
        "technical": technical,
        "artistic": {"verdict": artistic_verdict(state, root), "evidence": evidence(state)},
    }
    return packed


def evidence(state: Any) -> dict[str, Any]:
    """Names only. No image bytes."""
    if not isinstance(state, dict):
        return _empty_evidence()
    frames = []
    raw = state.get("frames")
    if isinstance(raw, dict):
        for key, name in raw.items():
            if isinstance(key, str) and isinstance(name, str) and name:
                frames.append({"key": key, "file": name})
            if len(frames) >= 8:
                break
    return {
        "contact_sheet": _file_name(state.get("contact_sheet")),
        "animatic": _file_name(state.get("animatic_video")),
        "frames": frames,
    }


def _combine(code: Any, smooth: dict | None) -> str:
    level = _smooth_level(smooth)
    if code == "retake" or level == "fail":
        return "fail"
    if level == "watch":
        return "watch"
    if code == "ok":
        return "ok"
    return "unreliable"


def _smooth_level(smooth: dict | None) -> str | None:
    if not smooth:
        return None
    levels = set((smooth.get("stages") or {}).values())
    if "fail" in levels:
        return "fail"
    if "watch" in levels:
        return "watch"
    return None


def _smooth(state: Any) -> dict | None:
    if not isinstance(state, dict) or not state.get("smoothness"):
        return None
    from services.production_smoothness import for_status

    shown = for_status(state)
    return shown or None


def _file_name(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        return None
    return value


def _empty_evidence() -> dict[str, Any]:
    return {"contact_sheet": None, "animatic": None, "frames": []}


def artistic_verdict(state: Any, root: str | None = None) -> str:
    """pending until a review says otherwise. Never an automatic ok."""
    shots = _shot_map(state, root)
    if not isinstance(shots, dict) or not shots:
        return "pending"
    statuses = [_status(item) for item in shots.values()]
    if "changes_requested" in statuses:
        return "changes_requested"
    if all(item == "approved" for item in statuses):
        return "approved_by_review"
    return "pending"


def cache_token(state: Any, root: str | None = None) -> tuple:
    """Shot statuses, so a new review.json is not served from the old pending cache."""
    shots = _shot_map(state, root) or {}
    if not isinstance(shots, dict):
        return ()
    pairs = ((str(key), _status(value)) for key, value in shots.items() if isinstance(key, str))
    return tuple(sorted(pairs))


def _shot_map(state: Any, root: str | None) -> dict | None:
    if isinstance(state, dict) and isinstance(state.get("review_shots"), dict):
        return state["review_shots"]
    path = _review_file(state, root)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    shots = data.get("shots") if isinstance(data, dict) else None
    return shots if isinstance(shots, dict) else None


def _review_file(state: Any, root: str | None) -> Path | None:
    if not isinstance(root, str) or not root:
        return None
    base = Path(root)
    pid = _production_id(state)
    if pid:
        path = base / f"{pid}.review.json"
        return path if path.is_file() else None
    found = [item for item in base.glob("*.production.json") if item.is_file()]
    if len(found) != 1:
        return None
    sibling = base / f"{found[0].name.removesuffix('.production.json')}.review.json"
    return sibling if sibling.is_file() else None


def _production_id(state: Any) -> str | None:
    if not isinstance(state, dict):
        return None
    for key in ("production_id", "id"):
        value = state.get(key)
        if isinstance(value, str) and _ID.fullmatch(value):
            return value
    return None


def _status(item: Any) -> str:
    if isinstance(item, dict) and isinstance(item.get("status"), str):
        return item["status"]
    return ""

"""Three review layers for production.status.

execution: the final file exists and can be opened.
technical: the code checks, plus a smoothness watch or fail.
artistic: never an automatic ok. It lists the contact sheet, the animatic,
and the start frames, and stays pending for a person.
"""
from __future__ import annotations

from typing import Any


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


def apply(packed: dict, state: Any, execution: str) -> dict:
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
        "artistic": {"verdict": "pending", "evidence": evidence(state)},
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

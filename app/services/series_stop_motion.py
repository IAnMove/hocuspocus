"""Optional stop-motion on a Series shot: the picture holds every N frames.

``motionStep`` is 2, 3 or 4. ``stopMotionJitter`` is a deterministic shake of
0–2 px per hold. Absent, both are omitted and the shot is unchanged. The
exporters quantize animation time; they do not touch the audio.
"""
from __future__ import annotations

from typing import Any

STEPS = (2, 3, 4)


def motion_step(value: Any) -> int | None:
    """``None`` when the field is absent. Anything else must be 2, 3 or 4."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or int(value) not in STEPS:
        raise ValueError("motionStep must be 2, 3 or 4")
    return int(value)


def jitter_px(value: Any) -> float | None:
    """``None`` when absent or zero. A set value is 0–2 px."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 2:
        raise ValueError("stopMotionJitter must be from 0 to 2")
    rounded = round(float(value), 3)
    return rounded or None


def layout_fields(shot: dict[str, Any]) -> dict[str, Any]:
    """The fields a script shot stores. Empty when both are absent."""
    found: dict[str, Any] = {}
    step = motion_step(shot.get("motionStep"))
    shake = jitter_px(shot.get("stopMotionJitter"))
    if step:
        found["motionStep"] = step
    if shake:
        found["stopMotionJitter"] = shake
    return found


def check_shot(shot: dict[str, Any], where: str, problems: list[str]) -> None:
    try:
        layout_fields(shot if isinstance(shot, dict) else {})
    except ValueError as error:
        problems.append(f"{where}: {error}")


def read_fields(shot: dict[str, Any] | None) -> dict[str, Any]:
    """Stored fields for a render. A bad value is ignored, so an old shot still renders."""
    if not isinstance(shot, dict):
        return {}
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    source = {
        "motionStep": layout.get("motionStep", shot.get("motionStep")),
        "stopMotionJitter": layout.get("stopMotionJitter", shot.get("stopMotionJitter")),
    }
    try:
        return layout_fields(source)
    except ValueError:
        return {}

"""Progress and ETA for production.status. ETA is measured or null."""
from __future__ import annotations

from typing import Any

from services.production_estimate import history_clip_median, history_scene_median


def progress_summary(state: dict, root: str | None = None) -> dict[str, Any]:
    """``stage`` plus clip and scene counts. ``eta_s`` is null when nothing was measured."""
    spec_state = state if isinstance(state, dict) else {}
    clips_total = _h3_total(spec_state)
    clips_landed = _landed(spec_state)
    scenes_total = _scene_total(spec_state)
    scenes_done = _scenes_done(spec_state)
    return {
        "stage": _stage(spec_state),
        "clips": {"landed": clips_landed, "total": clips_total, "eta_s": _eta(clips_total, clips_landed, _clip_rate(spec_state, root))},
        "scenes": {"done": scenes_done, "total": scenes_total, "eta_s": _eta(scenes_total, scenes_done, _scene_rate(spec_state, root))},
    }


def _stage(state: dict) -> str | None:
    stage = state.get("stage")
    return stage if isinstance(stage, str) and stage else None


def _h3_total(state: dict) -> int:
    spec = state.get("spec") if isinstance(state.get("spec"), dict) else {}
    shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
    fill = spec.get("fill") if isinstance(spec.get("fill"), list) else []
    return sum(1 for shot in (*shots, *fill) if isinstance(shot, dict) and shot.get("kind") == "h3")


def _landed(state: dict) -> int:
    clips = state.get("clips")
    return len(clips) if isinstance(clips, dict) else 0


def _scene_total(state: dict) -> int:
    segments = state.get("segments")
    return len(segments) if isinstance(segments, list) else 0


def _scenes_done(state: dict) -> int:
    scenes = state.get("scenes")
    if not isinstance(scenes, dict):
        return 0
    return sum(1 for scene in scenes.values() if isinstance(scene, dict) and scene.get("file"))


def _eta(total: int, done: int, rate: float | None) -> int | None:
    remaining = total - done
    if remaining <= 0:
        return 0
    if rate is None or rate <= 0:
        return None
    return int(round(remaining * rate))


def _clip_rate(state: dict, root: str | None) -> float | None:
    measured = _median(_clip_values(state))
    if measured is not None and measured > 0:
        return measured
    return history_clip_median(root)


def _clip_values(state: dict) -> list:
    raw = state.get("clip_seconds")
    if isinstance(raw, dict) and raw:
        return list(raw.values())
    timing = state.get("timing") if isinstance(state.get("timing"), dict) else {}
    rows = timing.get("shots") if isinstance(timing.get("shots"), list) else []
    return [row.get("seconds") for row in rows if isinstance(row, dict)]


def _scene_rate(state: dict, root: str | None) -> float | None:
    explicit = state.get("scene_seconds")
    measured = _median(list(explicit.values())) if isinstance(explicit, dict) and explicit else None
    if measured is not None and measured > 0:
        return measured
    timing = state.get("timing") if isinstance(state.get("timing"), dict) else {}
    done = _scenes_done(state)
    total = timing.get("scenes")
    if done > 0 and isinstance(total, (int, float)) and not isinstance(total, bool) and total > 0:
        return float(total) / done
    return history_scene_median(root)


def _median(values: list) -> float | None:
    nums = sorted(item for item in values if _finite(item))
    if not nums:
        return None
    mid = len(nums) // 2
    if len(nums) % 2:
        return float(nums[mid])
    return (float(nums[mid - 1]) + float(nums[mid])) / 2


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value >= 0 and value == value

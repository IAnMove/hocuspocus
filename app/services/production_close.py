"""Record one run when Production.run finishes. The branch stays in this module."""
from __future__ import annotations

from typing import Any

_STAGES = ("song", "analyze", "cast", "models", "frames", "clips", "scenes", "montage")


def note_resume(production: Any) -> None:
    """Keys that already had a clip file before this run. A fresh run stores an empty list."""
    clips = production.state.get("clips") if isinstance(production.state.get("clips"), dict) else {}
    production.state["kept_clips"] = [key for key, clip in clips.items() if isinstance(clip, dict) and clip.get("file")]


def close_run(production: Any, retake: tuple | list = ()) -> None:
    note_run(production, retake)
    if production.state.get("status") == "completed":
        from services.production_estimate import record_observation
        record_observation(production.root, production.state)


def note_run(production: Any, retake: tuple | list) -> None:
    runs = production.state.get("runs")
    if not isinstance(runs, list):
        runs = []
    timing = production.state.get("timing") if isinstance(production.state.get("timing"), dict) else {}
    runs.append({
        "started": production.state.get("started"),
        "finished": production.state.get("finished"),
        "retake": [item for item in retake if isinstance(item, str)][:20],
        "timing": {name: timing.get(name, 0) for name in _STAGES},
    })
    production.state["runs"] = runs[-12:]

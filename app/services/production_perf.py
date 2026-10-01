"""Copy H3 job performance onto the production. Absent performance adds no keys."""
from __future__ import annotations

from typing import Any


def remember_performance(state: dict, key: str, job: Any) -> None:
    """Store s_per_step, degraded and model only when the job payload has a performance object."""
    if not isinstance(state, dict) or not isinstance(job, dict) or not isinstance(job.get("performance"), dict):
        return
    perf = job["performance"]
    step = perf.get("s_per_step")
    model = perf.get("model")
    state.setdefault("clip_perf", {})[str(key)] = {
        "s_per_step": float(step) if isinstance(step, (int, float)) and not isinstance(step, bool) else None,
        "degraded": perf.get("degraded") if isinstance(perf.get("degraded"), bool) else None,
        "model": model[:80] if isinstance(model, str) and model else None,
    }


def shot_fields(perf: Any) -> dict[str, Any]:
    """The three published fields. Missing ones are null. No performance object means no fields."""
    if not isinstance(perf, dict):
        return {}
    step = perf.get("s_per_step")
    model = perf.get("model")
    return {
        "s_per_step": float(step) if isinstance(step, (int, float)) and not isinstance(step, bool) else None,
        "degraded": perf.get("degraded") if isinstance(perf.get("degraded"), bool) else None,
        "model": model[:80] if isinstance(model, str) and model else None,
    }

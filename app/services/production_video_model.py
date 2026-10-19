"""Which model shoots a production's H3 clips: ``spec.video``, visible and overridable.

``spec.video`` is ``{model, steps}``. Without it the clips are shot the way every production was shot before the
field existed: ``minimax_h3_fused_turbo`` at 4 steps (fixed here, not read from the model file, so a new default in
``app/defaults`` cannot shoot old clips again). ``model`` is one of the first-frame + audio H3 models that have a
definition in ``app/defaults`` (the same request contract and the same 124 + 17k frame lattice); ``steps`` defaults to
that definition's ``num_inference_steps`` and must be in the range the model accepts (``inference_steps_min`` to
``inference_steps_max`` of its definition, else 1 to 50: Fused Turbo takes 4 to 8). LTX-2 and the Ref2VA models are
not offered: they take other inputs.

Each kept clip and each take records the model and steps it was shot with. A clip with no record was shot before
this field existed, so it counts as the legacy default. When the spec asks for another model or other steps, the
clips pass shoots the kept clips of unlocked shots again (``model_changes``) and a new take replaces the old one
whatever its score; a locked shot keeps its take. Nothing is written on the kept clip, so a spec that goes back to
the model that shot it keeps that clip.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.production_image_defaults import model_image_steps
from services.production_takes import obsolete_clip
from services.video_generation_v3 import FL2VA_MODEL_TYPES

DEFAULT_MODEL = "minimax_h3_fused_turbo"
DEFAULT_STEPS = 4
MAX_STEPS = 50                  # the H3 handler's range for a model whose definition names none
# First frame + audio H3 models with a definition in app/defaults: what submit_clip can send unchanged.
VIDEO_MODELS = tuple(sorted(model for model in FL2VA_MODEL_TYPES if model_image_steps(model)))
_FIELDS = {"model", "steps"}
_DEFAULTS = Path(__file__).resolve().parents[1] / "defaults"


def step_range(model: str) -> tuple[int, int]:
    """(lowest, highest) steps the model accepts: its definition's ``inference_steps_min/max``, else 1 to 50."""
    try:
        definition = json.loads((_DEFAULTS / f"{model}.json").read_text(encoding="utf-8")).get("model") or {}
    except (OSError, ValueError, AttributeError):
        definition = {}
    low, high = definition.get("inference_steps_min"), definition.get("inference_steps_max")
    return (low if isinstance(low, int) else 1), (high if isinstance(high, int) else MAX_STEPS)


def check_video(spec: dict) -> None:
    """validate_spec hook: ``spec.video`` is absent or ``{model, steps}`` with a model from VIDEO_MODELS and steps
    that model accepts (the generate call refuses others after the GPU stages before it)."""
    video = spec.get("video")
    if video is None:
        return
    from services.music_production import ProductionError
    if not isinstance(video, dict) or set(video) - _FIELDS:
        raise ProductionError("invalid_spec", "spec.video is {model, steps}")
    model = video.get("model", DEFAULT_MODEL)
    if model not in VIDEO_MODELS:
        raise ProductionError("invalid_spec", f"video.model must be one of {', '.join(VIDEO_MODELS)}")
    steps = video.get("steps")
    low, high = step_range(model)
    if steps is not None and (not isinstance(steps, int) or isinstance(steps, bool) or not low <= steps <= high):
        raise ProductionError("invalid_spec", f"video.steps for {model} is a whole number from {low} to {high}")


def resolve_video(spec: Any) -> dict:
    """``{model, steps, source}``: what the clips pass will send. ``source`` is ``spec`` when the spec names a
    model or steps, else ``default``."""
    video = spec.get("video") if isinstance(spec, dict) and isinstance(spec.get("video"), dict) else {}
    model = video.get("model") if video.get("model") in VIDEO_MODELS else DEFAULT_MODEL
    steps = video.get("steps") if isinstance(video.get("steps"), int) and not isinstance(video.get("steps"), bool) else None
    own = DEFAULT_STEPS if model == DEFAULT_MODEL else model_image_steps(model)
    return {"model": model, "steps": steps or own or DEFAULT_STEPS, "source": "spec" if video else "default"}


def shot_with(record: Any) -> tuple[str, int]:
    """(model, steps) a clip or take was shot with; a record from before ``spec.video`` is the legacy default."""
    record = record if isinstance(record, dict) else {}
    return str(record.get("model") or DEFAULT_MODEL), int(record.get("steps") or DEFAULT_STEPS)


def other_model(record: Any, video: dict) -> bool:
    """True when a kept clip was shot with another model or other steps than ``video``."""
    return isinstance(record, dict) and shot_with(record) != (video["model"], video["steps"])


def stamp(record: dict, video: dict) -> dict:
    """Write the model and steps onto a clip or take record."""
    record.update(model=video["model"], steps=video["steps"])
    return record


def model_changes(production: Any, video: dict, windows: list[dict]) -> list[str]:
    """The (unlocked) H3 windows whose kept clip another model or other steps shot: the clips pass shoots them again.
    A clip already ``obsolete`` (song switch, changed shot) is shot again anyway."""
    clips = production.state.get("clips") or {}
    changed = []
    for window in windows:
        key = window.get("key")
        clip = clips.get(key)
        if window.get("kind") != "h3" or not other_model(clip, video) or obsolete_clip(clip):
            continue
        model, steps = shot_with(clip)
        changed.append(key)
        production.log(f"clip {key}: shot with {model} ({steps} steps), the spec asks for {video['model']} ({video['steps']} steps): shooting it again")
    return changed

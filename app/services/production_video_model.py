"""Which model shoots a production's H3 clips: ``spec.video``, visible and overridable.

``spec.video`` is ``{model, steps}``. Without it the clips are shot the way every production was shot before the
field existed: ``minimax_h3_fused_turbo`` at 4 steps. ``model`` is one of the first-frame + audio H3 models that have
a definition in ``app/defaults`` (the same request contract and the same 124 + 17k frame lattice); ``steps``
defaults to that definition's ``num_inference_steps``. LTX-2 and the Ref2VA models are not offered: they take
other inputs.

Each kept clip and each take records the model and steps it was shot with. A clip with no record was shot before
this field existed, so it counts as the legacy default. When the spec asks for another model or other steps, the
clips pass marks the kept clips of unlocked shots ``obsolete`` (as a song switch does) and shoots them again; a
locked shot keeps its take.
"""
from __future__ import annotations

from typing import Any

from services.production_image_defaults import model_image_steps
from services.video_generation_v3 import FL2VA_MODEL_TYPES

DEFAULT_MODEL = "minimax_h3_fused_turbo"
DEFAULT_STEPS = 4
MAX_STEPS = 100
# First frame + audio H3 models with a definition in app/defaults: what submit_clip can send unchanged.
VIDEO_MODELS = tuple(sorted(model for model in FL2VA_MODEL_TYPES if model_image_steps(model)))
_FIELDS = {"model", "steps"}


def check_video(spec: dict) -> None:
    """validate_spec hook: ``spec.video`` is absent or ``{model, steps}`` with a model from VIDEO_MODELS."""
    video = spec.get("video")
    if video is None:
        return
    from services.music_production import ProductionError
    if not isinstance(video, dict) or set(video) - _FIELDS:
        raise ProductionError("invalid_spec", "spec.video is {model, steps}")
    if video.get("model", DEFAULT_MODEL) not in VIDEO_MODELS:
        raise ProductionError("invalid_spec", f"video.model must be one of {', '.join(VIDEO_MODELS)}")
    steps = video.get("steps")
    if steps is not None and (not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= MAX_STEPS):
        raise ProductionError("invalid_spec", f"video.steps is a whole number from 1 to {MAX_STEPS}")


def resolve_video(spec: Any) -> dict:
    """``{model, steps, source}``: what the clips pass will send. ``source`` is ``spec`` when the spec names a
    model or steps, else ``default``."""
    video = spec.get("video") if isinstance(spec, dict) and isinstance(spec.get("video"), dict) else {}
    model = video.get("model") if video.get("model") in VIDEO_MODELS else DEFAULT_MODEL
    steps = video.get("steps") if isinstance(video.get("steps"), int) else None
    return {"model": model, "steps": steps or model_image_steps(model) or DEFAULT_STEPS,
            "source": "spec" if video else "default"}


def shot_with(record: Any) -> tuple[str, int]:
    """(model, steps) a clip or take was shot with; a record from before ``spec.video`` is the legacy default."""
    record = record if isinstance(record, dict) else {}
    return str(record.get("model") or DEFAULT_MODEL), int(record.get("steps") or DEFAULT_STEPS)


def stamp(record: dict, video: dict) -> dict:
    """Write the model and steps onto a clip or take record."""
    record.update(model=video["model"], steps=video["steps"])
    return record


def mark_model_changes(production: Any, video: dict, windows: list[dict]) -> list[str]:
    """Flag the kept clips of these (unlocked) H3 windows that another model or other steps shot. Returns the keys."""
    clips = production.state.get("clips") or {}
    wanted = (video["model"], video["steps"])
    changed = []
    for window in windows:
        key = window.get("key")
        clip = clips.get(key)
        if window.get("kind") != "h3" or not isinstance(clip, dict) or clip.get("obsolete") is True:
            continue
        model, steps = shot_with(clip)
        if (model, steps) != wanted:
            clip["obsolete"] = True
            changed.append(key)
            production.log(f"clip {key}: shot with {model} ({steps} steps), the spec asks for {wanted[0]} ({wanted[1]} steps): shooting it again")
    return changed

"""Conservative image defaults; explicit production choices always win.

Prefer Qwen Image 2.1 INT8 on >=16 GiB NVIDIA cards, its Q4 variant on
10--16 GiB cards. Unknown hardware retains the requested Qwen default.
This is a capacity policy, not a measured ranking of artistic quality.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import subprocess

DEFAULT_IMAGE_MODEL = "qwen_image_21"
_DEFAULTS = Path(__file__).resolve().parents[1] / "defaults"


@lru_cache(maxsize=64)
def model_image_steps(model: str) -> int | None:
    """``num_inference_steps`` from ``app/defaults/<model>.json`` (Qwen 40, its Turbo 6, Flux 2 Klein 4); None if unknown."""
    if not isinstance(model, str) or not model or Path(model).name != model:
        return None
    try:
        steps = json.loads((_DEFAULTS / f"{model}.json").read_text(encoding="utf-8")).get("num_inference_steps")
    except (OSError, ValueError, AttributeError):
        return None
    return steps if isinstance(steps, int) and not isinstance(steps, bool) and steps > 0 else None


def default_image_steps(model: str) -> int:
    return model_image_steps(model) or (40 if str(model).startswith("qwen_image_21") else 4)


def image_model_for_memory(memory_mib: float | None) -> str:
    if memory_mib is not None and 10240 <= memory_mib < 16384:
        return "qwen_image_21_gguf_q4_k"
    return DEFAULT_IMAGE_MODEL


@lru_cache(maxsize=1)
def default_image_model() -> str:
    """Inspect capacity without initializing CUDA or loading any model."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True, timeout=2,
        )
        capacities = [float(line) for line in result.stdout.splitlines() if line.strip()]
    except (OSError, ValueError, subprocess.SubprocessError):
        return DEFAULT_IMAGE_MODEL
    # Multiple devices may differ. Do not infer that generation uses the largest.
    return image_model_for_memory(capacities[0] if len(capacities) == 1 else None)


def image_choice(entry: dict, style: dict) -> tuple[str, int | None]:
    """(model, steps) for one cast member or shot. An entry that picks its own model without steps runs it
    at that model's default (None here; ``Production.image`` reads app/defaults), not at the style's steps."""
    look = style.get("image_model") or DEFAULT_IMAGE_MODEL
    model = entry.get("image_model") or look
    return model, entry.get("image_steps", style.get("image_steps") if model == look else None)


def image_style_defaults(style: dict, explicit: dict) -> dict:
    """Set only omitted choices, including inherited preset model/step defaults.

    A model chosen without steps runs at its own default steps, never at the
    steps a preset set for another model (Flux 2 Klein on a Qwen look gets 4, not 40).
    """
    if "image_model" in explicit:
        chosen = explicit["image_model"]
        steps = model_image_steps(chosen) if isinstance(chosen, str) and "image_steps" not in explicit else None
        return {**style, "image_steps": steps} if steps else style
    model = default_image_model()
    return {**style, "image_model": model, "image_steps": explicit.get("image_steps", default_image_steps(model))}

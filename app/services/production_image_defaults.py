"""Conservative image defaults; explicit production choices always win.

Prefer Qwen Image 2.1 INT8 on >=16 GiB NVIDIA cards, its Q4 variant on
10--16 GiB cards. Unknown hardware retains the requested Qwen default.
This is a capacity policy, not a measured ranking of artistic quality.
"""
from __future__ import annotations

from functools import lru_cache
import subprocess

DEFAULT_IMAGE_MODEL = "qwen_image_21"


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


def image_style_defaults(style: dict, explicit: dict) -> dict:
    """Set only omitted choices, including inherited preset model/step defaults."""
    if "image_model" in explicit:
        return style
    return {**style, "image_model": default_image_model(),
            "image_steps": explicit.get("image_steps", 40)}

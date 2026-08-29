"""FastH3 Preview v1: FastVideo's 4-step T2VA distillation of MiniMax H3.

The recommended checkpoint is VSA / Data-Free. FastVideo trains it for four
transformer forwards and requires the VSA-H3 attention backend for the published
quality. Maestro's native H3 path still uses dense attention, so this preset is
an experimental trial: it downloads the matching LoRA, locks 4 steps, and
forces text-to-audio-video (no first/last frame, no Omni Ref).

Source:
https://huggingface.co/FastVideo/FastVideo-FastH3-4-step-Preview-v1-VSA-DataFree
Matching LoRA:
https://huggingface.co/FastVideo/FastVideo-FastH3-4-step-Preview-v1-LoRA
"""

from __future__ import annotations

import os


FASTH3_PREVIEW_LORA_FILENAME = "fasth3_4step_preview_vsa_datafree.safetensors"
FASTH3_PREVIEW_LORA_REPO_ID = "FastVideo/FastVideo-FastH3-4-step-Preview-v1-LoRA"
FASTH3_PREVIEW_LORA_REVISION = "bcf40ca6f457ed66f8badf13514943e390205fca"
FASTH3_PREVIEW_LORA_REMOTE_PATH = "vsa-datafree/adapter_model.safetensors"
FASTH3_PREVIEW_LORA_SHA256 = (
    "42dc502a2078f166c396a1fa75f29728d1844363652d345d5ef3e2b444ed6470"
)
FASTH3_PREVIEW_LORA_SIZE = 5_339_117_712
FASTH3_PREVIEW_STEPS = 4
FASTH3_PREVIEW_WEIGHT = 1.00
FASTH3_PREVIEW_GUIDE_URL = (
    "https://huggingface.co/FastVideo/FastVideo-FastH3-4-step-Preview-v1-VSA-DataFree"
)

_FASTH3_ARCHITECTURES = {"minimax_h3", "minimax_h3_full"}


def fasth3_preview_supported(architecture: str) -> bool:
    return str(architecture or "") in _FASTH3_ARCHITECTURES


def is_fasth3_preview_lora(path: str) -> bool:
    basename = os.path.basename(str(path or "")).lower().replace("-", "_")
    return (
        basename == FASTH3_PREVIEW_LORA_FILENAME.lower()
        or "fasth3_4step_preview_vsa_datafree" in basename
        or basename.endswith("vsa-datafree/adapter_model.safetensors".replace("/", "_"))
    )


def normalize_fasth3_preview_request(body: dict) -> bool:
    """Apply the 4-step FastH3 Preview recipe. T2VA only.

    Returns True when the preset was applied. Raises ValueError when the
    request asks for FastH3 on a path the student was not distilled for.
    """

    if not isinstance(body, dict) or body.get("minimax_h3_fasth3_mode") is not True:
        return False

    architecture = str(body.get("architecture") or body.get("_architecture") or "")
    model_type = str(body.get("model_type") or "")
    if architecture.startswith("minimax_h3_ref2va") or "ref2va" in model_type:
        raise ValueError(
            "FastH3 Preview v1 is T2VA only. FL2VA first/last frames and Omni "
            "Ref (Ref2VA) were not distilled. Use a Full/Pruned H3 First/Last "
            "model with text only, or disable FastH3."
        )

    image_prompt_type = str(body.get("image_prompt_type") or "").strip()
    if image_prompt_type:
        raise ValueError(
            "FastH3 Preview v1 does not use a first or last frame. Clear the "
            "start/end images or disable FastH3."
        )
    references = body.get("minimax_h3_references")
    if isinstance(references, (list, tuple)) and any(references):
        raise ValueError(
            "FastH3 Preview v1 does not accept Omni references. Remove them "
            "or disable FastH3."
        )

    raw_loras = body.get("activated_loras")
    source_loras = (
        [str(item).strip() for item in raw_loras if str(item).strip()]
        if isinstance(raw_loras, (list, tuple))
        else []
    )
    raw_multipliers = body.get("loras_multipliers")
    if isinstance(raw_multipliers, (list, tuple)):
        source_multipliers = [str(item).strip() for item in raw_multipliers]
    else:
        source_multipliers = str(raw_multipliers or "").split()

    normalized_loras: list[str] = []
    normalized_multipliers: list[str] = []
    selected_weight: str | None = None
    for index, lora in enumerate(source_loras):
        basename = os.path.basename(lora.replace("\\", "/")).lower().replace("-", "_")
        if "minimax_h3_turbo" in basename or is_fasth3_preview_lora(lora):
            if is_fasth3_preview_lora(lora):
                token = (
                    source_multipliers[index].split(";", 1)[0]
                    if index < len(source_multipliers)
                    else ""
                )
                try:
                    value = float(token)
                except (TypeError, ValueError):
                    value = -1.0
                if 0.0 <= value <= 2.0:
                    selected_weight = f"{value:.2f}"
            continue
        normalized_loras.append(lora)
        normalized_multipliers.append(
            source_multipliers[index]
            if index < len(source_multipliers) and source_multipliers[index]
            else "1.00"
        )

    normalized_loras.append(FASTH3_PREVIEW_LORA_FILENAME)
    normalized_multipliers.append(selected_weight or f"{FASTH3_PREVIEW_WEIGHT:.2f}")
    body["activated_loras"] = normalized_loras
    body["loras_multipliers"] = " ".join(normalized_multipliers)
    body["num_inference_steps"] = FASTH3_PREVIEW_STEPS
    body["minimax_h3_turbo_mode"] = False
    body["image_prompt_type"] = ""
    return True


__all__ = [
    "FASTH3_PREVIEW_GUIDE_URL",
    "FASTH3_PREVIEW_LORA_FILENAME",
    "FASTH3_PREVIEW_LORA_REMOTE_PATH",
    "FASTH3_PREVIEW_LORA_REPO_ID",
    "FASTH3_PREVIEW_LORA_REVISION",
    "FASTH3_PREVIEW_LORA_SHA256",
    "FASTH3_PREVIEW_LORA_SIZE",
    "FASTH3_PREVIEW_STEPS",
    "FASTH3_PREVIEW_WEIGHT",
    "fasth3_preview_supported",
    "is_fasth3_preview_lora",
    "normalize_fasth3_preview_request",
]

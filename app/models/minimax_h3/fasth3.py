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
import re
from collections import defaultdict


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

# Reverse of FastVideo's convert_minimax_h3_comfy_lora.py. FastH3 adapters are
# trained on Diffusers MiniMax-H3 names; Maestro's consumer transformer uses
# the Comfy/WanGP module paths. QKV is fused here, and the two SwiGLU halves
# of mlp.fc1 are stored in the opposite order from ff.net.0.proj.
_FASTVIDEO_HEAD_DIM_TOTAL = 7168
_FASTVIDEO_FFN_HALF = 14336
_FASTVIDEO_PREFIX_RENAMES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^token_refiner\.refiner_blocks\.(\d+)(?=\.|$)"),
        r"token_refiner.blocks.\1",
    ),
    (re.compile(r"^transformer_blocks\.(\d+)(?=\.|$)"), r"blocks.\1"),
    (re.compile(r"^norm_out\.linear(?=\.|$)"), "final_layer.adaln_proj.linear"),
    (re.compile(r"^norm_out\.norm(?=\.|$)"), "final_layer.norm"),
    (re.compile(r"^proj_out(?=\.|$)"), "final_layer.video_out"),
    (re.compile(r"^audio_proj_out(?=\.|$)"), "final_layer.audio_out"),
    (re.compile(r"^proj_in(?=\.|$)"), "video_patch_proj"),
    (re.compile(r"^audio_proj_in(?=\.|$)"), "audio_patch_proj"),
    (re.compile(r"^context_embedder(?=\.|$)"), "condition_proj"),
    (re.compile(r"^time_embedder\.linear_1(?=\.|$)"), "time_embedder.proj_in"),
    (re.compile(r"^time_embedder\.linear_2(?=\.|$)"), "time_embedder.proj_out"),
]
_FASTVIDEO_MODULE_RENAMES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\.attn\.to_out\.0$"), ".attn.out_proj"),
    (re.compile(r"\.ff\.net\.2$"), ".mlp.fc2"),
]
_LORA_A_SUFFIXES = (".lora_A.weight", ".lora_down.weight")
_LORA_B_SUFFIXES = (".lora_B.weight", ".lora_up.weight")
_QKV_PROJECTIONS = ("to_q", "to_k", "to_v")


def fasth3_preview_supported(architecture: str) -> bool:
    return str(architecture or "") in _FASTH3_ARCHITECTURES


def is_fasth3_preview_lora(path: str) -> bool:
    basename = os.path.basename(str(path or "")).lower().replace("-", "_")
    return (
        basename == FASTH3_PREVIEW_LORA_FILENAME.lower()
        or "fasth3_4step_preview_vsa_datafree" in basename
        or basename.endswith("vsa-datafree/adapter_model.safetensors".replace("/", "_"))
    )


def _rename_fastvideo_h3_module(name: str) -> str:
    for pattern, replacement in _FASTVIDEO_PREFIX_RENAMES:
        renamed = pattern.sub(replacement, name, count=1)
        if renamed != name:
            name = renamed
            break
    for pattern, replacement in _FASTVIDEO_MODULE_RENAMES:
        name = pattern.sub(replacement, name)
    return name


def _fastvideo_lora_stem(key: str) -> tuple[str, str] | None:
    for suffix in _LORA_A_SUFFIXES:
        if key.endswith(suffix):
            return key[: -len(suffix)], "A"
    for suffix in _LORA_B_SUFFIXES:
        if key.endswith(suffix):
            return key[: -len(suffix)], "B"
    return None


def is_fastvideo_h3_lora_state_dict(state_dict: dict) -> bool:
    for key in state_dict:
        if not isinstance(key, str):
            continue
        if key.startswith("transformer_blocks.") or key.startswith(
            "token_refiner.refiner_blocks."
        ):
            return True
        if ".attn.to_q." in key or ".ff.net." in key or ".attn.to_out.0." in key:
            return True
    return False


def convert_fastvideo_h3_lora_to_native(
    state_dict: dict,
    *,
    drop_time_embedder: bool = False,
) -> dict:
    """Rewrite a FastVideo MiniMax-H3 adapter onto Maestro's native modules.

    VSA ``to_gate_compress.set_weight`` tensors are dropped: that gate does not
    exist on Maestro's dense H3 path. Independent ``to_q`` / ``to_k`` / ``to_v``
    factors are fused into ``qkv_proj`` with a block-diagonal rank expansion
    because FastH3 trains those projections with distinct A matrices.
    """

    if not isinstance(state_dict, dict) or not is_fastvideo_h3_lora_state_dict(
        state_dict
    ):
        return dict(state_dict)

    import torch

    factors: dict[str, dict[str, object]] = defaultdict(dict)
    passthrough: dict[str, object] = {}
    dropped_vsa = 0
    dropped_time = 0
    for key, tensor in state_dict.items():
        if not isinstance(key, str):
            passthrough[key] = tensor
            continue
        if "to_gate_compress" in key or key.endswith(".set_weight"):
            dropped_vsa += 1
            continue
        if drop_time_embedder and key.startswith("time_embedder."):
            dropped_time += 1
            continue
        parsed = _fastvideo_lora_stem(key)
        if parsed is None:
            passthrough[key] = tensor
            continue
        stem, side = parsed
        factors[stem][side] = tensor

    qkv_groups: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    other_factors: dict[str, dict[str, object]] = {}
    for stem, pair in factors.items():
        matched = False
        for projection in _QKV_PROJECTIONS:
            suffix = f".attn.{projection}"
            if stem.endswith(suffix):
                parent = stem[: -len(f".{projection}")]
                qkv_groups[parent][projection] = pair
                matched = True
                break
        if not matched:
            other_factors[stem] = pair

    converted: dict[str, object] = {}
    fused_qkv = 0
    swapped_swiglu = 0

    for parent, parts in qkv_groups.items():
        missing = [name for name in _QKV_PROJECTIONS if name not in parts]
        if missing:
            raise ValueError(
                "FastH3 LoRA is missing fused-QKV factors for "
                f"{parent}: {', '.join(missing)}"
            )
        a_parts = []
        b_parts = []
        for projection in _QKV_PROJECTIONS:
            pair = parts[projection]
            if "A" not in pair or "B" not in pair:
                raise ValueError(
                    "FastH3 LoRA is missing A/B for "
                    f"{parent}.{projection}"
                )
            a_parts.append(pair["A"])
            b_parts.append(pair["B"])
        rows = [int(part.shape[0]) for part in b_parts]
        if any(row != _FASTVIDEO_HEAD_DIM_TOTAL for row in rows):
            raise ValueError(
                "FastH3 QKV LoRA B rows are not the Diffusers head width "
                f"{_FASTVIDEO_HEAD_DIM_TOTAL}: {parent} -> {rows}"
            )
        a_fused = torch.cat(a_parts, dim=0)
        b_fused = torch.block_diag(*b_parts)
        native = _rename_fastvideo_h3_module(parent + ".qkv_proj")
        converted[f"{native}.lora_A.weight"] = a_fused.contiguous()
        converted[f"{native}.lora_B.weight"] = b_fused.contiguous()
        fused_qkv += 1

    for stem, pair in other_factors.items():
        if "A" not in pair or "B" not in pair:
            raise ValueError(f"FastH3 LoRA is missing A/B for {stem}")
        a_tensor = pair["A"]
        b_tensor = pair["B"]
        if stem.endswith(".ff.net.0.proj"):
            if int(b_tensor.shape[0]) != 2 * _FASTVIDEO_FFN_HALF:
                raise ValueError(
                    "FastH3 SwiGLU LoRA B rows are not 2x "
                    f"{_FASTVIDEO_FFN_HALF}: {stem} -> {tuple(b_tensor.shape)}"
                )
            b_tensor = torch.cat(
                (b_tensor[_FASTVIDEO_FFN_HALF:], b_tensor[:_FASTVIDEO_FFN_HALF]),
                dim=0,
            )
            native = _rename_fastvideo_h3_module(
                stem[: -len(".ff.net.0.proj")] + ".mlp.fc1"
            )
            swapped_swiglu += 1
        else:
            native = _rename_fastvideo_h3_module(stem)
        converted[f"{native}.lora_A.weight"] = a_tensor.contiguous()
        converted[f"{native}.lora_B.weight"] = b_tensor.contiguous()

    leftover = 0
    for key, tensor in passthrough.items():
        native_key = _rename_fastvideo_h3_module(key)
        if (
            native_key.startswith("transformer_blocks.")
            or ".attn.to_" in native_key
            or ".ff.net." in native_key
        ):
            leftover += 1
            continue
        converted[native_key] = tensor

    print(
        "[FastH3 Preview] Converted FastVideo adapter to native H3 keys: "
        f"{len(converted)} tensors, fused {fused_qkv} QKV groups to rank-"
        f"expanded qkv_proj, swapped {swapped_swiglu} SwiGLU halves, "
        f"dropped {dropped_vsa} VSA gate tensors"
        + (f" and {dropped_time} pruned time-embedder tensors" if dropped_time else "")
        + (f", skipped {leftover} leftover Diffusers keys" if leftover else "")
        + "."
    )
    return converted


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
    "convert_fastvideo_h3_lora_to_native",
    "fasth3_preview_supported",
    "is_fasth3_preview_lora",
    "is_fastvideo_h3_lora_state_dict",
    "normalize_fasth3_preview_request",
]

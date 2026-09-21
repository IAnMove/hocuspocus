"""Convert ComfyUI Qwen-Image-2.1 VAE weights to Diffusers AutoencoderKLQwenImage21."""

from __future__ import annotations

import re
from typing import Dict, Mapping

import torch

_RESIDUAL = {
    "residual.0.gamma": "norm1.gamma",
    "residual.2.bias": "conv1.bias",
    "residual.2.weight": "conv1.weight",
    "residual.3.gamma": "norm2.gamma",
    "residual.6.bias": "conv2.bias",
    "residual.6.weight": "conv2.weight",
}

_EXACT = {
    "conv1.weight": "quant_conv.weight",
    "conv1.bias": "quant_conv.bias",
    "conv2.weight": "post_quant_conv.weight",
    "conv2.bias": "post_quant_conv.bias",
    "encoder.conv1.weight": "encoder.conv_in.weight",
    "encoder.conv1.bias": "encoder.conv_in.bias",
    "decoder.conv1.weight": "decoder.conv_in.weight",
    "decoder.conv1.bias": "decoder.conv_in.bias",
    "encoder.head.0.gamma": "encoder.norm_out.gamma",
    "encoder.head.2.bias": "encoder.conv_out.bias",
    "encoder.head.2.weight": "encoder.conv_out.weight",
    "decoder.head.0.gamma": "decoder.norm_out.gamma",
    "decoder.head.2.bias": "decoder.conv_out.bias",
    "decoder.head.2.weight": "decoder.conv_out.weight",
    "encoder.middle.0.residual.0.gamma": "encoder.mid_block.resnets.0.norm1.gamma",
    "encoder.middle.0.residual.2.bias": "encoder.mid_block.resnets.0.conv1.bias",
    "encoder.middle.0.residual.2.weight": "encoder.mid_block.resnets.0.conv1.weight",
    "encoder.middle.0.residual.3.gamma": "encoder.mid_block.resnets.0.norm2.gamma",
    "encoder.middle.0.residual.6.bias": "encoder.mid_block.resnets.0.conv2.bias",
    "encoder.middle.0.residual.6.weight": "encoder.mid_block.resnets.0.conv2.weight",
    "encoder.middle.2.residual.0.gamma": "encoder.mid_block.resnets.1.norm1.gamma",
    "encoder.middle.2.residual.2.bias": "encoder.mid_block.resnets.1.conv1.bias",
    "encoder.middle.2.residual.2.weight": "encoder.mid_block.resnets.1.conv1.weight",
    "encoder.middle.2.residual.3.gamma": "encoder.mid_block.resnets.1.norm2.gamma",
    "encoder.middle.2.residual.6.bias": "encoder.mid_block.resnets.1.conv2.bias",
    "encoder.middle.2.residual.6.weight": "encoder.mid_block.resnets.1.conv2.weight",
    "encoder.middle.1.norm.gamma": "encoder.mid_block.attentions.0.norm.gamma",
    "encoder.middle.1.to_qkv.weight": "encoder.mid_block.attentions.0.to_qkv.weight",
    "encoder.middle.1.to_qkv.bias": "encoder.mid_block.attentions.0.to_qkv.bias",
    "encoder.middle.1.proj.weight": "encoder.mid_block.attentions.0.proj.weight",
    "encoder.middle.1.proj.bias": "encoder.mid_block.attentions.0.proj.bias",
    "decoder.middle.0.residual.0.gamma": "decoder.mid_block.resnets.0.norm1.gamma",
    "decoder.middle.0.residual.2.bias": "decoder.mid_block.resnets.0.conv1.bias",
    "decoder.middle.0.residual.2.weight": "decoder.mid_block.resnets.0.conv1.weight",
    "decoder.middle.0.residual.3.gamma": "decoder.mid_block.resnets.0.norm2.gamma",
    "decoder.middle.0.residual.6.bias": "decoder.mid_block.resnets.0.conv2.bias",
    "decoder.middle.0.residual.6.weight": "decoder.mid_block.resnets.0.conv2.weight",
    "decoder.middle.2.residual.0.gamma": "decoder.mid_block.resnets.1.norm1.gamma",
    "decoder.middle.2.residual.2.bias": "decoder.mid_block.resnets.1.conv1.bias",
    "decoder.middle.2.residual.2.weight": "decoder.mid_block.resnets.1.conv1.weight",
    "decoder.middle.2.residual.3.gamma": "decoder.mid_block.resnets.1.norm2.gamma",
    "decoder.middle.2.residual.6.bias": "decoder.mid_block.resnets.1.conv2.bias",
    "decoder.middle.2.residual.6.weight": "decoder.mid_block.resnets.1.conv2.weight",
    "decoder.middle.1.norm.gamma": "decoder.mid_block.attentions.0.norm.gamma",
    "decoder.middle.1.to_qkv.weight": "decoder.mid_block.attentions.0.to_qkv.weight",
    "decoder.middle.1.to_qkv.bias": "decoder.mid_block.attentions.0.to_qkv.bias",
    "decoder.middle.1.proj.weight": "decoder.mid_block.attentions.0.proj.weight",
    "decoder.middle.1.proj.bias": "decoder.mid_block.attentions.0.proj.bias",
}

_DOWN = re.compile(r"^encoder\.downsamples\.(\d+)\.downsamples\.(\d+)\.(.+)$")
_UP = re.compile(r"^decoder\.upsamples\.(\d+)\.upsamples\.(\d+)\.(.+)$")


def _squeeze_comfy_conv(value: torch.Tensor) -> torch.Tensor:
    """Comfy stores CausalConv as 5D (out, in, 1, kH, kW); Diffusers 2.1 uses Conv2d 4D."""
    if getattr(value, "ndim", 0) == 5 and value.shape[2] == 1:
        return value.squeeze(2)
    return value


def _map_nested(block: int, idx: int, rest: str, kind: str) -> str | None:
    stem = "encoder.down_blocks" if kind == "down" else "decoder.up_blocks"
    sampler = "downsampler" if kind == "down" else "upsampler"
    if rest.startswith("residual."):
        mapped = _RESIDUAL.get(rest)
        if mapped is None:
            return None
        return f"{stem}.{block}.resnets.{idx}.{mapped}"
    if rest.startswith("shortcut."):
        return f"{stem}.{block}.resnets.{idx}.conv_shortcut.{rest.split('.', 1)[1]}"
    if rest.startswith("resample.") or rest.startswith("time_conv."):
        return f"{stem}.{block}.{sampler}.{rest}"
    return None


def convert_qwen_image_21_vae_state_dict(
    state_dict: Mapping[str, torch.Tensor],
) -> Dict[str, torch.Tensor]:
    converted: Dict[str, torch.Tensor] = {}
    for key, value in state_dict.items():
        mapped = _EXACT.get(key)
        if mapped is None:
            match = _DOWN.match(key)
            if match is not None:
                mapped = _map_nested(int(match.group(1)), int(match.group(2)), match.group(3), "down")
            else:
                match = _UP.match(key)
                if match is not None:
                    mapped = _map_nested(int(match.group(1)), int(match.group(2)), match.group(3), "up")
        converted[mapped or key] = _squeeze_comfy_conv(value)
    return converted

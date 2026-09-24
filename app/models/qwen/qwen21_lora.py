"""Adapt Diffusers split SwiGLU LoRAs to the native Comfy fused gate/up layer."""
import torch


def fuse_qwen21_lora_projections(state_dict):
    """Keep updates unmerged using block-diagonal B and concatenated A factors.

    cat(B_gate A_gate, B_up A_up) = block_diag(B_gate, B_up) cat(A_gate, A_up).
    No base/quantized weights are changed. Already-fused LoRAs pass through.
    """
    result = dict(state_dict)
    suffix = ".gate_layer.lora_A.weight"
    for key in state_dict:
        if not key.endswith(suffix):
            continue
        stem = key[:-len(suffix)]
        fused = stem + ".gate_up"
        if any(name.startswith(fused + ".") for name in result):
            raise ValueError(f"LoRA contains both split and fused Qwen 2.1 projections: {stem}")
        factors = []
        for projection in ("gate_layer", "proj"):
            prefix = f"{stem}.{projection}"
            try:
                a = result.pop(prefix + ".lora_A.weight")
                b = result.pop(prefix + ".lora_B.weight")
            except KeyError as error:
                raise ValueError(f"Incomplete Qwen 2.1 split LoRA: {prefix}") from error
            rank = a.shape[0]
            alpha = result.pop(prefix + ".alpha", None)
            if alpha is not None:
                b = b * (float(alpha) / rank)
            factors.append((a, b))
        result[fused + ".lora_A.weight"] = torch.cat([a for a, _ in factors], dim=0)
        result[fused + ".lora_B.weight"] = torch.block_diag(*[b for _, b in factors])
        # The packed adapter has twice the rank; preserve a unit multiplier.
        result[fused + ".alpha"] = torch.tensor(float(sum(a.shape[0] for a, _ in factors)))
    return result

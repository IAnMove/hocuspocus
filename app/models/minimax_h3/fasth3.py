"""Policy and loader helpers for the official FastVideo FastH3 checkpoints.

FastH3 is MiniMax-H3 distilled by Hao AI Lab (FastVideo) to eight denoising
evaluations with DMD2, trained with Video Sparse Attention (VSA).  Two
text-to-video checkpoints are supported, both published as ComfyUI INT8
ConvRot files:

* ``FastVideo/FastVideo-FastH3-Comfy`` - the 8-step V2 model, same 50-block
  "pruned rank-8" network the app already loads for H3 Pruned.
* ``FastVideo/FastVideo-FastH3-Trim-Comfy`` - 42 blocks and a rank-16
  timestep curve.

They reuse the fused-recipe plumbing (``minimax_h3_fused_turbo``): baked
weights, ``res_multistep``, grouped QKV, the INT8 ConvRot video VAE and no
stacked LoRAs.  What differs lives here: shift 10 (video) / 3 (audio), a
locked eight-step schedule, dense attention by default, and the extra tensors
of the VSA-trained files.  See ``H3_FASTH3_NOTICE.md`` for revisions and
licence terms.
"""

from __future__ import annotations

import os
import re

from .turbo import is_minimax_h3_turbo_lora


FASTH3_STEPS = 8
FASTH3_VIDEO_SHIFT = 10.0
FASTH3_AUDIO_SHIFT = 3.0
FASTH3_SOLVER = "res_multistep"
FASTH3_ASSET_FOLDER = "fasth3"

DEFAULT_VIDEO_SHIFT = 12.0
DEFAULT_AUDIO_SHIFT = 3.0

# VSA compress-branch gate.  It blends the coarse branch of Video Sparse
# Attention into the output.  Maestro runs these models with dense (or SLA)
# attention, which has no coarse branch, so the tensor has nowhere to go.
# FastVideo's own dense backends ignore it in the same way.
_VSA_GATE_MARKER = ".attn.to_gate_compress."
_DIT_BLOCK = re.compile(
    r"^(?:model\.diffusion_model\.|diffusion_model\.)?blocks\.(\d+)\."
)


def is_fasth3(model_def: dict | None) -> bool:
    """Return whether a model definition is a FastVideo FastH3 entry."""

    return bool((model_def or {}).get("minimax_h3_fasth3", False))


def h3_shifts(model_def: dict | None) -> tuple[float, float]:
    """Return the (video, audio) sigma shifts a model definition asks for."""

    model_def = model_def or {}
    video = model_def.get("minimax_h3_video_shift", DEFAULT_VIDEO_SHIFT)
    audio = model_def.get("minimax_h3_audio_shift", DEFAULT_AUDIO_SHIFT)
    return float(video), float(audio)


def normalize_fasth3_request(body: dict) -> int:
    """Pin the distilled recipe on a generation request.

    The checkpoint is a DMD2 eight-step distillation: other step counts, a
    different shift or classifier-free guidance fall outside what it was
    trained for, so they are overwritten instead of rejected.  Ordinary user
    LoRAs are rejected rather than silently lost.  Attention stays dense
    unless the caller explicitly asks for SLA or SDPA.

    Returns the number of stale managed Turbo/PDD selections removed.
    """

    selected = list(body.get("activated_loras") or [])
    stale_managed = [item for item in selected if is_minimax_h3_turbo_lora(item)]
    ordinary = [item for item in selected if not is_minimax_h3_turbo_lora(item)]
    if ordinary:
        names = ", ".join(
            str(item).rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for item in ordinary
        )
        raise ValueError(
            "FastH3 is a distilled checkpoint and cannot be combined with "
            f"LoRAs. Disable these additional LoRAs before generating: {names}."
        )
    body["activated_loras"] = []
    body["loras_multipliers"] = ""
    body["minimax_h3_turbo_mode"] = False
    body["minimax_h3_turbo_preset"] = ""
    body["num_inference_steps"] = FASTH3_STEPS
    body["guidance_scale"] = 1.0
    body["flow_shift"] = FASTH3_VIDEO_SHIFT
    body["audio_flow_shift"] = FASTH3_AUDIO_SHIFT
    body["skip_steps_cache_type"] = ""
    requested = str(body.get("override_attention") or "").strip().lower()
    body["override_attention"] = requested if requested in {"sla", "sdpa"} else ""
    return len(stale_managed)


# Capabilities of the frames workflow that FastVideo did not distill: first and
# last frames, timed frames, source-video continuation, control video, masks and
# soundtrack-driven generation.  Keys the omni-reference entries never declare
# are removed (WanGP reads them with defaults); the others are switched off.
_TEXT_TO_VIDEO_REMOVED = (
    "guide_custom_choices",
    "video_guide_label",
    "video_to_video_inpaint",
    "mask_preprocessing",
    "any_audio_prompt",
    "audio_prompt_choices",
    "audio_guide_label",
    "audio_prompt_type_sources",
    "infer_audio_prompt_from_guide",
    "video_length_not_limited_by_audio",
    "output_audio_is_input_audio",
    "minimax_h3_media_sources",
    "sliding_window_defaults",
    "sliding_window_memory_policy",
)
_TEXT_TO_VIDEO_DISABLED = (
    "i2v_class",
    "end_frames_always_enabled",
    "custom_frames_injection",
    "sliding_window",
    "video_continuation",
    "sliding_window_exact_total_frames",
    "sliding_window_trim_to_requested",
    "sliding_window_end_image_at_final",
    "sliding_window_auto_prompt_pacing",
    "audio_guide_window_slicing",
    "sliding_window_audio_history",
    "director_endpoint_continuity",
)


def restrict_to_text_to_video(definition: dict) -> dict:
    """Reduce an FL2VA model definition to FastH3's distilled mode.

    FastVideo distilled text-to-video only; image-to-video and the reference
    workflow were not distilled, so the entry offers a prompt and nothing
    else.  A clip is one native pass (up to the model's 345-frame limit).
    """

    for key in _TEXT_TO_VIDEO_REMOVED:
        definition.pop(key, None)
    for key in _TEXT_TO_VIDEO_DISABLED:
        definition[key] = False
    definition["image_prompt_types_allowed"] = ""
    definition["t2v_class"] = True
    return definition


def fasth3_attribution_downloads(repo_id: str, revision: str, assets_root: str) -> list[dict]:
    """Download list for the licence the FastH3 weights are published under.

    The FastVideo repositories carry no licence file, only a pointer to the
    MiniMax H3 Community License, so the pinned official MiniMax-H3 copy is
    stored beside the weights.
    """

    return [
        {
            "repoId": repo_id,
            "revision": revision,
            "sourceFolderList": [""],
            "targetFolderList": [os.path.join(assets_root, FASTH3_ASSET_FOLDER)],
            "fileList": [["LICENSE"]],
        }
    ]


def count_dit_blocks(keys) -> int | None:
    """Count the main transformer blocks named in a checkpoint's tensor keys.

    Token-refiner blocks (``token_refiner.blocks.N``) are not counted.  The
    indices must be contiguous from zero: a gap means a damaged or unsupported
    export, and silently building a different depth would leave tensors
    unloaded.  Returns ``None`` when no block keys exist.
    """

    indices = set()
    for key in keys:
        match = _DIT_BLOCK.match(key)
        if match:
            indices.add(int(match.group(1)))
    if not indices:
        return None
    count = max(indices) + 1
    if len(indices) != count:
        missing = sorted(set(range(count)) - indices)
        raise ValueError(
            "MiniMax H3 checkpoint has non-contiguous transformer blocks; "
            f"missing indices {missing[:5]}."
        )
    return count


def transformer_depth_kwargs(checkpoint: dict) -> dict:
    """Constructor arguments that give the transformer the file's own depth.

    Every earlier H3 export has the network's default 50 blocks, so for them
    this repeats the default.  FastH3 Trim has 42.
    """

    layers = checkpoint.get("num_layers")
    return {"num_layers": int(layers)} if layers else {}


def drop_unused_vsa_tensors(state_dict: dict) -> int:
    """Remove VSA compress-gate tensors the dense runtime cannot use.

    Done before quantization routing so their INT8 data is neither decoded nor
    pinned.  Returns how many tensors were dropped.
    """

    unused = [key for key in state_dict if _VSA_GATE_MARKER in key]
    for key in unused:
        del state_dict[key]
    return len(unused)


__all__ = [
    "FASTH3_ASSET_FOLDER",
    "FASTH3_AUDIO_SHIFT",
    "FASTH3_SOLVER",
    "FASTH3_STEPS",
    "FASTH3_VIDEO_SHIFT",
    "count_dit_blocks",
    "drop_unused_vsa_tensors",
    "fasth3_attribution_downloads",
    "h3_shifts",
    "is_fasth3",
    "normalize_fasth3_request",
    "restrict_to_text_to_video",
    "transformer_depth_kwargs",
]

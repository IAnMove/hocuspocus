"""Weights and 24 GB settings for ``shot.lipsync.redo``.

Byte figures are disk sizes from the Hugging Face API on 2026-10-24
(``model_info(..., files_metadata=True)``). They are not VRAM measurements.
The defaults JSON files name no VRAM number. This operation asks for the
quanto int8 file of each engine, not the bf16 file.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Disk bytes. InfiniteTalk's own JSON sets ``URLs`` to ``"i2v"``, so the int8
# image-to-video base is part of the same stack. Shared VAE, umt5 and wav2vec
# are what the Wan2GP handlers already request for these model types.
_I2V = {
    "path": "wan2.1_image2video_480p_14B_quanto_mbf16_int8.safetensors",
    "bytes": 17_012_166_697, "license": "Apache-2.0", "repo": "DeepBeepMeep/Wan2.1",
}
_TALK = {
    "path": "wan2.1_infinitetalk_single_14B_quanto_mbf16_int8.safetensors",
    "bytes": 2_565_167_934, "license": "Apache-2.0", "repo": "DeepBeepMeep/Wan2.1",
}
_LONGCAT = {
    "path": "longcat_avatar_single_quanto_bf16_int8.safetensors",
    "bytes": 16_247_232_819, "license": "MIT", "repo": "DeepBeepMeep/LongCat",
}
_VAE = {
    "path": "Wan2.1_VAE_bf16.safetensors",
    "bytes": 253_808_213, "license": "Apache-2.0", "repo": "DeepBeepMeep/Wan2.1",
}
_UMT5 = {
    "path": "umt5-xxl/models_t5_umt5-xxl-enc-quanto_int8.safetensors",
    "bytes": 6_733_337_738, "license": "Apache-2.0", "repo": "DeepBeepMeep/Wan2.1",
}
_WAV2VEC = {
    "path": "chinese-wav2vec2-base/pytorch_model.bin",
    "bytes": 380_261_837, "license": "MIT", "repo": "TencentGameMate/chinese-wav2vec2-base",
}
_SHARED = (_VAE, _UMT5, _WAV2VEC)

WEIGHTS: dict[str, tuple[dict[str, Any], ...]] = {
    "infinitetalk": (_I2V, _TALK, *_SHARED),
    "longcat_avatar": (_LONGCAT, *_SHARED),
}

# ``steps`` is the 24 GB choice. InfiniteTalk's JSON has no step field (20 is
# this operation's choice). ``longcat_avatar`` stays in ``WEIGHTS`` (the model
# catalog) and is not an engine here: its ``generate`` declares ``input_frames``
# and ``image_start`` and never reads them, so a control video does not keep
# the person in the shot.
ENGINES: dict[str, dict[str, Any]] = {
    "infinitetalk": {
        "model_type": "infinitetalk", "license": "Apache-2.0", "source": "MeiGen-AI/InfiniteTalk",
        "resolution": "832x480", "steps": 20, "guidance_scale": 1, "audio_guidance_scale": 1,
        "denoising_strength": 0.7, "video_prompt_type": "GUV", "sliding_window_size": 81, "fps": 16,
    },
}

PROMPT = (
    "The person keeps the camera and the body of the source video. "
    "Only the mouth, jaw and lips follow the driving audio."
)


def files_for(engine: str) -> list[dict[str, Any]]:
    return [dict(item) for item in WEIGHTS[engine]]


def stack_bytes(engine: str) -> int:
    return sum(int(item["bytes"]) for item in WEIGHTS[engine])


def _found(root: Path, relative: str) -> bool:
    """True when ``relative`` or the same file name is already under ``root``.

    ``pytorch_model.bin`` counts only inside a wav2vec directory, so an
    unrelated checkpoint of that name is not treated as this stack.
    """
    if (root / relative).is_file():
        return True
    if not root.is_dir():
        return False
    name = Path(relative).name
    needle = "wav2vec" if "wav2vec" in relative.lower() else ""
    for dirpath, _dirs, names in os.walk(root):
        if name not in names:
            continue
        found = Path(dirpath) / name
        if needle and needle not in found.as_posix().lower():
            continue
        return True
    return False


def missing_files(engine: str, root: Path) -> list[dict[str, Any]]:
    return [item for item in files_for(engine) if not _found(root, str(item["path"]))]


def video_length(engine: str, span: tuple[float, float] | None) -> int:
    """One sliding window, or the span in frames when that is longer."""
    spec = ENGINES[engine]
    window = int(spec["sliding_window_size"])
    if span is None:
        return window
    frames = int(round((span[1] - span[0]) * int(spec["fps"])))
    return min(max(frames, window), 4000)

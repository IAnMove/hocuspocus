"""VoxCPM2 speech for WanGP: voice design, voice cloning and two-speaker dialogue.

VoxCPM2 (OpenBMB, 2B, Apache-2.0) is one checkpoint with three ways to pick a voice:

* **design** - no reference audio; a voice description is written in parentheses at the
  start of the text: ``"(young woman, warm voice)Hola"``.
* **clone** - a reference recording conditions the voice (``reference_wav_path``); an
  optional style instruction still goes in parentheses before the text.
* **clone with transcript** - the reference's exact transcript is added, so the model
  continues the recording (``prompt_wav_path`` + ``prompt_text``) as well as using it as a
  reference. This is the closest match to the speaker, but it cannot take a style direction:
  the parenthesised lead would follow the transcript and be read aloud, so a direction
  switches the clone to reference-only.

The model keeps a static KV cache that is allocated on a device at construction time and is
not a registered buffer. The weights are built on the CPU and handed to WanGP's memory
manager; the caches are allocated again on the execution device before each generation.
The audio VAE stays in float32 and outside the managed modules, as upstream runs it.
"""
from __future__ import annotations

import math
import os
import random
import re
from typing import Callable, Optional

import numpy as np
import torch

from .model.voxcpm2 import VoxCPM2Model
from .model.utils import get_dtype, next_and_close

# 16 kHz encoder hop of 640 samples -> 25 latent frames per second; one LM step makes a
# patch of 4 frames, so 6.25 steps per second of speech.
STEPS_PER_SECOND = 6.25
SAMPLE_RATE = 48_000
DEFAULT_PAUSE_SECONDS = 0.5
AUTO_SPLIT_SETTING_ID = "auto_split_every_s"
# Rough speaking rate used to turn "split every N seconds" into a text length.
CHARS_PER_SECOND = 14
_SPEAKER_LINE = re.compile(r"^\s*Speaker\s*(\d+)\s*:\s*(.*)$", re.IGNORECASE)
_LEADING_DIRECTION = re.compile(r"^\s*\(([^()]*)\)\s*")


class VoxCPM2Aborted(Exception):
    """The user stopped the job; the pipeline returns ``None``."""


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_direction(value: str) -> str:
    return " ".join(value.replace("(", " ").replace(")", " ").split())


def compose_text(text: str, direction: str = "") -> str:
    """VoxCPM2 reads a parenthesised lead as voice direction, not as words to speak.

    A separate direction (voice description or style) and a line's own lead such as
    ``(whispering)`` are merged into one lead, so neither is read aloud.
    """
    body = text.strip()
    direction = _clean_direction(direction)
    match = _LEADING_DIRECTION.match(body)
    lead = _clean_direction(match.group(1)) if match else ""
    if match:
        body = body[match.end():]
    merged = ", ".join(part for part in (direction, lead) if part)
    return f"({merged}){body}" if merged else body


def split_paragraphs(text: str) -> list[str]:
    """Manual split: one empty line separates segments that are generated one by one."""
    parts = [" ".join(part.split()) for part in re.split(r"\n\s*\n", text)]
    return [part for part in parts if part]


def split_long_segment(text: str, max_chars: int) -> list[str]:
    """Auto split at sentence ends (then commas) so no segment exceeds ``max_chars``."""
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?¡¿…;:])\s+", text):
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    result = []
    for piece in pieces:
        while len(piece) > max_chars:
            cut = piece.rfind(",", 0, max_chars)
            cut = cut + 1 if cut > max_chars // 3 else piece.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            result.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            result.append(piece)
    return result


def parse_dialogue(text: str) -> list[tuple[int, str]]:
    """``Speaker 1: ...`` / ``Speaker 2: ...`` lines; untagged lines continue the last speaker."""
    turns: list[tuple[int, str]] = []
    for line in text.splitlines():
        match = _SPEAKER_LINE.match(line)
        if match:
            turns.append((int(match.group(1)), match.group(2).strip()))
        elif line.strip() and turns:
            speaker, said = turns[-1]
            turns[-1] = (speaker, f"{said} {line.strip()}".strip())
    return [(speaker, said) for speaker, said in turns if said]


class VoxCPM2Pipeline:
    def __init__(self, model_dir: str, base_model_type: str = "voxcpm2_base", *, device: Optional[str] = None) -> None:
        self.base_model_type = base_model_type
        if not os.path.isfile(os.path.join(model_dir, "config.json")):
            raise FileNotFoundError(f"VoxCPM2 weights are missing in {model_dir}")
        # Built on the CPU in the checkpoint's bfloat16; WanGP's memory manager places it.
        self.model = VoxCPM2Model.from_local(model_dir, optimize=False, device="cpu")
        self.model.eval()
        # The VAE stays float32 (upstream decodes in float32) and outside the managed modules.
        vae = self.model._modules.pop("audio_vae")
        object.__setattr__(self.model, "audio_vae", vae.float().eval())
        self.execution_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.device = self.execution_device
        self.model.config.device = self.execution_device
        self.sample_rate = int(self.model.sample_rate)
        self._cache_device = "cpu"
        self._interrupt = False
        self._early_stop = False

    # -- WanGP hooks -------------------------------------------------------------------
    def request_early_stop(self) -> None:
        self._early_stop = True

    def release(self) -> None:
        for lm in (getattr(self.model, "base_lm", None), getattr(self.model, "residual_lm", None)):
            if lm is not None:
                lm.kv_cache = None
        vae = getattr(self.model, "audio_vae", None)
        if vae is not None:
            vae.to("cpu")
        self._cache_device = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # -- device preparation ------------------------------------------------------------
    def _prepare_device(self) -> None:
        device = self.execution_device
        if self._cache_device != device:
            dtype = get_dtype(self.model.config.dtype)
            length = self.model.config.max_length
            self.model.base_lm.setup_cache(1, length, device, dtype)
            self.model.residual_lm.setup_cache(1, length, device, dtype)
            self._cache_device = device
        self.model.audio_vae.to(device)

    # -- generation --------------------------------------------------------------------
    def _step_hook(self, callback, done_steps: int, total_steps: int, label: str) -> Callable[[int, int], bool]:
        def hook(step: int, max_steps: int) -> bool:
            if self._interrupt:
                raise VoxCPM2Aborted()
            if self._early_stop:
                return True
            if callback is not None:
                callback(
                    step_idx=min(total_steps, done_steps + step),
                    override_num_inference_steps=total_steps,
                    denoising_extra=label,
                    progress_unit="steps",
                )
            return False
        return hook

    def _voice_cache(self, voice: dict) -> Optional[dict]:
        reference = voice.get("reference")
        if not reference:
            return None
        transcript = _text(voice.get("transcript"))
        return self.model.build_prompt_cache(
            prompt_text=transcript or None,
            prompt_wav_path=reference if transcript else None,
            reference_wav_path=reference,
        )

    def _speak(self, text: str, cache: Optional[dict], *, steps: int, cfg: float, max_steps: int,
               hook: Callable[[int, int], bool]) -> torch.Tensor:
        self.model._step_hook = hook
        try:
            result = self.model._generate_with_prompt_cache(
                target_text=text,
                prompt_cache=cache,
                min_len=2,
                max_len=max(4, int(max_steps)),
                inference_timesteps=int(steps),
                cfg_value=float(cfg),
                retry_badcase=True,
                retry_badcase_max_times=3,
                retry_badcase_ratio_threshold=6.0,
            )
            wav, _, _ = next_and_close(result)
        finally:
            self.model._step_hook = None
        return wav.reshape(-1).float().cpu()

    def _voices(self, audio_guide, audio_guide2, audio_prompt_type, alt_prompt, settings) -> tuple[dict, str]:
        if self.base_model_type == "voxcpm2_voicedesign":
            return {}, _text(alt_prompt)
        prompt_type = str(audio_prompt_type or "A").upper()
        if not audio_guide:
            raise ValueError("VoxCPM2 voice clone requires Speaker 1 reference audio.")
        raw = alt_prompt if isinstance(alt_prompt, str) else ""
        two = "B" in prompt_type
        if two and not audio_guide2:
            raise ValueError("Two-speaker mode requires Speaker 2 reference audio.")
        lines = [line.strip() for line in raw.splitlines()] if two else [" ".join(raw.split())]
        lines += ["", ""]
        style = _text(settings.get("style"))
        if style:
            # With a transcript VoxCPM2 continues the recording, so a parenthesised direction
            # lands mid-text and is read aloud; style steering needs reference-only cloning.
            lines = ["", ""]
        voices = {1: {"reference": audio_guide, "transcript": lines[0]}}
        if two:
            voices[2] = {"reference": audio_guide2, "transcript": lines[1]}
        return voices, style

    def _plan(self, text: str, voices: dict[int, dict], dialogue: bool, auto_split_chars: int) -> list[tuple[int, str]]:
        if dialogue:
            turns = parse_dialogue(text)
            missing = sorted({speaker for speaker, _ in turns} - set(voices))
            if missing:
                raise ValueError(f"No reference voice for Speaker {missing[0]}.")
        else:
            turns = [(1, segment) for segment in split_paragraphs(text)]
        plan = []
        for speaker, said in turns:
            plan.extend((speaker, piece) for piece in split_long_segment(said, auto_split_chars))
        if not plan:
            raise ValueError("Prompt text cannot be empty for VoxCPM2.")
        return plan

    def generate(self, *args, **kwargs):
        """See :meth:`_generate`.

        WanGP makes the GPU torch's default device; VoxCPM2 builds some tensors without a
        device and moves them itself, assuming the CPU default it has when run on its own.
        """
        with torch.device("cpu"):
            return self._generate(*args, **kwargs)

    @torch.inference_mode()
    def _generate(
        self,
        input_prompt: str,
        model_mode: Optional[str] = None,
        audio_guide: Optional[str] = None,
        *,
        alt_prompt: Optional[str] = None,
        seed: int = -1,
        callback=None,
        audio_prompt_type: str = "",
        sampling_steps: int = 10,
        guide_scale: float = 2.0,
        **kwargs,
    ):
        """Return ``{"x": waveform, "audio_sampling_rate": 48000}`` or ``None`` when stopped.

        Same fields as Qwen3 TTS: for ``voxcpm2_voicedesign`` ``alt_prompt`` is the voice
        description; for ``voxcpm2_base`` it holds the reference transcript(s), one line per
        speaker (empty: reference-only cloning), and ``custom_settings.style`` is an optional
        style direction.
        """
        self._interrupt = False
        self._early_stop = False
        text = input_prompt if isinstance(input_prompt, str) else ""
        if not text.strip():
            raise ValueError("Prompt text cannot be empty for VoxCPM2.")
        if seed is not None and int(seed) >= 0:
            _seed_everything(int(seed))
        settings = kwargs.get("custom_settings") or {}
        voices, direction = self._voices(audio_guide, kwargs.get("audio_guide2"), audio_prompt_type, alt_prompt, settings)
        dialogue = 2 in voices
        auto_split = int(round(float(settings.get(AUTO_SPLIT_SETTING_ID) or 0) * CHARS_PER_SECOND))
        plan = self._plan(text, voices or {1: {}}, dialogue, auto_split)

        duration = kwargs.get("duration_seconds")
        budget = int(math.ceil(float(duration) * STEPS_PER_SECOND)) if duration else 4096
        pause = max(0.0, float(kwargs.get("pause_seconds", DEFAULT_PAUSE_SECONDS) or 0.0))
        steps = int(sampling_steps or 10)
        cfg = float(guide_scale if guide_scale is not None else 2.0)

        self._prepare_device()
        caches = {speaker: self._voice_cache(voice) for speaker, voice in voices.items()}
        reference_only: dict[int, dict] = {}
        pieces, used = [], 0
        silence = torch.zeros(int(round(pause * self.sample_rate)))
        try:
            for index, (speaker, said) in enumerate(plan):
                if used >= budget or self._early_stop:
                    break
                label = f"Segment {index + 1}/{len(plan)}" if len(plan) > 1 else ""
                hook = self._step_hook(callback, used, budget, label)
                spoken = compose_text(said, direction)
                cache = caches.get(speaker)
                if cache is not None and cache.get("mode") == "ref_continuation" and spoken.startswith("("):
                    # A continuation would read the line's own direction aloud (see the module notes).
                    if speaker not in reference_only:
                        reference_only[speaker] = self.model.build_prompt_cache(
                            reference_wav_path=voices[speaker]["reference"])
                    cache = reference_only[speaker]
                wav = self._speak(spoken, cache, steps=steps, cfg=cfg, max_steps=budget - used, hook=hook)
                used += int(math.ceil(wav.numel() / self.sample_rate * STEPS_PER_SECOND))
                if pieces and silence.numel():
                    pieces.append(silence)
                pieces.append(wav)
        except VoxCPM2Aborted:
            return None
        if self._interrupt or not pieces:
            return None
        audio = torch.cat(pieces)
        if duration:
            audio = audio[: int(float(duration) * self.sample_rate)]
        return {"x": audio, "audio_sampling_rate": self.sample_rate}

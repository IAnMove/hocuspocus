"""Isolated MiniMax-H3 runtime backed by the official ComfyUI implementation.

The open H3 checkpoints are too large to load through Maestro's normal WanGP
process on a 24 GB card.  This module keeps ComfyUI in a separate environment,
offers quantized profiles for 16-24 GB cards, and starts/stops the sidecar on
demand so it never competes with WanGP for VRAM.
"""

from __future__ import annotations

import atexit
import json
import math
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import requests
import websocket as websocket_client


MODEL_ID = "minimax_h3"
MODEL_NAME = "MiniMax H3 (native audio, 768p)"
HF_REPO = "Comfy-Org/MiniMax-H3"
COMMUNITY_HF_REPO = "Abiray/Minimax-H3-nvfp4-INT4-INT8-Convrot"

SERVICE_DIR = Path(__file__).resolve().parent / "minimax_h3"
COMFY_DIR = SERVICE_DIR / "vendor" / "ComfyUI"
ENV_DIR = SERVICE_DIR / "env"
INPUT_DIR = COMFY_DIR / "input"
OUTPUT_DIR = COMFY_DIR / "output"

FL2VA_MODEL = "MiniMax_H3_FL2VA_pruned_mixed_int4_int8_convrot.safetensors"
# The community model card still documents a mixed Ref2VA file, but the Hub
# repository does not publish it. Balanced Ref2VA therefore uses the available
# INT4 ConvRot checkpoint; FL2VA keeps the mixed checkpoint.
REF2VA_MODEL = "MiniMax_H3_Ref2VA_pruned_int4_convrot.safetensors"
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_int4_convrot.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"

DEFAULT_AUDIO_DIRECTION = (
    "Natural synchronized production sound matching the visible environment "
    "and actions; include explicitly described dialogue or music, otherwise "
    "use ambience and sound effects only; clear, audible stereo mix."
)

MODEL_PROFILES = {
    # ``balanced`` is retained as a backwards-compatible saved-settings alias.
    # It now resolves to the same INT8 pair as ``quality`` so existing 4090
    # users never silently fall back to the visibly softer INT4 Ref2VA model.
    "balanced": {
        "text_encoder": "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
        "fl2va": "MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors",
        "ref2va": "MiniMax_H3_Ref2VA_pruned_int8_convrot.safetensors",
    },
    "quality": {
        "text_encoder": "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
        "fl2va": "MiniMax_H3_FL2VA_pruned_int8_convrot.safetensors",
        "ref2va": "MiniMax_H3_Ref2VA_pruned_int8_convrot.safetensors",
    },
    "low_memory": {
        "text_encoder": "qwen3vl_32b_minimax_h3_int4_convrot.safetensors",
        "fl2va": "MiniMax_H3_FL2VA_pruned_int4_convrot.safetensors",
        "ref2va": "MiniMax_H3_Ref2VA_pruned_int4_convrot.safetensors",
    },
}

VAE_FILES = (
    (HF_REPO, f"vae/{VIDEO_VAE}", VIDEO_VAE),
    (HF_REPO, f"vae/{AUDIO_VAE}", AUDIO_VAE),
)

# Cache entries from the original integration, retained only so Settings can
# remove them after a user moves to one of the Ada-safe ConvRot profiles.
LEGACY_FILES = (
    (HF_REPO, "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
     "minimax_h3_fl2va_pruned_int8_convrot.safetensors"),
    (HF_REPO, "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
     "minimax_h3_ref2va_pruned_int8_convrot.safetensors"),
    (HF_REPO, "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
     "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
)

DEFAULTS = {
    "prompt": "",
    "model_type": MODEL_ID,
    "resolution": "960x544",
    "video_length": 124,
    "num_inference_steps": 20,
    "guidance_scale": 1.0,
    "seed": -1,
    "image_mode": 0,
    "negative_prompt": "",
    "repeat_generation": 1,
    "activated_loras": [],
    "loras_multipliers": "",
    "flow_shift": 12.0,
    "h3_audio_shift": 3.0,
    "h3_audio_prompt": DEFAULT_AUDIO_DIRECTION,
    "h3_ref_image_size": "match",
    "h3_model_profile": "quality",
    "h3_reference_mode": "first_frame",
    "image_fit_mode": "contain",
}


def prepare_extend_anchor(
    params: dict,
    job_id: str,
    source_path: str,
    cache_dir: str | Path,
) -> dict:
    """Turn an Extend source video into an exact FL2VA start frame.

    H3's FL2VA pipeline has no video-continuation input. Passing
    ``video_source`` through unchanged therefore made the model ignore it.
    Capturing the final decodable frame gives Extend deterministic visual
    continuity without paying the cost of Ref2VA or treating the source as a
    loose semantic reference.
    """
    from .video_editor import extract_frame, probe_media

    media = probe_media(source_path)
    destination_dir = Path(cache_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"minimax_h3_extend_{job_id}_last.png"
    frame = extract_frame(source_path, str(destination), float(media["duration"]))

    ignored_references = sum(
        len([item for item in (params.get(key) or []) if item])
        for key in ("image_refs", "h3_ref_videos", "h3_ref_audios")
    )
    params["image_start"] = str(destination)
    params["image_prompt_type"] = "S"
    params["h3_reference_mode"] = "first_frame"
    params["image_mode"] = 0
    params.pop("image_refs", None)
    params.pop("h3_ref_videos", None)
    params.pop("h3_ref_audios", None)
    params["h3_extend_anchor_time"] = frame["time"]

    return {
        "path": str(destination),
        "time": frame["time"],
        "width": frame["width"],
        "height": frame["height"],
        "ignored_references": ignored_references,
    }


MODEL_OPTIONS = {
    "model_type": MODEL_ID,
    "architecture": MODEL_ID,
    "guidance_max_phases": 1,
    "lock_guidance_phases": True,
    "sliding_window": False,
    "motion_amplitude": False,
    "flow_shift": True,
    "tea_cache": False,
    "returns_audio": True,
    "any_audio_prompt": False,
    "audio_scale_name": "",
    "lock_inference_steps": False,
    "lock_guidance_scale": True,
    "no_negative_prompt": True,
    "i2v_class": True,
    "t2v_class": True,
    "image_outputs": False,
    "supports_end_frame": True,
    "guide_preprocessing": None,
    "guide_custom_choices": None,
    "image_ref_choices": {"choices": [["References", "I"]], "default": "I"},
    "audio_prompt_type_sources": None,
    "background_removal_label": None,
    "sample_solvers": [["RES Multistep", "res_multistep"]],
    "self_refiner": False,
    "self_refiner_max_plans": 1,
    "sliding_window_defaults": None,
    "fps": 24,
    "frames_minimum": 107,
    "frames_steps": 17,
    "default_num_inference_steps": 20,
    "default_guidance_scale": 1.0,
    "hide_resolution_presets": False,
    "input_video_strength_label": "",
    "vae_upsampler_modes": [],
    "audio_only": False,
    "duration_slider": None,
    "pause_between_sentences": False,
    "temperature_enabled": False,
    "custom_settings_def": None,
    "h3_reference_inputs": True,
}

_process: subprocess.Popen | None = None
_port: int | None = None
_runtime_profile: str | None = None
_runtime_lock = threading.RLock()
_active_prompt: str | None = None
_idle_shutdown_timer: threading.Timer | None = None

# Keep the large H3 sidecar warm briefly after the queue becomes idle. The
# caller cancels this timer when a compatible job arrives, so a run of clips
# does not repeatedly reload the model just to generate the next one.
DEFAULT_IDLE_SHUTDOWN_SECONDS = 45.0


def _python_executable() -> Path:
    return ENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def is_runtime_installed() -> bool:
    return _python_executable().is_file() and (COMFY_DIR / "main.py").is_file()


def _model_path(relative_name: str) -> Path:
    return COMFY_DIR / "models" / relative_name


def _profile_name(params: dict | None = None) -> str:
    requested = str((params or {}).get("h3_model_profile") or "quality").strip().lower()
    requested = {"mixed": "balanced", "int8": "quality", "int4": "low_memory"}.get(
        requested, requested
    )
    return requested if requested in MODEL_PROFILES else "balanced"


def ensure_audio_prompt(prompt: str, audio_direction: str = "") -> str:
    """Give H3 an explicit audio contract without duplicating authored audio.

    H3 always returns an audio stream, but a visual-only prompt can yield a
    nearly silent mix.  An authored ``Audio:`` clause remains authoritative;
    otherwise Maestro appends either the selected direction or its practical
    production-sound default.
    """
    normalized_prompt = str(prompt or "").strip()
    if (
        re.search(r"\baudio\s*:", normalized_prompt, flags=re.IGNORECASE)
        or "overall_soundscape:" in normalized_prompt
    ):
        return normalized_prompt
    normalized_audio = " ".join(str(audio_direction or "").split())
    if not normalized_audio:
        normalized_audio = DEFAULT_AUDIO_DIRECTION
    prefix = f"{normalized_prompt}\n" if normalized_prompt else ""
    return f"{prefix}Audio: {normalized_audio}"


def _profile_files(profile: str, pipeline: str | None = None) -> list[tuple[str, str, str]]:
    selected = MODEL_PROFILES[profile]
    files = [
        (COMMUNITY_HF_REPO, f"text_encoders/{selected['text_encoder']}", selected["text_encoder"]),
        *VAE_FILES,
    ]
    pipelines = (pipeline,) if pipeline else ("fl2va", "ref2va")
    files.extend(
        (COMMUNITY_HF_REPO, f"diffusion_models/{selected[kind]}", selected[kind])
        for kind in pipelines
    )
    return files


def is_model_downloaded() -> bool:
    for profile in MODEL_PROFILES:
        files = _profile_files(profile)
        shared = files[:3]
        pipelines = files[3:]
        if all(_model_path(relative).is_file() for _, relative, _ in shared) and any(
            _model_path(relative).is_file() for _, relative, _ in pipelines
        ):
            return True
    return False


def delete_model_cache() -> list[str]:
    stop_runtime()
    deleted: list[str] = []
    all_files = [item for profile in MODEL_PROFILES for item in _profile_files(profile)]
    all_files.extend(LEGACY_FILES)
    seen: set[str] = set()
    for _, relative, _ in all_files:
        if relative in seen:
            continue
        seen.add(relative)
        path = _model_path(relative)
        if path.is_file():
            path.unlink()
            deleted.append(path.name)
    return deleted


def _ensure_models(pipeline: str, profile: str, progress: Callable[[str], None]) -> None:
    from huggingface_hub import hf_hub_download

    wanted = _profile_files(profile, pipeline)
    for index, (repo_id, relative, display_name) in enumerate(wanted, 1):
        destination = _model_path(relative)
        if destination.is_file():
            continue
        progress(f"Downloading MiniMax H3 ({index}/{len(wanted)}): {display_name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Abiray publishes DiT files at the repository root, while ComfyUI
        # requires them under models/diffusion_models. Text encoders and the
        # official VAEs already use their desired subfolders on the Hub.
        if repo_id == COMMUNITY_HF_REPO and relative.startswith("diffusion_models/"):
            remote_filename = display_name
            local_dir = destination.parent
        else:
            remote_filename = relative
            local_dir = COMFY_DIR / "models"
        hf_hub_download(
            repo_id=repo_id,
            filename=remote_filename,
            local_dir=str(local_dir),
        )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _drain_output(process: subprocess.Popen) -> None:
    if process.stdout is None:
        return
    for line in iter(process.stdout.readline, ""):
        if line:
            print(f"[MiniMax H3] {line.rstrip()}")


def _runtime_command(port: int, profile: str = "quality") -> list[str]:
    """Build the ComfyUI command used by the isolated H3 sidecar."""
    command = [
        str(_python_executable()), "main.py", "--listen", "127.0.0.1",
        "--port", str(port), "--disable-auto-launch",
        # The eager INT8 fallback materializes a large torch.cat result and can
        # exhaust a 24 GB card. H3's ComfyUI stack includes Triton's fused
        # int8_linear backend, which avoids that transient allocation.
        "--enable-triton-backend",
    ]
    # The 21 GB quality DiT needs chunked loading on a 24 GB card.  MIXED and
    # INT4 fit alongside the VAE at the recommended 540p canvas and are faster
    # with ComfyUI's normal VRAM manager.
    if profile in {"quality", "balanced"}:
        command.append("--lowvram")
    return command


def ensure_runtime(progress: Callable[[str], None], profile: str = "quality") -> str:
    global _process, _port, _runtime_profile
    with _runtime_lock:
        _cancel_idle_shutdown_locked()
        if _process is not None and _process.poll() is None and _port is not None:
            if _runtime_profile == profile:
                return f"http://127.0.0.1:{_port}"
            stop_runtime()
        if not is_runtime_installed():
            raise RuntimeError(
                "MiniMax H3 support is not installed. Run Update (or Install) from the Pinokio menu first."
            )
        _port = _free_port()
        _runtime_profile = profile
        progress("Starting the isolated MiniMax H3 runtime…")
        _process = subprocess.Popen(
            _runtime_command(_port, profile),
            cwd=str(COMFY_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=_drain_output, args=(_process,), daemon=True).start()
        base_url = f"http://127.0.0.1:{_port}"
        deadline = time.time() + 180
        while time.time() < deadline:
            if _process.poll() is not None:
                raise RuntimeError(f"MiniMax H3 runtime exited with code {_process.returncode}")
            try:
                if requests.get(f"{base_url}/system_stats", timeout=2).ok:
                    return base_url
            except requests.RequestException:
                pass
            time.sleep(1)
        stop_runtime()
        raise RuntimeError("MiniMax H3 runtime did not become ready within 3 minutes")


def _cancel_idle_shutdown_locked() -> None:
    global _idle_shutdown_timer
    if _idle_shutdown_timer is not None:
        _idle_shutdown_timer.cancel()
        _idle_shutdown_timer = None


def cancel_idle_shutdown() -> None:
    """Keep H3 warm because another H3 job is about to run."""
    with _runtime_lock:
        _cancel_idle_shutdown_locked()


def _stop_runtime_locked() -> None:
    global _process, _port, _runtime_profile, _active_prompt
    process = _process
    _process = None
    _port = None
    _runtime_profile = None
    _active_prompt = None
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def stop_runtime() -> None:
    """Release the isolated H3 runtime immediately."""
    with _runtime_lock:
        _cancel_idle_shutdown_locked()
        _stop_runtime_locked()


def schedule_idle_shutdown(
    delay_seconds: float = DEFAULT_IDLE_SHUTDOWN_SECONDS,
    should_keep_warm: Callable[[], bool] | None = None,
) -> None:
    """Release H3 after a short idle period unless the queue becomes active.

    ``should_keep_warm`` is evaluated under the runtime lock immediately
    before shutdown. It is a final race-safe queue check; enqueueing a job
    should also call :func:`cancel_idle_shutdown` for an immediate cancel.
    """
    global _idle_shutdown_timer
    delay = max(0.0, float(delay_seconds))

    with _runtime_lock:
        _cancel_idle_shutdown_locked()

        def _shutdown_if_still_idle() -> None:
            global _idle_shutdown_timer
            with _runtime_lock:
                if _idle_shutdown_timer is not timer:
                    return
                _idle_shutdown_timer = None
                if should_keep_warm is not None and should_keep_warm():
                    return
                _stop_runtime_locked()

        timer = threading.Timer(delay, _shutdown_if_still_idle)
        timer.daemon = True
        _idle_shutdown_timer = timer
        timer.start()


def cancel() -> None:
    if _port is None:
        return
    try:
        requests.post(f"http://127.0.0.1:{_port}/interrupt", timeout=3)
    except requests.RequestException:
        pass


def _node(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def _copy_input(source: str, job_id: str, index: int) -> str:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Reference file does not exist: {source}")
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"maestro_h3_{job_id}_{index}_{path.name}"
    shutil.copy2(path, INPUT_DIR / name)
    return name


def _copy_frame_input(
    source: str,
    job_id: str,
    index: int,
    width: int,
    height: int,
    fit_mode: str = "contain",
) -> str:
    """Prepare an FL2VA boundary frame without ever stretching its content.

    MiniMax's Comfy node receives the configured canvas size separately.  A raw
    portrait image on a landscape canvas can therefore be resized non-uniformly
    inside the node.  We remove that ambiguity by supplying an already-sized
    RGB PNG: contain/legacy-source uses a centered black matte, while crop is an
    explicit opt-in that fills the canvas and discards the outer edges.
    """
    from PIL import Image, ImageOps

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Frame image does not exist: {source}")
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = (max(1, int(width)), max(1, int(height)))
    mode = str(fit_mode or "contain").strip().lower()
    mode = "contain" if mode in {"", "source", "fit", "preserve"} else mode

    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        if mode == "crop":
            prepared = ImageOps.fit(
                image,
                target,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
        else:
            contained = ImageOps.contain(image, target, method=Image.Resampling.LANCZOS)
            prepared = Image.new("RGB", target, (0, 0, 0))
            offset = (
                (target[0] - contained.width) // 2,
                (target[1] - contained.height) // 2,
            )
            prepared.paste(contained, offset)

        name = f"maestro_h3_{job_id}_{index}_frame.png"
        prepared.save(INPUT_DIR / name, format="PNG", optimize=True)
    return name


def _probe_duration(source: str) -> float:
    """Read media duration with PyAV without decoding the complete asset."""
    import av

    with av.open(source) as container:
        if container.duration is not None:
            # PyAV exposes a container duration in AV_TIME_BASE units
            # (microseconds), while ``av.time_base`` is the number of those
            # units per second. Multiplying produces absurd durations such as
            # 14,083,333,000,000s for a 14.083s MP4; convert to seconds by
            # dividing instead.
            return float(container.duration / av.time_base)
        durations = [float(stream.duration * stream.time_base)
                     for stream in container.streams if stream.duration is not None]
        if durations:
            return max(durations)
    raise ValueError(f"Could not determine reference duration: {source}")


def _validate_timed_references(sources: list[str], label: str) -> None:
    durations = []
    for source in sources:
        duration = _probe_duration(source)
        if duration < 2 or duration > 15:
            raise ValueError(f"MiniMax H3 {label} references must each be 2–15 seconds ({Path(source).name}: {duration:.1f}s)")
        durations.append(duration)
    if sum(durations) > 15.05:
        raise ValueError(f"MiniMax H3 {label} references may total at most 15 seconds")


def _base_sampling_graph(params: dict, model_name: str, text_encoder: str) -> dict:
    steps = max(1, min(100, int(params.get("num_inference_steps", 20))))
    seed = int(params.get("seed", -1))
    if seed < 0:
        seed = uuid.uuid4().int % (2**63 - 1)
    return {
        "1": _node("UNETLoader", unet_name=model_name, weight_dtype="default"),
        "2": _node("MiniMaxH3SigmaShift", model=["1", 0],
                   shift_video=float(params.get("flow_shift", 12.0)),
                   shift_audio=float(params.get("h3_audio_shift", 3.0))),
        "3": _node("CLIPLoader", clip_name=text_encoder, type="minimax", device="default"),
        "4": _node("VAELoader", vae_name=VIDEO_VAE),
        "5": _node("VAELoader", vae_name=AUDIO_VAE),
        "20": _node("RandomNoise", noise_seed=seed),
        "21": _node("BasicGuider", model=["2", 0], conditioning=["10", 0]),
        "22": _node("KSamplerSelect", sampler_name="res_multistep"),
        "23": _node("BasicScheduler", model=["2", 0], scheduler="simple", steps=steps, denoise=1.0),
        "24": _node("SamplerCustomAdvanced", noise=["20", 0], guider=["21", 0],
                    sampler=["22", 0], sigmas=["23", 0], latent_image=["10", 1]),
        "25": _node("VAEDecode", samples=["24", 0], vae=["4", 0]),
        "26": _node("VAEDecodeAudio", samples=["24", 0], vae=["5", 0]),
        "27": _node("CreateVideo", images=["25", 0], audio=["26", 0], fps=24.0),
        # DynamicCombo API inputs are submitted as their selected key. ComfyUI
        # expands "auto" into {"codec": "auto"} before invoking SaveVideo.
        "28": _node("SaveVideo", video=["27", 0], filename_prefix="Maestro/MiniMax_H3",
                    format="auto", codec="auto"),
    }


def build_workflow(params: dict, job_id: str) -> tuple[dict, str]:
    """Build a Comfy API workflow and return it with the selected H3 pipeline."""
    width, height = (int(v) for v in str(params.get("resolution", "960x544")).lower().split("x", 1))
    width = max(32, round(width / 32) * 32)
    height = max(32, round(height / 32) * 32)
    # The open Base canvas is capped at 768*1344 pixels. Preserve the user's
    # aspect ratio while reducing oversized 1080p/4K UI presets to that cap.
    max_pixels = 768 * 1344
    if width * height > max_pixels:
        scale = math.sqrt(max_pixels / (width * height))
        width = max(32, round(width * scale / 32) * 32)
        height = max(32, round(height * scale / 32) * 32)
    length = int(params.get("video_length", 124))
    length = max(107, min(362, length))
    while length % 17 != 5:
        length += 1

    image_refs = [p for p in (params.get("image_refs") or []) if p]
    video_refs = [p for p in (params.get("h3_ref_videos") or []) if p]
    audio_refs = [p for p in (params.get("h3_ref_audios") or []) if p]
    has_omni_refs = bool(image_refs or video_refs or audio_refs)
    requested_mode = str(params.get("h3_reference_mode") or "").strip().lower()
    requested_mode = {
        "fl2va": "first_frame",
        "ref2va": "references",
        "reference": "references",
    }.get(requested_mode, requested_mode)
    if requested_mode == "first_frame":
        if has_omni_refs:
            raise ValueError(
                "MiniMax H3 First-frame mode cannot also use omni references; "
                "remove them or choose Ref2VA References mode."
            )
        pipeline = "fl2va"
    elif requested_mode == "references":
        if not has_omni_refs:
            raise ValueError(
                "MiniMax H3 Ref2VA References mode needs at least one image, "
                "video, or paired audio reference."
            )
        pipeline = "ref2va"
    else:
        # Backwards compatibility for saved jobs created before the explicit
        # selector existed. New jobs always submit h3_reference_mode.
        pipeline = "ref2va" if has_omni_refs else "fl2va"
    profile = _profile_name(params)
    selected = MODEL_PROFILES[profile]
    workflow = _base_sampling_graph(params, selected[pipeline], selected["text_encoder"])
    raw_prompt = str(params.get("prompt", ""))
    authored_audio = re.search(r"\bAudio\s*:\s*(.*)$", raw_prompt, flags=re.I | re.S)
    audio_direction = (
        authored_audio.group(1).strip()
        if authored_audio
        else str(params.get("h3_audio_prompt", ""))
    )
    try:
        from .director.minimax_h3_prompting import format_minimax_h3_prompt
    except ImportError:
        from services.director.minimax_h3_prompting import format_minimax_h3_prompt
    prompt = format_minimax_h3_prompt(
        {},
        raw_prompt,
        reference_mode="references" if pipeline == "ref2va" else "first_frame",
        audio_direction=audio_direction,
    )
    copy_index = 0

    if pipeline == "fl2va":
        inputs = {"clip": ["3", 0], "vae": ["4", 0], "prompt": prompt,
                  "width": width, "height": height, "length": length}
        for key, input_name in (("image_start", "first_frame"), ("image_end", "last_frame")):
            source = params.get(key)
            if isinstance(source, list):
                source = next((item for item in source if item), None)
            if source:
                copy_index += 1
                node_id = str(30 + copy_index)
                workflow[node_id] = _node(
                    "LoadImage",
                    image=_copy_frame_input(
                        source,
                        job_id,
                        copy_index,
                        width,
                        height,
                        str(params.get("image_fit_mode") or "contain"),
                    ),
                )
                inputs[input_name] = [node_id, 0]
        workflow["10"] = _node("MiniMaxH3ImageToVideo", **inputs)
        return workflow, pipeline

    if len(image_refs) > 9 or len(video_refs) > 3 or len(audio_refs) > 3:
        raise ValueError("MiniMax H3 accepts at most 9 images, 3 videos, and 3 audio references")
    if len(image_refs) + len(video_refs) + len(audio_refs) > 12:
        raise ValueError("MiniMax H3 accepts at most 12 reference files in total")
    if audio_refs and not (image_refs or video_refs):
        raise ValueError("MiniMax H3 Ref2VA cannot use audio alone; add an image or video reference")
    _validate_timed_references(video_refs, "video")
    _validate_timed_references(audio_refs, "audio")

    inputs = {"clip": ["3", 0], "vae": ["4", 0], "audio_vae": ["5", 0],
              "prompt": prompt, "width": width, "height": height, "length": length,
              "ref_image_size": params.get("h3_ref_image_size", "match")}
    # ComfyUI V3 autogrow inputs use dotted API keys.  The executor expands
    # ``ref_images.ref_image_0`` into ``ref_images={"ref_image_0": tensor}``
    # before calling the node.  Bare ``ref_image_1`` keys bypass that expansion
    # and are forwarded as unexpected execute() keyword arguments.
    for index, source in enumerate(image_refs):
        copy_index += 1
        node_id = str(40 + copy_index)
        workflow[node_id] = _node("LoadImage", image=_copy_input(source, job_id, copy_index))
        inputs[f"ref_images.ref_image_{index}"] = [node_id, 0]
    for index, source in enumerate(video_refs):
        copy_index += 1
        load_id = str(50 + copy_index * 2)
        components_id = str(51 + copy_index * 2)
        workflow[load_id] = _node("LoadVideo", file=_copy_input(source, job_id, copy_index))
        workflow[components_id] = _node("GetVideoComponents", video=[load_id, 0])
        inputs[f"ref_videos.ref_video_{index}"] = [components_id, 0]
        inputs[f"ref_video_audios.ref_video_audio_{index}"] = [components_id, 1]
    for index, source in enumerate(audio_refs):
        copy_index += 1
        node_id = str(80 + copy_index)
        workflow[node_id] = _node("LoadAudio", audio=_copy_input(source, job_id, copy_index))
        inputs[f"ref_audios.ref_audio_{index}"] = [node_id, 0]
    workflow["10"] = _node("MiniMaxH3ReferenceToVideo", **inputs)
    return workflow, pipeline


def _comfy_progress_event(raw: object, prompt_id: str) -> tuple[str, int, int, int] | None:
    """Turn a ComfyUI websocket sampling event into Maestro job progress."""
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if payload.get("type") != "progress":
        return None
    data = payload.get("data") or {}
    if data.get("prompt_id") != prompt_id:
        return None
    try:
        current = int(data.get("value", 0))
        total = int(data.get("max", 0))
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    current = max(0, min(current, total))
    percent = max(10, min(95, 10 + round((current / total) * 85)))
    if current >= total:
        message = f"MiniMax H3 sampling complete ({current}/{total}); decoding video and audio…"
    else:
        message = f"MiniMax H3 sampling — step {current}/{total}"
    return message, percent, current, total


def _generate_impl(params: dict, job_id: str, out_dir: str, progress: Callable[[str, int, int, int], None],
                   cancelled: Callable[[], bool]) -> list[str]:
    global _active_prompt
    workflow, pipeline = build_workflow(params, job_id)
    profile = _profile_name(params)
    if not is_runtime_installed():
        raise RuntimeError(
            "MiniMax H3 support is not installed. Run Update (or Install) from the Pinokio menu first."
        )
    _ensure_models(pipeline, profile, lambda message: progress(message, 3, 0, 0))
    base_url = ensure_runtime(lambda message: progress(message, 8, 0, 0), profile)
    progress("Loading MiniMax H3 and generating native video + stereo audio…", 10, 0, 0)
    client_id = f"maestro-{job_id}"
    response = requests.post(
        f"{base_url}/prompt", json={"prompt": workflow, "client_id": client_id}, timeout=30
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("node_errors"):
        raise RuntimeError(f"MiniMax H3 workflow validation failed: {payload['node_errors']}")
    prompt_id = payload["prompt_id"]
    ws = None
    try:
        ws_scheme = "wss" if base_url.startswith("https://") else "ws"
        ws_host = base_url.split("://", 1)[-1]
        ws = websocket_client.create_connection(
            f"{ws_scheme}://{ws_host}/ws?clientId={client_id}",
            timeout=2,
        )
        ws.settimeout(1)
    except Exception:
        # Progress telemetry is an enhancement; history polling remains the
        # reliable completion path if a websocket cannot be established.
        if ws is not None:
            ws.close()
        ws = None
    _active_prompt = prompt_id
    deadline = time.time() + 6 * 60 * 60
    history = None
    last_history_poll = 0.0
    try:
        while time.time() < deadline:
            if cancelled():
                cancel()
                raise InterruptedError("MiniMax H3 generation cancelled")

            if ws is not None:
                try:
                    update = _comfy_progress_event(ws.recv(), prompt_id)
                    if update is not None:
                        progress(*update)
                except websocket_client.WebSocketTimeoutException:
                    pass
                except Exception:
                    ws.close()
                    ws = None

            now = time.time()
            if now - last_history_poll >= 1:
                # H3 can still be decoding and writing the final video/audio
                # when ComfyUI receives this status request.  Ten seconds is
                # too short on large local renders and incorrectly reports a
                # completed prompt as failed.
                result = requests.get(f"{base_url}/history/{prompt_id}", timeout=60).json()
                last_history_poll = now
                if prompt_id in result:
                    history = result[prompt_id]
                    break
            if ws is None:
                time.sleep(1)
    finally:
        _active_prompt = None
        if ws is not None:
            ws.close()
    if history is None:
        cancel()
        raise TimeoutError("MiniMax H3 generation exceeded the 6-hour safety timeout")
    status = history.get("status", {})
    if status.get("status_str") == "error" or not status.get("completed", False):
        messages = status.get("messages", [])
        raise RuntimeError(f"MiniMax H3 generation failed: {json.dumps(messages)[-2000:]}")

    output_files: list[str] = []
    for node_output in history.get("outputs", {}).values():
        for media_key in ("videos", "images"):
            for item in node_output.get(media_key, []):
                if item.get("type") != "output":
                    continue
                source = OUTPUT_DIR / item.get("subfolder", "") / item["filename"]
                if source.is_file():
                    Path(out_dir).mkdir(parents=True, exist_ok=True)
                    destination = Path(out_dir) / f"minimax_h3_{job_id}{source.suffix}"
                    shutil.copy2(source, destination)
                    try:
                        source.unlink()
                    except OSError:
                        pass
                    output_files.append(str(destination))
    if not output_files:
        raise RuntimeError("MiniMax H3 completed but ComfyUI returned no saved video")
    progress("MiniMax H3 generation complete", 100, 0, 0)
    return output_files


def generate(params: dict, job_id: str, out_dir: str, progress: Callable[[str, int, int, int], None],
             cancelled: Callable[[], bool], *, keep_runtime: bool = False) -> list[str]:
    try:
        try:
            return _generate_impl(params, job_id, out_dir, progress, cancelled)
        except RuntimeError as exc:
            message = str(exc).casefold()
            profile = _profile_name(params)
            is_oom = any(marker in message for marker in (
                "out of memory",
                "cuda error: memory allocation",
                "allocation on device",
                "failed to allocate",
            ))
            if profile not in {"quality", "balanced"} or not is_oom or cancelled():
                raise
            stop_runtime()
            params["h3_model_fallback_from"] = profile
            params["h3_model_profile"] = "low_memory"
            progress(
                "INT8 exceeded available VRAM; retrying this clip with the INT4 fallback…",
                2,
                0,
                0,
            )
            return _generate_impl(params, job_id, out_dir, progress, cancelled)
    finally:
        if INPUT_DIR.is_dir():
            for staged in INPUT_DIR.glob(f"maestro_h3_{job_id}_*"):
                try:
                    staged.unlink()
                except OSError:
                    pass
        if not keep_runtime:
            stop_runtime()


atexit.register(stop_runtime)

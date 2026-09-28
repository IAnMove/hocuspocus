"""RAM headroom and step-pace for queued video loads.

Before a large video model is loaded, ``prepare_queued_model`` unloads
inactive image, speech, and music families when available RAM is below
``HOCUSPOCUS_QUEUE_RAM_MIN_BYTES`` (default 24 GiB, ``24 * 1024**3``).
Available RAM is MemAvailable: ``psutil.virtual_memory().available`` when
psutil imports, otherwise ``MemAvailable`` from ``/proc/meminfo``. An
unknown reading is not treated as low RAM.

``HOCUSPOCUS_QUEUE_PACE_PATH`` is an optional JSON file for the per-model
seconds-per-step baseline. When it is unset the book stays in process
memory. A run is degraded when its seconds per step are strictly greater
than 1.6 times that baseline. The first sample records the baseline and
is not degraded.

Large video ids are the defaults whose ``model.architecture`` is MiniMax
H3 (not H3 Advanced), LTX-2.3 (``ltx2_22B``, not ``ltx2_19B``), or Wan
14B. Wan 1.3B, Wan 5B (``ti2v_2_2``, ``lucy_edit``, ``kiwi_edit``), and
``ovi`` are not in that set. Architecture strings come from the family
handlers' ``query_supported_types`` lists.
"""

from __future__ import annotations

import json
import math
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

_DEFAULT_MIN_BYTES = 24 * 1024**3
_PACE_RATIO = 1.6
_RAM_ENV = "HOCUSPOCUS_QUEUE_RAM_MIN_BYTES"
_PACE_ENV = "HOCUSPOCUS_QUEUE_PACE_PATH"
_INACTIVE_FAMILIES = ("image", "tts", "music")
_DEFAULTS_DIR = Path(__file__).resolve().parents[1] / "defaults"

# minimax_h3_handler.query_supported_types. Fused-turbo presets reuse these
# architectures. h3_advanced_* is a separate family and stays out.
_H3_ARCHITECTURES = frozenset({
    "minimax_h3",
    "minimax_h3_full",
    "minimax_h3_legacy",
    "minimax_h3_ref2va",
    "minimax_h3_ref2va_full",
})

# ltx2_handler architecture for LTX-2.3. ltx2_19B is the older LTX-2 line.
_LTX23_ARCHITECTURES = frozenset({"ltx2_22B"})

# wan_handler.query_supported_types minus the 1.3B list and the 5B editors
# (ti2v_2_2, lucy_edit, kiwi_edit), plus vace_lynx_lite_14B from the
# compatibility map and sky_df_14B from df_handler. ovi is its own handler.
_WAN14_ARCHITECTURES = frozenset({
    "alpha",
    "alpha2",
    "alpha_lynx",
    "animate",
    "chrono_edit",
    "fantasy",
    "flf2v_720p",
    "fun_inp",
    "i2v",
    "i2v_2_2",
    "i2v_2_2_multitalk",
    "i2v_2_2_svi2pro",
    "infinitetalk",
    "lynx",
    "lynx_lite",
    "mocha",
    "multitalk",
    "phantom_14B",
    "scail",
    "scail2_14B",
    "sky_df_14B",
    "standin",
    "steadydancer",
    "t2v",
    "t2v_2_2",
    "vace_14B",
    "vace_14B_2_2",
    "vace_ditto_14B",
    "vace_lynx_14B",
    "vace_lynx_lite_14B",
    "vace_multitalk_14B",
    "vace_standin_14B",
    "wanmove",
})

_LARGE_VIDEO_ARCHITECTURES = _H3_ARCHITECTURES | _LTX23_ARCHITECTURES | _WAN14_ARCHITECTURES

# Image families: flux, qwen, z_image, hidream, and krea2 handlers.
_IMAGE_ARCHITECTURES = frozenset({
    "flux",
    "flux2_dev",
    "flux2_klein_4b",
    "flux2_klein_9b",
    "flux_chroma",
    "flux_chroma_radiance",
    "flux_dev_kontext",
    "flux_dev_kontext_dreamomni2",
    "flux_dev_umo",
    "flux_dev_uso",
    "flux_schnell",
    "hidream_o1",
    "hidream_o1_dev",
    "krea2_raw",
    "krea2_raw_edit",
    "krea2_turbo",
    "krea2_turbo_edit",
    "pi_flux2",
    "qwen_image_20B",
    "qwen_image_21",
    "qwen_image_edit_20B",
    "qwen_image_edit_plus2_20B",
    "qwen_image_edit_plus_20B",
    "qwen_image_layered_20B",
    "z_image",
    "z_image_base",
    "z_image_control",
    "z_image_control2",
    "z_image_control2_1",
})

# Speech catalog in studio_speech_spec.SPEECH_MODEL_TYPES. Presets such as
# auk_flash share the architecture of the base id.
_TTS_ARCHITECTURES = frozenset({
    "auk",
    "chatterbox",
    "dramabox_audio",
    "index_tts2",
    "kugelaudio_0_open",
    "qwen3_tts_base",
    "qwen3_tts_customvoice",
    "qwen3_tts_voicedesign",
    "scenema_audio",
})

# Music handlers under app/models/TTS. They share WGP family "tts" with
# speech, so the product family is the architecture, not that string.
_MUSIC_ARCHITECTURES = frozenset({
    "ace_step_v1",
    "ace_step_v1_5",
    "ace_step_v1_5_xl",
    "heartmula_oss_3b",
    "minimax_music3",
    "yue",
    "yue2",
})

_MODEL_CACHE: dict[str, dict[str, Any]] = {}
_PACE: dict[str, float] = {}
_PACE_READY = False
_PACE_LOCK = threading.Lock()


def min_available_bytes() -> int:
    """Threshold from ``HOCUSPOCUS_QUEUE_RAM_MIN_BYTES``, or 24 GiB."""
    raw = os.environ.get(_RAM_ENV, "").strip()
    if not raw:
        return _DEFAULT_MIN_BYTES
    try:
        value = int(raw, 10)
    except ValueError:
        return _DEFAULT_MIN_BYTES
    if value < 0:
        return _DEFAULT_MIN_BYTES
    return value


def available_ram_bytes() -> int | None:
    """MemAvailable in bytes, or None when neither probe can read it."""
    try:
        probed = _psutil_available()
        if probed is not None:
            return probed
        return _proc_memavailable()
    except Exception:
        return None


def is_large_video_model(model_type: str) -> bool:
    return architecture_of(model_type) in _LARGE_VIDEO_ARCHITECTURES


def large_video_model_ids() -> list[str]:
    """Defaults stems plus architecture ids that count as large video."""
    found = set(_LARGE_VIDEO_ARCHITECTURES)
    if not _DEFAULTS_DIR.is_dir():
        return sorted(found)
    for path in sorted(_DEFAULTS_DIR.glob("*.json")):
        if architecture_of(path.stem) in _LARGE_VIDEO_ARCHITECTURES:
            found.add(path.stem)
    return sorted(found)


def architecture_of(model_type: str) -> str:
    record = _model_record(model_type)
    arch = record.get("architecture")
    if isinstance(arch, str) and arch:
        return arch
    return _text(model_type)


def inactive_family(model_type: str) -> str | None:
    """Product family to drop before a large video load: image, tts, or music."""
    arch = architecture_of(model_type)
    if arch in _TTS_ARCHITECTURES:
        return "tts"
    if arch in _MUSIC_ARCHITECTURES:
        return "music"
    if arch in _IMAGE_ARCHITECTURES or _image_flag(model_type):
        return "image"
    return None


def prepare_queued_params(params: object) -> dict[str, Any]:
    """Queue-worker entry. Reads ``model_type`` without adding a caller branch."""
    model = ""
    if isinstance(params, dict):
        model = _text(params.get("model_type"))
    return prepare_queued_model(model)


def prepare_queued_model(
    model_type: str,
    *,
    available_bytes: int | float | None = None,
    probe: Callable[[], object] | None = None,
    unload: Callable[[str], None] | None = None,
    release_cache: Callable[[], None] | None = None,
    threshold: int | None = None,
) -> dict[str, Any]:
    """Unload inactive families when a large video model needs RAM.

    Tests inject ``available_bytes`` or ``probe``, ``unload``, and
    ``release_cache``. Production uses MemAvailable, ``wgp.release_model``
    for the loaded inactive family, and the torch cache.
    """
    if not is_large_video_model(_text(model_type)):
        return _decision(False, "not_large_video")
    available = _available_reading(available_bytes, probe)
    if available is None or available >= _threshold(threshold):
        return _decision(False, "ram_available")
    _release_inactive(unload, release_cache)
    return _decision(True, "low_ram")


def assess_pace(s_per_step: object, baseline: object) -> dict[str, Any]:
    """Degraded only when ``s_per_step`` is strictly above 1.6 times a baseline."""
    current = _finite_number(s_per_step)
    base = _positive(baseline)
    degraded = False
    reason = "no_baseline"
    if base is not None and current is not None:
        degraded = current > (_PACE_RATIO * base)
        reason = "slower_than_baseline" if degraded else "within_baseline"
    return {
        "s_per_step": current,
        "baseline_s_per_step": base,
        "degraded": degraded,
        "reason": reason,
    }


def record_pace(
    model_type: str,
    s_per_step: object,
    *,
    book: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compare against the first stored sample. Later samples do not replace it."""
    if book is not None:
        return _record_into(book, model_type, s_per_step, persist=False)
    with _PACE_LOCK:
        _ensure_pace_book()
        return _record_into(_PACE, model_type, s_per_step, persist=True)


def note_inference_step(
    job: object,
    *,
    step: object,
    now: object,
    message: str = "",
    book: dict[str, float] | None = None,
    model_type: object = None,
) -> dict[str, Any]:
    """Seconds per step after the denoising anchor is already on the job.

    Returns ``{}`` or ``{"performance": ...}`` so the caller can
    ``progress_updates.update`` the result with no branch of its own.
    The first denoising progress only anchors the clock, so this returns
    nothing until a later denoising step.
    """
    if "denoising" not in str(message).lower():
        return {}
    sample = _pace_sample(job, step, now, model_type)
    if sample is None:
        return {}
    performance = record_pace(sample["model_type"], sample["s_per_step"], book=book)
    if isinstance(job, dict):
        job["performance"] = performance
    return {"performance": performance}


def performance_fields(measurement: object) -> dict[str, Any]:
    normalized = _normalize_performance(measurement)
    if normalized is None:
        return {}
    return {"performance": normalized}


def include_performance(document: object, source: object = None) -> object:
    """Shallow-copy ``document`` and attach ``performance`` when one exists.

    ``source`` may be the performance object, a job/status dict, or a task
    whose ``metadata`` carries it. With no measurement the copy has the same
    keys as ``document``. The input mapping is not mutated.
    """
    if not isinstance(document, dict):
        return document
    view = dict(document)
    found = _performance_from(document if source is None else source)
    if found is not None:
        view["performance"] = found
    return view


def _decision(released: bool, reason: str) -> dict[str, Any]:
    families = list(_INACTIVE_FAMILIES) if released else []
    return {"released": released, "reason": reason, "families": families}


def _threshold(threshold: int | None) -> int:
    if threshold is None:
        return min_available_bytes()
    try:
        value = int(threshold)
    except (TypeError, ValueError):
        return min_available_bytes()
    if value < 0:
        return min_available_bytes()
    return value


def _available_reading(
    available_bytes: object,
    probe: Callable[[], object] | None,
) -> float | None:
    if available_bytes is not None:
        return _finite_number(available_bytes)
    reader = probe if probe is not None else available_ram_bytes
    try:
        return _finite_number(reader())
    except Exception:
        return None


def _release_inactive(
    unload: Callable[[str], None] | None,
    release_cache: Callable[[], None] | None,
) -> None:
    unloader = unload if unload is not None else _unload_family
    for family in _INACTIVE_FAMILIES:
        unloader(family)
    releaser = release_cache if release_cache is not None else _release_torch_cache
    releaser()


def _record_into(
    store: dict[str, float],
    model_type: str,
    s_per_step: object,
    *,
    persist: bool,
) -> dict[str, Any]:
    key = _text(model_type)
    previous = _positive(store.get(key))
    performance = assess_pace(s_per_step, previous)
    if previous is None and performance["s_per_step"] is not None:
        store[key] = performance["s_per_step"]
        if persist:
            _save_pace_file()
    return performance


def _pace_sample(
    job: object,
    step: object,
    now: object,
    model_type: object,
) -> dict[str, Any] | None:
    if not isinstance(job, dict):
        return None
    started = _finite_number(job.get("inference_started_at"))
    moment = _finite_number(now)
    origin = _whole_step(job.get("inference_start_step"))
    current = _whole_step(step)
    if started is None or moment is None or origin is None or current is None:
        return None
    if current <= origin or moment < started:
        return None
    elapsed = moment - started
    return {
        "model_type": _explicit_model(job, model_type),
        "s_per_step": elapsed / (current - origin),
    }


def _explicit_model(job: dict, model_type: object) -> str:
    if model_type is not None:
        return _text(model_type)
    params = job.get("params")
    if not isinstance(params, dict):
        return ""
    return _text(params.get("model_type"))


def _whole_step(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _performance_from(source: object) -> dict[str, Any] | None:
    if not isinstance(source, Mapping):
        return None
    if "performance" in source:
        nested = _normalize_performance(source.get("performance"))
        if nested is not None:
            return nested
    direct = _normalize_performance(source)
    if direct is not None:
        return direct
    metadata = source.get("metadata")
    if isinstance(metadata, Mapping) and "performance" in metadata:
        return _normalize_performance(metadata.get("performance"))
    return None


def _normalize_performance(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if "s_per_step" not in value or "degraded" not in value:
        return None
    current = _finite_number(value.get("s_per_step"))
    if current is None:
        return None
    baseline = value.get("baseline_s_per_step")
    base = None if baseline is None else _positive(baseline)
    degraded = value.get("degraded") is True
    return {
        "s_per_step": current,
        "baseline_s_per_step": base,
        "degraded": degraded,
        "reason": _pace_reason(value.get("reason"), degraded, base),
    }


def _pace_reason(reason: object, degraded: bool, base: float | None) -> str:
    if isinstance(reason, str) and reason:
        return reason
    if base is None:
        return "no_baseline"
    if degraded:
        return "slower_than_baseline"
    return "within_baseline"


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _positive(value: object) -> float | None:
    number = _finite_number(value)
    if number is None or number <= 0:
        return None
    return number


def _model_record(model_type: str) -> dict[str, Any]:
    key = _text(model_type)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    record = _load_model_record(key)
    _MODEL_CACHE[key] = record
    return record


def _image_flag(model_type: str) -> bool:
    return _model_record(model_type).get("image_outputs") is True


def _load_model_record(model_type: str) -> dict[str, Any]:
    stem = _safe_stem(model_type)
    if not stem:
        return {}
    path = _DEFAULTS_DIR / f"{stem}.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    model = data.get("model") if isinstance(data, dict) else None
    if not isinstance(model, dict):
        return {}
    return model


def _safe_stem(model_type: str) -> str:
    text = _text(model_type)
    if not text or "/" in text or "\\" in text or ".." in text:
        return ""
    if Path(text).name != text:
        return ""
    return text


def _ensure_pace_book() -> None:
    global _PACE_READY
    if _PACE_READY:
        return
    _PACE_READY = True
    _load_pace_file()


def _pace_path() -> Path | None:
    raw = os.environ.get(_PACE_ENV, "").strip()
    if not raw:
        return None
    return Path(raw)


def _load_pace_file() -> None:
    path = _pace_path()
    if path is None or not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        number = _positive(value)
        if number is not None:
            _PACE[str(key)] = number


def _save_pace_file() -> None:
    path = _pace_path()
    if path is None:
        return
    try:
        path.write_text(json.dumps(_PACE, sort_keys=True), encoding="utf-8")
    except OSError:
        return


def _psutil_available() -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    memory = psutil.virtual_memory()
    available = getattr(memory, "available", None)
    if not isinstance(available, (int, float)) or isinstance(available, bool):
        return None
    if not math.isfinite(float(available)):
        return None
    return int(available)


def _proc_memavailable() -> int | None:
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if not line.startswith("MemAvailable:"):
            continue
        parts = line.split()
        if len(parts) < 2:
            return None
        try:
            return int(parts[1]) * 1024
        except ValueError:
            return None
    return None


def _bound_wgp():
    try:
        from services.generation.runtime import get_wgp
    except ImportError:
        return None
    try:
        return get_wgp()
    except RuntimeError:
        return None


def _unload_family(family: str) -> None:
    loaded = _loaded_transformer()
    if inactive_family(loaded) != family:
        return
    runtime = _bound_wgp()
    if runtime is None:
        return
    release = getattr(runtime, "release_model", None)
    if callable(release):
        release()


def _loaded_transformer() -> str:
    runtime = _bound_wgp()
    if runtime is None:
        return ""
    return _text(getattr(runtime, "transformer_type", None))


def _release_torch_cache() -> None:
    import gc

    gc.collect()
    torch = _import_torch()
    if torch is None:
        return
    _empty_torch_cache(torch)


def _import_torch() -> object | None:
    try:
        import torch
    except ImportError:
        return None
    return torch


def _empty_torch_cache(torch: object) -> None:
    cuda = getattr(torch, "cuda", None)
    if _cache_ready(cuda):
        cuda.empty_cache()
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if _cache_ready(mps):
        mps.empty_cache()


def _cache_ready(device: object) -> bool:
    available = getattr(device, "is_available", None)
    empty = getattr(device, "empty_cache", None)
    if not callable(available) or not callable(empty):
        return False
    try:
        return bool(available())
    except Exception:
        return False

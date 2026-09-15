"""User-facing install and generation diagnostics.

Explains why an operation or model is available using observed facts:
component, driver/backend, RAM/VRAM, version, and an existing repair path.
Does not import CUDA, Torch, WanGP or other heavy engines.
"""
from __future__ import annotations

import hashlib
import json
import platform as host_platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Mapping

from app_identity import read_app_version
from services import runtime_profiles as profiles

SCHEMA = "hocuspocus.user-diagnostics-report"
SCHEMA_VERSION = 1

REPAIR = {
    "install_update": {
        "id": "install_update",
        "summary": "Run Install or Update to repair the selected runtime before Start.",
    },
    "repair_web_ui": {
        "id": "repair_web_ui",
        "summary": "Retry Repair Web UI, then restart Start. This does not reinstall engines.",
    },
    "nvidia_driver": {
        "id": "nvidia_driver",
        "summary": "Install or upgrade the NVIDIA driver to the recipe minimum, then re-run Install or Update.",
    },
    "cpu_amd_recipe": {
        "id": "cpu_amd_recipe",
        "summary": "Local AI installation currently requires NVIDIA; CPU/AMD/Intel/MPS recipes are not enabled.",
    },
    "platform_unsupported": {
        "id": "platform_unsupported",
        "summary": "No installation recipe for this OS/architecture; Windows and Linux x64 are supported.",
    },
    "download_model": {
        "id": "download_model",
        "summary": "Install required model files from the model catalog before submitting.",
    },
    "lower_vram": {
        "id": "lower_vram",
        "summary": "Lower VRAM headroom (vram_safety_coefficient) or choose a smaller catalog variant.",
    },
    "unpublished": {
        "id": "unpublished",
        "summary": "This operation is not published in the native command catalog.",
    },
}

OPERATIONS = (
    {"id": "generation.image", "kind": "operation", "component": "wangp",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 6, "ram_gb": 16},
    {"id": "generation.speech", "kind": "operation", "component": "wangp",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 4, "ram_gb": 16},
    {"id": "generation.music", "kind": "operation", "component": "wangp",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 6, "ram_gb": 16},
    {"id": "generation.sfx", "kind": "operation", "component": "wangp",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 6, "ram_gb": 16},
    {"id": "generation.video", "kind": "operation", "component": "wangp",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 8, "ram_gb": 16},
    {"id": "generation.receipt", "kind": "operation", "component": "wangp",
     "published": True, "needs_gpu": False, "requires_install": False, "vram_gb": None, "ram_gb": None},
    {"id": "tools.upscale", "kind": "operation", "component": "wangp",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 8, "ram_gb": 16},
    {"id": "generation.model3d", "kind": "operation", "component": "hunyuan3d",
     "published": False, "needs_gpu": True, "requires_install": True, "vram_gb": 8, "ram_gb": 16},
    {"id": "engine.minimax_h3", "kind": "operation", "component": "minimax_h3",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 24, "ram_gb": 32},
    {"id": "engine.sam", "kind": "operation", "component": "sam",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 6, "ram_gb": 16},
    {"id": "engine.rigging", "kind": "operation", "component": "rigging",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 8, "ram_gb": 16},
)

MODELS = (
    {"id": "flux2_klein_4b", "kind": "model", "component": "wangp",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 6, "ram_gb": 16},
    {"id": "ltx2_22B", "kind": "model", "component": "wangp",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 16, "ram_gb": 32},
    {"id": "minimax_h3", "kind": "model", "component": "minimax_h3",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 24, "ram_gb": 32},
    {"id": "hunyuan3d-2.1", "kind": "model", "component": "hunyuan3d",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 10, "ram_gb": 16},
    {"id": "ace_step_v1_5_xl", "kind": "model", "component": "wangp",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 6, "ram_gb": 16},
    {"id": "kugelaudio_0_open", "kind": "model", "component": "wangp",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 6, "ram_gb": 16},
    {"id": "trellis2", "kind": "model", "component": "hunyuan3d",
     "published": True, "needs_gpu": True, "requires_install": True, "vram_gb": 24, "ram_gb": 32},
)

_OMIT_KEYS = frozenset({
    "prompt", "negative_prompt", "lyrics", "prompt_full", "prompt_original",
    "prompt_effective", "prompt_display", "enhanced_prompt", "video_prompt",
    "cookie", "cookies", "set_cookie",
})
_SENSITIVE_PARTS = (
    "api_key", "apikey", "access_token", "refresh_token", "authorization",
    "password", "passwd", "client_secret", "private_key", "cookie", "session",
    "secret", "credential",
)
_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_QUERY_RE = re.compile(r"(?i)([?&](?:token|api[_-]?key|access[_-]?token|session)=)[^&#\s]+")
_COOKIE_RE = re.compile(r"(?i)((?:cookie|set-cookie)\s*[:=]\s*)[^\r\n]+")
_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|password|secret|session|token)\s*[:=]\s*[^\s,;]+"
)
_SK_RE = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]+")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sensitive_action(key: str) -> str:
    token = str(key or "").strip().casefold().replace("-", "_")
    if token in _OMIT_KEYS:
        return "omit"
    if token == "token" or token.endswith("_token"):
        return "redact"
    for part in _SENSITIVE_PARTS:
        if part in token:
            return "redact"
    return "keep"


def _redact_string(value: str) -> str:
    text = _BEARER_RE.sub(r"\1 [REDACTED]", value)
    text = _QUERY_RE.sub(r"\1[REDACTED]", text)
    text = _COOKIE_RE.sub(r"\1[REDACTED]", text)
    text = _ASSIGN_RE.sub(r"\1=[REDACTED]", text)
    return _SK_RE.sub("[REDACTED]", text)[:2000]


def _redact_mapping(value: Mapping[str, Any], depth: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in list(value.items())[:80]:
        name = str(key)[:160]
        action = _sensitive_action(name)
        if action == "omit":
            continue
        if action == "redact":
            result[name] = "[REDACTED]"
            continue
        result[name] = redact_for_pack(item, depth + 1)
    return result


def redact_for_pack(value: Any, depth: int = 0) -> Any:
    """Drop prompts/cookies and mask credentials before a support pack is written."""
    if depth > 8:
        return None
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, list):
        return [redact_for_pack(item, depth + 1) for item in value[:80]]
    if isinstance(value, dict):
        return _redact_mapping(value, depth)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


def _gpu_csv() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or "").strip()
    return text or None


def _mib_to_gb(raw: str) -> float | None:
    try:
        mib = float(raw)
    except (TypeError, ValueError):
        return None
    if mib < 0:
        return None
    return round(mib / 1024.0, 1)


def parse_gpu(csv_text: str | None) -> dict[str, Any]:
    empty = {"name": None, "driver": None, "vram_gb": None, "backend": "none", "kind": "unknown"}
    if not csv_text or not str(csv_text).strip():
        return dict(empty)
    line = str(csv_text).strip().splitlines()[0]
    parts = [part.strip() for part in line.split(",")]
    name = parts[0] if parts else ""
    driver = parts[1] if len(parts) > 1 else ""
    memory = parts[2] if len(parts) > 2 else ""
    driver_ok = bool(re.fullmatch(r"\d+(?:\.\d+)+", driver))
    kind = "nvidia" if driver_ok or name else "unknown"
    return {
        "name": name or None,
        "driver": driver if driver_ok else None,
        "vram_gb": _mib_to_gb(memory),
        "backend": "nvidia" if kind == "nvidia" else "none",
        "kind": kind,
    }


def _ram_gb() -> float | None:
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        return None


def _cpu_count() -> int | None:
    try:
        import psutil
        return int(psutil.cpu_count(logical=True) or 0) or None
    except Exception:
        return None


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(profiles.APP_DIR.parent), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = (result.stdout or "").strip()
    return value or None


def _ui_build_id() -> str:
    index = profiles.APP_DIR.parent / "ui" / "dist" / "index.html"
    try:
        return hashlib.sha256(index.read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"


def _pick(observe: Mapping[str, Any], key: str, fallback):
    if key in observe:
        return observe[key]
    return fallback() if callable(fallback) else fallback


def receipt_status(engine: str, platform: str) -> dict[str, Any]:
    """Read the managed receipt only. Never spawn engine Python or import Torch."""
    spec = profiles.recipe(engine, platform)
    # Core and WanGP share app/env, but have different platform recipes.
    # A receipt in that folder is not evidence for an unsupported engine.
    if platform not in spec["platforms"]:
        return {"present": False, "installed": False, "fingerprint_match": False}
    path = profiles.APP_DIR.parent / spec["env"] / ".hocus-runtime-profile.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"present": False, "installed": False, "fingerprint_match": False}
    if not isinstance(payload, dict):
        return {"present": True, "installed": False, "fingerprint_match": False}
    try:
        expected = profiles.dependency_fingerprint(engine, platform)
    except OSError:
        # An incomplete installation is a diagnostic result, not a server error.
        return {"present": True, "installed": False, "fingerprint_match": False}
    fingerprint_match = payload.get("fingerprint") == expected
    installed = (
        fingerprint_match
        and payload.get("profile") == spec["id"]
        and payload.get("cudaCalculation") is bool(spec.get("cuda"))
    )
    return {
        "present": True,
        "installed": bool(installed),
        "fingerprint_match": bool(fingerprint_match),
        "profile": payload.get("profile"),
        "cuda_calculation": payload.get("cudaCalculation"),
    }


def repair_for_reason(reason: str | None) -> dict[str, str]:
    text = (reason or "").lower()
    if "driver" in text and "nvidia" in text:
        return REPAIR["nvidia_driver"]
    if "cpu/amd" in text or "intel/mps" in text or "requires nvidia" in text:
        return REPAIR["cpu_amd_recipe"]
    if "architecture" in text or "no installation recipe" in text:
        return REPAIR["platform_unsupported"]
    return REPAIR["install_update"]


def memory_blockers(
    spec: Mapping[str, Any], observed: Mapping[str, Any],
) -> list[tuple[str, dict[str, str]]]:
    blockers: list[tuple[str, dict[str, str]]] = []
    vram_need = spec.get("vram_gb")
    vram = observed.get("vram_gb")
    if isinstance(vram_need, (int, float)) and isinstance(vram, (int, float)) and vram < vram_need:
        repair = REPAIR["lower_vram"] if vram >= 8 else REPAIR["download_model"]
        blockers.append((
            f"Observed VRAM {vram} GB is below the {vram_need} GB catalog minimum.",
            repair,
        ))
    ram_need = spec.get("ram_gb")
    ram = observed.get("ram_gb")
    if isinstance(ram_need, (int, float)) and isinstance(ram, (int, float)) and ram < ram_need:
        blockers.append((
            f"Observed RAM {ram} GB is below the {ram_need} GB catalog minimum.",
            REPAIR["install_update"],
        ))
    return blockers


def engine_blockers(
    spec: Mapping[str, Any], engine: Mapping[str, Any], observed: Mapping[str, Any],
) -> list[tuple[str, dict[str, str]]]:
    blockers: list[tuple[str, dict[str, str]]] = []
    if not spec.get("published", True):
        blockers.append((
            "This operation is not published in the native command catalog.",
            REPAIR["unpublished"],
        ))
    needs_gpu = spec.get("needs_gpu", True)
    if needs_gpu and not engine.get("supported"):
        reason = str(engine.get("reason") or "No compatible engine recipe.")
        blockers.append((reason, repair_for_reason(reason)))
    if spec.get("requires_install", True) and engine.get("supported") and not engine.get("installed"):
        label = engine.get("label") or spec["component"]
        blockers.append((
            f"{label} is not installed with a matching runtime receipt.",
            REPAIR["install_update"],
        ))
    if needs_gpu and observed.get("backend") != "nvidia":
        blockers.append((
            "No NVIDIA driver/backend was observed; local generation recipes require NVIDIA.",
            REPAIR["cpu_amd_recipe"],
        ))
    blockers.extend(memory_blockers(spec, observed))
    return blockers


def explain_target(
    spec: Mapping[str, Any],
    engines: Mapping[str, Mapping[str, Any]],
    observed: Mapping[str, Any],
    app_version: str,
) -> dict[str, Any]:
    engine = engines.get(str(spec["component"])) or {}
    blockers = engine_blockers(spec, engine, observed)
    reasons = [text for text, _repair in blockers]
    if not blockers:
        reasons.append("Recipe, driver, and observed memory meet the published facts.")
    reasons.append("Weight files are not probed by this report.")
    return {
        "kind": spec["kind"],
        "id": spec["id"],
        "available": not blockers,
        "component": spec["component"],
        "driver": observed.get("driver"),
        "backend": observed.get("backend"),
        "ram_gb_observed": observed.get("ram_gb"),
        "vram_gb_observed": observed.get("vram_gb"),
        "version": {
            "app": app_version,
            "recipe": engine.get("recipe_id"),
            "python": engine.get("python"),
            "torch": engine.get("torch"),
            "cuda": engine.get("cuda"),
        },
        "repair_path": blockers[0][1] if blockers else None,
        "reasons": reasons,
        "weights": "not_probed",
    }


def describe_engine(name: str, selected: Mapping[str, Any], receipt: Mapping[str, Any]) -> dict[str, Any]:
    supported = bool(selected.get("supported"))
    repair = None
    if not supported:
        repair = repair_for_reason(selected.get("reason") if isinstance(selected.get("reason"), str) else None)
    elif not receipt.get("installed"):
        repair = REPAIR["install_update"]
    return {
        "id": name,
        "label": selected.get("label"),
        "required": bool(selected.get("required")),
        "supported": supported,
        "installed": bool(receipt.get("installed")) and supported,
        "reason": selected.get("reason"),
        "warning": selected.get("warning"),
        "recipe_id": selected.get("id"),
        "python": selected.get("python"),
        "torch": selected.get("torch"),
        "cuda": selected.get("cuda"),
        "driver_minimum": selected.get("driverMinimum"),
        "repair_path": repair,
        "receipt": {
            "present": bool(receipt.get("present")),
            "fingerprint_match": bool(receipt.get("fingerprint_match")),
        },
    }


def _observe_host(observe: Mapping[str, Any]) -> dict[str, Any]:
    gpu = parse_gpu(_pick(observe, "gpu_csv", _gpu_csv))
    platform = str(observe.get("platform") or sys.platform)
    architecture = profiles.normalize_arch(str(observe.get("architecture") or host_platform.machine()))
    return {
        "platform": platform,
        "architecture": architecture,
        "python": host_platform.python_version(),
        "gpu_name": gpu["name"],
        "driver": gpu["driver"],
        "backend": gpu["backend"],
        "gpu_kind": gpu["kind"],
        "ram_gb": _pick(observe, "ram_gb", _ram_gb),
        "vram_gb": gpu["vram_gb"],
        "cpu_count": _pick(observe, "cpu_count", _cpu_count),
        "app_version": _pick(observe, "app_version", read_app_version),
        "git_revision": _pick(observe, "git_revision", _git_revision),
        "ui_build_id": _pick(observe, "ui_build_id", _ui_build_id),
        "receipts": observe.get("receipts"),
    }


def _receipt_for(name: str, platform: str, overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    if overrides is not None and name in overrides:
        item = overrides[name]
        return dict(item) if isinstance(item, Mapping) else {"present": False, "installed": False}
    return receipt_status(name, platform)


def _engine_table(host: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    selected = profiles.select_profiles(
        host["platform"], host["architecture"], host["gpu_kind"], host["driver"],
    )
    overrides = host.get("receipts") if isinstance(host.get("receipts"), dict) else None
    engines: dict[str, dict[str, Any]] = {}
    for name, item in selected["engines"].items():
        engines[name] = describe_engine(name, item, _receipt_for(name, selected["platform"], overrides))
    return engines


def snapshot(*, observe: Mapping[str, Any] | None = None) -> dict[str, Any]:
    host = _observe_host(observe or {})
    engines = _engine_table(host)
    availability = [
        explain_target(spec, engines, host, str(host["app_version"] or ""))
        for spec in (*OPERATIONS, *MODELS)
    ]
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "build": {
            "app_version": host["app_version"],
            "git_revision": host["git_revision"],
            "ui_build_id": host["ui_build_id"],
        },
        "platform": {
            "os": host["platform"],
            "architecture": host["architecture"],
            "python": host["python"],
            "gpu": host["gpu_kind"],
            "gpu_name": host["gpu_name"],
            "driver": host["driver"],
            "backend": host["backend"],
        },
        "observed": {
            "ram_gb": host["ram_gb"],
            "vram_gb": host["vram_gb"],
            "cpu_count": host["cpu_count"],
        },
        "capabilities": {"engines": list(engines.values())},
        "availability": availability,
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bounded_message(value: Any) -> str | None:
    if value is None:
        return None
    text = _redact_string(" ".join(str(value).split()))
    return text[:300] or None


def _oom_fields(value: Any) -> dict[str, Any] | None:
    info = _mapping(value)
    if not info:
        return None
    keys = ("is_oom", "current_coefficient", "suggested_coefficient")
    picked = {key: info[key] for key in keys if key in info}
    return picked or None


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _error_payload(task_map: Mapping[str, Any], receipt_map: Mapping[str, Any], error_map: Mapping[str, Any]) -> dict[str, Any]:
    result = _mapping(receipt_map.get("result"))
    oom = _oom_fields(_mapping(task_map.get("metadata")).get("oom_info"))
    return {
        "task_id": _first(task_map.get("id"), result.get("task_id")),
        "intent_id": _first(receipt_map.get("commandId"), receipt_map.get("command_id")),
        "operation": _first(receipt_map.get("operation"), task_map.get("workflow")),
        "status": _first(task_map.get("status"), receipt_map.get("status"), result.get("status")),
        "job_id": _first(task_map.get("backend_job_id"), result.get("job_id")),
        "workspace": _first(task_map.get("workspace"), result.get("workspace")),
        "code": _first(error_map.get("code"), "oom" if oom else None),
        "message": _bounded_message(_first(error_map.get("message"), task_map.get("message"))),
        "oom": oom,
    }


def correlate_error(*, task: Any = None, receipt: Any = None, error: Any = None) -> dict[str, Any] | None:
    if task is None and receipt is None and error is None:
        return None
    payload = _error_payload(_mapping(task), _mapping(receipt), _mapping(error))
    cleaned = {key: value for key, value in payload.items() if value not in (None, "", {})}
    return redact_for_pack(cleaned)


def collect_report(
    *,
    observe: Mapping[str, Any] | None = None,
    task: Any = None,
    receipt: Any = None,
    error: Any = None,
) -> dict[str, Any]:
    pack = snapshot(observe=observe)
    pack["generated_at"] = _now()
    pack["error"] = correlate_error(task=task, receipt=receipt, error=error)
    return redact_for_pack(pack)

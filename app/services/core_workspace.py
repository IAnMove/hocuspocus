"""Filesystem workspaces and core JSON config without WanGP or Torch."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from app_identity import read_app_version

_LOCK = threading.Lock()
_WORKSPACE_NAME = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)")
MEDIA_EXTS = {".mp4", ".webm", ".gif", ".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3",
              ".glb", ".gltf", ".obj", ".ply", ".stl", ".usdz", ".zip", ".json"}
VIDEO_EXTS = {".mp4", ".webm", ".gif"}
AUDIO_EXTS = {".wav", ".mp3"}
MODEL3D_EXTS = {".glb", ".gltf", ".obj", ".ply", ".stl", ".usdz", ".zip"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def classify_output_type(name: str) -> str | None:
    """Match the NVIDIA gallery kinds the UI filters on (`image`, `model3d`, …)."""
    filename = os.path.basename(str(name or ""))
    if filename.endswith(".preview.png"):
        return None
    if filename.endswith(".scene.json"):
        return "scene"
    if filename.endswith(".comic.json"):
        return "comic"
    ext = os.path.splitext(filename)[1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in MODEL3D_EXTS:
        return "model3d"
    if ext in IMAGE_EXTS:
        return "image"
    return None


def root() -> Path:
    return Path(os.getcwd())


def outputs_root() -> Path:
    path = root() / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def uploads_dir() -> str:
    path = root() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def settings_path() -> Path:
    path = root() / "app" / "settings"
    path.mkdir(parents=True, exist_ok=True)
    return path / "core_config.json"


def load_config() -> dict[str, Any]:
    path = settings_path()
    if not path.is_file():
        return {"services": {"active_workspace": "default"}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"services": {"active_workspace": "default"}}
    if not isinstance(data, dict):
        return {"services": {"active_workspace": "default"}}
    data.setdefault("services", {})
    return data


def save_config(data: dict[str, Any]) -> None:
    path = settings_path()
    temporary = path.with_suffix(".tmp")
    with _LOCK:
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(path)


def active_workspace() -> str:
    name = str(load_config().get("services", {}).get("active_workspace") or "default")
    return name if _WORKSPACE_NAME.fullmatch(name) else "default"


def workspace_dir(workspace: str | None = None) -> str:
    name = active_workspace() if workspace is None else workspace
    if not isinstance(name, str) or not _WORKSPACE_NAME.fullmatch(name):
        raise ValueError("Invalid workspace name")
    base = outputs_root().resolve()
    target = base if name == "default" else (base / name).resolve()
    if os.path.commonpath((str(base), str(target))) != str(base):
        raise ValueError("Invalid workspace path")
    if name != "default":
        target.mkdir(parents=True, exist_ok=True)
    return str(target)


def safe_join(base: str, *parts: str) -> str | None:
    try:
        candidate = Path(base).joinpath(*parts).resolve()
        root = Path(base).resolve()
        if os.path.commonpath((str(root), str(candidate))) != str(root):
            return None
        return str(candidate)
    except (OSError, ValueError):
        return None


def _file_count(path: str) -> int:
    try:
        with os.scandir(path) as entries:
            return sum(1 for item in entries if not item.name.startswith(".") and item.is_file())
    except OSError:
        return 0


def list_workspaces() -> list[dict[str, Any]]:
    base = outputs_root()
    rows = [{"name": "default", "path": str(base), "file_count": _file_count(str(base))}]
    try:
        names = sorted(os.listdir(base))
    except OSError:
        names = []
    for name in names:
        full = base / name
        if full.is_dir() and not name.startswith(("_", ".")):
            rows.append({"name": name, "path": str(full), "file_count": _file_count(str(full))})
    return rows


def list_outputs(
    workspace: str = "",
    media_type: str = "",
    limit: int = 0,
    offset: int = 0,
) -> dict[str, Any]:
    folder = Path(uploads_dir()) if workspace == "__uploads__" else Path(workspace_dir(workspace or None))
    if not folder.is_dir():
        return {"outputs": [], "total": 0}
    wanted = str(media_type or "").strip()
    items = []
    for entry in folder.iterdir():
        if not entry.is_file() or entry.name.startswith("."):
            continue
        kind = classify_output_type(entry.name)
        if kind is None or (wanted and kind != wanted):
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        suffix = f"?workspace={workspace}" if workspace else ""
        items.append({
            "name": entry.name,
            "type": kind,
            "mode": None,
            "size": stat.st_size,
            "created_at": stat.st_mtime,
            "completed_at": stat.st_mtime,
            "completion_time_source": "file",
            "url": f"/api/v1/file/{entry.name}{suffix}",
        })
    items.sort(key=lambda row: row["created_at"], reverse=True)
    total = len(items)
    start = max(0, int(offset or 0))
    if limit and int(limit) > 0:
        items = items[start:start + int(limit)]
    return {"outputs": items, "total": total}


def system_config() -> dict[str, Any]:
    cfg = load_config()
    return {
        "app_version": read_app_version(),
        "attention_mode": "auto",
        "transformer_quantization": "int8",
        "vae_config": 0,
        "compile": "",
        "video_profile": 4,
        "image_profile": 4,
        "audio_profile": 4,
        "video_output_codec": cfg.get("video_output_codec", "libx264_8"),
        "image_output_codec": cfg.get("image_output_codec", "jpeg_95"),
        "enhancer_enabled": 0,
        "prompt_enhancer_quantization": "quanto_int8",
        "attention_modes_available": ["auto"],
        "vram_safety_coefficient": 0.8,
        "model_folders": [],
        "execution_mode": "real",
        "execution_workspace": active_workspace(),
        "execution_allow_paid": True,
    }


def services_raw() -> dict[str, Any]:
    return dict(load_config().get("services", {}))


def services_config() -> dict[str, Any]:
    services = load_config().get("services", {})
    return {
        "llm_model_id": services.get("llm_model_id", ""),
        "llm_device": "cpu",
        "llm_provider": services.get("llm_provider", "minimax"),
        "llm_remote_url": services.get("llm_remote_url", ""),
        "enhance_llm_model_id": "",
        "enhance_llm_device": "cpu",
        "google_api_key_set": bool(services.get("google_api_key")),
        "openai_api_key_set": bool(services.get("openai_api_key")),
        "deepseek_api_key_set": bool(services.get("deepseek_api_key")),
        "compatible_api_key_set": bool(services.get("compatible_api_key")),
        "compatible_base_url": services.get("compatible_base_url", ""),
        "anthropic_api_key_set": bool(services.get("anthropic_api_key")),
        "minimax_api_key_set": bool(services.get("minimax_api_key")),
        "minimax_llm_api_key_set": bool(services.get("minimax_llm_api_key")),
        "minimax_image_api_key_set": bool(services.get("minimax_image_api_key")),
        "minimax_music_api_key_set": bool(services.get("minimax_music_api_key")),
        "grok_api_key_set": bool(services.get("grok_api_key")),
        "meshy_api_key_set": bool(services.get("meshy_api_key")),
        "hi3d_api_key_set": bool(services.get("hi3d_api_key")),
        "use_director_v2": False,
        "nsfw_mode": False,
        "nsfw_accepted_at": None,
        "director_prompt_polish": "off",
        "workflow_parallelism_enabled": False,
        "debug_trace_enabled": False,
        "civitai_api_key_set": False,
        "voice_reference_enabled": False,
        "ltx_progressive_pipeline": False,
        "show_experimental": False,
        "auto_performance": False,
    }


def merge_services(partial: dict[str, Any]) -> dict[str, Any]:
    data = load_config()
    services = data.setdefault("services", {})
    for key, value in partial.items():
        if key.endswith("_set"):
            continue
        services[key] = value
    save_config(data)
    return services_config()

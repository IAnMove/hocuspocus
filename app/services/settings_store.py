"""Settings helpers moved out of the full server.

The preset file stays ``app/presets.json``, the file the launch module opened
beside itself. Route handlers live in ``app/routers/settings.py`` and call
these functions. ``wgp`` is the launch module's WanGP binding, set by the
settings router before any request.
"""
from __future__ import annotations

import json
import os

import torch
from fastapi import HTTPException

# app/presets.json — one directory above this service, same file as before.
_PRESETS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "presets.json",
)

_PUBLIC_LLM_PROVIDERS = {"openai", "anthropic", "minimax", "grok", "deepseek"}

# Default LLM repo — kept in sync with DEFAULT_HF_REPO in
# services/llm_service.py. Updated to Gemma 4 4B 2026-05-03.
_DEFAULT_LLM_REPO = "Abhiray/gemma-4-E4B-it-heretic-GGUF"

def _load_presets() -> list[dict]:
    if os.path.isfile(_PRESETS_FILE):
        try:
            with open(_PRESETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []
def _save_presets(presets: list[dict]):
    with open(_PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2)
def _get_linked_model_folders():
    from shared.utils.files_locator import is_external_root
    paths = wgp.server_config.get("checkpoints_paths") or []
    # Index 0 is the primary download root — even when it is an absolute
    # user-chosen path (upstream supports e.g. D:/models first), it is NOT
    # a linked folder and must never be demoted to read-only.
    return [p for p in paths[1:] if isinstance(p, str) and is_external_root(p)]
def _apply_linked_model_folders(folders):
    """Validate and apply a list of linked model folders.

    Rebuilds checkpoints_paths as [primary] + [linked] + ["."], preserving
    whatever primary download root the config already had (default
    "ckpts"). Applies live via the files locator — no restart needed for
    lookups. Raises (400) BEFORE any state is mutated.
    """
    from shared.utils.files_locator import is_external_root
    if not isinstance(folders, list):
        raise HTTPException(status_code=400, detail="model_folders must be a list of folder paths")
    existing = wgp.server_config.get("checkpoints_paths") or []
    primary = existing[0] if existing and isinstance(existing[0], str) and existing[0].strip() else "ckpts"
    primary_n = os.path.normcase(os.path.normpath(os.path.abspath(primary)))
    normalized = []
    seen = set()
    for p in folders:
        if not isinstance(p, str) or not p.strip():
            raise HTTPException(status_code=400, detail=f"Invalid folder entry: {p!r}")
        # Tolerate Windows Explorer "Copy as path" quoting.
        cleaned = p.strip().strip('"').strip("'").strip()
        ap = os.path.normpath(os.path.abspath(cleaned))
        if not os.path.isdir(ap):
            raise HTTPException(status_code=400, detail=f"Folder does not exist: {ap}")
        if not is_external_root(ap):
            raise HTTPException(status_code=400, detail=f"Folder is inside the HocusPocus Lab install (already searched): {ap}")
        ap_n = os.path.normcase(ap)
        if ap_n == primary_n:
            raise HTTPException(status_code=400, detail=f"Folder is the primary download root: {ap}")
        if ap_n not in seen:
            seen.add(ap_n)
            normalized.append(ap)
    new_paths = [primary] + normalized + ["."]
    wgp.server_config["checkpoints_paths"] = new_paths
    wgp.fl.set_checkpoints_paths(new_paths)
    return normalized
def _validated_memory_profile_updates(body):
    """Reject invalid profiles before any configuration changes are applied."""
    profiles = {}
    for key in ("video_profile", "image_profile", "audio_profile"):
        if key not in body:
            continue
        value = body[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in (1, 2, 3, 3.5, 4, 4.5, 5):
            raise HTTPException(status_code=400, detail=f"Invalid memory profile for {key}")
        profiles[key] = value
    return profiles
def _nsfw_allowed() -> bool:
    return bool(wgp.server_config.get("services", {}).get("nsfw_mode", False))
def _mask_key(key: str) -> str:
    """Mask an API key for safe display: show first 4 and last 4 chars."""
    if not key or len(key) < 10:
        return "***" if key else ""
    return key[:4] + "..." + key[-4:]
def _llm_default_device() -> str:
    """Default LLM device — CUDA when the system has it, else CPU.

    This is the value returned for `services.llm_device` when the user
    has never explicitly set it in Settings → Services. Previously
    hardcoded to "cpu" which left CUDA-equipped users stuck on CPU
    inference until they noticed the dropdown and flipped it. New
    installs on a CUDA box now get GPU LLM out of the box.

    User who already explicitly set "cpu" keeps "cpu" — the value is
    persisted in wgp_config.json and overrides this default. Same for
    explicit "cuda".
    """
    try:
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"

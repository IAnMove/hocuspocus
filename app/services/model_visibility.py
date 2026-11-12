"""Model visibility, selections and the production profile.

The handlers are the full server's functions, moved verbatim. ``configure``
binds the caller's engine and the download check the unsaved profile probes.
The visibility write lock is the one instance the full server aliases.
"""
from __future__ import annotations

import json
import os
import threading

from fastapi import HTTPException, Request

wgp = None
_check_model_downloaded = None


def configure(*, engine, check_model_downloaded) -> None:
    """Bind the caller's engine and the download check the default profile probes."""
    global wgp, _check_model_downloaded
    wgp = engine
    _check_model_downloaded = check_model_downloaded


_MODEL_VISIBILITY_CONFIG_KEY = "maestro_model_visibility"
_MODEL_VISIBILITY_WRITE_LOCK = threading.RLock()


def _normalize_model_visibility_ids(values):
    """Return a stable, de-duplicated list of persisted model identifiers."""
    if not isinstance(values, list):
        raise ValueError("Model visibility must be a list.")
    normalized = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Model visibility entries must be strings.")
        model_type = value.strip()
        if not model_type or model_type in seen:
            continue
        if len(model_type) > 200:
            raise ValueError("A model identifier is too long.")
        seen.add(model_type)
        normalized.append(model_type)
    if len(normalized) > 5000:
        raise ValueError("Too many model visibility entries.")
    return normalized


def _model_visibility_response():
    raw = wgp.server_config.get(_MODEL_VISIBILITY_CONFIG_KEY)
    configured = isinstance(raw, dict) and isinstance(
        raw.get("enabled_models"), list,
    )
    if not configured:
        return {
            "configured": False,
            "enabled_models": [],
            "initialized_mature_models": [],
            "defaults_version": 0,
        }
    try:
        enabled_models = _normalize_model_visibility_ids(
            raw.get("enabled_models", []),
        )
        initialized_mature_models = _normalize_model_visibility_ids(
            raw.get("initialized_mature_models", []),
        )
    except ValueError:
        return {
            "configured": False,
            "enabled_models": [],
            "initialized_mature_models": [],
            "defaults_version": 0,
        }
    try:
        defaults_version = max(0, int(raw.get("defaults_version", 0)))
    except (TypeError, ValueError):
        defaults_version = 0
    return {
        "configured": True,
        "enabled_models": enabled_models,
        "initialized_mature_models": initialized_mature_models,
        "defaults_version": defaults_version,
    }


def _persist_model_visibility_config():
    """Atomically persist visibility across Pinokio's changing UI ports."""
    config_path = os.path.abspath(wgp.server_config_filename)
    temp_path = (
        f"{config_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    with _MODEL_VISIBILITY_WRITE_LOCK:
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(wgp.server_config, handle, indent=4)
            os.replace(temp_path, config_path)
        finally:
            if os.path.isfile(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


def get_model_visibility():
    """Return the server-persisted model selector whitelist."""
    return _model_visibility_response()


async def update_model_visibility(request: Request):
    """Persist model visibility independently of the browser's origin."""
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail="Model visibility payload must be an object.",
        )
    try:
        enabled_models = _normalize_model_visibility_ids(
            body.get("enabled_models"),
        )
        initialized_mature_models = _normalize_model_visibility_ids(
            body.get("initialized_mature_models", []),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        defaults_version = max(0, int(body.get("defaults_version", 0)))
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=400,
            detail="defaults_version must be an integer.",
        ) from error

    with _MODEL_VISIBILITY_WRITE_LOCK:
        wgp.server_config[_MODEL_VISIBILITY_CONFIG_KEY] = {
            "enabled_models": enabled_models,
            "initialized_mature_models": initialized_mature_models,
            "defaults_version": defaults_version,
        }
        _persist_model_visibility_config()
        return _model_visibility_response()


_MODEL_SELECTION_CONFIG_KEY = "maestro_model_selections"
_MODEL_SELECTION_MODES = frozenset({
    "image", "video", "audio", "model3d", "avatar",
})

_PRODUCTION_PROFILE_CONFIG_KEY = "maestro_production_profile"
from services.production_profile import (
    _PRODUCTION_PROFILE_VERSION,
    _normalize_production_profile,
)
_DEFAULT_PRODUCTION_PROFILE = {
    "version": _PRODUCTION_PROFILE_VERSION,
    "text": {"provider": "minimax", "model": "MiniMax-M3", "base_url": "https://api.minimax.io"},
    "image": {"provider": "minimax", "model": "image-01"},
    "music": {"provider": "local", "model": "ace_step_v1_5_xl_sft_lm_4b"},
    "video": {
        "provider": "local",
        "model": "minimax_h3_legacy",
        "settings": {
            "profile": "quality",
            "steps": 20,
            "flowShift": 12.0,
            "audioShift": 3.0,
            "turbo": False,
            "cache": False,
            "loras": [],
            "resolution": "540p",
            "aspectRatio": "16:9",
        },
    },
    "model3d": {"provider": "local", "model": "hunyuan3d-2mini-turbo"},
}


def _default_production_profile() -> dict:
    """The unsaved profile: local Qwen Image 2.1 when installed, else the static default."""
    from services import production_profile_defaults

    return production_profile_defaults.default_profile(_DEFAULT_PRODUCTION_PROFILE, _check_model_downloaded)


_warned_invalid_profiles: set[str] = set()


def _active_production_profile() -> dict:
    raw = wgp.server_config.get(_PRODUCTION_PROFILE_CONFIG_KEY)
    try:
        return _normalize_production_profile(raw)
    except ValueError as error:
        # The defaults stand in, but never silently: say so once per reason,
        # and /production-profile reports it so the UI can show it.
        if raw is not None and str(error) not in _warned_invalid_profiles:
            _warned_invalid_profiles.add(str(error))
            print(f"[Production profile] The saved profile is invalid ({error}); using the defaults until it is saved again.")
        return _default_production_profile()


def _production_profile_response() -> dict:
    raw = wgp.server_config.get(_PRODUCTION_PROFILE_CONFIG_KEY)
    invalid_reason = ""
    try:
        profile = _normalize_production_profile(raw)
        configured = True
    except ValueError as error:
        profile = _default_production_profile()
        configured = False
        invalid_reason = str(error) if raw is not None else ""
    return {"configured": configured, "profile": profile, "invalid_reason": invalid_reason}


def _profile_image_model_type(profile: dict | None = None) -> str:
    image = (profile or _active_production_profile()).get("image", {})
    provider = str(image.get("provider") or "").lower()
    model = str(image.get("model") or "").strip()
    if provider == "minimax" and not model.startswith("minimax:"):
        return f"minimax:{model or 'image-01'}"
    return model


def get_production_profile():
    """Return credential-free defaults shared by Studio and every Lab."""
    return _production_profile_response()


async def update_production_profile(request: Request):
    body = await request.json()
    try:
        profile = _normalize_production_profile(
            body.get("profile") if isinstance(body, dict) else None,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    with _MODEL_VISIBILITY_WRITE_LOCK:
        wgp.server_config[_PRODUCTION_PROFILE_CONFIG_KEY] = profile
        # Generic tools (Director, prompt enhancement, planning) consume the
        # text section of this same profile. Mirror only provider/model/base
        # URL into the legacy services keys; credentials stay independent.
        services = wgp.server_config.setdefault("services", {})
        services["llm_provider"] = profile["text"]["provider"]
        services["llm_model_id"] = profile["text"]["model"]
        if profile["text"].get("base_url"):
            services["llm_remote_url"] = profile["text"]["base_url"]
        elif profile["text"]["provider"] == "minimax":
            services["llm_remote_url"] = "https://api.minimax.io"
        elif profile["text"]["provider"] == "grok":
            services["llm_remote_url"] = "https://api.x.ai"
        elif profile["text"]["provider"] == "ollama" and not services.get("llm_remote_url"):
            services["llm_remote_url"] = "http://127.0.0.1:11434"
        # Saving the global profile is an explicit request to make Studio and
        # Director inherit it. Later manual model choices are persisted again
        # as ordinary per-mode overrides.
        selections = wgp.server_config.get(_MODEL_SELECTION_CONFIG_KEY)
        if isinstance(selections, dict):
            selections.pop("image", None)
            selections.pop("video", None)
        _persist_model_visibility_config()
    return {"configured": True, "profile": profile}


def _normalize_model_selections(values):
    """Validate the small per-mode model preference map persisted by the UI."""
    if not isinstance(values, dict):
        raise ValueError("Model selections must be an object.")
    if len(values) > len(_MODEL_SELECTION_MODES):
        raise ValueError("Too many model selection entries.")
    normalized = {}
    for raw_mode, raw_model in values.items():
        mode = str(raw_mode or "").strip()
        if mode not in _MODEL_SELECTION_MODES:
            raise ValueError(f"Unknown generation mode: {mode or '(empty)'}.")
        if not isinstance(raw_model, str):
            raise ValueError("Every model selection must be a string.")
        model_type = raw_model.strip()
        if not model_type:
            continue
        if len(model_type) > 200:
            raise ValueError("A model identifier is too long.")
        normalized[mode] = model_type
    return normalized


def _model_selections_response():
    raw = wgp.server_config.get(_MODEL_SELECTION_CONFIG_KEY)
    profile = _active_production_profile()
    profile_defaults = {
        "image": _profile_image_model_type(profile),
        "video": str(profile.get("video", {}).get("model") or "").strip(),
    }
    try:
        explicit_models = _normalize_model_selections(raw)
    except ValueError:
        explicit_models = {}
    selected_models = {
        **{key: value for key, value in profile_defaults.items() if value},
        **explicit_models,
    }
    return {
        "configured": isinstance(raw, dict),
        "selected_models": selected_models,
        "sources": {
            key: "override" if key in explicit_models else "global"
            for key in selected_models
        },
    }


def get_model_selections():
    """Return model choices independently of Pinokio's changing UI port."""
    return _model_selections_response()


async def update_model_selections(request: Request):
    """Persist the user's last model for each generation mode."""
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail="Model selection payload must be an object.",
        )
    try:
        selected_models = _normalize_model_selections(
            body.get("selected_models"),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    with _MODEL_VISIBILITY_WRITE_LOCK:
        wgp.server_config[_MODEL_SELECTION_CONFIG_KEY] = selected_models
        _persist_model_visibility_config()
        return _model_selections_response()

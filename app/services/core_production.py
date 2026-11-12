"""Credential-free production profile and remote LLM routing for core/remote."""
from __future__ import annotations

import copy
from typing import Any

from services import core_workspace as core
from services.music_model_contract import DEFAULT_MUSIC_MODEL
from services.production_profile import normalize_production_profile
from services.provider_profile import resolve_writing_override
from services import llm_routing

PROFILE_KEY = "production_profile"
PROFILE_VERSION = 1

DEFAULT_VIDEO = {
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
}

CORE_DEFAULT_PROFILE = {
    "version": PROFILE_VERSION,
    "text": {"provider": "minimax", "model": "MiniMax-M3", "base_url": "https://api.minimax.io"},
    "image": {"provider": "minimax", "model": "image-01"},
    # Local music first, as in the full runtime: the paid MiniMax API is never a default.
    "music": {"provider": "local", "model": DEFAULT_MUSIC_MODEL},
    "model3d": {"provider": "meshy", "model": "latest"},
    "video": copy.deepcopy(DEFAULT_VIDEO),
}


def production_profile_response() -> dict[str, Any]:
    raw = core.load_config().get(PROFILE_KEY)
    try:
        return {"configured": raw is not None, "profile": normalize_production_profile(raw or CORE_DEFAULT_PROFILE)}
    except ValueError:
        return {"configured": False, "profile": dict(CORE_DEFAULT_PROFILE)}


def save_production_profile(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_production_profile(profile)
    data = core.load_config()
    data[PROFILE_KEY] = normalized
    services = data.setdefault("services", {})
    services["llm_provider"] = normalized["text"]["provider"]
    services["llm_model_id"] = normalized["text"]["model"]
    if normalized["text"].get("base_url"):
        services["llm_remote_url"] = normalized["text"]["base_url"]
    core.save_config(data)
    return {"configured": True, "profile": normalized}


def effective_llm_routing(services: dict | None = None) -> tuple[str, str, str]:
    values = services if isinstance(services, dict) else core.services_raw()
    text = production_profile_response()["profile"].get("text", {})
    return llm_routing._effective_llm_routing(values, text_profile=text, default_provider="minimax")


def llm_provider_credentials(provider: str, services: dict, remote_url: str = "") -> tuple[str, str]:
    return llm_routing._llm_provider_credentials(provider, services, remote_url)


def ensure_llm_loaded() -> None:
    from routers.system_capabilities import require_capability_http

    services = core.services_raw()
    provider, model, remote_url = effective_llm_routing(services)
    llm_routing._ensure_llm_loaded(
        services=services,
        provider=provider,
        model=model,
        remote_url=remote_url,
        device="cpu",
        default_model="MiniMax-M3",
        require_local=lambda: require_capability_http("local_llm"),
    )


def comic_writing_llm(body: dict) -> dict | None:
    try:
        return resolve_writing_override(
            provider=str(body.get("writingProvider") or "maestro"),
            model=str(body.get("writingModel") or ""),
            requested_url=str(body.get("writingBaseUrl") or ""),
            services=core.services_raw(),
            mode=str(body.get("mode") or ""),
        )
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def resolve_visual_media(value: str, workspace: str | None) -> str:
    return core.resolve_media(str(value or ""), workspace)

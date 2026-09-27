"""Credential-free production profile and remote LLM routing for core/remote."""
from __future__ import annotations

import copy
from typing import Any

from services import core_workspace as core
from services.provider_profile import (
    IMAGE_PROVIDERS,
    MODEL3D_PROVIDERS,
    MUSIC_PROVIDERS,
    TEXT_PROVIDERS,
    alias_model3d_provider,
    alias_text_provider,
    canonicalize_remote_url,
    default_url_for_provider,
    resolve_minimax_key,
    resolve_writing_override,
)

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
    "music": {"provider": "minimax", "model": "music-3.0"},
    "model3d": {"provider": "meshy", "model": "latest"},
    "video": copy.deepcopy(DEFAULT_VIDEO),
}


def _text(value: Any, label: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    result = value.strip()
    if not result:
        raise ValueError(f"{label} cannot be empty.")
    if len(result) > maximum:
        raise ValueError(f"{label} is too long.")
    return result


def _named_provider(section: dict[str, Any], label: str, allowed: frozenset[str] | set[str]) -> str:
    provider = _text(section.get("provider"), f"{label} provider").lower()
    if provider not in allowed:
        raise ValueError(f"Unsupported production {label.lower()} provider.")
    return provider


def _video_settings(settings: Any) -> dict[str, Any]:
    if not isinstance(settings, dict):
        raise ValueError("Production video settings must be an object.")
    try:
        steps = int(settings.get("steps", 20))
        flow_shift = float(settings.get("flowShift", 12.0))
        audio_shift = float(settings.get("audioShift", 3.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Production video steps and shifts must be numeric.") from exc
    loras = settings.get("loras", [])
    if not isinstance(loras, list) or len(loras) > 32:
        raise ValueError("Production video LoRAs must be a list of at most 32 entries.")
    return {
        "profile": _text(settings.get("profile", "quality"), "Video profile", maximum=40).lower(),
        "steps": steps,
        "flowShift": flow_shift,
        "audioShift": audio_shift,
        "turbo": bool(settings.get("turbo", False)),
        "cache": bool(settings.get("cache", False)),
        "loras": [_text(item, "Production video LoRA", maximum=500) for item in loras],
        "resolution": str(settings.get("resolution") or "540p"),
        "aspectRatio": str(settings.get("aspectRatio") or "16:9"),
    }


def normalize_production_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Production profile must be an object.")
    text, image, music, video = value.get("text"), value.get("image"), value.get("music"), value.get("video")
    model3d = value.get("model3d") if isinstance(value.get("model3d"), dict) else {
        "provider": "meshy", "model": "latest",
    }
    if not all(isinstance(item, dict) for item in (text, image, music, video)):
        raise ValueError("Production profile needs text, image, music and video sections.")
    text_provider = alias_text_provider(
        _named_provider(text, "Text", TEXT_PROVIDERS), str(text.get("base_url") or ""),
    )
    if text_provider not in TEXT_PROVIDERS:
        raise ValueError("Unsupported production text provider.")
    text_base_url = default_url_for_provider(
        text_provider, canonicalize_remote_url(str(text.get("base_url") or "")),
    )
    return {
        "version": PROFILE_VERSION,
        "text": {"provider": text_provider, "model": _text(text.get("model"), "Text model"), "base_url": text_base_url},
        "image": {"provider": _named_provider(image, "Image", IMAGE_PROVIDERS), "model": _text(image.get("model"), "Image model")},
        "music": {"provider": _named_provider(music, "Music", MUSIC_PROVIDERS), "model": _text(music.get("model"), "Music model")},
        "model3d": {
            "provider": alias_model3d_provider(_named_provider(model3d, "3D", MODEL3D_PROVIDERS)),
            "model": _text(model3d.get("model") or "latest", "3D model"),
        },
        "video": {
            "provider": _named_provider(video, "Video", {"maestro", "local"}),
            "model": _text(video.get("model"), "Video model"),
            "settings": _video_settings(video.get("settings")),
        },
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
    remote_url = str(text.get("base_url") or values.get("llm_remote_url") or "").strip()
    provider = alias_text_provider(str(text.get("provider") or "minimax").strip().lower(), remote_url)
    model = str(text.get("model") or "").strip()
    return provider, model, default_url_for_provider(provider, remote_url)


def llm_provider_credentials(provider: str, services: dict, remote_url: str = "") -> tuple[str, str]:
    api_key = ""
    if provider == "openai":
        api_key = str(services.get("openai_api_key") or "")
    elif provider == "anthropic":
        api_key = str(services.get("anthropic_api_key") or "")
    elif provider == "minimax":
        api_key = resolve_minimax_key(services, "llm")
    elif provider == "grok":
        api_key = str(services.get("grok_api_key") or "")
    elif provider == "deepseek":
        api_key = str(services.get("deepseek_api_key") or "")
    return api_key, default_url_for_provider(provider, remote_url)


def ensure_llm_loaded() -> None:
    from routers.system_capabilities import require_capability_http
    from services import llm_service

    services = core.services_raw()
    provider, model, remote_url = effective_llm_routing(services)
    if provider == "local":
        require_capability_http("local_llm")
    api_key, remote_url = llm_provider_credentials(provider, services, remote_url)
    desired = model or "MiniMax-M3"
    if llm_service.is_loaded():
        status = llm_service.get_status()
        remote_changed = (
            provider in {"remote", "ollama", "openai", "minimax", "grok", "anthropic", "deepseek"}
            and status.get("remote_url", "") != remote_url
        )
        if (
            status.get("model_id") != desired
            or status.get("provider") != provider
            or remote_changed
        ):
            llm_service.unload_model()
            llm_service.load_model(
                model_id=desired, device="cpu", provider=provider,
                remote_url=remote_url, api_key=api_key,
            )
        return
    llm_service.load_model(
        model_id=desired, device="cpu", provider=provider,
        remote_url=remote_url, api_key=api_key,
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
    from services import core_editor
    return core_editor.resolve_media(str(value or ""), workspace)

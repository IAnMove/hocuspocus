"""Production-profile validation for both servers.

The full server and the core server do not share one checker. Each function
below is the body that server already had. The full server's checker is
stricter (ranges, resolution, aspect). The core server's checker is the
looser one, and each caller still passes its own default profile.
"""
from __future__ import annotations

from typing import Any

from services.provider_profile import (
    IMAGE_PROVIDERS,
    MODEL3D_PROVIDERS,
    MUSIC_PROVIDERS,
    TEXT_PROVIDERS,
    alias_model3d_provider,
    alias_text_provider,
    canonicalize_remote_url,
    default_url_for_provider,
)

# Both servers store version 1. The two names are the ones the moved bodies use.
_PRODUCTION_PROFILE_VERSION = 1
PROFILE_VERSION = _PRODUCTION_PROFILE_VERSION


def _bounded_profile_text(value, label: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    result = value.strip()
    if not result:
        raise ValueError(f"{label} cannot be empty.")
    if len(result) > maximum:
        raise ValueError(f"{label} is too long.")
    return result


def _normalize_production_profile(value) -> dict:
    """Validate the credential-free defaults shared by every production UI."""
    from services.provider_profile import (
        IMAGE_PROVIDERS,
        MODEL3D_PROVIDERS,
        MUSIC_PROVIDERS,
        TEXT_PROVIDERS,
        alias_model3d_provider,
        alias_text_provider,
        canonicalize_remote_url,
        default_url_for_provider,
    )

    if not isinstance(value, dict):
        raise ValueError("Production profile must be an object.")
    text_profile = value.get("text")
    image_profile = value.get("image")
    music_profile = value.get("music")
    video_profile = value.get("video")
    model3d_profile = value.get("model3d") if isinstance(value.get("model3d"), dict) else {
        "provider": "local",
        "model": "hunyuan3d-2mini-turbo",
    }
    if not all(isinstance(item, dict) for item in (
        text_profile, image_profile, music_profile, video_profile,
    )):
        raise ValueError("Production profile needs text, image, music and video sections.")

    text_provider = alias_text_provider(_bounded_profile_text(
        text_profile.get("provider"), "Text provider",
    ).lower(), str(text_profile.get("base_url") or ""))
    if text_provider not in TEXT_PROVIDERS:
        raise ValueError("Unsupported production text provider.")
    image_provider = _bounded_profile_text(
        image_profile.get("provider"), "Image provider",
    ).lower()
    if image_provider not in IMAGE_PROVIDERS:
        raise ValueError("Unsupported production image provider.")
    music_provider = _bounded_profile_text(
        music_profile.get("provider"), "Music provider",
    ).lower()
    if music_provider not in MUSIC_PROVIDERS:
        raise ValueError("Unsupported production music provider.")
    model3d_provider = alias_model3d_provider(_bounded_profile_text(
        model3d_profile.get("provider"), "3D provider",
    ).lower())
    if model3d_provider not in MODEL3D_PROVIDERS:
        raise ValueError("Unsupported production 3D provider.")
    music_model = _bounded_profile_text(music_profile.get("model"), "Music model")
    video_provider = _bounded_profile_text(
        video_profile.get("provider"), "Video provider",
    ).lower()
    if video_provider not in {"maestro", "local"}:
        raise ValueError("Unsupported production video provider.")

    settings = video_profile.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("Production video settings must be an object.")
    try:
        steps = int(settings.get("steps", 20))
        flow_shift = float(settings.get("flowShift", 12.0))
        audio_shift = float(settings.get("audioShift", 3.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Production video steps and shifts must be numeric.") from exc
    if not 1 <= steps <= 50:
        raise ValueError("Production video steps must be between 1 and 50.")
    if not -100 <= flow_shift <= 100 or not -100 <= audio_shift <= 100:
        raise ValueError("Production video shifts must be between -100 and 100.")
    loras = settings.get("loras", [])
    if not isinstance(loras, list) or len(loras) > 32:
        raise ValueError("Production video LoRAs must be a list of at most 32 entries.")
    normalized_loras = [
        _bounded_profile_text(item, "Production video LoRA", maximum=500)
        for item in loras
    ]
    resolution = _bounded_profile_text(
        settings.get("resolution", "540p"), "Production video resolution",
        maximum=40,
    ).lower()
    if resolution not in {"auto", "480p", "540p", "720p", "768p", "1080p"}:
        raise ValueError("Unsupported production video resolution preset.")
    aspect_ratio = _bounded_profile_text(
        settings.get("aspectRatio", "16:9"), "Production video aspect ratio",
        maximum=20,
    ).lower()
    if aspect_ratio not in {"auto", "21:9", "16:9", "9:16", "1:1", "4:3", "3:4"}:
        raise ValueError("Unsupported production video aspect ratio.")

    text_base_url = canonicalize_remote_url(str(text_profile.get("base_url") or ""))
    if text_provider in {"ollama", "remote", "openai-compatible", "grok", "openai", "minimax"}:
        text_base_url = default_url_for_provider(text_provider, text_base_url)

    return {
        "version": _PRODUCTION_PROFILE_VERSION,
        "text": {
            "provider": text_provider,
            "model": _bounded_profile_text(text_profile.get("model"), "Text model"),
            "base_url": text_base_url,
        },
        "image": {
            "provider": image_provider,
            "model": _bounded_profile_text(image_profile.get("model"), "Image model"),
        },
        "music": {
            "provider": music_provider,
            "model": music_model,
        },
        "model3d": {
            "provider": model3d_provider,
            "model": _bounded_profile_text(
                model3d_profile.get("model") or "hunyuan3d-2mini-turbo",
                "3D model",
            ),
        },
        "video": {
            "provider": video_provider,
            "model": _bounded_profile_text(video_profile.get("model"), "Video model"),
            "settings": {
                "profile": _bounded_profile_text(
                    settings.get("profile", "quality"), "Video profile", maximum=40,
                ).lower(),
                "steps": steps,
                "flowShift": flow_shift,
                "audioShift": audio_shift,
                "turbo": bool(settings.get("turbo", False)),
                "cache": bool(settings.get("cache", False)),
                "loras": normalized_loras,
                "resolution": resolution,
                "aspectRatio": aspect_ratio,
            },
        },
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

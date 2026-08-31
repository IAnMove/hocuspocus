"""Canonical production-provider helpers shared by Settings, Labs and jobs.

Credentials stay in ``services``. Routing (which engine, which model, which
URL) lives on the credential-free production profile. MiniMax chat, Image-01
and Music each have their own key field so a future split does not require
another migration; empty specific keys still fall back to the legacy shared
``minimax_api_key``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


TEXT_PROVIDERS = frozenset({
    "local",
    "remote",
    "ollama",
    "openai",
    "anthropic",
    "deepseek",
    "minimax",
    "grok",
    "openai-compatible",
})
IMAGE_PROVIDERS = frozenset({"maestro", "local", "minimax"})
MUSIC_PROVIDERS = frozenset({"maestro", "local", "minimax"})
VIDEO_PROVIDERS = frozenset({"maestro", "local"})
MODEL3D_PROVIDERS = frozenset({"maestro", "local", "hunyuan", "meshy", "hi3d"})
SCOPED_WRITING_PROVIDERS = frozenset({
    "deepseek",
    "minimax",
    "openai",
    "openai-compatible",
    "ollama",
    "grok",
})
MINIMAX_CHAT_MODELS = frozenset({
    "MiniMax-M3",
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
})
PUBLIC_LLM_PROVIDERS = frozenset({
    "openai", "anthropic", "minimax", "grok", "deepseek",
})
DEFAULT_URLS = {
    "minimax": "https://api.minimax.io",
    "openai": "https://api.openai.com",
    "deepseek": "https://api.deepseek.com",
    "grok": "https://api.x.ai",
    "ollama": "http://127.0.0.1:11434",
}
GROK_MODELS = (
    "grok-4",
    "grok-4-fast",
    "grok-3",
    "grok-3-mini",
    "grok-2-1212",
    "grok-2-vision-1212",
)


def canonicalize_remote_url(url: str) -> str:
    """Strip trailing slashes and a redundant ``/v1`` so callers can append paths."""
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        path = parsed.path.rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3].rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    value = value.rstrip("/")
    if value.endswith("/v1"):
        value = value[:-3].rstrip("/")
    return value


def openai_chat_completions_url(url: str) -> str:
    origin = canonicalize_remote_url(url)
    if not origin:
        raise ValueError("A remote LLM URL is required")
    return f"{origin}/v1/chat/completions"


def openai_models_url(url: str) -> str:
    origin = canonicalize_remote_url(url)
    if not origin:
        raise ValueError("A remote LLM URL is required")
    return f"{origin}/v1/models"


def ollama_tags_url(url: str) -> str:
    origin = canonicalize_remote_url(url)
    if not origin:
        raise ValueError("An Ollama URL is required")
    return f"{origin}/api/tags"


def looks_like_ollama(url: str) -> bool:
    value = str(url or "").lower()
    return "ollama" in value or ":11434" in value


def _bounded_text(value: Any, label: str, *, maximum: int = 200, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    result = value.strip()
    if not result and not allow_empty:
        raise ValueError(f"{label} cannot be empty.")
    if len(result) > maximum:
        raise ValueError(f"{label} is too long.")
    return result


def resolve_minimax_key(services: dict | None, purpose: str) -> str:
    """Return the MiniMax key for llm, image or music.

    Specific fields win. The legacy shared key is the fallback so existing
    installs keep working after the split.
    """
    values = services if isinstance(services, dict) else {}
    if purpose not in {"llm", "image", "music"}:
        raise ValueError(f"Unknown MiniMax key purpose: {purpose}")
    specific = str(values.get(f"minimax_{purpose}_api_key") or "").strip()
    if specific:
        return specific
    return str(values.get("minimax_api_key") or "").strip()


def default_url_for_provider(provider: str, current: str = "") -> str:
    if str(current or "").strip():
        return canonicalize_remote_url(current)
    return DEFAULT_URLS.get(str(provider or "").strip().lower(), "")


def alias_text_provider(provider: str, remote_url: str = "") -> str:
    value = str(provider or "local").strip().lower()
    if value == "remote" and looks_like_ollama(remote_url):
        return "ollama"
    if value == "hunyuan":
        return "local"
    return value


def alias_model3d_provider(provider: str) -> str:
    value = str(provider or "local").strip().lower()
    if value in {"maestro", "hunyuan"}:
        return "local"
    return value


def resolve_writing_override(
    *,
    provider: str,
    model: str = "",
    requested_url: str = "",
    services: dict | None = None,
    mode: str = "",
) -> dict[str, str] | None:
    """Map a per-project writing override onto an isolated OpenAI-compatible call.

    ``maestro`` / ``local`` / ``internal`` mean "use the Settings singleton".
    """
    name = str(provider or "maestro").strip().lower()
    if name in ("", "maestro", "internal", "local"):
        return None
    if name == "remote":
        name = "ollama" if looks_like_ollama(requested_url) else "openai-compatible"
    if name not in SCOPED_WRITING_PROVIDERS:
        raise ValueError("Unsupported production writing provider")

    values = services if isinstance(services, dict) else {}
    requested = canonicalize_remote_url(requested_url)[:1000]
    model_id = str(model or "").strip()[:200]

    if name == "openai-compatible":
        host = (urlparse(requested or values.get("compatible_base_url") or "").hostname or "").lower()
        if host in {"api.deepseek.com", "api.deepseek.com"}:
            name = "deepseek"
        elif host in {"api.openai.com"}:
            name = "openai"
        elif host in {"api.x.ai"}:
            name = "grok"
        elif host in {"api.minimax.io"}:
            name = "minimax"

    if name == "deepseek":
        model_id = model_id or "deepseek-v4-pro"
        if model_id in ("deepseek-chat", "deepseek-reasoner"):
            model_id = "deepseek-v4-pro"
        if str(mode or "").lower() == "translate":
            model_id = "deepseek-v4-flash"
        if model_id not in {"deepseek-v4-pro", "deepseek-v4-flash"}:
            raise ValueError("Choose DeepSeek V4 Pro or V4 Flash")
        base_url = "https://api.deepseek.com"
        api_key = str(values.get("deepseek_api_key") or "")
        missing = "Configure the DeepSeek API key in Settings → Services first"
    elif name == "minimax":
        model_id = model_id or "MiniMax-M3"
        if model_id not in MINIMAX_CHAT_MODELS:
            raise ValueError("Choose MiniMax M3, M2.7, or M2.7 Highspeed")
        base_url = "https://api.minimax.io/v1"
        api_key = resolve_minimax_key(values, "llm")
        missing = "Configure the MiniMax LLM API key in Settings → Services first"
    elif name == "openai":
        model_id = model_id or "gpt-4.1"
        base_url = "https://api.openai.com"
        api_key = str(values.get("openai_api_key") or "")
        missing = "Configure the OpenAI API key in Settings → Services first"
    elif name == "grok":
        model_id = model_id or "grok-4"
        base_url = "https://api.x.ai/v1"
        api_key = str(values.get("grok_api_key") or "")
        missing = "Configure the Grok API key in Settings → Services first"
    elif name == "ollama":
        base_url = requested or canonicalize_remote_url(str(values.get("llm_remote_url") or ""))
        if not base_url:
            raise ValueError("Set the Ollama URL in Settings → Services first")
        api_key = str(values.get("compatible_api_key") or "")
        missing = ""
    else:
        model_id = model_id
        base_url = canonicalize_remote_url(str(values.get("compatible_base_url") or ""))
        if not base_url:
            raise ValueError("Configure the custom compatible URL in Settings → Services first")
        if requested and canonicalize_remote_url(requested) != base_url:
            raise ValueError("The production's custom URL does not match the trusted compatible profile")
        api_key = str(values.get("compatible_api_key") or "")
        missing = ""

    if not model_id:
        raise ValueError("Choose an OpenAI-compatible writing model")
    if not str(base_url).startswith(("http://", "https://")):
        raise ValueError("OpenAI-compatible URL must start with http:// or https://")
    if name not in {"openai-compatible", "ollama"} and not api_key:
        raise ValueError(missing)
    return {
        "provider": name,
        "model": model_id,
        "base_url": str(base_url).rstrip("/"),
        "api_key": api_key,
    }


def character_describe_backend(text_provider: str) -> str:
    """Vision A-prompt: MiniMax, internal local, or unavailable."""
    name = str(text_provider or "local").strip().lower()
    if name in {"minimax"}:
        return "minimax"
    if name in {"local", "maestro", "internal"}:
        return "local"
    return "unavailable"


def image_provider_uses_minimax(image: dict | None) -> bool:
    block = image if isinstance(image, dict) else {}
    return str(block.get("provider") or "").strip().lower() == "minimax"

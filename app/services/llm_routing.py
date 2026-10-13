"""LLM routing, credentials and the load-or-reload decision.

Launch, Director and the core server each decide which model they want.
This module loads it. A caller passes the services map, the provider, the
model, the URL, the device and its own default model. Core also passes
``require_local`` so a local model on a machine without one is refused
before any load. The default model is the caller's: launch's Gemma repo,
core's ``MiniMax-M3``, Director's own Gemma string.
"""
from __future__ import annotations

from collections.abc import Callable


# A changed URL for any of these providers means the loaded client is stale.
# Launch used to omit anthropic and deepseek, so it kept calling the old host.
_URL_RELOAD_PROVIDERS = (
    "remote",
    "ollama",
    "openai",
    "minimax",
    "grok",
    "anthropic",
    "deepseek",
)


def _effective_llm_routing(
    services: dict | None = None,
    *,
    text_profile: dict | None = None,
    default_provider: str = "local",
) -> tuple[str, str, str]:
    """Resolve generic LLM work from a production-profile text section.

    API keys and device preferences remain in ``services``. ``text_profile``
    is the caller's already-chosen text section (launch's active profile,
    core's saved profile). ``default_provider`` is used only when that
    section has no provider: ``local`` on the full server, ``minimax`` on core.
    """
    from services.provider_profile import alias_text_provider, default_url_for_provider

    service_values = services if isinstance(services, dict) else {}
    profile = text_profile or {}
    remote_url = str(
        profile.get("base_url")
        or service_values.get("llm_remote_url")
        or ""
    ).strip()
    provider = alias_text_provider(
        str(profile.get("provider") or default_provider).strip().lower(),
        remote_url,
    )
    model = str(profile.get("model") or "").strip()
    remote_url = default_url_for_provider(provider, remote_url)
    return provider, model, remote_url


def _llm_provider_credentials(provider: str, services: dict, remote_url: str = "") -> tuple[str, str]:
    from services.provider_profile import default_url_for_provider, resolve_minimax_key

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


def _ensure_llm_loaded(
    *,
    services: dict,
    provider: str,
    model: str,
    remote_url: str,
    device: str,
    default_model: str,
    require_local: Callable[[], None] | None = None,
) -> None:
    """Load the LLM, or reload it when the model, provider, device or URL changed."""
    from services import llm_service

    if provider == "local" and require_local is not None:
        require_local()
    desired = model or default_model
    desired_provider = provider
    desired_device = device
    desired_api_key, desired_remote_url = _llm_provider_credentials(
        desired_provider, services, remote_url,
    )

    if llm_service.is_loaded():
        status = llm_service.get_status()
        remote_changed = (
            desired_provider in _URL_RELOAD_PROVIDERS
            and status.get("remote_url", "") != desired_remote_url
        )
        if (
            status.get("model_id") != desired
            or status.get("provider") != desired_provider
            or status.get("device") != (desired_device if desired_provider == "local" else desired_provider)
            or remote_changed
        ):
            llm_service.unload_model()
            llm_service.load_model(
                model_id=desired,
                device=desired_device,
                provider=desired_provider,
                remote_url=desired_remote_url,
                api_key=desired_api_key,
            )
    else:
        llm_service.load_model(
            model_id=desired,
            device=desired_device,
            provider=desired_provider,
            remote_url=desired_remote_url,
            api_key=desired_api_key,
        )

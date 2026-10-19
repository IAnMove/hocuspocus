"""Director defaults that used to be hidden house rules, as visible run options.

Each option is resolved in this order: the request, then Settings › Services,
then the default. The pipeline writes the resolved value into the run's
params, so resume and repair do the same thing as the first run. The
defaults keep today's behaviour.

- ``reference_anchor``: with no reference image, Director draws one picture
  from shot 1 and draws every shot from it (Maestro). ``always`` (default),
  ``no_cast_refs`` (only when there are no character references) or ``off``.
- ``lighting_continuity``: image prompts end with "Use lighting and color
  temp from reference image" (Maestro). ``auto`` (default: only with the
  user's own reference image), ``reference`` (always) or ``per_shot``.
- ``keep_reference_wardrobe``: clothing words are removed from image prompts
  so the image model copies the clothes in the reference (Maestro). ``True``
  by default.
"""

from __future__ import annotations

import sys
from typing import Any, Mapping, Optional

REFERENCE_ANCHOR_MODES = ("always", "no_cast_refs", "off")
LIGHTING_MODES = ("auto", "reference", "per_shot")

# Run option → (Settings › Services key, allowed values or None for a flag, default).
_RUN_OPTIONS: dict[str, tuple[str, Optional[tuple[str, ...]], Any]] = {
    "reference_anchor": ("director_reference_anchor", REFERENCE_ANCHOR_MODES, "always"),
    "lighting_continuity": ("director_lighting_continuity", LIGHTING_MODES, "auto"),
    "keep_reference_wardrobe": ("director_keep_reference_wardrobe", None, True),
}
RUN_OPTION_NAMES = tuple(_RUN_OPTIONS)


def _valid(value: Any, allowed: Optional[tuple[str, ...]]) -> Any:
    """The value when it is valid for the option, else None."""
    if allowed is None:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower() if isinstance(value, str) else ""
        return {"true": True, "false": False}.get(text)
    text = str(value or "").strip().lower()
    return text if text in allowed else None


def resolve_option(name: str, requested: Any, services: Optional[Mapping[str, Any]]) -> Any:
    """Request → Settings › Services → default. Unknown values are ignored."""
    settings_key, allowed, default = _RUN_OPTIONS[name]
    settings = services if isinstance(services, Mapping) else {}
    for candidate in (requested, settings.get(settings_key)):
        value = _valid(candidate, allowed)
        if value is not None:
            return value
    return default


def resolve_run_options(params: dict, services: Optional[Mapping[str, Any]]) -> dict:
    """Write every resolved option into ``params`` (persisted with the run)."""
    for name in _RUN_OPTIONS:
        params[name] = resolve_option(name, params.get(name), services)
    return params


def saved_option(params: Optional[Mapping[str, Any]], name: str) -> Any:
    """The option a saved run used. Runs saved before it existed get the default."""
    _settings_key, allowed, default = _RUN_OPTIONS[name]
    value = _valid((params or {}).get(name), allowed)
    return default if value is None else value


def wants_generated_anchor(mode: str, *, has_cast_refs: bool) -> bool:
    """Whether a run with no reference image draws a shared reference picture."""
    if mode == "off":
        return False
    if mode == "no_cast_refs":
        return not has_cast_refs
    return True


def lighting_from_reference(mode: str, *, has_user_reference: bool) -> bool:
    """Whether image prompts copy the reference's light and colour temperature."""
    if mode == "per_shot":
        return False
    if mode == "reference":
        return True
    return has_user_reference


def current_services() -> Mapping[str, Any]:
    """Settings › Services of the running app, or an empty mapping.

    The planners never import wgp (its module owns the CLI parser); in the app
    it is already loaded.
    """
    config = getattr(sys.modules.get("wgp"), "server_config", None)
    services = config.get("services") if isinstance(config, dict) else None
    return services if isinstance(services, Mapping) else {}

"""Opt-in reuse of downloaded variants without changing global precision."""


def installed_weight_variant(preferred, choices, definition, locate):
    if not (definition or {}).get("prefer_installed_variants"):
        return preferred
    folder = definition.get("text_encoder_folder")
    if locate(preferred, extra_paths=folder):
        return preferred
    return next((url for url in choices if locate(url, extra_paths=folder)), preferred)

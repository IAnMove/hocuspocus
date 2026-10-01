"""``media.options``: what this machine can create with, in one small answer, so an assistant can ask before it generates.

Every install has different things: one has a 24 GB GPU and Qwen Image 2.1 on disk, another has no GPU and a MiniMax
key, another has both. A hard-coded default is a fallback, not a decision: before creating something an assistant should
look at what is available, tell the user the options that make sense, ask once if they have not said, and then go.

``models.list`` cannot do that job: it is the whole catalog (hundreds of models, ~60 KB), with no sign of what is
installed, which cloud providers have a key, or what the profile would pick. This command answers just that, in about a
kilobyte, and never returns a secret: a provider is only ``ready`` or in ``needs_key``.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from starlette.concurrency import run_in_threadpool

OPERATION = "media.options"
IMAGE_ARCH = re.compile(r"^(flux|pi_flux2|qwen_image|z_image|krea2|hidream|minimax_image)")
# provider -> (profile kind, services flag that says its key is configured, the model a profile would use)
CLOUD = {
    "image": [("minimax", "minimax_image_api_key_set", "image-01")],
    "music": [("minimax", "minimax_music_api_key_set", "music-3.0")],
    "model3d": [("meshy", "meshy_api_key_set", "latest"), ("hi3d", "hi3d_api_key_set", "hitem3dv2.1")],
    "text": [("minimax", "minimax_llm_api_key_set", "MiniMax-M3"), ("openai", "openai_api_key_set", ""),
             ("anthropic", "anthropic_api_key_set", ""), ("google", "google_api_key_set", ""),
             ("deepseek", "deepseek_api_key_set", ""), ("grok", "grok_api_key_set", "")],
}
GUIDANCE = ("Choose with the user before creating: if more than one option fits (a local model and a cloud provider that is ready) "
            "and they have not said which, ask once, naming the options and what each costs (local = GPU time and no tokens; "
            "cloud = provider tokens). If they already said, or only one fits, go. `profile` is what a request with no choice would use.")


def _local_images(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found = []
    for model in models:
        model_type = str(model.get("model_type") or "")
        architecture = str(model.get("architecture") or model_type)
        if not IMAGE_ARCH.match(architecture) or model.get("is_downloaded") is not True:
            continue
        if model.get("tool_only") or model.get("nsfw_only"):
            continue
        needs = model.get("resource_requirements") or {}
        entry = {"id": model_type, "name": model.get("name") or model_type}
        if isinstance(needs.get("vram_gb"), (int, float)):
            entry["vram_gb"] = needs["vram_gb"]
        if "edit" in model_type:
            entry["needs_input_image"] = True
        found.append(entry)
    return sorted(found, key=lambda entry: entry["id"])


def _cloud(services: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for kind, providers in CLOUD.items():
        ready = [name for name, flag, _ in providers if services.get(flag) is True]
        result[kind] = {"ready": ready, "needs_key": [name for name, _, _ in providers if name not in ready]}
    return result


def _profile(response: dict[str, Any]) -> dict[str, Any]:
    profile = response.get("profile") if isinstance(response.get("profile"), dict) else {}
    chosen = {kind: {"provider": section.get("provider"), "model": section.get("model")}
              for kind, section in profile.items() if isinstance(section, dict) and "provider" in section}
    return {"configured": response.get("configured") is True, **chosen}


def build(models: list[dict[str, Any]], services: dict[str, Any], profile_response: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": _profile(profile_response),
        "local": {"image": _local_images(models)},
        "cloud": _cloud(services),
        "guidance": GUIDANCE,
    }


def command_catalog() -> list[dict[str, Any]]:
    return [{
        "name": OPERATION, "version": 1, "domain": "studio", "mutation": False,
        "description": ("What this machine can create with: installed local image models, which cloud providers have a key "
                        "(never the key), and the profile a request with no choice would use. About 1 KB; read it before creating "
                        "images, music, 3D or text and ask the user which to use when more than one fits."),
        "inputSchema": {"type": "object", "additionalProperties": False,
                        "properties": {"version": {"type": "integer", "const": 1},
                                       "input": {"type": "object", "additionalProperties": False, "properties": {}}},
                        "required": ["version"]},
    }]


def command_handlers(sources: Callable[[], tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]]) -> dict[str, Callable]:
    """``sources()`` returns (models, services settings, profile response); it is called per request."""
    async def run(arguments: Any) -> dict[str, Any]:
        models, services, profile = await run_in_threadpool(sources)
        return {"version": 1, "status": "completed", "operation": OPERATION, "result": build(models, services, profile)}
    return {OPERATION: run}

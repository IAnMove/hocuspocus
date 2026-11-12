"""Catalog and request checks for MiniMax H3-Image.

The open weights stay out of this install. They are a large BF16 checkpoint
and are not for local inference from the EU. Studio, Director and the core
profile call the public image API through ``minimax_h3_image_service``.

Text-to-image and edits share one canvas rule: send an exact ``WIDTHxHEIGHT``.
The default canvas is 2048x2048. A named ratio uses the published 2K table.
The API's own default is 4K, which this module does not use.
"""
from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Callable, Mapping

from services.minimax_h3_image_service import (
    MAX_REFERENCES,
    MODEL_FAST,
    MODEL_STANDARD,
    MiniMaxImageError,
    output_size,
    prepare_prompt,
)
from services.remote_image_generation import (
    FAMILY,
    NEUTRAL,
    error,
    legacy_resolver,
    receipt_notes,
    require_api_key,
)

_MODELS = (
    (MODEL_STANDARD, "MiniMax H3-Image (remote, no GPU)",
     "Remote MiniMax H3-Image: no GPU and no local weights, billed to your MiniMax plan. "
     "Default canvas 2048x2048. Up to 16 reference pictures. 4096x4096 costs more."),
    (MODEL_FAST, "MiniMax H3-Image Highspeed (remote, no GPU)",
     "Remote MiniMax H3-Image Highspeed: the faster API tier, same limits as H3-Image. "
     "No GPU and no local weights. Default canvas 2048x2048. Up to 16 reference pictures."),
)
_SENT_FIELDS = ("image_guide", "image_refs", "image_start")
_IGNORED_FIELDS = {
    "image_end": "MiniMax H3-Image has no end frame; this image was not sent",
    "image_mask": "MiniMax H3-Image has no mask; this image was not sent",
}
_EXTRA = "MiniMax H3-Image takes at most 16 reference pictures; this one was not sent"


def catalog_entries(key_set: bool | None = None) -> list[dict[str, Any]]:
    return [_entry(model_type, name, description, key_set) for model_type, name, description in _MODELS]


def model_options(model_type: str) -> dict[str, Any]:
    return {
        "model_type": model_type,
        "architecture": "minimax_image",
        "guidance_max_phases": 1,
        "lock_guidance_phases": True,
        "sliding_window": False,
        "motion_amplitude": False,
        "flow_shift": False,
        "tea_cache": False,
        "returns_audio": False,
        "any_audio_prompt": False,
        "audio_scale_name": "",
        "lock_inference_steps": True,
        "lock_guidance_scale": True,
        "no_negative_prompt": True,
        "i2v_class": False,
        "t2v_class": False,
        "image_outputs": True,
        "supports_end_frame": False,
        "fps": 0,
        "image_ref_choices": {
            "choices": [["None", ""], ["Reference pictures (up to 16, in the order they are attached)", "I"]],
            "letters_filter": "I",
            "default": "",
        },
        "max_image_refs": MAX_REFERENCES,
    }


def defaults(model_type: str) -> dict[str, Any]:
    return {
        "model_type": model_type,
        "prompt": "",
        "resolution": "2048x2048",
        "image_mode": 1,
        "generation_mode": "image",
        **NEUTRAL,
    }


def _entry(model_type: str, name: str, description: str, key_set: bool | None) -> dict[str, Any]:
    entry = {
        "model_type": model_type,
        "name": name,
        "description": description,
        "family": FAMILY["id"],
        "architecture": "minimax_image",
        "resource_requirements": {"tier": "remote", "backend": "minimax", "note": "Remote API, no GPU"},
        "remote": True,
        "requires_api_key": True,
        "is_i2v": False,
        "is_t2v": False,
        "guidance_max_phases": 1,
        "fps": 0,
        "supports_end_frame": False,
        "supports_audio": False,
        "supports_ref_images": True,
        "is_downloaded": True,
        "nsfw_only": False,
        "director": {
            "image": {"compatible": True, "reason": ""},
            "video": {},
            "supports_audio_input": False,
            "generates_audio": False,
            "supports_voice_reference": False,
            "max_image_refs": MAX_REFERENCES,
        },
    }
    if key_set is not None:
        entry["api_key_set"] = bool(key_set)
    return entry


def _values(params: Mapping[str, Any], field: str) -> list[tuple[str, int, str]]:
    raw = params.get(field)
    found = []
    for index, value in enumerate(raw if isinstance(raw, list) else [raw]):
        if isinstance(value, str) and value.strip():
            found.append((field, index, value.strip()))
    return found


def _ordered(params: Mapping[str, Any]) -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for field in _SENT_FIELDS:
        found.extend(_values(params, field))
    return found


def _ignored(field: str, index: int, value: str, reason: str) -> dict[str, Any]:
    return {
        "role": "ignored_reference",
        "source_field": field,
        "index": index,
        "url": value,
        "reason": f"{field}[{index}]: {reason}",
    }


def _check_file(path: str, field: str, index: int) -> None:
    if not os.path.isfile(path):
        raise error(422, "invalid_reference", f"{field}[{index}]: the picture is not available")
    if os.path.getsize(path) > 20 * 1024 * 1024:
        raise error(422, "invalid_reference", f"{field}[{index}]: the picture is larger than 20 MB")


def _canvas_note(params: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
    size = output_size(str(params.get("resolution") or ""))
    asked = str(params.get("resolution") or "").strip().replace(" ", "").replace("×", "x").replace("X", "x")
    if size.lower() == asked.lower():
        return size, None
    return size, {
        "role": "resolution",
        "reason": f"The canvas was sent as {size}. H3-Image needs between 655360 and 20000000 pixels and a ratio from 1:3 to 3:1",
    }


def _keep_references(
    params: Mapping[str, Any],
    resolve: Callable[[str], tuple[str, Mapping[str, Any]]] | None,
) -> tuple[list[str], list[dict[str, Any]]]:
    kept: list[str] = []
    seen: set[str] = set()
    resources: list[dict[str, Any]] = []
    for field, index, value in _ordered(params):
        if len(kept) >= MAX_REFERENCES:
            resources.append(_ignored(field, index, value, _EXTRA))
            continue
        if resolve is None:
            raise error(422, "invalid_reference", f"{field}[{index}]: this door cannot resolve pictures")
        try:
            path, identity = resolve(value)
        except (ValueError, OSError) as exc:
            raise error(422, "invalid_reference", f"{field}[{index}]: {exc}") from exc
        _check_file(path, field, index)
        key = os.path.normcase(os.path.realpath(path))
        if key in seen:
            resources.append(_ignored(field, index, value, "This picture was already attached"))
            continue
        seen.add(key)
        kept.append(path)
        resources.append({
            "role": "reference",
            "source_field": field,
            "index": index,
            "url": value,
            **identity,
            "uses": f"MiniMax H3-Image picture {len(kept)}",
        })
    return kept, resources


def _unused_inputs(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for field, reason in _IGNORED_FIELDS.items():
        for item_field, index, value in _values(params, field):
            resources.append(_ignored(item_field, index, value, reason))
    if str(params.get("negative_prompt") or "").strip():
        resources.append({
            "role": "ignored_negative_prompt",
            "reason": "MiniMax H3-Image has no negative prompt; it was not sent",
        })
    if params.get("activated_loras"):
        resources.append({
            "role": "ignored_loras",
            "reason": "MiniMax H3-Image takes no LoRA; they were not sent",
        })
    return resources


def prepare_h3_image(
    params: Mapping[str, Any],
    *,
    services: Mapping[str, Any] | None,
    resolve: Callable[[str], tuple[str, Mapping[str, Any]]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate one H3-Image request. Returns the job parameters and the receipt resources."""
    from services import execution_mode

    workspace = str(params.get("workspace") or "default")
    try:
        execution_mode.validate_remote_provider(workspace, "minimax-image")
    except execution_mode.ExecutionModeError as exc:
        raise error(409, "execution_policy", str(exc)) from exc
    require_api_key(services)
    try:
        prepare_prompt(str(params.get("prompt") or ""))
    except MiniMaxImageError as exc:
        raise error(422, "invalid_command", str(exc)) from exc
    working = deepcopy(dict(params))
    working["generation_mode"] = "image"
    size, canvas = _canvas_note(params)
    resources: list[dict[str, Any]] = []
    if canvas is not None:
        resources.append(canvas)
    working["resolution"] = size
    working.pop("aspect_ratio", None)
    kept, attached = _keep_references(params, resolve)
    resources.extend(attached)
    if kept:
        working["image_refs"] = kept
    else:
        working.pop("image_refs", None)
    for field in ("image_start", "image_end", "image_guide", "image_mask"):
        working.pop(field, None)
    resources.extend(_unused_inputs(params))
    notes = receipt_notes(resources)
    if notes:
        working["_remote_notes"] = notes
    return working, resources


def prepare_core(params: Mapping[str, Any], workspace: str, services: Mapping[str, Any] | None):
    """The core command door: resolve upload and workspace URLs, then the same checks."""
    from services.core_workspace import uploads_dir, workspace_dir

    resolve = legacy_resolver(workspace, uploads_dir=uploads_dir(), workspace_dir=workspace_dir(workspace))
    working, resources = prepare_h3_image(params, services=services, resolve=resolve)
    return working, receipt_notes(resources)

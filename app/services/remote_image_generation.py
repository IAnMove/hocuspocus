"""MiniMax Image-01 as a normal ``generation.image`` model.

``minimax:image-01`` is chosen the way ``qwen_image_21_turbo`` is (model pickers, ``generation.image`` v1 and v2,
``POST /api/v1/generate``), but it never touches the GPU: the request goes to the MiniMax API, so it does not wait in
the local generation queue. This module is the one definition every door uses:

* the catalog entry, defaults and options that make the model appear in the pickers (full and core runtime);
* ``prepare_remote_image``: the checks and the one reference a request needs before it is admitted;
* ``complete_remote_command``: a command may omit what a remote model does not use (steps, guidance, seed).

The worker that calls the API for a queued job is ``services/remote_image_worker.py``.

Image-01 keeps the face of ONE character reference (``subject_reference``): it invents the outfit and ignores the pose.
The first reference is used; every other reference, a negative prompt and LoRAs are not sent, and each one is listed in
the returned resources with a ``reason`` that the receipt shows as a note.
"""
from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Callable, Mapping

from fastapi import HTTPException

from services import execution_mode, resource_scheduler
from services.minimax_image_service import (
    API_URL,
    MODEL_ID,
    MiniMaxImageError,
    aspect_ratio_for_resolution,
    prepare_prompt,
)
from services.provider_profile import resolve_minimax_key

PREFIX = "minimax:"
FAMILY = {"id": "minimax", "label": "MiniMax (remote API)", "order": 1170}
KEY_MISSING = (
    "MiniMax Image-01 needs a MiniMax API key. Add it in Settings → Services → MiniMax Image API key "
    "(saved as services.minimax_image_api_key; services.minimax_api_key also works) and submit again."
)
ONE_REFERENCE = "MiniMax Image-01 takes one character reference (the first one); this reference was not sent"
# The fields a remote image model does not use but the shared command contract asks for.
NEUTRAL = {"num_inference_steps": 1, "guidance_scale": 1.0, "seed": -1}
MAX_REFERENCE_BYTES = 20 * 1024 * 1024
REFERENCE_FIELDS = ("image_refs", "image_start", "image_end", "image_guide", "image_mask")
NOT_SENT = {
    "image_end": "MiniMax Image-01 has no end frame; this image was not sent",
    "image_guide": "MiniMax Image-01 has no guide image; this image was not sent",
    "image_mask": "MiniMax Image-01 has no mask; this image was not sent",
}


def is_remote_image_model(model_type: Any) -> bool:
    return isinstance(model_type, str) and model_type.startswith(PREFIX)


def is_remote_image_params(params: Any) -> bool:
    return isinstance(params, Mapping) and is_remote_image_model(params.get("model_type"))


def lane_key() -> str:
    return resource_scheduler.remote_lane("minimax", API_URL).key


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message, "retryable": status >= 500})


def api_key(services: Mapping[str, Any] | None) -> str:
    return resolve_minimax_key(dict(services or {}), "image")


def require_api_key(services: Mapping[str, Any] | None) -> str:
    key = api_key(services)
    if not key:
        raise error(409, "provider_key_missing", KEY_MISSING)
    return key


# ----- catalog: what the pickers, ``models.list`` and the options panel read -----

def catalog_entry(key_set: bool | None = None) -> dict[str, Any]:
    entry = {
        "model_type": MODEL_ID,
        "name": "MiniMax Image-01 (remote, no GPU)",
        "description": ("Remote MiniMax Image-01: no GPU, billed to your MiniMax plan. Needs an API key in Settings → Services. "
                        "Takes one character reference (it keeps the face and invents the outfit)."),
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
            "max_image_refs": 1,
        },
    }
    if key_set is not None:
        entry["api_key_set"] = bool(key_set)
    return entry


def model_options() -> dict[str, Any]:
    return {
        "model_type": MODEL_ID,
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
        # One character picture: the Studio's «character» intent is available and refuses a second reference.
        "image_ref_choices": {
            "choices": [["None", ""], ["The reference is the character (one picture; its face is kept)", "I"]],
            "letters_filter": "I",
            "default": "",
        },
        "max_image_refs": 1,
    }


def defaults() -> dict[str, Any]:
    return {"prompt": "", "resolution": "1024x1024", "image_mode": 1, "generation_mode": "image", **NEUTRAL}


# ----- command: the fields a remote model does not use may be omitted -----

def _input_of(command: Mapping[str, Any]) -> Mapping[str, Any] | None:
    payload = command.get("input")
    if not isinstance(payload, Mapping):
        return None
    params = payload.get("params") if command.get("version") == 2 else payload
    return params if isinstance(params, Mapping) else None


def complete_remote_command(command: Any) -> Any:
    """The command with neutral steps, guidance and seed filled in when it names a remote image model without them.

    Returns the same object when nothing needs filling, so a local model's command is never touched.
    """
    if not isinstance(command, dict) or command.get("operation") != "generation.image":
        return command
    params = _input_of(command)
    if params is None or not is_remote_image_model(params.get("model_type")):
        return command
    missing = {key: value for key, value in NEUTRAL.items() if key not in params}
    if not missing:
        return command
    completed = deepcopy(command)
    target = completed["input"]["params"] if command.get("version") == 2 else completed["input"]
    target.update(missing)
    return completed


# ----- preparation: the checks that must pass before a request is admitted -----

def _reference_error(field: str, index: int, reason: str) -> HTTPException:
    return error(422, "invalid_reference", f"{field}[{index}]: {reason}")


def _reference_values(params: Mapping[str, Any]) -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for field in REFERENCE_FIELDS:
        raw = params.get(field)
        for index, value in enumerate(raw if isinstance(raw, list) else [raw]):
            if isinstance(value, str) and value.strip():
                found.append((field, index, value))
    return found


def _check_file(path: str, field: str, index: int) -> None:
    if not os.path.isfile(path):
        raise _reference_error(field, index, "the picture is not available")
    if os.path.getsize(path) > MAX_REFERENCE_BYTES:
        raise _reference_error(field, index, "the picture is larger than 20 MB")


def _subject_resource(field: str, index: int, value: str, identity: Mapping[str, Any]) -> dict[str, Any]:
    return {"role": "subject_reference", "source_field": field, "index": index, "url": value, **identity,
            "uses": "MiniMax subject_reference (character)"}


def _ignored(field: str, index: int, value: str, reason: str) -> dict[str, Any]:
    return {"role": "ignored_reference", "source_field": field, "index": index, "url": value,
            "reason": f"{field}[{index}]: {reason}"}


def subject_of(params: Mapping[str, Any]) -> tuple[str, int, str] | None:
    """The one reference Image-01 gets: the first image_refs entry, else the start frame."""
    values = _reference_values(params)
    return next((item for item in values if item[0] == "image_refs"), None) or next((i for i in values if i[0] == "image_start"), None)


def ignored_notes(params: Mapping[str, Any]) -> list[str]:
    """What a request names that Image-01 does not take, as receipt notes (the door that has no ``resources`` uses this)."""
    return receipt_notes(_ignored_inputs(params, subject_of(params)))


def _ignored_inputs(params: Mapping[str, Any], subject: tuple[str, int, str] | None) -> list[dict[str, Any]]:
    """Every reference after the first, every frame/guide/mask, a negative prompt and LoRAs: not sent, and said so."""
    notes = []
    for field, index, value in _reference_values(params):
        if (field, index, value) == subject:
            continue
        notes.append(_ignored(field, index, value, NOT_SENT.get(field, ONE_REFERENCE)))
    if str(params.get("negative_prompt") or "").strip():
        notes.append({"role": "ignored_negative_prompt", "reason": "MiniMax Image-01 has no negative prompt; it was not sent"})
    if params.get("activated_loras"):
        notes.append({"role": "ignored_loras", "reason": "MiniMax Image-01 takes no LoRA; they were not sent"})
    return notes


def prepare_remote_image(
    params: Mapping[str, Any],
    *,
    services: Mapping[str, Any] | None,
    resolve: Callable[[str], tuple[str, Mapping[str, Any]]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate one remote image request. Returns the job's parameters and the resources the receipt keeps.

    ``resolve(value)`` turns the first reference into ``(path, identity)``; a request without references needs none.
    Raises ``HTTPException`` (4xx) with a ``code`` and a message that says what to change.
    """
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
    resources: list[dict[str, Any]] = []
    subject = subject_of(params)
    if subject is not None:
        field, index, value = subject
        if resolve is None:
            raise _reference_error(field, index, "this door cannot resolve pictures")
        try:
            path, identity = resolve(value)
        except (ValueError, OSError) as exc:
            raise _reference_error(field, index, str(exc)) from exc
        _check_file(path, field, index)
        resources.append(_subject_resource(field, index, value, identity))
        working["image_refs"] = [path]
    else:
        working.pop("image_refs", None)
    for field in REFERENCE_FIELDS[1:]:
        working.pop(field, None)
    resources.extend(_ignored_inputs(params, subject))
    if len(" ".join(str(params.get("prompt") or "").split())) >= 1500:
        resources.append({"role": "prompt", "reason": "The prompt was shortened to fit Image-01's 1,500 character limit (start and end kept)"})
    working["aspect_ratio"] = aspect_ratio_for_resolution(str(params.get("resolution") or "1024x1024"))
    notes = receipt_notes(resources)
    if notes:
        working["_remote_notes"] = notes
    return working, resources


def legacy_resolver(workspace: str, *, uploads_dir: str, workspace_dir: str) -> Callable[[str], tuple[str, Mapping[str, Any]]]:
    """``resolve`` for a caller that sends an upload or workspace URL (or an old relative name) instead of a prepared command."""
    from services.studio_image_resources import file_identity
    from services.wangp_submission import resolve_wangp_media

    def resolve(value: str) -> tuple[str, Mapping[str, Any]]:
        path = resolve_wangp_media(value, workspace, uploads_dir=uploads_dir, workspace_dir=workspace_dir)
        return path, file_identity(path)

    return resolve


def receipt_notes(resources: Any) -> list[str]:
    """The ``reason`` of every resource that says something was not applied: the receipt shows them as notes."""
    if not isinstance(resources, list):
        return []
    return [str(item["reason"]) for item in resources if isinstance(item, dict) and item.get("reason")]

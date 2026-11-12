"""Validated Meshy generation options and the request bodies built from them.

Only options the Meshy API documents for the current models are accepted; an unknown or
contradictory option is a ``ValueError`` (a 400 for the caller) before any credit is spent.
``lowpoly`` is retired by Meshy on 2026-10-30 and is not offered.

Defaults chosen for HocusPocus: a remeshed mesh of 30000 triangles (a dense mesh is too heavy
for the Video 3D renderer) and, with ``auto_size``, the origin at the bottom.
"""
from __future__ import annotations

from typing import Any

DEFAULT_AI_MODEL = "latest"
STANDARD_MODELS = ("meshy-6-lite", "meshy-6", "meshy-7.1", "latest")
SMART_MODELS = ("meshy-t2", "meshy-t2.5")
SMART_DEFAULT = "meshy-t2.5"
SMART_MAX_POLYCOUNT = {"meshy-t2": 15000, "meshy-t2.5": 30000}
HIGH_GEOMETRY_MODELS = ("meshy-7.1", "latest")
DEFAULT_POLYCOUNT = 30000
MIN_POLYCOUNT, MAX_POLYCOUNT = 100, 300000
MAX_PROMPT_CHARS = 800

# field -> ("choice", allowed values) | ("bool",) | ("int", low, high) | ("text", max chars)
FIELDS: dict[str, tuple] = {
    "pose_mode": ("choice", ("", "a-pose", "t-pose")),
    "ai_model": ("choice", STANDARD_MODELS + SMART_MODELS),
    "model_type": ("choice", ("standard", "smart-topology")),
    "should_remesh": ("bool",),
    "topology": ("choice", ("triangle", "quad")),
    "target_polycount": ("int", MIN_POLYCOUNT, MAX_POLYCOUNT),
    "geometry_resolution": ("choice", ("standard", "2k", "4k")),
    "enable_pbr": ("bool",),
    "texture_resolution": ("choice", ("2k", "4k", "8k")),
    "texture_prompt": ("text", MAX_PROMPT_CHARS),
    "auto_size": ("bool",),
    "origin_at": ("choice", ("bottom", "center")),
}
# What each Meshy request takes besides prompt, image and the ids it needs.
_SHAPE_KEYS = ("pose_mode", "model_type", "topology", "geometry_resolution", "auto_size", "origin_at")
_TEXTURE_KEYS = ("enable_pbr", "texture_resolution", "texture_prompt")
_REFINE_KEYS = ("auto_size", "origin_at") + _TEXTURE_KEYS


def _clean(name: str, value: Any) -> Any:
    kind, *rules = FIELDS[name]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"Meshy option {name} must be true or false")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or not rules[0] <= value <= rules[1]:
            raise ValueError(f"Meshy option {name} must be a whole number from {rules[0]} to {rules[1]}")
        return value
    if kind == "text":
        text = str(value or "").strip()
        if len(text) > rules[0]:
            raise ValueError(f"Meshy option {name} is limited to {rules[0]} characters")
        return text
    if value not in rules[0]:
        allowed = ", ".join(repr(item) if item == "" else str(item) for item in rules[0])
        raise ValueError(f"Meshy option {name} must be one of: {allowed}")
    return value


def _smart_rules(opts: dict[str, Any], model: str) -> None:
    if model not in SMART_MODELS:
        raise ValueError(f"model_type smart-topology needs ai_model {' or '.join(SMART_MODELS)}")
    if opts.get("topology", "triangle") != "triangle":
        raise ValueError("Smart topology produces triangles only")
    if opts.get("should_remesh") is not None:
        raise ValueError("should_remesh does not apply to smart-topology")
    if opts.get("target_polycount", 0) > SMART_MAX_POLYCOUNT[model]:
        raise ValueError(f"target_polycount for {model} is limited to {SMART_MAX_POLYCOUNT[model]}")


def _standard_rules(opts: dict[str, Any], model: str) -> None:
    if model in SMART_MODELS:
        raise ValueError(f"ai_model {model} needs model_type smart-topology")
    if opts.get("should_remesh") is False:
        stray = [name for name in ("topology", "target_polycount") if name in opts]
        if stray:
            raise ValueError(f"{' and '.join(stray)} need should_remesh true")
    if opts.get("geometry_resolution", "standard") != "standard" and model not in HIGH_GEOMETRY_MODELS:
        raise ValueError("geometry_resolution 2k/4k needs ai_model meshy-7.1 or latest")


def normalize_options(options: Any, *, model: str = DEFAULT_AI_MODEL) -> dict[str, Any]:
    """The validated options with defaults applied. ``model`` is the profile's model id."""
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError("meshy options must be an object")
    unknown = sorted(set(options) - set(FIELDS))
    if unknown:
        raise ValueError(f"Unknown Meshy option(s): {', '.join(unknown)}")
    opts = {name: _clean(name, value) for name, value in options.items() if value is not None}
    smart = opts.get("model_type") == "smart-topology"
    chosen = opts.get("ai_model") or (SMART_DEFAULT if smart else str(model or DEFAULT_AI_MODEL))
    if smart:
        _smart_rules(opts, chosen)
    else:
        _standard_rules(opts, chosen)
    if opts.get("texture_resolution", "2k") != "2k" and chosen == "meshy-6-lite":
        raise ValueError("texture_resolution 4k/8k is not available with meshy-6-lite")
    if "origin_at" in opts and not opts.get("auto_size"):
        raise ValueError("origin_at needs auto_size true")
    opts["ai_model"] = chosen
    if not smart:
        opts.setdefault("should_remesh", True)
        if opts["should_remesh"]:
            opts.setdefault("target_polycount", DEFAULT_POLYCOUNT)
    if opts.get("auto_size"):
        opts.setdefault("origin_at", "bottom")
    return opts


def _pick(opts: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: opts[key] for key in keys if opts.get(key) not in (None, "")}


def _mesh_params(opts: dict[str, Any]) -> dict[str, Any]:
    """Geometry parameters: the ones every first request (text preview or image) takes."""
    body = _pick(opts, _SHAPE_KEYS)
    if body.get("geometry_resolution") == "standard":
        del body["geometry_resolution"]   # the default; only meshy-7.1 and latest take the parameter at all
    body["ai_model"] = opts["ai_model"]
    for name in ("should_remesh", "target_polycount"):
        if name in opts:
            body[name] = opts[name]
    return body


def text_preview_body(prompt: str, opts: dict[str, Any]) -> dict[str, Any]:
    return {"mode": "preview", "prompt": prompt, "target_formats": ["glb"], **_mesh_params(opts)}


def text_refine_body(preview_task_id: str, opts: dict[str, Any]) -> dict[str, Any]:
    body = {"mode": "refine", "preview_task_id": preview_task_id, "target_formats": ["glb"], **_pick(opts, _REFINE_KEYS)}
    if opts.get("model_type") != "smart-topology":
        body["ai_model"] = opts["ai_model"]   # a smart-topology preview passes its model on by itself
    return body


def image_body(image_url: str, opts: dict[str, Any]) -> dict[str, Any]:
    return {"image_url": image_url, "target_formats": ["glb"], **_mesh_params(opts), **_pick(opts, _TEXTURE_KEYS)}


def request_options(body: dict[str, Any] | None, model_id: str = "") -> dict[str, Any]:
    """The options of a model3d request body (``body["meshy"]``), validated at submission.

    ``model_id`` is the profile's model; a value that is not a Meshy model name (the provider
    name stands in when the profile has none) means the default model.
    """
    model = str(model_id or "")
    if model != DEFAULT_AI_MODEL and not model.startswith("meshy-"):
        model = DEFAULT_AI_MODEL
    return normalize_options((body or {}).get("meshy"), model=model)


def json_schema() -> dict[str, Any]:
    """The ``meshy`` object of the model3d.generate input, built from the same table that validates it."""
    properties: dict[str, Any] = {}
    for name, (kind, *rules) in FIELDS.items():
        if kind == "choice":
            properties[name] = {"enum": list(rules[0])}
        elif kind == "bool":
            properties[name] = {"type": "boolean"}
        elif kind == "int":
            properties[name] = {"type": "integer", "minimum": rules[0], "maximum": rules[1]}
        else:
            properties[name] = {"type": "string", "maxLength": rules[0]}
    return {
        "type": "object", "additionalProperties": False, "properties": properties,
        "description": (
            "Meshy-only options (provider meshy). Defaults: should_remesh true with target_polycount 30000, "
            "origin_at bottom with auto_size. pose_mode a-pose/t-pose helps a later model3d.rig (engine meshy). "
            "ai_model meshy-6-lite is cheapest; smart-topology needs ai_model meshy-t2 or meshy-t2.5."
        ),
    }

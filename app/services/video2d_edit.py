"""Edit a Video 2D document with small operations. Nothing is saved or rendered.

``add_layer`` camera presets are the ``RECIPE_CAMERA_PRESETS`` table from
``ui/src/lib/sceneRecipe.ts``. M1's JSON catalog should replace that hardcoded
list. Motion preset ids are not accepted until then. Title cues are a Python
port of the defaults in ``ui/src/lib/kineticText/templates.ts``; this module
does not execute the TypeScript ``build()``.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from services.scene_commands import DocumentInput, command_error

OPERATION = "scenes.video2d.edit"
MAX_OPERATIONS = 32
MAX_LAYERS = 500
MAX_TEXTS = 48
MAX_TRACKS = 32
MAX_LYRIC_LINES = 400
_DURABLE_PREFIXES = ("/api/v1/file/", "/api/v1/uploads/", "/examples/")
_BLOCKED_PREFIXES = ("blob:", "file:", "javascript:", "filesystem:", "http://", "https://", "data:", "//")
_VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov", ".m4v", ".mkv"})
_LAYER_TYPES = frozenset({"image", "video", "overlay", "model3d"})
_CURVES = frozenset({"linear", "ease", "dramatic", "bounce", "hold"})
_AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"})
_AUDIO_KINDS = frozenset({"speech", "music", "sfx", "audio"})
_FINISH_PRESET_IDS = ("warmCinema", "oldDoc", "nightNeon", "paperComic")
_FINISH_KEYS = frozenset({"grade", "bloom", "rays", "vignette", "grain", "texture", "letterbox", "applyToTexts"})
_TEXTURES = frozenset({"paper", "film-dust", "scratches"})
_LETTERBOX = {1.85, 2, 2.39}
_LYRIC_MODES = frozenset({"karaoke", "word-pop", "line-fade", "bounce"})
_LYRIC_FONTS = frozenset({"sans", "mono", "display", "condensed", "serif", "hand", "marker"})
_LYRIC_ALIGNS = frozenset({"left", "center", "right"})
_LYRIC_SOURCES = frozenset({"timing-bundle", "srt", "lrc", "manual"})
_TEXT_PRESETS = frozenset({"impact", "rise", "typewriter", "wave"})
_TEXT_FONTS = _LYRIC_FONTS
_TEXT_ALIGNS = _LYRIC_ALIGNS
_TEXT_WEIGHTS = frozenset({400, 500, 600, 700, 800, 900})
_TEXT_ENTERS = frozenset({"none", "fade", "impact", "rise", "drop", "typewriter", "letters", "words", "blur", "wipe", "scale", "slide-left", "slide-right"})
_TEXT_EXITS = frozenset({"none", "fade", "fall", "blur", "wipe", "scale", "slide-left", "slide-right"})
_TEXT_LOOPS = frozenset({"none", "wave", "pulse", "shake", "float", "flicker"})
_TEXT_BOXES = frozenset({"none", "solid", "paper", "pill", "bar", "underline", "plate"})
_TEXT_RANGES = {"x": (0, 100), "y": (0, 100), "size": (2, 25), "rotation": (-45, 45), "maxWidth": (10, 100), "lineHeight": (0.8, 2), "letterSpacing": (-0.1, 0.5)}
_TEXT_ENUMS = {"font": _TEXT_FONTS, "align": _TEXT_ALIGNS, "preset": _TEXT_PRESETS, "loop": _TEXT_LOOPS}
_TEXT_FIELDS = set(_TEXT_RANGES) | set(_TEXT_ENUMS) | {"text", "start", "end", "weight", "uppercase", "italic", "enter", "exit", "box", "counter", "color"}
_POINT_RANGES = {"x": (-50, 150), "y": (-50, 150), "scale": (0.01, 20), "opacity": (0, 1), "rotation": (-180, 180)}
_LAYER_PATCH = frozenset({"name", "source", "visible", "locked", "z", "fill", "type", "transform", "animation"})
_TRANSFORM_KEYS = frozenset({"x", "y", "scale", "opacity", "rotation"})


class Video2dEditError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = 422


def _fail(code: str, message: str) -> None:
    raise Video2dEditError(code, message)


def http_error(code: str, message: str, status: int = 422):
    from fastapi import HTTPException
    return HTTPException(status, {"code": code, "message": message, "retryable": status >= 500, "recoverable": False})


def _warn(warnings: list, code: str, message: str) -> None:
    if any(item.get("code") == code for item in warnings):
        return
    warnings.append({"code": code, "message": message})


def _only(operation: dict, allowed: set[str]) -> None:
    if any(key not in allowed for key in operation):
        _fail("invalid_input", "Unexpected operation fields")


def _number(value, low: float, high: float, code: str, message: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or not low <= value <= high:
        _fail(code, message)
    return value


def _id(value, code: str = "invalid_id") -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 160 or value != value.strip():
        _fail(code, "Ids must be 1..160 characters")
    if any(ord(char) < 32 for char in value):
        _fail(code, "Ids must be 1..160 characters")
    return value


def _source(value) -> str:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= 2000:
        _fail("invalid_source", "Layer source must be a durable workspace or example URL")
    lowered = value.lower()
    path = urlsplit(value).path
    if lowered.startswith(_BLOCKED_PREFIXES) or not lowered.startswith(_DURABLE_PREFIXES):
        _fail("invalid_source", "Layer source must be a durable workspace or example URL")
    if "\\" in path or ".." in path.split("/"):
        _fail("invalid_source", "Layer source must be a durable workspace or example URL")
    return value


def _hex(value, fallback: str | None, code: str = "invalid_input"):
    if isinstance(value, str) and len(value) == 7 and value.startswith("#") and all(char in "0123456789abcdefABCDEF" for char in value[1:]):
        return value
    if fallback is None:
        _fail(code, "Color must be a #rrggbb hex")
    return fallback


def _clamp_num(value, fallback: float, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) == float("inf"):
        return fallback
    return max(low, min(high, float(value)))


def _point(x: float, y: float, scale: float, rotation: float) -> dict:
    return {"x": x, "y": y, "scale": scale, "rotation": rotation}


def _camera(start: dict, end: dict, duration: float, curve: str, shake: dict | None = None) -> dict:
    preset = {"start": start, "end": end, "duration": duration, "spin": False, "curve": curve}
    if shake is not None:
        preset["shake"] = shake
    return preset


# Hardcoded until M1 publishes app/shared/motion_presets.json.
# Values match ui/src/lib/sceneRecipe.ts RECIPE_CAMERA_PRESETS.
CAMERA_PRESETS = {
    "camera-locked": _camera(_point(50, 50, 1, 0), _point(50, 50, 1, 0), 5, "linear"),
    "camera-pan-right": _camera(_point(35, 50, 1, 0), _point(65, 50, 1, 0), 5, "ease"),
    "camera-pan-left": _camera(_point(65, 50, 1, 0), _point(35, 50, 1, 0), 5, "ease"),
    "camera-push-in": _camera(_point(50, 50, 1, 0), _point(50, 50, 1.55, 0), 6, "ease"),
    "camera-pull-out": _camera(_point(50, 50, 1.6, 0), _point(50, 50, 1, 0), 5, "ease"),
    "camera-crane-up": _camera(_point(50, 68, 1.15, 0), _point(50, 34, 1, 0), 5, "ease"),
    "camera-dutch-drift": _camera(_point(44, 54, 1.05, -6), _point(57, 46, 1.28, 7), 6, "ease"),
    "camera-handheld": _camera(_point(50, 50, 1.08, 0), _point(51, 49, 1.12, 0.6), 6, "ease", {"amount": 0.75, "frequency": 3.2, "seed": 1.7}),
    "camera-whip-pan": _camera(_point(28, 50, 1.18, -2), _point(72, 50, 1.05, 2), 1.1, "dramatic", {"amount": 0.35, "frequency": 7, "seed": 3.1}),
    "camera-dolly": _camera(_point(36, 57, 1.5, -2), _point(58, 46, 0.92, 0), 5.5, "ease"),
}

FINISH_PRESETS = {
    "warmCinema": {"grade": {"exposure": 0.05, "contrast": 0.12, "saturation": 0.08, "temperature": 0.25, "tint": 0.04, "fade": 0.08}, "vignette": {"amount": 0.35, "softness": 0.6}, "letterbox": {"ratio": 2.39, "color": "#000000"}},
    "oldDoc": {"grade": {"exposure": -0.04, "contrast": 0.18, "saturation": -0.35, "temperature": 0.2, "tint": 0.08, "fade": 0.16}, "grain": {"amount": 0.28, "size": 1.4}, "texture": {"kind": "scratches", "amount": 0.2}},
    "nightNeon": {"grade": {"exposure": 0.02, "contrast": 0.2, "saturation": 0.25, "temperature": -0.15, "tint": 0.2, "fade": 0}, "bloom": {"amount": 0.45, "threshold": 0.55, "radius": 0.5}},
    "paperComic": {"grade": {"exposure": 0.04, "contrast": 0.08, "saturation": -0.1, "temperature": 0.12, "tint": 0, "fade": 0.05}, "texture": {"kind": "paper", "amount": 0.45}},
}

_TITLE_DEFAULTS = {
    "lower-third-date": {"date": "1991", "caption": "A city keeps its name"},
    "chorus-banner": {"line": "The bird is freed"},
    "title-card": {"title": "Musktopia", "subtitle": ""},
    "end-card": {"title": "Coming soon", "cta": "@studio"},
    "year-counter": {"from": "1990", "to": "2000", "label": "Year"},
    "quote": {"quote": "Keep the line.", "author": ""},
    "trailer-slam": {"lines": "One|Two|Three"},
    "chapter": {"kicker": "CHAPTER", "title": "One"},
    "social-caption": {"caption": "Read this"},
}


def _ensure_document(document: dict) -> None:
    try:
        DocumentInput(document=document)
    except (ValidationError, ValueError, TypeError) as error:
        _fail("invalid_document", command_error(error))
    if "slots" in document or not isinstance(document.get("layers"), list):
        _fail("invalid_document", "Choose a Video 2D scene with layers")


def _copy_document(raw) -> dict:
    if not isinstance(raw, dict):
        _fail("invalid_document", "Use a version 1 Video 2D document")
    document = deepcopy(raw)
    _ensure_document(document)
    return document


def _payload(command) -> dict:
    if not isinstance(command, dict):
        _fail("invalid_command", "Use version 1 with input")
    keys = set(command)
    if keys == {"version", "operation", "input"} and command.get("operation") != OPERATION:
        _fail("invalid_command", "Use scenes.video2d.edit")
    if keys not in ({"version", "input"}, {"version", "operation", "input"}):
        _fail("invalid_command", "Use version 1 with input")
    if type(command.get("version")) is not int or command.get("version") != 1:
        _fail("invalid_command", "Use version 1")
    data = command.get("input")
    if not isinstance(data, dict) or set(data) != {"document", "operations"}:
        _fail("invalid_command", "input must include document and operations only")
    return data


def _operation_list(raw) -> list:
    if not isinstance(raw, list):
        _fail("invalid_command", "operations must be a list")
    if len(raw) > MAX_OPERATIONS:
        _fail("too_many_operations", "At most 32 operations")
    return raw


def _find(items: list, identity: str) -> dict | None:
    for item in items:
        if isinstance(item, dict) and item.get("id") == identity:
            return item
    return None


def _layer_type(source: str, explicit) -> str:
    if explicit is None:
        suffix = Path(urlsplit(source).path).suffix.lower()
        return "video" if suffix in _VIDEO_EXTENSIONS else "image"
    if explicit not in _LAYER_TYPES:
        _fail("invalid_input", "Layer type must be image, video, overlay or model3d")
    return explicit


def _static_motion(scene_duration: float) -> tuple[dict, dict]:
    start = {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0}
    return dict(start), {"start": dict(start), "end": dict(start), "duration": scene_duration, "curve": "linear", "spin": False}


def _preset_motion(preset_id, scene_duration: float, warnings: list) -> tuple[dict, dict]:
    if not isinstance(preset_id, str):
        _fail("invalid_input", "preset must be a camera preset id")
    preset = CAMERA_PRESETS.get(preset_id)
    if preset is None:
        _fail("unknown_preset", "Unknown camera preset. Motion presets wait for the M1 JSON catalog.")
    start = dict(preset["start"])
    end = dict(preset["end"])
    duration = preset["duration"]
    if duration > scene_duration:
        duration = scene_duration
        _warn(warnings, "preset_duration_clamped", "Preset duration was limited to the scene duration")
    animation = {"start": start, "end": end, "duration": duration, "curve": preset["curve"], "spin": False}
    if "shake" in preset:
        animation["shake"] = dict(preset["shake"])
    transform = {"x": start["x"], "y": start["y"], "scale": start["scale"], "opacity": start.get("opacity", 1), "rotation": start.get("rotation", 0)}
    return transform, animation


def _next_z(layers: list):
    highest = 0
    for layer in layers:
        value = layer.get("z") if isinstance(layer, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > highest:
            highest = value
    return highest + 10 if layers else 0


def _build_layer(document: dict, operation: dict, warnings: list) -> dict:
    if "id" not in operation or "source" not in operation:
        _fail("invalid_input", "add_layer needs id and source")
    identity = _id(operation["id"])
    source = _source(operation["source"])
    kind = _layer_type(source, operation.get("type"))
    name = operation.get("name", identity)
    if not isinstance(name, str) or not 1 <= len(name) <= 120:
        _fail("invalid_input", "Layer name must be 1..120 characters")
    if "preset" in operation:
        transform, animation = _preset_motion(operation["preset"], document["duration"], warnings)
    else:
        transform, animation = _static_motion(document["duration"])
    z = operation.get("z", None)
    if "z" in operation:
        z = _number(operation["z"], -10000, 10000, "invalid_input", "Layer z is out of range")
    else:
        z = _next_z(document["layers"])
    return {"id": identity, "name": name, "type": kind, "source": source, "visible": True, "z": z, "transform": transform, "animation": animation}


def _add_layer(document: dict, operation: dict, warnings: list) -> None:
    _only(operation, {"op", "id", "source", "preset", "name", "type", "z"})
    layer = _build_layer(document, operation, warnings)
    layers = document["layers"]
    for index, current in enumerate(layers):
        if current.get("id") == layer["id"]:
            if "z" not in operation:
                layer["z"] = current.get("z", layer["z"])
            layers[index] = layer
            return
    if len(layers) >= MAX_LAYERS:
        _fail("limit_exceeded", "Maximum 500 layers")
    layers.append(layer)


def _animation_point(value) -> dict:
    if not isinstance(value, dict) or any(key not in _POINT_RANGES for key in value) or any(key not in value for key in ("x", "y", "scale")):
        _fail("invalid_input", "Animation point needs x, y and scale")
    return {key: _number(value[key], *_POINT_RANGES[key], "invalid_input", "Animation point is out of range") for key in value}


def _shake(value) -> dict:
    if not isinstance(value, dict) or any(key not in {"amount", "frequency", "seed"} for key in value) or "amount" not in value or "frequency" not in value:
        _fail("invalid_input", "Camera shake needs amount and frequency")
    shake = {
        "amount": _number(value["amount"], 0, 20, "invalid_input", "Camera shake is out of range"),
        "frequency": _number(value["frequency"], 0, 30, "invalid_input", "Camera shake is out of range"),
    }
    if "seed" in value:
        shake["seed"] = _number(value["seed"], -1000000, 1000000, "invalid_input", "Camera shake is out of range")
    return shake


def _merge_transform(layer: dict, patch) -> None:
    current = layer.get("transform")
    if not isinstance(current, dict) or not isinstance(patch, dict) or not patch or any(key not in _TRANSFORM_KEYS for key in patch):
        _fail("invalid_input", "Layer transform patch is invalid")
    for key, bounds in _POINT_RANGES.items():
        if key in patch:
            current[key] = _number(patch[key], bounds[0], bounds[1], "invalid_input", "Transform is out of range")


def _patch_anim_duration(current: dict, patch: dict, scene_duration: float) -> None:
    if "duration" not in patch:
        return
    duration = _number(patch["duration"], 0.001, 600, "invalid_input", "Animation duration is out of range")
    if duration - scene_duration > 1e-6:
        _fail("timing_exceeds_duration", "Animation duration exceeds the scene duration")
    current["duration"] = duration


def _patch_curve(current: dict, patch: dict) -> None:
    if "curve" not in patch:
        return
    if patch["curve"] not in _CURVES:
        _fail("invalid_input", "Unknown animation curve")
    current["curve"] = patch["curve"]


def _patch_spin(current: dict, patch: dict) -> None:
    if "spin" not in patch:
        return
    if not isinstance(patch["spin"], bool):
        _fail("invalid_input", "spin must be boolean")
    current["spin"] = patch["spin"]


def _merge_animation(layer: dict, patch, scene_duration: float) -> None:
    current = layer.get("animation")
    allowed = {"start", "end", "duration", "curve", "spin", "shake"}
    if not isinstance(current, dict) or not isinstance(patch, dict) or not patch or any(key not in allowed for key in patch):
        _fail("invalid_input", "Layer animation patch is invalid")
    if "start" in patch:
        current["start"] = _animation_point(patch["start"])
    if "end" in patch:
        current["end"] = _animation_point(patch["end"])
    _patch_anim_duration(current, patch, scene_duration)
    _patch_curve(current, patch)
    _patch_spin(current, patch)
    if "shake" in patch:
        current["shake"] = _shake(patch["shake"])


def _patch_layer_name(layer: dict, patch: dict) -> None:
    if "name" not in patch:
        return
    if not isinstance(patch["name"], str) or not 1 <= len(patch["name"]) <= 120:
        _fail("invalid_input", "Layer name must be 1..120 characters")
    layer["name"] = patch["name"]


def _patch_layer_flags(layer: dict, patch: dict) -> None:
    for key in ("visible", "locked", "fill"):
        if key not in patch:
            continue
        if not isinstance(patch[key], bool):
            _fail("invalid_input", f"{key} must be boolean")
        layer[key] = patch[key]


def _apply_layer_patch(layer: dict, patch: dict, scene_duration: float) -> None:
    if not patch or any(key not in _LAYER_PATCH for key in patch):
        _fail("invalid_input", "update_layer patch has unsupported fields")
    _patch_layer_name(layer, patch)
    if "source" in patch:
        layer["source"] = _source(patch["source"])
    if "type" in patch:
        layer["type"] = _layer_type(layer.get("source") or "", patch["type"])
    _patch_layer_flags(layer, patch)
    if "z" in patch:
        layer["z"] = _number(patch["z"], -10000, 10000, "invalid_input", "Layer z is out of range")
    if "transform" in patch:
        _merge_transform(layer, patch["transform"])
    if "animation" in patch:
        _merge_animation(layer, patch["animation"], scene_duration)


def _update_layer(document: dict, operation: dict, warnings: list) -> None:
    del warnings
    _only(operation, {"op", "id", "patch"})
    layer = _find(document["layers"], _id(operation.get("id")))
    if layer is None or not isinstance(operation.get("patch"), dict):
        _fail("not_found" if layer is None else "invalid_input", "Layer was not found" if layer is None else "update_layer needs a patch")
    _apply_layer_patch(layer, operation["patch"], document["duration"])


def _remove_layer(document: dict, operation: dict, warnings: list) -> None:
    del warnings
    _only(operation, {"op", "id"})
    identity = _id(operation.get("id"))
    layers = document["layers"]
    if _find(layers, identity) is None:
        _fail("not_found", "Layer was not found")
    document["layers"] = [layer for layer in layers if layer.get("id") != identity]


def _reorder(document: dict, operation: dict, warnings: list) -> None:
    del warnings
    _only(operation, {"op", "ids"})
    ids = operation.get("ids")
    layers = document["layers"]
    current = [layer.get("id") for layer in layers]
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
        _fail("invalid_reorder", "Reorder ids must be a permutation of the layer ids")
    if len(ids) != len(current) or len(set(ids)) != len(ids) or set(ids) != set(current):
        _fail("invalid_reorder", "Reorder ids must be a permutation of the layer ids")
    by_id = {layer["id"]: layer for layer in layers}
    document["layers"] = [by_id[item] for item in ids]


def _cue(cue_id: str, text: str, frame: dict, extra: dict) -> dict:
    cue = {"id": cue_id, "text": text, "start": frame["start"], "end": frame["start"] + frame["duration"], "preset": "impact", "x": 50, "y": 80, "size": 8, "color": "#fff6e8", "rotation": 0}
    cue.update(extra)
    return cue


def _field(fields: dict, key: str) -> str:
    if key not in fields or fields[key] is None:
        return ""
    value = fields[key]
    if isinstance(value, str):
        text = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(value)
    else:
        _fail("invalid_input", "Title fields must be strings")
    if len(text) > 240:
        _fail("invalid_input", "Title field exceeds 240 characters")
    return text


def _vertical(frame: dict) -> bool:
    return frame["height"] > frame["width"]


def _lower_third(fields: dict, frame: dict) -> list:
    y = 72 if _vertical(frame) else 78
    return [
        _cue("date", _field(fields, "date") or "1991", frame, {"y": y - 8, "size": 14, "font": "display", "weight": 400, "align": "left", "x": 12, "enter": {"preset": "slide-right", "duration": 0.45}, "box": {"kind": "bar", "color": "#e85d4c", "opacity": 1, "padding": 0.2}}),
        _cue("caption", _field(fields, "caption") or "", frame, {"y": y, "size": 5, "font": "condensed", "x": 12, "align": "left", "enter": {"preset": "fade", "duration": 0.4}}),
    ]


def _chorus(fields: dict, frame: dict) -> list:
    return [_cue("chorus", _field(fields, "line") or "", frame, {"font": "marker", "y": 62 if _vertical(frame) else 48, "enter": {"preset": "words", "duration": 1.1}, "loop": "pulse", "box": {"kind": "paper", "color": "#f4e7cf", "opacity": 0.94, "padding": 0.4}, "color": "#2a2118"})]


def _title_card(fields: dict, frame: dict) -> list:
    cues = [_cue("title", _field(fields, "title") or "", frame, {"font": "display", "weight": 400, "size": 16, "y": 46, "enter": {"preset": "blur", "duration": 0.7}, "box": {"kind": "plate", "color": "#07080d", "opacity": 1, "padding": 0}})]
    subtitle = _field(fields, "subtitle")
    if subtitle:
        cues.append(_cue("sub", subtitle, frame, {"y": 62, "size": 5, "font": "serif", "enter": {"preset": "fade", "duration": 0.5}}))
    return cues


def _end_card(fields: dict, frame: dict) -> list:
    return [
        _cue("end", _field(fields, "title") or "", frame, {"font": "display", "weight": 400, "size": 12, "y": 44}),
        _cue("cta", _field(fields, "cta") or "", frame, {"y": 60, "size": 5, "font": "sans"}),
    ]


def _js_number(text: str):
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return 0
    if value != value or abs(value) == float("inf"):
        return 0
    if value == int(value) and abs(value) < 1e15:
        return int(value)
    return value


def _year_counter(fields: dict, frame: dict) -> list:
    cues = [_cue("count", "{value}", frame, {"font": "display", "weight": 400, "size": 18, "y": 42, "counter": {"from": _js_number(_field(fields, "from")), "to": _js_number(_field(fields, "to")), "decimals": 0, "ease": "ease"}})]
    label = _field(fields, "label")
    if label:
        cues.append(_cue("label", label, frame, {"y": 62, "size": 5, "font": "condensed"}))
    return cues


def _quote(fields: dict, frame: dict) -> list:
    width = 78 if _vertical(frame) else 60
    cues = [_cue("quote", "\u201c" + (_field(fields, "quote") or "") + "\u201d", frame, {"font": "serif", "italic": True, "size": 7, "y": 46, "maxWidth": width, "enter": {"preset": "typewriter", "duration": 1.4}})]
    author = _field(fields, "author")
    if author:
        cues.append(_cue("author", author, frame, {"y": 64, "size": 4, "font": "sans"}))
    return cues


def _trailer(fields: dict, frame: dict) -> list:
    lines = [line.strip() for line in (_field(fields, "lines") or "").split("|") if line.strip()][:8]
    if not lines:
        return []
    each = frame["duration"] / len(lines)
    cues = []
    for index, line in enumerate(lines):
        sliced = {**frame, "start": frame["start"] + each * index, "duration": each}
        cues.append(_cue(f"slam-{index + 1}", line, sliced, {"font": "display", "weight": 400, "size": 14, "y": 50, "enter": {"preset": "impact", "duration": 0.18}, "box": {"kind": "plate", "color": "#000000", "opacity": 1, "padding": 0}}))
    return cues


def _chapter(fields: dict, frame: dict) -> list:
    return [
        _cue("kicker", (_field(fields, "kicker") or "").upper(), frame, {"y": 40, "size": 3, "font": "condensed", "uppercase": True, "letterSpacing": 0.2}),
        _cue("chapter", _field(fields, "title") or "", frame, {"y": 50, "size": 12, "font": "display", "weight": 400}),
    ]


def _social(fields: dict, frame: dict) -> list:
    tall = _vertical(frame)
    return [_cue("social", _field(fields, "caption") or "", frame, {"y": 72 if tall else 84, "size": 4.5, "maxWidth": 76 if tall else 70, "font": "sans", "box": {"kind": "pill", "color": "#11131a", "opacity": 0.82, "padding": 0.45, "radius": 0.8}})]


_TITLE_BUILDERS = {
    "lower-third-date": _lower_third,
    "chorus-banner": _chorus,
    "title-card": _title_card,
    "end-card": _end_card,
    "year-counter": _year_counter,
    "quote": _quote,
    "trailer-slam": _trailer,
    "chapter": _chapter,
    "social-caption": _social,
}


def _merged_fields(template: str, operation: dict) -> dict:
    if "fields" not in operation or operation["fields"] is None:
        provided = {}
    else:
        provided = operation["fields"]
    if not isinstance(provided, dict):
        _fail("invalid_input", "Title fields must be an object")
    if any(key not in _TITLE_DEFAULTS[template] for key in provided):
        _fail("invalid_input", "Unknown title fields")
    merged = dict(_TITLE_DEFAULTS[template])
    merged.update(provided)
    return merged


def _frame(document: dict, start, duration, warnings: list) -> dict:
    width = document.get("width")
    height = document.get("height")
    usable = isinstance(width, (int, float)) and not isinstance(width, bool) and isinstance(height, (int, float)) and not isinstance(height, bool) and width > 0 and height > 0
    if not usable:
        _warn(warnings, "format_assumed", "Title layout assumed 1280x720 because width or height was missing")
        width, height = 1280, 720
    return {"start": start, "duration": duration, "width": int(width), "height": int(height)}


def _time_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        _fail("invalid_input", "Title start and duration must be numbers")
    return value


def _span(operation: dict, scene_duration: float) -> tuple[float, float]:
    start = _time_number(operation.get("start"))
    duration = _time_number(operation.get("duration"))
    if start < 0 or duration <= 0 or start >= 600 or duration > 600:
        _fail("invalid_input", "Title start and duration are out of range")
    if start + duration - scene_duration > 1e-6:
        _fail("timing_exceeds_duration", "Title timing exceeds the scene duration")
    return start, duration


def _tag_cues(cues: list, template: str, prefix) -> list:
    tagged = []
    for cue in cues:
        local = f"{prefix}-{cue['id']}" if prefix else cue["id"]
        if not 1 <= len(local) <= 160:
            _fail("invalid_id", "Ids must be 1..160 characters")
        tagged.append({**cue, "id": local, "template": template})
    return tagged


def _text_items(document: dict) -> list:
    current = document.get("texts")
    if current is None:
        return []
    if not isinstance(current, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in current):
        _fail("invalid_document", "texts must be a list of cues with ids")
    return current


def _store_named(document: dict, key: str, items: list) -> None:
    if items:
        document[key] = items
    else:
        document.pop(key, None)


def _upsert(document: dict, key: str, items: list, limit: int, label: str) -> None:
    current = _text_items(document) if key == "texts" else _track_items(document)
    order = [item["id"] for item in current]
    entries = {item["id"]: item for item in current}
    for item in items:
        if item["id"] not in entries:
            order.append(item["id"])
        entries[item["id"]] = item
    if len(order) > limit:
        _fail("limit_exceeded", f"Maximum {limit} {label}")
    _store_named(document, key, [entries[item] for item in order])


def _add_title(document: dict, operation: dict, warnings: list) -> None:
    _only(operation, {"op", "template", "fields", "start", "duration", "id"})
    template = operation.get("template")
    builder = _TITLE_BUILDERS.get(template)
    if builder is None:
        _fail("unknown_template", "Unknown text template")
    prefix = _id(operation["id"]) if "id" in operation else ""
    start, duration = _span(operation, document["duration"])
    cues = builder(_merged_fields(template, operation), _frame(document, start, duration, warnings))
    if not cues:
        _fail("invalid_input", "Template produced no text cues")
    _upsert(document, "texts", _tag_cues(cues, template, prefix), MAX_TEXTS, "text cues")


def _patch_text_ranges(cue: dict, patch: dict) -> None:
    for key, (low, high) in _TEXT_RANGES.items():
        if key in patch:
            cue[key] = _number(patch[key], low, high, "invalid_input", "Text field is out of range")


def _patch_text_enums(cue: dict, patch: dict) -> None:
    for key, allowed in _TEXT_ENUMS.items():
        if key not in patch:
            continue
        if patch[key] not in allowed:
            _fail("invalid_input", "Text field is not an allowed value")
        cue[key] = patch[key]


def _text_span(value, allowed: frozenset, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != {"preset", "duration"} or value.get("preset") not in allowed:
        _fail("invalid_input", f"{label} needs a known preset and duration")
    return {"preset": value["preset"], "duration": _number(value["duration"], 0.05, 3, "invalid_input", f"{label} duration is out of range")}


def _text_box(value) -> dict:
    if not isinstance(value, dict) or any(key not in {"kind", "color", "opacity", "padding", "radius"} for key in value):
        _fail("invalid_input", "Text box is invalid")
    if any(key not in value for key in ("kind", "color", "opacity", "padding")) or value.get("kind") not in _TEXT_BOXES:
        _fail("invalid_input", "Text box needs kind, color, opacity and padding")
    box = {"kind": value["kind"], "color": _hex(value["color"], None), "opacity": _number(value["opacity"], 0, 1, "invalid_input", "Text box is out of range"), "padding": _number(value["padding"], 0, 4, "invalid_input", "Text box is out of range")}
    if "radius" in value:
        box["radius"] = _number(value["radius"], 0, 2, "invalid_input", "Text box is out of range")
    return box


def _text_counter(value) -> dict:
    if not isinstance(value, dict) or set(value) != {"from", "to", "decimals", "ease"} or value.get("ease") not in {"linear", "ease"}:
        _fail("invalid_input", "Text counter is invalid")
    if isinstance(value.get("from"), bool) or isinstance(value.get("to"), bool) or not isinstance(value.get("from"), (int, float)) or not isinstance(value.get("to"), (int, float)):
        _fail("invalid_input", "Text counter is invalid")
    return {"from": value["from"], "to": value["to"], "decimals": int(_number(value["decimals"], 0, 4, "invalid_input", "Text counter is invalid")), "ease": value["ease"]}


def _patch_text_words(cue: dict, patch: dict) -> None:
    if "text" in patch:
        if not isinstance(patch["text"], str) or len(patch["text"]) > 240:
            _fail("invalid_input", "Text must be at most 240 characters")
        cue["text"] = patch["text"]
    if "color" in patch:
        cue["color"] = _hex(patch["color"], None)
    if "weight" not in patch:
        return
    if patch["weight"] not in _TEXT_WEIGHTS:
        _fail("invalid_input", "Text weight is not allowed")
    cue["weight"] = patch["weight"]


def _patch_text_flags(cue: dict, patch: dict) -> None:
    for key in ("uppercase", "italic"):
        if key not in patch:
            continue
        if not isinstance(patch[key], bool):
            _fail("invalid_input", f"{key} must be boolean")
        cue[key] = patch[key]


def _patch_text_nested(cue: dict, patch: dict) -> None:
    if "enter" in patch:
        cue["enter"] = _text_span(patch["enter"], _TEXT_ENTERS, "Text enter")
    if "exit" in patch:
        cue["exit"] = _text_span(patch["exit"], _TEXT_EXITS, "Text exit")
    if "box" in patch:
        cue["box"] = _text_box(patch["box"])
    if "counter" in patch:
        cue["counter"] = _text_counter(patch["counter"])


def _apply_text_patch(cue: dict, patch: dict, scene_duration: float) -> None:
    if not isinstance(patch, dict) or not patch or any(key not in _TEXT_FIELDS for key in patch):
        _fail("invalid_input", "update_text patch has unsupported fields")
    _patch_text_words(cue, patch)
    _patch_text_flags(cue, patch)
    _patch_text_ranges(cue, patch)
    _patch_text_enums(cue, patch)
    _patch_text_nested(cue, patch)
    _patch_text_time(cue, patch, scene_duration)


def _patch_text_time(cue: dict, patch: dict, scene_duration: float) -> None:
    start = _number(patch["start"], 0, 600, "invalid_input", "Text start is out of range") if "start" in patch else cue.get("start", 0)
    end = _number(patch["end"], 0, 600, "invalid_input", "Text end is out of range") if "end" in patch else cue.get("end", start)
    if end <= start:
        _fail("invalid_input", "Text end must be later than start")
    if end - scene_duration > 1e-6:
        _fail("timing_exceeds_duration", "Text timing exceeds the scene duration")
    cue["start"] = start
    cue["end"] = end


def _update_text(document: dict, operation: dict, warnings: list) -> None:
    del warnings
    _only(operation, {"op", "id", "patch"})
    cue = _find(_text_items(document), _id(operation.get("id")))
    if cue is None or not isinstance(operation.get("patch"), dict):
        _fail("not_found" if cue is None else "invalid_input", "Text cue was not found" if cue is None else "update_text needs a patch")
    _apply_text_patch(cue, operation["patch"], document["duration"])


def _remove_text(document: dict, operation: dict, warnings: list) -> None:
    del warnings
    _only(operation, {"op", "id"})
    identity = _id(operation.get("id"))
    items = _text_items(document)
    if _find(items, identity) is None:
        _fail("not_found", "Text cue was not found")
    _store_named(document, "texts", [item for item in items if item.get("id") != identity])


def _section(value, label: str):
    if value is None:
        return None
    if not isinstance(value, dict):
        _fail("invalid_finish", f"{label} must be an object")
    return value


def _grade(raw) -> dict | None:
    section = _section(raw, "grade")
    if section is None:
        return None
    grade = {key: _clamp_num(section.get(key), 0, -1, 1) for key in ("exposure", "contrast", "saturation", "temperature", "tint")}
    grade["fade"] = _clamp_num(section.get("fade"), 0, 0, 1)
    if section.get("beatFlash") is not None:
        grade["beatFlash"] = _clamp_num(section.get("beatFlash"), 0, 0, 1)
    return grade


def _bloom(raw) -> dict | None:
    section = _section(raw, "bloom")
    if section is None:
        return None
    bloom = {"amount": _clamp_num(section.get("amount"), 0, 0, 1), "threshold": _clamp_num(section.get("threshold"), 0.6, 0, 1), "radius": _clamp_num(section.get("radius"), 0.4, 0, 1)}
    if section.get("beat") is not None:
        bloom["beat"] = _clamp_num(section.get("beat"), 0, 0, 1)
    return bloom


def _rays(raw) -> dict | None:
    section = _section(raw, "rays")
    if section is None:
        return None
    return {"amount": _clamp_num(section.get("amount"), 0, 0, 1), "x": _clamp_num(section.get("x"), 50, 0, 100), "y": _clamp_num(section.get("y"), 30, 0, 100), "length": _clamp_num(section.get("length"), 0.5, 0, 1), "threshold": _clamp_num(section.get("threshold"), 0.7, 0, 1)}


def _vignette(raw) -> dict | None:
    section = _section(raw, "vignette")
    if section is None:
        return None
    return {"amount": _clamp_num(section.get("amount"), 0, 0, 1), "softness": _clamp_num(section.get("softness"), 0.5, 0, 1)}


def _grain(raw) -> dict | None:
    section = _section(raw, "grain")
    if section is None:
        return None
    return {"amount": _clamp_num(section.get("amount"), 0, 0, 1), "size": _clamp_num(section.get("size"), 1, 0.5, 4)}


def _texture(raw) -> dict | None:
    section = _section(raw, "texture")
    if section is None or section.get("kind") not in _TEXTURES:
        return None
    return {"kind": section["kind"], "amount": _clamp_num(section.get("amount"), 0, 0, 1)}


def _letterbox(raw) -> dict | None:
    section = _section(raw, "letterbox")
    if section is None or section.get("ratio") not in _LETTERBOX:
        return None
    return {"ratio": section["ratio"], "color": _hex(section.get("color"), "#000000")}


def _parse_finish(raw) -> dict:
    if not isinstance(raw, dict) or any(key not in _FINISH_KEYS for key in raw):
        _fail("invalid_finish", "Finish values are not valid")
    finish = {}
    for key, parser in (("grade", _grade), ("bloom", _bloom), ("rays", _rays), ("vignette", _vignette), ("grain", _grain), ("texture", _texture), ("letterbox", _letterbox)):
        parsed = parser(raw.get(key))
        if parsed:
            finish[key] = parsed
    if raw.get("applyToTexts") is True:
        finish["applyToTexts"] = True
    if not finish:
        _fail("invalid_finish", "Finish values are not valid")
    return finish


def _set_finish(document: dict, operation: dict, warnings: list) -> None:
    del warnings
    _only(operation, {"op", "preset", "finish"})
    has_preset = "preset" in operation
    has_finish = "finish" in operation
    if has_preset == has_finish:
        _fail("invalid_finish", "Use a finish preset or raw finish values, not both")
    if has_preset:
        preset = operation["preset"]
        if preset not in FINISH_PRESETS:
            _fail("unknown_preset", "Unknown finish preset")
        document["finish"] = deepcopy(FINISH_PRESETS[preset])
        return
    document["finish"] = _parse_finish(operation["finish"])


def _lyric_style(raw) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or any(key not in {"font", "size", "color", "activeColor", "weight", "x", "y", "maxWidth", "align", "uppercase", "visibleLines", "beatPulse"} for key in raw):
        _fail("invalid_lyrics", "Lyric style has unsupported fields")
    style = {
        "font": raw.get("font", "sans"),
        "size": raw.get("size", 7),
        "color": raw.get("color", "#f4efe6"),
        "activeColor": raw.get("activeColor", "#ffe08a"),
        "x": raw.get("x", 50),
        "y": raw.get("y", 78),
        "maxWidth": raw.get("maxWidth", 80),
        "align": raw.get("align", "center"),
        "visibleLines": raw.get("visibleLines", 1),
    }
    if style["font"] not in _LYRIC_FONTS or style["align"] not in _LYRIC_ALIGNS or style["visibleLines"] not in (1, 2):
        _fail("invalid_lyrics", "Lyric style is not valid")
    style["size"] = _number(style["size"], 2, 25, "invalid_lyrics", "Lyric size is out of range")
    style["x"] = _number(style["x"], 0, 100, "invalid_lyrics", "Lyric position is out of range")
    style["y"] = _number(style["y"], 0, 100, "invalid_lyrics", "Lyric position is out of range")
    style["maxWidth"] = _number(style["maxWidth"], 10, 100, "invalid_lyrics", "Lyric width is out of range")
    style["color"] = _hex(style["color"], None, "invalid_lyrics")
    style["activeColor"] = _hex(style["activeColor"], None, "invalid_lyrics")
    if "weight" in raw:
        style["weight"] = _number(raw["weight"], 400, 900, "invalid_lyrics", "Lyric weight is out of range")
    if raw.get("uppercase") is True:
        style["uppercase"] = True
    elif "uppercase" in raw and raw["uppercase"] is not False:
        _fail("invalid_lyrics", "Lyric uppercase must be boolean")
    if "beatPulse" in raw:
        style["beatPulse"] = _number(raw["beatPulse"], 0, 1, "invalid_lyrics", "Lyric beat pulse is out of range")
    return style


def _split_words(text: str, start: float, end: float) -> list:
    parts = [part for part in text.split() if part]
    if not parts or len(parts) > 80:
        _fail("invalid_lyrics", "A lyric line needs at most 80 words")
    weight = sum(max(1, len(part)) for part in parts)
    cursor = start
    words = []
    for part in parts:
        size = (end - start) * (max(1, len(part)) / weight)
        words.append({"text": part, "start": cursor, "end": cursor + size})
        cursor += size
    return words


def _given_words(words) -> list:
    if not isinstance(words, list) or not words or len(words) > 80:
        _fail("invalid_lyrics", "Lyric words must be a short list")
    cleaned = []
    for word in words:
        if not isinstance(word, dict) or not isinstance(word.get("text"), str) or not word["text"].strip() or len(word["text"]) > 80:
            _fail("invalid_lyrics", "Each lyric word needs text")
        start = _number(word.get("start"), 0, 36000, "invalid_lyrics", "Lyric word timing is out of range")
        end = _number(word.get("end"), 0, 36000, "invalid_lyrics", "Lyric word timing is out of range")
        if end <= start or any(key not in {"text", "start", "end"} for key in word):
            _fail("invalid_lyrics", "Lyric word timing is out of range")
        cleaned.append({"text": word["text"], "start": start, "end": end})
    return cleaned


def _lyric_line(raw, index: int, seen: set[str]) -> dict:
    if not isinstance(raw, dict) or any(key not in {"id", "start", "end", "text", "words"} for key in raw) or "start" not in raw or "end" not in raw:
        _fail("invalid_lyrics", "Each lyric line needs start and end")
    start = _number(raw["start"], 0, 36000, "invalid_lyrics", "Lyric line timing is out of range")
    end = _number(raw["end"], 0, 36000, "invalid_lyrics", "Lyric line timing is out of range")
    if end <= start:
        _fail("invalid_lyrics", "Lyric line end must be later than start")
    identity = _id(raw["id"]) if raw.get("id") else f"line-{index + 1}"
    if identity in seen:
        _fail("invalid_lyrics", "Lyric line ids must be unique")
    seen.add(identity)
    if "words" in raw and raw["words"] is not None:
        words = _given_words(raw["words"])
    else:
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            _fail("invalid_lyrics", "Each lyric line needs text")
        words = _split_words(text.strip(), start, end)
    return {"id": identity, "start": start, "end": end, "words": words}


def _lyric_source(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or any(key not in {"kind", "file"} for key in raw) or raw.get("kind") not in _LYRIC_SOURCES:
        _fail("invalid_lyrics", "Lyric source kind must be timing-bundle, srt, lrc or manual")
    source = {"kind": raw["kind"]}
    if "file" not in raw:
        return source
    label = raw["file"]
    if not isinstance(label, str) or not label or len(label) > 200 or any(char in label for char in "/\\:"):
        _fail("invalid_lyrics", "Lyric source file is a label, not a path or URL")
    source["file"] = label
    return source


def _lyrics_raw(raw):
    if not isinstance(raw, dict) or any(key not in {"mode", "lines", "style", "source"} for key in raw) or not isinstance(raw.get("lines"), list):
        _fail("invalid_lyrics", "Lyrics need lines with start, end and text")
    if "mode" in raw and raw["mode"] not in _LYRIC_MODES:
        _fail("invalid_lyrics", "Unknown lyric mode")
    if not raw["lines"] or len(raw["lines"]) > MAX_LYRIC_LINES:
        _fail("invalid_lyrics", "Lyrics need between 1 and 400 lines")
    return raw


def _set_lyrics(document: dict, operation: dict, warnings: list) -> None:
    _only(operation, {"op", "lyrics"})
    raw = _lyrics_raw(operation.get("lyrics"))
    seen: set[str] = set()
    lines = [_lyric_line(line, index, seen) for index, line in enumerate(raw["lines"])]
    if sum(len(line["words"]) for line in lines) > 4000:
        _fail("invalid_lyrics", "Lyrics exceed 4000 words")
    lyrics = {"mode": raw.get("mode", "karaoke"), "lines": lines, "style": _lyric_style(raw.get("style"))}
    source = _lyric_source(raw.get("source"))
    if source is not None:
        lyrics["source"] = source
    if any(line["end"] > document["duration"] for line in lines):
        _warn(warnings, "content_after_duration", "A lyric line ends after the scene duration")
    document["lyrics"] = lyrics


def _rhythm_marks(values, label: str) -> list:
    if not isinstance(values, list) or not 1 <= len(values) <= 2000:
        _fail("invalid_rhythm", f"{label} must contain 1..2000 times")
    return [_number(value, 0, 36000, "invalid_rhythm", f"{label} must be finite times") for value in values]


def _energy(raw) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"fps", "values"}:
        _fail("invalid_rhythm", "Rhythm energy needs fps and values")
    fps = _number(raw["fps"], 1, 60, "invalid_rhythm", "Rhythm energy fps must be from 1 to 60")
    values = raw["values"]
    if not isinstance(values, list) or not 1 <= len(values) <= 6000:
        _fail("invalid_rhythm", "Rhythm energy values must contain 1..6000 numbers")
    return {"fps": fps, "values": [_number(value, -1000000, 1000000, "invalid_rhythm", "Rhythm energy values must be finite numbers") for value in values]}


def _set_rhythm(document: dict, operation: dict, warnings: list) -> None:
    del warnings
    _only(operation, {"op", "rhythm"})
    raw = operation.get("rhythm")
    if not isinstance(raw, dict) or any(key not in {"bpm", "beats", "downbeats", "energy"} for key in raw) or "bpm" not in raw or "beats" not in raw:
        _fail("invalid_rhythm", "Rhythm needs bpm and beats and does not analyze audio")
    rhythm = {"bpm": _number(raw["bpm"], 40, 240, "invalid_rhythm", "bpm must be between 40 and 240"), "beats": _rhythm_marks(raw["beats"], "beats")}
    if "downbeats" in raw:
        rhythm["downbeats"] = _rhythm_marks(raw["downbeats"], "downbeats")
    if "energy" in raw:
        rhythm["energy"] = _energy(raw["energy"])
    document["rhythm"] = rhythm


def _track_items(document: dict) -> list:
    current = document.get("audioTracks")
    if current is None:
        return []
    if not isinstance(current, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in current):
        _fail("invalid_audio", "audioTracks must be a list of tracks with ids")
    return current


def _audio_name(track: dict, filename: str) -> str:
    if "name" not in track:
        return Path(filename).stem[:120] or "audio"
    name = track["name"]
    if not isinstance(name, str) or not 1 <= len(name) <= 120:
        _fail("invalid_audio", "Audio name must be 1..120 characters")
    return name


def _audio_filename(value) -> str:
    if not isinstance(value, str) or "/" in value or "\\" in value or ".." in value or not 1 <= len(value) <= 200:
        _fail("invalid_audio", "Audio filename must be a workspace audio basename")
    if Path(value).suffix.lower() not in _AUDIO_EXTENSIONS:
        _fail("invalid_audio", "Audio filename must be wav, mp3, flac, ogg, m4a or aac")
    return value


def _build_track(track: dict, scene_duration: float, warnings: list) -> dict:
    if not isinstance(track, dict) or any(key not in {"id", "filename", "name", "kind", "startTime", "volume", "prompt", "model"} for key in track):
        _fail("invalid_audio", "Audio track has unsupported fields")
    if "id" not in track or "filename" not in track:
        _fail("invalid_audio", "Audio track needs id and filename")
    filename = _audio_filename(track["filename"])
    kind = track.get("kind", "audio")
    if kind not in _AUDIO_KINDS:
        _fail("invalid_audio", "Audio kind must be speech, music, sfx or audio")
    start = _number(track.get("startTime", 0), 0, 600, "invalid_audio", "Audio startTime is out of range")
    if start - scene_duration > 1e-6:
        _warn(warnings, "content_after_duration", "An audio track starts after the scene duration")
    built = {"id": _id(track["id"]), "filename": filename, "name": _audio_name(track, filename), "kind": kind, "startTime": start, "volume": _number(track.get("volume", 1), 0, 1, "invalid_audio", "Audio volume must be from 0 to 1")}
    for key in ("prompt", "model"):
        if key in track:
            if not isinstance(track[key], str) or len(track[key]) > 240:
                _fail("invalid_audio", f"Audio {key} must be a short string")
            built[key] = track[key]
    _warn(warnings, "audio_not_loaded", "Audio filename is stored only; this operation does not read the file")
    return built


def _add_audio_track(document: dict, operation: dict, warnings: list) -> None:
    _only(operation, {"op", "track"})
    track = _build_track(operation.get("track"), document["duration"], warnings)
    _upsert(document, "audioTracks", [track], MAX_TRACKS, "audio tracks")


def _later_than(items, key: str, duration: float) -> bool:
    if not isinstance(items, list):
        return False
    for item in items:
        value = item.get(key) if isinstance(item, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > duration:
            return True
    return False


def _warn_content(document: dict, duration: float, warnings: list) -> None:
    lyrics = document.get("lyrics") if isinstance(document.get("lyrics"), dict) else {}
    late = _later_than(document.get("texts"), "end", duration)
    late = late or _later_than(lyrics.get("lines"), "end", duration)
    late = late or _later_than(document.get("audioTracks"), "startTime", duration)
    if late:
        _warn(warnings, "content_after_duration", "Scene content extends past the new duration")


def _set_duration(document: dict, operation: dict, warnings: list) -> None:
    _only(operation, {"op", "duration"})
    value = operation.get("duration")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or not 0 < value <= 600:
        _fail("invalid_duration", "Duration must be greater than 0 and at most 600 seconds")
    document["duration"] = value
    _warn_content(document, value, warnings)


def _dimension(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value % 2 or not 240 <= value <= 3840:
        _fail("invalid_format", "Width and height must be even integers from 240 to 3840")
    return value


def _set_format(document: dict, operation: dict, warnings: list) -> None:
    del warnings
    _only(operation, {"op", "width", "height"})
    if "width" not in operation or "height" not in operation:
        _fail("invalid_format", "Width and height must be even integers from 240 to 3840")
    document["width"] = _dimension(operation["width"])
    document["height"] = _dimension(operation["height"])


_HANDLERS = {
    "add_layer": _add_layer,
    "update_layer": _update_layer,
    "remove_layer": _remove_layer,
    "reorder": _reorder,
    "add_title": _add_title,
    "update_text": _update_text,
    "remove_text": _remove_text,
    "set_finish": _set_finish,
    "set_lyrics": _set_lyrics,
    "set_rhythm": _set_rhythm,
    "add_audio_track": _add_audio_track,
    "set_duration": _set_duration,
    "set_format": _set_format,
}


def _apply(document: dict, operation, warnings: list) -> None:
    if not isinstance(operation, dict) or not isinstance(operation.get("op"), str):
        _fail("invalid_operation", "Unknown operation")
    handler = _HANDLERS.get(operation["op"])
    if handler is None:
        _fail("invalid_operation", "Unknown operation")
    handler(document, operation, warnings)


def edit(command) -> dict:
    payload = _payload(command)
    document = _copy_document(payload["document"])
    warnings: list = []
    for operation in _operation_list(payload["operations"]):
        _apply(document, operation, warnings)
    _ensure_document(document)
    return {"version": 1, "status": "completed", "operation": OPERATION, "result": {"document": document, "warnings": warnings, "saved": False}}


def _schema_string(max_length: int) -> dict:
    return {"type": "string", "minLength": 1, "maxLength": max_length}


def _op_schema(op: str, required: list[str], properties: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": {"op": {"const": op}, **properties}, "required": ["op", *required]}


def command_catalog() -> list[dict]:
    preset = {"type": "string", "enum": list(CAMERA_PRESETS)}
    identity = _schema_string(160)
    description = (
        "Return an edited version 1 Video 2D document and warnings. Does not save, export, render or fetch. "
        "At most 32 operations. Ids are 1..160 characters. add_layer, add_title and add_audio_track replace an object with the same id. "
        "add_layer source must be a durable /api/v1/file, /api/v1/uploads or /examples URL. Optional preset ids are the hardcoded "
        "RECIPE_CAMERA_PRESETS list; M1 JSON should replace it, and RECIPE_MOTION_PRESETS are not accepted yet. "
        "add_title is a Python port of the defaults in kineticText/templates.ts, not the TypeScript build(). "
        "set_finish accepts warmCinema, oldDoc, nightNeon, paperComic or raw finish values. "
        "set_lyrics stores lines with start/end/text and does not fetch. set_rhythm stores bpm and beats and does not analyze audio. "
        "set_duration is greater than 0 and at most 600 seconds. set_format width and height are even integers from 240 to 3840. "
        "An unknown op fails with invalid_operation."
    )
    operations = {"type": "array", "maxItems": MAX_OPERATIONS, "items": {"oneOf": [
        _op_schema("add_layer", ["id", "source"], {"id": identity, "source": _schema_string(2000), "preset": preset, "name": _schema_string(120), "type": {"enum": sorted(_LAYER_TYPES)}, "z": {"type": "number"}}),
        _op_schema("update_layer", ["id", "patch"], {"id": identity, "patch": {"type": "object"}}),
        _op_schema("remove_layer", ["id"], {"id": identity}),
        _op_schema("reorder", ["ids"], {"ids": {"type": "array", "items": identity, "maxItems": MAX_LAYERS}}),
        _op_schema("add_title", ["template", "start", "duration"], {"template": {"enum": list(_TITLE_BUILDERS)}, "fields": {"type": "object"}, "start": {"type": "number", "minimum": 0}, "duration": {"type": "number", "exclusiveMinimum": 0}, "id": identity}),
        _op_schema("update_text", ["id", "patch"], {"id": identity, "patch": {"type": "object"}}),
        _op_schema("remove_text", ["id"], {"id": identity}),
        _op_schema("set_finish", [], {"preset": {"enum": list(_FINISH_PRESET_IDS)}, "finish": {"type": "object"}}),
        _op_schema("set_lyrics", ["lyrics"], {"lyrics": {"type": "object"}}),
        _op_schema("set_rhythm", ["rhythm"], {"rhythm": {"type": "object"}}),
        _op_schema("add_audio_track", ["track"], {"track": {"type": "object"}}),
        _op_schema("set_duration", ["duration"], {"duration": {"type": "number", "exclusiveMinimum": 0, "maximum": 600}}),
        _op_schema("set_format", ["width", "height"], {"width": {"type": "integer", "minimum": 240, "maximum": 3840}, "height": {"type": "integer", "minimum": 240, "maximum": 3840}}),
    ]}}
    envelope = {"type": "object", "additionalProperties": False, "properties": {"version": {"type": "integer", "const": 1}, "input": {"type": "object", "additionalProperties": False, "properties": {"document": {"type": "object"}, "operations": operations}, "required": ["document", "operations"]}}, "required": ["version", "input"]}
    return [{"name": OPERATION, "version": 1, "domain": "scenes", "mutation": False, "description": description, "inputSchema": envelope}]


def command_handlers() -> dict:
    async def handle(arguments):
        from starlette.concurrency import run_in_threadpool
        try:
            return await run_in_threadpool(edit, arguments)
        except Video2dEditError as error:
            raise http_error(error.code, str(error)) from error

    return {OPERATION: handle}


__all__ = ["OPERATION", "Video2dEditError", "command_catalog", "command_handlers", "edit", "http_error"]

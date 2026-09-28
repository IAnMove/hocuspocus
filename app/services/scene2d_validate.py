"""Normalize a Video 2D document and report errors and warnings.

``scenes.video2d.validate`` does not save, export, or render. Media checks only
stat paths that already exist.
"""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from services.media_refs import parse_media_ref
from services.scene2d_schema import FONTS, LAYER_TYPES, document_schema

OPERATION = "scenes.video2d.validate"
WORKSPACE_RE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]{0,119})")
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"})
_MAX_BYTES = 2 * 1024 * 1024
_MAX_ISSUES = 32
_TOP_CODES = {
    "version": "invalid_version", "duration": "invalid_duration", "width": "invalid_dimensions",
    "height": "invalid_dimensions", "fps": "invalid_fps", "generationPolicy": "invalid_generation_policy",
    "name": "invalid_name", "layers": "invalid_layers",
}
_KEYWORDS = {
    "type": "invalid_type", "const": "invalid_value", "enum": "invalid_value", "pattern": "invalid_value",
    "maximum": "invalid_range", "minimum": "invalid_range", "exclusiveMinimum": "invalid_range",
    "exclusiveMaximum": "invalid_range", "maxItems": "invalid_range", "minItems": "invalid_range",
    "maxLength": "invalid_range", "minLength": "invalid_range", "additionalProperties": "unexpected_field",
    "required": "missing_field",
}
_TEXT_RANGES = {
    "x": (0, 100), "y": (0, 100), "size": (2, 25), "rotation": (-45, 45), "maxWidth": (10, 100),
    "lineHeight": (0.8, 2), "letterSpacing": (-0.1, 0.5), "beatPulse": (0, 1),
}
_LYRIC_RANGES = {"size": (2, 25), "weight": (400, 900), "x": (0, 100), "y": (0, 100), "maxWidth": (10, 100), "beatPulse": (0, 1)}
_SAFE_Y = (12, 80)


class Scene2DValidateError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _issue(code: str, path: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "path": path, "message": message, **extra}


def _add(items: list[dict[str, Any]], issue: dict[str, Any]) -> None:
    if len(items) < _MAX_ISSUES:
        items.append(issue)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clamp(value: Any, low: float, high: float) -> Any:
    number = _number(value)
    if number is None:
        return value
    return min(high, max(low, number))


def _clamp_into(node: Any, ranges: dict[str, tuple[float, float]]) -> None:
    if not isinstance(node, dict):
        return
    for key, (low, high) in ranges.items():
        if key in node:
            node[key] = _clamp(node[key], low, high)


def _round_into(node: Any, key: str, low: float, high: float) -> None:
    if not isinstance(node, dict) or key not in node:
        return
    number = _number(_clamp(node[key], low, high))
    if number is not None:
        node[key] = int(round(number))


def _pointer(path: Any) -> str:
    parts: list[str] = []
    for item in path:
        if isinstance(item, int) and parts:
            parts[-1] = f"{parts[-1]}[{item}]"
        elif isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            parts.append(str(item))
    return ".".join(parts)


def _missing_name(message: str) -> str:
    if message.startswith("'") and "' " in message:
        return message.split("'", 2)[1]
    return ""


def _schema_code(error: Any, path: str) -> str:
    if path in _TOP_CODES:
        return _TOP_CODES[path]
    if error.validator == "required":
        missing = _missing_name(error.message)
        joined = f"{path}.{missing}" if path and missing else missing
        if joined in _TOP_CODES:
            return _TOP_CODES[joined]
    return _KEYWORDS.get(error.validator, "invalid_field")


def _font_enum(error: Any) -> bool:
    parts = list(error.absolute_path)
    return error.validator == "enum" and bool(parts) and parts[-1] == "font"


def _schema_errors(document: dict, errors: list[dict[str, Any]]) -> None:
    try:
        validator = Draft202012Validator(document_schema())
    except SchemaError as error:
        _add(errors, _issue("invalid_document", "", f"Scene schema is unavailable: {error}"))
        return
    for error in validator.iter_errors(document):
        if _font_enum(error):
            continue
        path = _pointer(error.absolute_path)
        message = error.message.split("\n", 1)[0][:500]
        _add(errors, _issue(_schema_code(error, path), path, message))


def _duplicate_ids(items: Any, path: str, errors: list[dict[str, Any]]) -> None:
    if not isinstance(items, list):
        return
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        identity = item.get("id")
        if not isinstance(identity, str) or not identity or identity not in seen:
            if isinstance(identity, str) and identity:
                seen.add(identity)
            continue
        _add(errors, _issue("duplicate_id", f"{path}[{index}].id", "Ids must be unique."))


def _timing(item: Any, path: str, errors: list[dict[str, Any]]) -> None:
    if not isinstance(item, dict):
        return
    start, end = _number(item.get("start")), _number(item.get("end"))
    if start is not None and end is not None and end <= start:
        _add(errors, _issue("invalid_timing", path, "end must be later than start."))


def _check_timings(items: Any, path: str, errors: list[dict[str, Any]]) -> None:
    if not isinstance(items, list):
        return
    for index, item in enumerate(items):
        _timing(item, f"{path}[{index}]", errors)


def _check_lyric_timing(document: dict, errors: list[dict[str, Any]]) -> None:
    lyrics = document.get("lyrics")
    lines = lyrics.get("lines") if isinstance(lyrics, dict) else None
    _check_timings(lines, "lyrics.lines", errors)


def _normalize_paint(node: Any) -> None:
    if not isinstance(node, dict):
        return
    _clamp_into(node.get("stroke"), {"width": (0, 0.3)})
    _clamp_into(node.get("shadow"), {"blur": (0, 2), "x": (-1, 1), "y": (-1, 1)})
    _clamp_into(node.get("fill"), {"angle": (-180, 180)})
    _clamp_into(node.get("box"), {"opacity": (0, 1), "padding": (0, 4), "radius": (0, 2)})
    span_ranges = {"duration": (0.05, 3)}
    _clamp_into(node.get("enter"), span_ranges)
    _clamp_into(node.get("exit"), span_ranges)


def _normalize_texts(document: dict) -> None:
    texts = document.get("texts")
    if not isinstance(texts, list):
        return
    for cue in texts:
        if not isinstance(cue, dict):
            continue
        _clamp_into(cue, _TEXT_RANGES)
        _normalize_paint(cue)


def _normalize_lyrics(document: dict) -> None:
    lyrics = document.get("lyrics")
    style = lyrics.get("style") if isinstance(lyrics, dict) else None
    if not isinstance(style, dict):
        return
    _clamp_into(style, _LYRIC_RANGES)
    _normalize_paint(style)


def _normalize_finish(document: dict) -> None:
    finish = document.get("finish")
    if not isinstance(finish, dict):
        return
    _clamp_into(finish.get("grade"), {
        "exposure": (-1, 1), "contrast": (-1, 1), "saturation": (-1, 1), "temperature": (-1, 1),
        "tint": (-1, 1), "fade": (0, 1), "beatFlash": (0, 1),
    })
    _clamp_into(finish.get("bloom"), {"amount": (0, 1), "threshold": (0, 1), "radius": (0, 1), "beat": (0, 1)})
    _clamp_into(finish.get("rays"), {"amount": (0, 1), "x": (0, 100), "y": (0, 100), "length": (0, 1), "threshold": (0, 1)})
    _clamp_into(finish.get("vignette"), {"amount": (0, 1), "softness": (0, 1)})
    _clamp_into(finish.get("grain"), {"amount": (0, 1), "size": (0.5, 4)})
    _clamp_into(finish.get("texture"), {"amount": (0, 1)})
    _clamp_into(finish.get("riso"), {
        "misreg": (0, 8), "cutKick": (0, 48), "beatKick": (0, 24), "gamma": (0.2, 3), "gain": (0, 2),
        "kLo": (0, 1), "kHi": (0, 1), "lift": (-0.2, 0.2), "grain": (0, 0.2), "fibre": (0, 2),
        "inkTex": (0, 1), "vignette": (0, 1),
    })


def _normalize_rhythm(document: dict) -> None:
    rhythm = document.get("rhythm")
    if not isinstance(rhythm, dict):
        return
    _clamp_into(rhythm, {"bpm": (40, 240)})
    energy = rhythm.get("energy")
    if isinstance(energy, dict):
        _clamp_into(energy, {"fps": (1, 60)})


def _normalize_sfx(document: dict) -> None:
    cues = document.get("sfx")
    if not isinstance(cues, list):
        return
    ranges = {
        "start": (0, 600), "end": (0, 600), "x": (0, 100), "y": (0, 100), "size": (1, 200),
        "intensity": (0.1, 2), "rotation": (-180, 180), "volume": (0, 1),
    }
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        _clamp_into(cue, ranges)
        _round_into(cue, "seed", 1, 1_000_000)


def _normalize_emitter(emitter: Any) -> None:
    _clamp_into(emitter, {
        "x": (0, 100), "y": (0, 100), "offsetX": (-100, 100), "offsetY": (-100, 100),
        "direction": (-180, 180), "spread": (0, 180), "rate": (0.1, 80),
        "lifetime": (0.05, 12), "speed": (0, 200), "gravity": (-80, 80),
    })


def _normalize_atmosphere(atmosphere: Any) -> None:
    if not isinstance(atmosphere, dict):
        return
    _clamp_into(atmosphere, {"speed": (0.05, 4), "size": (0.2, 8), "wind": (-100, 100)})
    _round_into(atmosphere, "density", 5, 240)
    _normalize_emitter(atmosphere.get("emitter"))


def _normalize_sequence(sequence: Any) -> None:
    if not isinstance(sequence, dict):
        return
    _clamp_into(sequence, {"fps": (1, 60)})
    _round_into(sequence, "columns", 1, 32)
    _round_into(sequence, "rows", 1, 32)
    _round_into(sequence, "count", 1, 120)


def _normalize_path(path: Any) -> None:
    if not isinstance(path, dict):
        return
    _clamp_into(path, {"rotationOffset": (-180, 180)})
    points = path.get("points")
    if not isinstance(points, list):
        return
    for point in points:
        _clamp_into(point, {"x": (-20, 120), "y": (-20, 120)})


def _normalize_effects(effects: Any) -> None:
    _clamp_into(effects, {
        "blur": (0, 3), "brightness": (0, 3), "contrast": (0, 3), "saturation": (0, 4),
        "hue": (-180, 180), "glow": (0, 5), "shadow": (0, 8), "maskRadius": (0, 50),
    })


def _normalize_strip(strip: Any) -> None:
    if not isinstance(strip, dict):
        return
    _clamp_into(strip, {"spacing": (2, 200), "speed": (0, 300), "phase": (-1000, 1000)})
    _round_into(strip, "count", 1, 12)
    seam = strip.get("seamOccluder")
    if isinstance(seam, dict):
        _clamp_into(seam, {"scale": (0.45, 1.8), "opacity": (0.2, 1)})


def _normalize_layer(layer: Any) -> None:
    if not isinstance(layer, dict):
        return
    _normalize_atmosphere(layer.get("atmosphere"))
    _normalize_sequence(layer.get("sequence"))
    _normalize_effects(layer.get("effects"))
    _normalize_strip(layer.get("strip"))
    animation = layer.get("animation")
    if isinstance(animation, dict):
        _normalize_path(animation.get("path"))


def _normalize_layers(document: dict) -> None:
    layers = document.get("layers")
    if not isinstance(layers, list):
        return
    for layer in layers:
        _normalize_layer(layer)


def _default_fps(document: dict) -> None:
    if "fps" not in document:
        document["fps"] = 30


def _portrait(document: dict) -> bool:
    width, height = _number(document.get("width")), _number(document.get("height"))
    return width is not None and height is not None and height > width


def _outside_y(value: Any) -> bool:
    number = _number(value)
    return number is not None and (number < _SAFE_Y[0] or number > _SAFE_Y[1])


def _wide(value: Any) -> bool:
    number = _number(value)
    return number is not None and number > 90


def _warn_text_box(node: Any, path: str, portrait: bool, warnings: list[dict[str, Any]]) -> None:
    if not isinstance(node, dict):
        return
    if _outside_y(node.get("y")):
        _add(warnings, _issue("text_outside_safe_area", f"{path}.y", "Text y is outside the vertical safe area (12–80)."))
    if portrait and _wide(node.get("maxWidth")):
        _add(warnings, _issue("text_outside_safe_area", f"{path}.maxWidth", "Text width is over 90 on a portrait frame."))


def _warn_safe_area(document: dict, warnings: list[dict[str, Any]]) -> None:
    portrait = _portrait(document)
    texts = document.get("texts")
    if isinstance(texts, list):
        for index, cue in enumerate(texts):
            _warn_text_box(cue, f"texts[{index}]", portrait, warnings)
    lyrics = document.get("lyrics")
    style = lyrics.get("style") if isinstance(lyrics, dict) else None
    _warn_text_box(style, "lyrics.style", portrait, warnings)
    layers = document.get("layers")
    if not isinstance(layers, list):
        return
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict) or layer.get("type") != "overlay":
            continue
        transform = layer.get("transform") if isinstance(layer.get("transform"), dict) else {}
        if _outside_y(transform.get("y")):
            _add(warnings, _issue("text_outside_safe_area", f"layers[{index}].transform.y", "Overlay y is outside the vertical safe area (12–80)."))


def _warn_font(value: Any, path: str, warnings: list[dict[str, Any]]) -> None:
    if isinstance(value, str) and value not in FONTS:
        known = ", ".join(FONTS)
        _add(warnings, _issue("unknown_font", path, f"Unknown font '{value}'. Known fonts: {known}."))


def _warn_fonts(document: dict, warnings: list[dict[str, Any]]) -> None:
    texts = document.get("texts")
    if isinstance(texts, list):
        for index, cue in enumerate(texts):
            if isinstance(cue, dict):
                _warn_font(cue.get("font"), f"texts[{index}].font", warnings)
    lyrics = document.get("lyrics")
    style = lyrics.get("style") if isinstance(lyrics, dict) else None
    if isinstance(style, dict):
        _warn_font(style.get("font"), "lyrics.style.font", warnings)


def _warn_frame(layer: Any, index: int, warnings: list[dict[str, Any]]) -> None:
    if not isinstance(layer, dict) or layer.get("type") not in LAYER_TYPES:
        return
    transform = layer.get("transform")
    if not isinstance(transform, dict):
        return
    x, y = _number(transform.get("x")), _number(transform.get("y"))
    if x is None or y is None or (0 <= x <= 100 and 0 <= y <= 100):
        return
    _add(warnings, _issue("layer_outside_frame", f"layers[{index}].transform", f"Layer is outside the frame (x={x:g}, y={y:g})."))


def _warn_layers(document: dict, warnings: list[dict[str, Any]]) -> None:
    layers = document.get("layers")
    if not isinstance(layers, list):
        return
    for index, layer in enumerate(layers):
        _warn_frame(layer, index, warnings)


def _warn_duration(document: dict, warnings: list[dict[str, Any]]) -> None:
    duration = _number(document.get("duration"))
    if duration is None:
        return
    if _portrait(document):
        limit, premium, platform = 60, 90, "shorts"
    else:
        limit, premium, platform = 140, 180, "x"
    if duration <= limit:
        return
    if duration > premium:
        message = f"Duration {duration:g}s exceeds the {platform} premium publish limit of {premium}s (standard {limit}s)."
    else:
        message = f"Duration {duration:g}s exceeds the {platform} publish limit of {limit}s (premium allows {premium}s)."
    _add(warnings, _issue(
        "duration_over_publish_limit", "duration", message,
        platform=platform, standardSeconds=limit, premiumSeconds=premium,
    ))


def _example_ready(url: str) -> bool:
    path = unquote(urlsplit(url).path)
    if ".." in path.split("/") or "\\" in path or not path.startswith("/examples/"):
        return False
    name = path[len("/examples/"):]
    if not name:
        return False
    try:
        from services.example_assets import example_assets
        example_assets.entry(name)
    except (KeyError, OSError):
        return False
    return example_assets.cached(name) is not None


def _workspace_file(url: str, workspace: str, workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str]) -> bool:
    path, scoped = parse_media_ref(url, workspace)
    name = os.path.basename((path or "").replace("\\", "/"))
    if not name or name in {".", ".."}:
        return False
    lowered = url.strip().lower()
    if lowered.startswith("/api/v1/uploads/") or scoped == "__uploads__":
        return (Path(uploads_dir()) / name).is_file()
    chosen = scoped or workspace
    if not isinstance(chosen, str) or not WORKSPACE_RE.fullmatch(chosen):
        return False
    return (Path(workspace_dir(chosen)) / name).is_file()


def _media_missing(url: str, workspace: str, workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str]) -> bool:
    text = url.strip().lower()
    if text.startswith(("blob:", "file:", "javascript:", "filesystem:", "http://", "https://", "//")):
        return True
    if text.startswith("data:image/"):
        return False
    if text.startswith("/examples/"):
        return not _example_ready(url)
    if text.startswith(("/api/v1/file/", "/api/v1/uploads/")):
        return not _workspace_file(url, workspace, workspace_dir, uploads_dir)
    return True


def _sequence_urls(layer: dict) -> list[str]:
    sequence = layer.get("sequence")
    if not isinstance(sequence, dict):
        return []
    if sequence.get("kind") == "frames":
        return [str(source).strip() for source in sequence.get("sources") or [] if str(source).strip()]
    if sequence.get("kind") == "sheet":
        source = str(sequence.get("source") or "").strip()
        return [source] if source else []
    return []


def _warn_layer_media(layer: Any, index: int, workspace: str, workspace_dir: Callable[[str], str],
                      uploads_dir: Callable[[], str], warnings: list[dict[str, Any]]) -> None:
    if not isinstance(layer, dict):
        return
    if layer.get("type") in {"effect", "camera"} or layer.get("visible") is False:
        return
    if layer.get("type") not in {"image", "video", "overlay", "model3d"}:
        return
    urls = [str(layer.get("source") or "").strip()]
    urls = [url for url in urls if url]
    urls.extend(_sequence_urls(layer))
    path = f"layers[{index}].source"
    if not urls:
        _add(warnings, _issue("missing_media", path, "Layer needs durable workspace or example media."))
        return
    for url in urls:
        if _media_missing(url, workspace, workspace_dir, uploads_dir):
            _add(warnings, _issue("missing_media", path, f"Missing durable media: {url}"))


def _warn_audio(document: dict, workspace: str, workspace_dir: Callable[[str], str], warnings: list[dict[str, Any]]) -> None:
    tracks = document.get("audioTracks")
    if not isinstance(tracks, list):
        return
    root = Path(workspace_dir(workspace))
    for index, track in enumerate(tracks):
        name = os.path.basename(str(track.get("filename") or "")) if isinstance(track, dict) else ""
        suffix = os.path.splitext(name)[1].lower()
        if name and suffix in AUDIO_EXTENSIONS and (root / name).is_file():
            continue
        _add(warnings, _issue("missing_media", f"audioTracks[{index}].filename", "Audio track file is missing."))


def _warn_media(document: dict, workspace: str, workspace_dir: Callable[[str], str],
                uploads_dir: Callable[[], str], warnings: list[dict[str, Any]]) -> None:
    layers = document.get("layers")
    if isinstance(layers, list):
        for index, layer in enumerate(layers):
            _warn_layer_media(layer, index, workspace, workspace_dir, uploads_dir, warnings)
    _warn_audio(document, workspace, workspace_dir, warnings)


def _finite_copy(raw: dict) -> tuple[dict | None, dict | None]:
    try:
        encoded = json.dumps(raw, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return None, _issue("invalid_document", "", "Scene JSON must be finite.")
    if len(encoded.encode("utf-8")) > _MAX_BYTES:
        return deepcopy(raw), _issue("document_too_large", "", "Scene exceeds 2 MB.")
    return deepcopy(raw), None


def normalize_document(raw: Any, *, workspace: str, workspace_dir: Callable[[str], str],
                       uploads_dir: Callable[[], str]) -> dict[str, Any]:
    """Return ``{document, errors, warnings}`` without writing a scene file."""
    if not isinstance(raw, dict):
        return {"document": {}, "errors": [_issue("invalid_document", "", "Use a version 1 Video 2D document.")], "warnings": []}
    document, size_error = _finite_copy(raw)
    if document is None:
        return {"document": {}, "errors": [size_error], "warnings": []}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if size_error:
        _add(errors, size_error)
    if "slots" in document:
        _add(errors, _issue("not_video2d", "slots", "Choose a Video 2D scene (layers); slots documents are Video 3D."))
        return {"document": document, "errors": errors, "warnings": warnings}
    _default_fps(document)
    _normalize_texts(document)
    _normalize_lyrics(document)
    _normalize_finish(document)
    _normalize_rhythm(document)
    _normalize_sfx(document)
    _normalize_layers(document)
    _schema_errors(document, errors)
    _duplicate_ids(document.get("layers"), "layers", errors)
    _duplicate_ids(document.get("texts"), "texts", errors)
    _duplicate_ids(document.get("sfx"), "sfx", errors)
    lyrics = document.get("lyrics")
    _duplicate_ids(lyrics.get("lines") if isinstance(lyrics, dict) else None, "lyrics.lines", errors)
    _check_timings(document.get("texts"), "texts", errors)
    _check_timings(document.get("sfx"), "sfx", errors)
    _check_lyric_timing(document, errors)
    _warn_safe_area(document, warnings)
    _warn_fonts(document, warnings)
    _warn_layers(document, warnings)
    _warn_duration(document, warnings)
    _warn_media(document, workspace, workspace_dir, uploads_dir, warnings)
    return {"document": document, "errors": errors, "warnings": warnings}


def command_catalog() -> list[dict[str, Any]]:
    workspace = {"type": "string", "minLength": 1, "maxLength": 120}
    description = (
        "Normalize a version 1 Video 2D document and return result.document, result.errors and result.warnings "
        "without saving or exporting. Errors use a stable code. Warnings use text_outside_safe_area "
        "(overlay or text y < 12 or y > 80, or width > 90 on a portrait frame), missing_media, unknown_font, "
        "layer_outside_frame, and duration_over_publish_limit (X 140s / premium 180s, shorts 60s / premium 90s). "
        "No GPU and no scene-file write."
    )
    return [{
        "name": OPERATION, "version": 1, "domain": "scenes", "mutation": False, "description": description,
        "inputSchema": {"type": "object", "additionalProperties": False,
                        "properties": {"version": {"type": "integer", "const": 1},
                                       "input": {"type": "object", "additionalProperties": False,
                                                 "properties": {"workspace": workspace, "document": document_schema()},
                                                 "required": ["document", "workspace"]}},
                        "required": ["version", "input"]},
    }]


def command_handlers(workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str] | None = None) -> dict[str, Callable[[Any], Any]]:
    uploads = uploads_dir or (lambda: os.path.join(os.getcwd(), "uploads"))

    def payload(arguments: Any) -> dict[str, Any]:
        data = arguments.get("input") if isinstance(arguments, dict) and arguments.get("version") == 1 else None
        if not isinstance(data, dict) or set(data) - {"document", "workspace"} or "document" not in data or "workspace" not in data:
            raise Scene2DValidateError("invalid_command", "Use version 1 with input.document and input.workspace")
        if not isinstance(data.get("workspace"), str) or not WORKSPACE_RE.fullmatch(data["workspace"]):
            raise Scene2DValidateError("invalid_workspace", "Use an explicit valid workspace")
        return data

    def run(arguments: Any) -> dict[str, Any]:
        data = payload(arguments)
        result = normalize_document(data["document"], workspace=data["workspace"], workspace_dir=workspace_dir, uploads_dir=uploads)
        return {"version": 1, "status": "completed", "operation": OPERATION, "result": result}

    async def handle(arguments: Any) -> dict[str, Any]:
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool
        try:
            return await run_in_threadpool(run, arguments)
        except Scene2DValidateError as error:
            raise HTTPException(error.status, {"code": error.code, "message": str(error)}) from error

    return {OPERATION: handle}


__all__ = ["OPERATION", "Scene2DValidateError", "command_catalog", "command_handlers", "normalize_document"]

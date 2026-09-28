"""JSON Schema for a version 1 Video 2D scene.

Names and limits follow ``Scene`` in ``ui/src/types/index.ts`` and the parsers
in sceneFile, kineticText, lyrics, scene2d/finish, scene2d/motion and sceneFx.
Extra keys stay allowed so a later editor field still round-trips.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

_EFFECTS = json.loads((Path(__file__).resolve().parents[1] / "shared" / "scene_effects.json").read_text(encoding="utf-8"))
EFFECT_IDS = tuple(item["id"] for item in _EFFECTS)
FONTS = ("sans", "mono", "display", "condensed", "serif", "hand", "marker")
HEX = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}
CURVE = {"enum": ["linear", "ease", "dramatic", "bounce", "hold"]}
LOOP = {"enum": ["loop", "pingpong", "once"]}
LAYER_TYPES = ("model3d", "image", "video", "overlay", "effect", "camera")


def _object(properties: dict, required: list[str] | None = None) -> dict:
    schema = {"type": "object", "additionalProperties": True, "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


def _number(low: float | None = None, high: float | None = None, *, exclusive_low: bool = False) -> dict:
    schema: dict = {"type": "number"}
    if low is not None:
        schema["exclusiveMinimum" if exclusive_low else "minimum"] = low
    if high is not None:
        schema["maximum"] = high
    return schema


def _string(max_length: int | None = None) -> dict:
    schema: dict = {"type": "string"}
    if max_length is not None:
        schema["maxLength"] = max_length
    return schema


def _array(items: dict, *, max_items: int | None = None, min_items: int | None = None) -> dict:
    schema = {"type": "array", "items": items}
    if max_items is not None:
        schema["maxItems"] = max_items
    if min_items is not None:
        schema["minItems"] = min_items
    return schema


def _enum(values) -> dict:
    return {"enum": list(values)}


def _span(presets: tuple[str, ...]) -> dict:
    return _object({"preset": _enum(presets), "duration": _number(0.05, 3)}, ["preset", "duration"])


def _text_paint() -> dict:
    return {
        "stroke": _object({"color": HEX, "width": _number(0, 0.3)}, ["color", "width"]),
        "shadow": _object({
            "color": HEX, "blur": _number(0, 2), "x": _number(-1, 1), "y": _number(-1, 1),
        }, ["color", "blur", "x", "y"]),
        "fill": _object({
            "kind": _enum(["solid", "gradient"]), "from": HEX, "to": HEX, "angle": _number(-180, 180),
        }, ["kind"]),
        "box": _object({
            "kind": _enum(["none", "solid", "paper", "pill", "bar", "underline", "plate"]),
            "color": HEX, "opacity": _number(0, 1), "padding": _number(0, 4), "radius": _number(0, 2),
        }, ["kind", "color", "opacity", "padding"]),
    }


def _pose() -> dict:
    return _object({"x": _number(), "y": _number(), "scale": _number(), "opacity": _number(), "rotation": _number()}, ["x", "y", "scale"])


def _emitter() -> dict:
    return _object({
        "mode": _enum(["frame", "point", "layer"]),
        "x": _number(0, 100), "y": _number(0, 100), "targetLayerId": _string(120),
        "offsetX": _number(-100, 100), "offsetY": _number(-100, 100),
        "direction": _number(-180, 180), "spread": _number(0, 180), "rate": _number(0.1, 80),
        "lifetime": _number(0.05, 12), "speed": _number(0, 200), "gravity": _number(-80, 80),
    }, ["mode"])


def _atmosphere() -> dict:
    return _object({
        "kind": _enum([
            "rain", "snow", "dust", "embers", "fog", "smoke", "ash", "fireflies",
            "confetti", "bokeh", "sparkles", "bubbles", "speedlines", "leaves",
        ]),
        "density": _number(5, 240), "speed": _number(0.05, 4), "size": _number(0.2, 8),
        "wind": _number(-100, 100), "color": HEX, "emitter": _emitter(),
    }, ["kind", "density", "speed", "size", "wind", "color"])


def _sequence() -> dict:
    return _object({
        "kind": _enum(["frames", "sheet"]),
        "sources": _array(_string(), max_items=120), "source": _string(),
        "columns": _number(1, 32), "rows": _number(1, 32), "count": _number(1, 120),
        "fps": _number(1, 60), "loop": LOOP,
    }, ["kind"])


def _path() -> dict:
    point = _object({"x": _number(-20, 120), "y": _number(-20, 120)}, ["x", "y"])
    return _object({
        "points": _array(point, max_items=32, min_items=2), "orient": {"type": "boolean"},
        "rotationOffset": _number(-180, 180),
    }, ["points", "orient"])


def _effects() -> dict:
    return _object({
        "blur": _number(0, 3), "brightness": _number(0, 3), "contrast": _number(0, 3),
        "saturation": _number(0, 4), "hue": _number(-180, 180), "glow": _number(0, 5),
        "shadow": _number(0, 8),
        "blendMode": _enum(["normal", "multiply", "screen", "overlay", "lighten", "darken"]),
        "mask": _enum(["none", "rounded", "ellipse"]), "maskRadius": _number(0, 50),
    })


def _strip() -> dict:
    return _object({
        "enabled": {"type": "boolean"}, "count": _number(1, 12), "spacing": _number(2, 200),
        "direction": _enum(["up", "down", "left", "right"]), "speed": _number(0, 300),
        "phase": _number(-1000, 1000),
        "seamOccluder": _object({
            "enabled": {"type": "boolean"}, "kind": _enum(["pole", "lamp", "tree", "column"]),
            "scale": _number(0.45, 1.8), "opacity": _number(0.2, 1),
        }, ["enabled", "kind"]),
    }, ["enabled", "count", "spacing", "direction", "speed"])


def _animation() -> dict:
    return _object({
        "start": _pose(), "end": _pose(), "keyframes": _array(_object({
            "id": _string(), "time": _number(), "x": _number(), "y": _number(), "scale": _number(),
            "opacity": _number(), "rotation": _number(), "curve": CURVE,
        }, ["id", "time", "x", "y", "scale", "opacity", "rotation", "curve"])),
        "path": _path(),
        "events": _array(_object({"id": _string(), "time": _number(), "name": _string(), "payload": _string()}, ["id", "time", "name"])),
        "duration": _number(), "curve": CURVE, "offset": _number(), "speed": _number(),
        "loop": {"type": "boolean"}, "trimStart": _number(), "trimEnd": _number(),
        "shake": _object({
            "amount": _number(), "frequency": _number(), "seed": _number(),
            "startTime": _number(), "endTime": _number(),
        }, ["amount", "frequency"]),
        "spin": {"type": "boolean"}, "rotationSpeed": _number(), "clip": _string(),
        "clipOffset": _number(), "clipSpeed": _number(), "clipReverse": {"type": "boolean"},
        "clipLoop": {"type": "boolean"}, "clipTrimStart": _number(), "clipTrimEnd": _number(),
        "orbit": _object({
            "targetLayerId": _string(), "radiusX": _number(), "radiusY": _number(),
            "turns": _number(), "phase": _number(), "count": _number(),
            "facing": _enum(["fixed", "center", "outward"]),
            "centerOffsetX": _number(), "centerOffsetY": _number(),
        }, ["targetLayerId", "radiusX", "radiusY", "turns", "phase"]),
    }, ["start", "end", "duration", "curve"])


def _layer() -> dict:
    return _object({
        "characterKitRef": _object({"id": _string(), "workspace": _string()}, ["id", "workspace"]),
        "id": {"type": "string", "minLength": 1}, "name": _string(), "type": _enum(LAYER_TYPES),
        "source": _string(), "thumbnail": _string(), "visible": {"type": "boolean"}, "z": _number(),
        "locked": {"type": "boolean"}, "missingAsset": {"type": "boolean"}, "fill": {"type": "boolean"},
        "atmosphere": _atmosphere(), "parallax": _number(),
        "beatPulse": _object({"amount": _number(), "on": _enum(["beats", "downbeats"])}, ["amount", "on"]),
        "sequence": _sequence(), "seamlessHorizontal": {"type": "boolean"},
        "faceBinding": _object({
            "poseLayerId": _string(), "role": _enum(["mouth", "blink", "eyes"]),
            "state": _enum(["closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue", "blink", "open"]),
        }, ["poseLayerId", "role"]),
        "relationship": _object({
            "type": _enum(["parent", "follow", "lookAt"]), "targetLayerId": _string(),
            "offsetX": _number(), "offsetY": _number(), "strength": _number(), "rotationOffset": _number(),
        }, ["type", "targetLayerId"]),
        "effects": _effects(), "strip": _strip(),
        "transform": _object({
            "x": _number(), "y": _number(), "scale": _number(), "opacity": _number(),
            "rotation": _number(), "rotationX": _number(), "rotationY": _number(),
        }, ["x", "y", "scale", "opacity"]),
        "animation": _animation(),
    }, ["id", "name", "type", "source", "visible", "z", "transform", "animation"])


def _texts() -> dict:
    paint = _text_paint()
    return _array(_object({
        "id": {"type": "string", "minLength": 1}, "text": _string(240), "start": _number(0), "end": _number(0),
        "preset": _enum(["impact", "rise", "typewriter", "wave"]),
        "x": _number(0, 100), "y": _number(0, 100), "size": _number(2, 25), "color": HEX,
        "rotation": _number(-45, 45), "font": _enum(FONTS),
        "enter": _span(("none", "fade", "impact", "rise", "drop", "typewriter", "letters", "words", "blur", "wipe", "scale", "slide-left", "slide-right")),
        "exit": _span(("none", "fade", "fall", "blur", "wipe", "scale", "slide-left", "slide-right")),
        "loop": _enum(["none", "wave", "pulse", "shake", "float", "flicker"]),
        "weight": _enum([400, 500, 600, 700, 800, 900]), "align": _enum(["left", "center", "right"]),
        "maxWidth": _number(10, 100), "lineHeight": _number(0.8, 2), "letterSpacing": _number(-0.1, 0.5),
        "uppercase": {"type": "boolean"}, "italic": {"type": "boolean"},
        "stroke": paint["stroke"], "shadow": paint["shadow"], "fill": paint["fill"], "box": paint["box"],
        "counter": _object({
            "from": _number(), "to": _number(), "decimals": {"type": "integer", "minimum": 0, "maximum": 4},
            "ease": _enum(["linear", "ease"]),
        }, ["from", "to", "decimals", "ease"]),
        "template": _string(80), "beatPulse": _number(0, 1),
    }, ["id", "text", "start", "end", "preset"]), max_items=48)


def _lyrics() -> dict:
    paint = _text_paint()
    word = _object({"text": _string(), "start": _number(0, 36000), "end": _number(0, 36000)}, ["text", "start", "end"])
    line = _object({
        "id": _string(80), "start": _number(0, 36000), "end": _number(0, 36000),
        "words": _array(word, max_items=4000),
    }, ["id", "start", "end", "words"])
    return _object({
        "mode": _enum(["karaoke", "word-pop", "line-fade", "bounce"]),
        "lines": _array(line, max_items=400),
        "style": _object({
            "font": _enum(FONTS), "size": _number(2, 25), "color": HEX, "activeColor": HEX,
            "weight": _number(400, 900), "x": _number(0, 100), "y": _number(0, 100),
            "maxWidth": _number(10, 100), "align": _enum(["left", "center", "right"]),
            "uppercase": {"type": "boolean"}, "stroke": paint["stroke"], "shadow": paint["shadow"],
            "box": paint["box"], "visibleLines": _enum([1, 2]), "beatPulse": _number(0, 1),
        }, ["font", "size", "color", "activeColor", "x", "y", "maxWidth", "align", "visibleLines"]),
        "source": _object({"kind": _enum(["timing-bundle", "srt", "lrc", "manual"]), "file": _string()}),
    }, ["mode", "lines", "style"])


def _finish() -> dict:
    unit = _number(-1, 1)
    return _object({
        "grade": _object({
            "exposure": unit, "contrast": unit, "saturation": unit, "temperature": unit, "tint": unit,
            "fade": _number(0, 1), "beatFlash": _number(0, 1),
        }, ["exposure", "contrast", "saturation", "temperature", "tint", "fade"]),
        "bloom": _object({
            "amount": _number(0, 1), "threshold": _number(0, 1), "radius": _number(0, 1), "beat": _number(0, 1),
        }, ["amount", "threshold", "radius"]),
        "rays": _object({
            "amount": _number(0, 1), "x": _number(0, 100), "y": _number(0, 100),
            "length": _number(0, 1), "threshold": _number(0, 1),
        }, ["amount", "x", "y", "length", "threshold"]),
        "vignette": _object({"amount": _number(0, 1), "softness": _number(0, 1)}, ["amount", "softness"]),
        "grain": _object({"amount": _number(0, 1), "size": _number(0.5, 4)}, ["amount", "size"]),
        "texture": _object({"kind": _enum(["none", "paper", "film-dust", "scratches"]), "amount": _number(0, 1)}, ["kind", "amount"]),
        "letterbox": _object({"ratio": _enum([1.85, 2, 2.39]), "color": HEX}, ["ratio", "color"]),
        "applyToTexts": {"type": "boolean"},
    })


def _rhythm() -> dict:
    return _object({
        "bpm": _number(40, 240), "beats": _array(_number(), max_items=2000, min_items=1),
        "downbeats": _array(_number(), max_items=2000),
        "energy": _object({"fps": _number(1, 60), "values": _array(_number(), max_items=6000)}, ["fps", "values"]),
    }, ["bpm", "beats"])


def _sfx() -> dict:
    return _array(_object({
        "id": _string(160), "kind": _enum(EFFECT_IDS), "label": _string(80),
        "start": _number(0, 600), "end": _number(0, 600), "x": _number(0, 100), "y": _number(0, 100),
        "size": _number(1, 200), "intensity": _number(0.1, 2), "color": HEX,
        "rotation": _number(-180, 180), "seed": {"type": "integer", "minimum": 1, "maximum": 1000000},
        "sound": {"type": "boolean"}, "volume": _number(0, 1),
    }, ["id", "kind", "start", "end"]), max_items=64)


def _lip_sync() -> dict:
    cue = _object({
        "start": _number(0, 90), "end": {"type": "number", "exclusiveMinimum": 0, "maximum": 90.1},
        "viseme": _enum(["rest", "M", "I", "E", "A", "O", "U", "F", "L"]), "manual": {"const": True},
    }, ["start", "end", "viseme"])
    return _object({
        "version": {"const": 1}, "driver": _enum(["phonetic", "pocketSphinx", "energy"]),
        "text": _string(4000), "audioTrackId": _string(120), "filename": _string(1200),
        "offset": _number(0, 600), "duration": {"type": "number", "exclusiveMinimum": 0, "maximum": 90},
        "cues": _array(cue, max_items=10000),
    }, ["version", "driver", "text", "audioTrackId", "filename", "offset", "duration", "cues"])


def _catalog_asset() -> dict:
    return _object({
        "assetId": _string(), "workspaceId": _string(), "filename": _string(),
        "metadataStatus": {"const": "canonical"}, "originTool": _string(),
        "provider": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "modelId": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "runId": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "taskId": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    }, ["assetId", "workspaceId", "filename", "metadataStatus", "originTool"])


def _narrative() -> dict:
    asset = _object({
        "slot": _string(), "source": _string(), "name": _string(), "type": _enum(LAYER_TYPES),
        "catalogAtAssignment": _catalog_asset(),
    }, ["slot", "source"])
    return _object({
        "templateId": _string(),
        "controls": {"type": "object", "additionalProperties": {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]}},
        "category": _string(), "visualIntent": _string(), "referenceMotion": _string(),
        "evaluationCues": _array(_string()), "assets": _array(asset), "prompt": _string(),
    }, ["templateId", "controls"])


def _document_properties() -> dict:
    return {
        "sfx": _sfx(),
        "texts": _texts(),
        "lyrics": _lyrics(),
        "finish": _finish(),
        "rhythm": _rhythm(),
        "version": {"const": 1},
        "name": _string(),
        "generationPolicy": _enum(["auto", "no_video_generation", "provided_only"]),
        "width": _number(0, exclusive_low=True),
        "height": _number(0, exclusive_low=True),
        "fps": _enum([24, 30, 60]),
        "duration": {"type": "number", "exclusiveMinimum": 0, "maximum": 600},
        "layers": _array(_layer(), max_items=500),
        "audioTracks": _array(_object({
            "id": _string(), "filename": _string(), "name": _string(),
            "kind": _enum(["speech", "music", "sfx", "audio"]),
            "startTime": _number(0), "volume": _number(0, 2), "prompt": _string(), "model": _string(),
        }, ["id", "filename", "name", "kind", "startTime", "volume"])),
        "dialogueBeats": _array(_object({
            "id": _string(), "text": _string(), "start": _number(), "end": _number(),
            "mouthLayerIds": _array(_string()), "audioTrackId": _string(),
            "confidence": _enum(["known-text", "aligned-audio", "energy-fallback"]),
            "lipSync": _lip_sync(),
        }, ["id", "text", "start", "end", "mouthLayerIds", "confidence"])),
        "composition": _object({
            "showGrid": {"type": "boolean"}, "gridSize": _number(), "snap": {"type": "boolean"},
            "safeArea": _enum(["none", "action", "title", "vertical", "all"]),
        }, ["showGrid", "gridSize", "snap", "safeArea"]),
        "copilotAudit": _array(_object({
            "id": _string(), "createdAt": _string(), "scope": _enum(["layer", "scene"]),
            "selectedLayerId": _string(), "intent": _string(), "summary": _string(),
            "operations": _array({"type": "object", "additionalProperties": True}),
            "validation": {"const": "applied"}, "model": _string(),
        }, ["id", "createdAt", "scope", "intent", "summary", "operations", "validation"])),
        "narrative": _narrative(),
    }


DOCUMENT_SCHEMA = _object(
    _document_properties(),
    ["version", "name", "width", "height", "duration", "layers"],
)
DOCUMENT_SCHEMA["$schema"] = "https://json-schema.org/draft/2020-12/schema"
DOCUMENT_SCHEMA["$id"] = "https://hocuspocus.local/schemas/video2d-document-v1.json"
DOCUMENT_SCHEMA["description"] = (
    "Version 1 Video 2D scene. Known keys are listed; additional properties are kept "
    "so a later editor field still loads. scenes.document.save also accepts a Video 3D slots document."
)


def document_schema() -> dict:
    return deepcopy(DOCUMENT_SCHEMA)


__all__ = ["DOCUMENT_SCHEMA", "EFFECT_IDS", "FONTS", "LAYER_TYPES", "document_schema"]

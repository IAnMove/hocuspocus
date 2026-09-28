"""Compile Video 2D templates and lyrics through the UI builders.

Catalog ids are checked here before Node starts. The script returns a document
or cues and does not save, export, or use the GPU.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from services.video2d_catalogs import CATALOGS

BRIDGE_TIMEOUT = 30
UI_ROOT = Path(__file__).resolve().parents[2] / "ui"
TSX = UI_ROOT / "node_modules" / "tsx" / "dist" / "cli.mjs"
SCRIPT = UI_ROOT / "scripts" / "video2d-compile.ts"
OPERATIONS = ("scenes.template.compile", "scenes.text.template", "scenes.lyrics.import")
LYRIC_FORMATS = ("srt", "lrc", "plain", "timing-bundle")
FRAME_RATES = (24, 30, 60)
FIELDS = {
    "scenes.template.compile": frozenset({"templateId", "controls", "assets", "width", "height", "duration", "fps"}),
    "scenes.text.template": frozenset({"templateId", "fields", "start", "duration", "width", "height"}),
    "scenes.lyrics.import": frozenset({"format", "text", "duration"}),
}
REQUIRED = {
    "scenes.template.compile": frozenset({"templateId"}),
    "scenes.text.template": frozenset({"templateId"}),
    "scenes.lyrics.import": frozenset({"format", "text"}),
}
DESCRIPTIONS = {
    "scenes.template.compile": (
        "Compile one scene template with the UI TypeScript builders. assets maps slot id to a durable "
        "source. Returns result.document and result.warnings. template_unknown and template_missing_slot "
        "are stable errors. Does not save or export. No GPU."
    ),
    "scenes.text.template": (
        "Build kinetic text cues with buildTextTemplate. Returns result.texts. "
        "text_template_unknown is a stable error. Does not save or export. No GPU."
    ),
    "scenes.lyrics.import": (
        "Import srt, lrc, plain, or timing-bundle text with the UI lyrics parser. Returns result.lyrics "
        "in the scene document shape. lyrics_bad_format and lyrics_bad_file are stable errors. "
        "Does not save, export, or fetch the network. No GPU."
    ),
}
_SOURCE_PREFIXES = ("javascript:", "blob:", "file:", "filesystem:")


class CompileError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _number(value: Any, *, low: float, high: float, code: str, label: str, integer: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompileError(code, label)
    if integer and type(value) is not int:
        raise CompileError(code, label)
    if not low <= value <= high:
        raise CompileError(code, label)
    return value


def _find(operation: str, item_id: str) -> dict | None:
    catalog = CATALOGS[operation]
    entries = catalog["entries"] if isinstance(catalog, dict) else catalog
    for item in entries:
        if item.get("id") == item_id:
            return item
    return None


def _envelope(command: Any) -> tuple[str, dict]:
    if not isinstance(command, dict) or set(command) != {"version", "operation", "input"}:
        raise CompileError("compile_bad_envelope", "Expected version, operation and input only")
    if type(command["version"]) is not int or command["version"] != 1:
        raise CompileError("compile_bad_envelope", "Expected version 1")
    name = command["operation"]
    data = command["input"]
    if type(name) is not str or name not in FIELDS or not isinstance(data, dict):
        raise CompileError("compile_bad_envelope", "Unknown compile operation")
    if set(data) - FIELDS[name] or REQUIRED[name] - set(data):
        raise CompileError("compile_bad_envelope", "Unexpected or missing input fields")
    return name, data


def _durable(source: str) -> bool:
    text = source.strip()
    if not text or len(text) > 2_000_000:
        return False
    lowered = text.lower()
    if lowered.startswith(_SOURCE_PREFIXES):
        return False
    if lowered.startswith("data:image/") or lowered.startswith("data:model/gltf-binary;"):
        return True
    if text.startswith("/api/v1/"):
        return True
    return lowered.startswith("https://") or lowered.startswith("http://")


def _assets(template: dict, raw: Any) -> dict[str, str]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or len(raw) > 16:
        raise CompileError("template_bad_asset", "assets")
    known = {slot.get("id") for slot in template.get("slots") or []}
    assets: dict[str, str] = {}
    for slot_id, source in raw.items():
        if type(slot_id) is not str or slot_id not in known or type(source) is not str:
            raise CompileError("template_bad_asset", str(slot_id))
        if not source.strip():
            continue
        if not _durable(source):
            raise CompileError("template_bad_asset", slot_id)
        assets[slot_id] = source.strip()
    return assets


def _missing_slot(template: dict, assets: dict[str, str]) -> str | None:
    for slot in template.get("slots") or []:
        if not slot.get("required"):
            continue
        source = assets.get(slot.get("id"))
        if not isinstance(source, str) or not source.strip():
            return str(slot.get("id") or "slot")
    return None


def _control_value(key: str, value: Any, spec: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isinstance(spec, dict):
        raise CompileError("template_bad_control", key)
    low, high = spec.get("min"), spec.get("max")
    if isinstance(low, bool) or isinstance(high, bool) or not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        raise CompileError("template_bad_control", key)
    if not low <= value <= high:
        raise CompileError("template_bad_control", key)


def _control_map(data: dict) -> dict:
    raw = data.get("controls", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise CompileError("template_bad_control", "controls")
    return raw


def _with_duration(data: dict, declared: dict, raw: dict) -> dict:
    if "duration" in data and "duration" in raw and raw["duration"] != data["duration"]:
        raise CompileError("template_bad_control", "duration")
    if "duration" not in data or "duration" not in declared or "duration" in raw:
        return raw
    return {**raw, "duration": data["duration"]}


def _declared_controls(declared: dict, provided: dict) -> dict[str, float]:
    controls: dict[str, float] = {}
    for key, spec in declared.items():
        if key in provided:
            value = provided[key]
        elif isinstance(spec, dict):
            value = spec.get("default")
        else:
            value = None
        _control_value(str(key), value, spec)
        controls[str(key)] = value
    return controls


def _reject_extra_controls(declared: dict, provided: dict) -> None:
    for key in provided:
        if key not in declared:
            raise CompileError("template_bad_control", str(key))


def _controls(template: dict, data: dict) -> dict[str, float]:
    declared = template.get("controls") or {}
    if not isinstance(declared, dict):
        raise CompileError("template_bad_control", "controls")
    provided = _with_duration(data, declared, _control_map(data))
    _reject_extra_controls(declared, provided)
    return _declared_controls(declared, provided)


def _frame(data: dict) -> None:
    if "width" in data:
        _number(data["width"], low=64, high=7680, code="template_bad_frame", label="width", integer=True)
    if "height" in data:
        _number(data["height"], low=64, high=7680, code="template_bad_frame", label="height", integer=True)
    if "fps" in data and (type(data["fps"]) is not int or data["fps"] not in FRAME_RATES):
        raise CompileError("template_bad_frame", "fps")


def _prepare_template(data: dict) -> dict:
    template_id = data.get("templateId")
    if type(template_id) is not str or not template_id.strip():
        raise CompileError("template_unknown", "templateId")
    template = _find("scenes.templates.catalog", template_id)
    if template is None:
        raise CompileError("template_unknown", template_id)
    _frame(data)
    assets = _assets(template, data.get("assets", {}))
    missing = _missing_slot(template, assets)
    if missing:
        raise CompileError("template_missing_slot", missing)
    controls = _controls(template, data)
    request: dict[str, Any] = {"templateId": template_id, "assets": assets, "controls": controls}
    if "duration" in controls:
        request["duration"] = controls["duration"]
    for key in ("width", "height", "fps"):
        if key in data:
            request[key] = data[key]
    return request


def _text_template(data: dict) -> dict:
    template_id = data.get("templateId")
    if type(template_id) is not str or not template_id.strip():
        raise CompileError("text_template_unknown", "templateId")
    template = _find("scenes.text.catalog", template_id)
    if template is None:
        raise CompileError("text_template_unknown", template_id)
    return template


def _fields(template: dict, raw: Any) -> dict[str, str]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or len(raw) > 12:
        raise CompileError("text_template_bad_field", "fields")
    allowed = {field.get("key") for field in template.get("fields") or []}
    fields: dict[str, str] = {}
    for key, value in raw.items():
        if type(key) is not str or key not in allowed or type(value) is not str or len(value) > 400:
            raise CompileError("text_template_bad_field", str(key))
        fields[key] = value
    return fields


def _prepare_text(data: dict) -> dict:
    template = _text_template(data)
    start = _number(data["start"], low=0, high=600, code="text_template_bad_frame", label="start") if "start" in data else 0
    duration = _number(data["duration"], low=0.05, high=600, code="text_template_bad_frame", label="duration") if "duration" in data else 4
    if start + duration > 600:
        raise CompileError("text_template_bad_frame", "duration")
    request: dict[str, Any] = {"templateId": template["id"], "fields": _fields(template, data.get("fields", {})), "start": start, "duration": duration}
    for key, limit in (("width", 7680), ("height", 7680)):
        if key in data:
            request[key] = _number(data[key], low=64, high=limit, code="text_template_bad_frame", label=key, integer=True)
    return request


def _prepare_lyrics(data: dict) -> dict:
    if data.get("format") not in LYRIC_FORMATS:
        raise CompileError("lyrics_bad_format", "format")
    text = data.get("text")
    if type(text) is not str or not text.strip() or len(text) > 400_000:
        raise CompileError("lyrics_bad_file", "text")
    request: dict[str, Any] = {"format": data["format"], "text": text}
    if "duration" in data:
        request["duration"] = _number(data["duration"], low=0.2, high=3600, code="lyrics_bad_file", label="duration")
    return request


def _prepare(name: str, data: dict) -> dict:
    if name == "scenes.template.compile":
        return _prepare_template(data)
    if name == "scenes.text.template":
        return _prepare_text(data)
    return _prepare_lyrics(data)


def _parse_bridge(stdout: str) -> dict:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise CompileError("compile_bridge_failed", "TypeScript compile returned invalid JSON") from error
    if not isinstance(parsed, dict):
        raise CompileError("compile_bridge_failed", "TypeScript compile returned invalid JSON")
    return parsed


def spawn_bridge(payload: dict) -> dict:
    try:
        completed = subprocess.run(
            ["node", str(TSX), "--tsconfig", "tsconfig.app.json", str(SCRIPT)],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=BRIDGE_TIMEOUT,
            cwd=UI_ROOT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CompileError("compile_bridge_timeout", "TypeScript compile timed out") from error
    except OSError as error:
        raise CompileError("compile_bridge_failed", "TypeScript compile could not start") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "compile failed").strip()
        raise CompileError("compile_bridge_failed", detail[:300])
    return _parse_bridge(completed.stdout)


def _bridge_result(bridged: dict) -> dict:
    if bridged.get("ok") is True and isinstance(bridged.get("result"), dict):
        return bridged["result"]
    code = bridged.get("code")
    if type(code) is not str or not code:
        code = "compile_bridge_failed"
    message = bridged.get("message")
    detail = message if type(message) is str and message else "Compile failed"
    raise CompileError(code, detail[:500])


def _shape(name: str, result: dict) -> dict:
    if name == "scenes.template.compile":
        document, warnings = result.get("document"), result.get("warnings")
        if not isinstance(document, dict) or not isinstance(warnings, list):
            raise CompileError("compile_bridge_failed", "document")
        return {"document": document, "warnings": [str(item) for item in warnings[:20]]}
    if name == "scenes.text.template":
        texts = result.get("texts")
        if not isinstance(texts, list):
            raise CompileError("compile_bridge_failed", "texts")
        return {"texts": texts}
    lyrics = result.get("lyrics")
    if not isinstance(lyrics, dict):
        raise CompileError("compile_bridge_failed", "lyrics")
    return {"lyrics": lyrics}


def execute(command: Any) -> dict[str, Any]:
    name, data = _envelope(command)
    bridged = spawn_bridge({"operation": name, "input": _prepare(name, data)})
    return {"version": 1, "status": "completed", "operation": name, "result": _shape(name, _bridge_result(bridged))}


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "version": {"type": "integer", "const": 1},
            "input": {"type": "object", "additionalProperties": False, "properties": properties, "required": required},
        },
        "required": ["version", "input"],
    }


def command_catalog() -> list[dict[str, Any]]:
    number = {"type": "number"}
    size = {"type": "integer", "minimum": 64, "maximum": 7680}
    template_input = {
        "templateId": {"type": "string", "minLength": 1},
        "controls": {"type": "object", "additionalProperties": number},
        "assets": {"type": "object", "additionalProperties": {"type": "string"}},
        "width": size, "height": size,
        "duration": {"type": "number", "minimum": 3, "maximum": 12},
        "fps": {"type": "integer", "enum": [24, 30, 60]},
    }
    text_input = {
        "templateId": {"type": "string", "minLength": 1},
        "fields": {"type": "object", "additionalProperties": {"type": "string", "maxLength": 400}},
        "start": {"type": "number", "minimum": 0, "maximum": 600},
        "duration": {"type": "number", "exclusiveMinimum": 0, "maximum": 600},
        "width": size, "height": size,
    }
    lyrics_input = {
        "format": {"type": "string", "enum": list(LYRIC_FORMATS)},
        "text": {"type": "string", "minLength": 1, "maxLength": 400000},
        "duration": {"type": "number", "minimum": 0.2, "maximum": 3600},
    }
    specs = {
        "scenes.template.compile": (template_input, ["templateId"]),
        "scenes.text.template": (text_input, ["templateId"]),
        "scenes.lyrics.import": (lyrics_input, ["format", "text"]),
    }
    return [{
        "name": name,
        "description": DESCRIPTIONS[name],
        "mutation": False,
        "inputSchema": _schema(properties, required),
    } for name, (properties, required) in specs.items()]


def command_handlers() -> dict[str, Callable[[Any], Any]]:
    def handler(name: str) -> Callable[[Any], Any]:
        async def handle(arguments: Any) -> dict[str, Any]:
            from fastapi import HTTPException
            from starlette.concurrency import run_in_threadpool

            payload = arguments if isinstance(arguments, dict) else {}
            try:
                return await run_in_threadpool(execute, {**payload, "operation": name})
            except CompileError as error:
                raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error

        return handle

    return {name: handler(name) for name in OPERATIONS}


__all__ = [
    "CompileError",
    "command_catalog",
    "command_handlers",
    "execute",
    "spawn_bridge",
]

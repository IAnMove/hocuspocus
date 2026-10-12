"""Compile Video 2D templates and lyrics through the UI builders.

Catalog ids are checked here before Node starts. The script returns a document
or cues and does not save, export, or use the GPU. Template inputs follow the
2026-10-12 model (docs/development/VIDEO2D_TEMPLATE_MODEL.md): an alias id
compiles as its card with a control preset, a retired id names what to use
instead, old slot names translate once, and controls are numbers, choices or
texts checked as the TypeScript compile checks them.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from services import resource_scheduler
from services.mcp_compact import compact_compile
from services.resource_scheduler import ResourceAcquireCancelled
from services.video2d_catalogs import CATALOGS

BRIDGE_TIMEOUT = 30
UI_ROOT = Path(__file__).resolve().parents[2] / "ui"
TSX = UI_ROOT / "node_modules" / "tsx" / "dist" / "cli.mjs"
SCRIPT = UI_ROOT / "scripts" / "video2d-compile.ts"
OPERATIONS = ("scenes.template.compile", "scenes.text.template", "scenes.lyrics.import")
LYRIC_FORMATS = ("srt", "lrc", "plain", "timing-bundle")
FRAME_RATES = (24, 30, 60)
FIELDS = {
    "scenes.template.compile": frozenset({"templateId", "controls", "assets", "width", "height", "duration", "fps", "full"}),
    "scenes.text.template": frozenset({"templateId", "fields", "start", "duration", "width", "height", "full"}),
    "scenes.lyrics.import": frozenset({"format", "text", "duration", "full"}),
}
REQUIRED = {
    "scenes.template.compile": frozenset({"templateId"}),
    "scenes.text.template": frozenset({"templateId"}),
    "scenes.lyrics.import": frozenset({"format", "text"}),
}
DESCRIPTIONS = {
    "scenes.template.compile": (
        "Compile one scene template with the UI TypeScript builders. assets maps slot id (subject_1, subject_2, "
        "background, prop_1, prop_2, foreground; old hero/plate/prop are translated) to a durable source; a "
        "background may be a looping video. controls are numbers, choices or texts the card declares. An alias id "
        "compiles as its card with a preset. Default result is layer ids, text ids, warning codes (cutout_without_alpha), "
        "duration and size. Pass full true for result.document and result.warnings. template_unknown, "
        "template_retired (with use_instead), template_missing_slot, template_bad_control and slot_alias_conflict "
        "are stable errors. Does not save or export. No GPU."
    ),
    "scenes.text.template": (
        "Build kinetic text cues with buildTextTemplate. Default result is text ids and textCount. "
        "Pass full true for result.texts. text_template_unknown is a stable error. Does not save or export. No GPU."
    ),
    "scenes.lyrics.import": (
        "Import srt, lrc, plain, or timing-bundle text with the UI lyrics parser. Default result is "
        "line ids, duration and lineCount. Pass full true for result.lyrics. lyrics_bad_format and "
        "lyrics_bad_file are stable errors. Does not save, export, or fetch the network. No GPU."
    ),
}
_SOURCE_PREFIXES = ("javascript:", "blob:", "file:", "filesystem:")
# Same reading as slotType in ui/scripts/video2dCompile.ts.
_MODEL_SOURCE = re.compile(r"^data:model/gltf-binary;|\.glb(?:$|[?#])", re.IGNORECASE)
_VIDEO_SOURCE = re.compile(r"^data:video/|\.(?:mp4|webm|mov|m4v)(?:$|[?#])", re.IGNORECASE)
_WORKSPACE_NAME = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)")
# Cutout slots of the choreographies: a picture without a transparent pixel shows its rectangle.
CUTOUT_SLOTS = ("subject_1", "subject_2", "prop_1")

WorkspaceDir = Callable[[Any], str]


class CompileError(ValueError):
    def __init__(self, code: str, detail: str, **extra: Any) -> None:
        self.code = code
        self.extra = extra
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
    if text.startswith("/api/v1/") or lowered.startswith("/examples/"):
        return True
    return lowered.startswith("https://") or lowered.startswith("http://")


def _templates() -> dict:
    return CATALOGS["scenes.templates.catalog"]


def _resolve(template_id: str) -> tuple[dict, dict, str | None]:
    """The card for a card id or an alias id, the alias's control preset, and the alias (None for a card)."""
    retired = (_templates().get("retired") or {}).get(template_id)
    if isinstance(retired, dict):
        note = str(retired.get("note") or "")
        raise CompileError("template_retired", f"{template_id} is retired. {note}".strip(), use_instead=list(retired.get("useInstead") or []))
    alias = (_templates().get("aliases") or {}).get(template_id)
    template = _find("scenes.templates.catalog", alias["card"] if isinstance(alias, dict) else template_id)
    if template is None:
        raise CompileError("template_unknown", template_id)
    if not isinstance(alias, dict):
        return template, {}, None
    return template, dict(alias.get("preset") or {}), template_id


def _slots(template: dict) -> dict[str, dict]:
    return {slot.get("id"): slot for slot in template.get("slots") or [] if isinstance(slot, dict)}


def canonical_slot(template: dict, name: str) -> str | None:
    """The card's slot for a new or an old slot name (hero, plate, prop), or None when the card has no such slot."""
    aliases = {**(_templates().get("slotAliases") or {}), **(template.get("slotAliases") or {})}
    slot = aliases.get(name, name)
    return slot if slot in _slots(template) else None


def slot_type(source: str, kinds: list) -> str:
    """The asset type a source declares by its MIME or extension."""
    if _MODEL_SOURCE.search(source):
        return "model3d"
    if _VIDEO_SOURCE.search(source):
        return "video"
    if len(kinds) == 1 and kinds[0] != "image":
        return str(kinds[0])
    return "image"


def _asset_source(template: dict, slot_id: str, source: str) -> str:
    if not _durable(source):
        raise CompileError("template_bad_asset", slot_id)
    kinds = _slots(template)[slot_id].get("types") or []
    if slot_type(source.strip(), kinds) not in kinds:
        raise CompileError("template_bad_asset", slot_id)
    return source.strip()


def _assets(template: dict, raw: Any) -> dict[str, str]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or len(raw) > 16:
        raise CompileError("template_bad_asset", "assets")
    assets: dict[str, str] = {}
    named: dict[str, str] = {}
    for name, source in raw.items():
        slot_id = canonical_slot(template, name) if type(name) is str else None
        if slot_id is None or type(source) is not str:
            raise CompileError("template_bad_asset", str(name))
        if slot_id in named:
            raise CompileError("slot_alias_conflict", f"{named[slot_id]} and {name} name the same slot {slot_id}")
        named[slot_id] = name
        if source.strip():
            assets[slot_id] = _asset_source(template, slot_id, source)
    return assets


def _required(slot: dict, controls: dict) -> bool:
    when = slot.get("requiredWhen")
    if isinstance(when, dict) and when:
        return bool(slot.get("required")) or all(controls.get(key) == value for key, value in when.items())
    return bool(slot.get("required"))


def _missing_slot(template: dict, assets: dict[str, str], controls: dict) -> str | None:
    for slot in template.get("slots") or []:
        if not _required(slot, controls):
            continue
        source = assets.get(slot.get("id"))
        if not isinstance(source, str) or not source.strip():
            return str(slot.get("id") or "slot")
    return None


def _choice_or_text(key: str, value: Any, spec: dict) -> bool:
    """Checks a choice or text control; False when the spec is numeric."""
    if "options" in spec:
        if type(value) is not str or value not in (spec.get("options") or []):
            raise CompileError("template_bad_control", key)
        return True
    if spec.get("text") is True:
        limit = spec.get("maxLength")
        if type(value) is not str or type(limit) is not int or len(value) > limit:
            raise CompileError("template_bad_control", key)
        return True
    return False


def _control_value(key: str, value: Any, spec: Any) -> None:
    if not isinstance(spec, dict):
        raise CompileError("template_bad_control", key)
    if _choice_or_text(key, value, spec):
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
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


def _declared_controls(declared: dict, provided: dict, preset: dict) -> dict[str, Any]:
    """Every control of the card: the caller's value, else the alias preset, else the card default."""
    controls: dict[str, Any] = {}
    for key, spec in declared.items():
        if key in provided:
            value = provided[key]
        elif key in preset:
            value = preset[key]
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


def _controls(template: dict, data: dict, preset: dict | None = None) -> dict[str, Any]:
    declared = template.get("controls") or {}
    if not isinstance(declared, dict):
        raise CompileError("template_bad_control", "controls")
    provided = _with_duration(data, declared, _control_map(data))
    _reject_extra_controls(declared, provided)
    return _declared_controls(declared, provided, preset or {})


def _frame(data: dict) -> None:
    if "width" in data:
        _number(data["width"], low=64, high=7680, code="template_bad_frame", label="width", integer=True)
    if "height" in data:
        _number(data["height"], low=64, high=7680, code="template_bad_frame", label="height", integer=True)
    if "fps" in data and (type(data["fps"]) is not int or data["fps"] not in FRAME_RATES):
        raise CompileError("template_bad_frame", "fps")


def _default_workspace_dir(name: Any) -> str:
    """The workspace folder under ./outputs, without creating it: a compile only reads."""
    from services import core_workspace

    chosen = core_workspace.active_workspace() if name is None else name
    if type(chosen) is not str or not _WORKSPACE_NAME.fullmatch(chosen):
        raise ValueError("workspace")
    base = (core_workspace.root() / "outputs").resolve()
    return str(base if chosen == "default" else base / chosen)


def _example_path(name: str) -> Path | None:
    from services.example_assets import example_assets

    try:
        example_assets.entry(name)
        return example_assets.cached(name)
    except (KeyError, OSError):
        return None


def _workspace_path(address: Any, workspace_dir: WorkspaceDir) -> Path | None:
    name = unquote(address.path[len("/api/v1/file/"):])
    workspace = (parse_qs(address.query).get("workspace") or [None])[0]
    try:
        root = Path(workspace_dir(workspace)).resolve()
    except Exception:  # noqa: BLE001 - the runtime resolver raises HTTPException for a bad name
        return None
    candidate = root.joinpath(*name.split("/")).resolve()
    return candidate if candidate.is_relative_to(root) and candidate.is_file() else None


def _picture(source: str, workspace_dir: WorkspaceDir) -> Any:
    """A local or inline picture as a file path or bytes; None for remote or unreadable sources (never fetched)."""
    if source.lower().startswith("data:image/"):
        header, _, payload = source.partition(",")
        if ";base64" not in header.lower():
            return None
        try:
            return io.BytesIO(base64.b64decode(payload))
        except (ValueError, binascii.Error):
            return None
    address = urlparse(source)
    if address.path.startswith("/api/v1/file/"):
        return _workspace_path(address, workspace_dir)
    if address.path.startswith("/examples/"):
        return _example_path(unquote(address.path[len("/examples/"):]))
    return None


def has_transparency(source: str, workspace_dir: WorkspaceDir = _default_workspace_dir) -> bool | None:
    """True when the picture has a transparent pixel, False when it has none (a JPEG never does), None when it
    cannot be read here."""
    picture = _picture(source, workspace_dir)
    if picture is None:
        return None
    try:
        from PIL import Image

        with Image.open(picture) as image:
            if "transparency" in image.info:
                image = image.convert("RGBA")
            if "A" not in image.getbands():
                return False
            return image.getchannel("A").getextrema()[0] < 255
    except Exception:  # noqa: BLE001 - an unreadable picture is not a compile error
        return None


def _alpha_warnings(template: dict, assets: dict[str, str], workspace_dir: WorkspaceDir) -> list[dict]:
    if template.get("group") != "music-motion":
        return []
    warnings = []
    for slot_id in CUTOUT_SLOTS:
        source = assets.get(slot_id)
        if source and has_transparency(source, workspace_dir) is False:
            warnings.append({
                "code": "cutout_without_alpha", "slot": slot_id,
                "message": f"{slot_id} has no transparent pixel: the cutout will show its rectangle.",
            })
    return warnings


def _template_id(data: dict) -> str:
    template_id = data.get("templateId")
    if type(template_id) is not str or not template_id.strip():
        raise CompileError("template_unknown", "templateId")
    return template_id


def prepare_template(data: dict, *, workspace_dir: WorkspaceDir | None = None) -> dict:
    """Check one scenes.template.compile input before Node starts.

    Returns ``request`` (what the TypeScript bridge compiles: assets under the new slot names, every control
    resolved with the alias preset), ``card`` (the card id), ``alias`` (the alias id or None) and ``warnings``
    (``cutout_without_alpha``). Production calls it for scene2d shots, so both paths check the same way.
    """
    template_id = _template_id(data)
    template, preset, alias = _resolve(template_id)
    _frame(data)
    assets = _assets(template, data.get("assets", {}))
    controls = _controls(template, data, preset)
    missing = _missing_slot(template, assets, controls)
    if missing:
        raise CompileError("template_missing_slot", missing)
    request: dict[str, Any] = {"templateId": template_id, "assets": assets, "controls": controls}
    if "duration" in controls:
        request["duration"] = controls["duration"]
    for key in ("width", "height", "fps"):
        if key in data:
            request[key] = data[key]
    warnings = _alpha_warnings(template, assets, workspace_dir or _default_workspace_dir)
    return {"request": request, "card": template["id"], "alias": alias, "warnings": warnings}


def _prepare_template(data: dict) -> dict:
    return prepare_template(data)["request"]


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


def _run_bridge(payload: dict) -> dict:
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


def spawn_bridge(payload: dict) -> dict:
    """Run one TypeScript compile on the video2d-compile CPU lane (one at a time)."""
    try:
        with resource_scheduler.coordinator.acquire(
            resource_scheduler.cpu_lane("video2d-compile"),
            task_id=f"video2d-compile-{uuid.uuid4().hex}",
            description="Video 2D TypeScript compile",
        ):
            return _run_bridge(payload)
    except ResourceAcquireCancelled as error:
        raise CompileError("compile_bridge_timeout", "TypeScript compile timed out") from error


def _bridge_result(bridged: dict) -> dict:
    if bridged.get("ok") is True and isinstance(bridged.get("result"), dict):
        return bridged["result"]
    code = bridged.get("code")
    if type(code) is not str or not code:
        code = "compile_bridge_failed"
    message = bridged.get("message")
    detail = message if type(message) is str and message else "Compile failed"
    raise CompileError(code, detail[:500])


def warning_text(item: Any) -> str:
    """One compile warning as text: ``code:slot`` for a structured one (``cutout_without_alpha:subject_2``)."""
    if isinstance(item, dict):
        code, slot = str(item.get("code") or "warning"), item.get("slot")
        return f"{code}:{slot}" if slot else code
    return str(item)


def _shape(name: str, result: dict, early: list[dict] | None = None) -> dict:
    if name == "scenes.template.compile":
        document, warnings = result.get("document"), result.get("warnings")
        if not isinstance(document, dict) or not isinstance(warnings, list):
            raise CompileError("compile_bridge_failed", "document")
        # One shape for every warning: the bridge's plain ones become {"code": ...} next to the structured alpha ones.
        bridged = [item if isinstance(item, dict) else {"code": str(item)} for item in warnings]
        return {"document": document, "warnings": [*(early or []), *bridged][:20]}
    if name == "scenes.text.template":
        texts = result.get("texts")
        if not isinstance(texts, list):
            raise CompileError("compile_bridge_failed", "texts")
        return {"texts": texts}
    lyrics = result.get("lyrics")
    if not isinstance(lyrics, dict):
        raise CompileError("compile_bridge_failed", "lyrics")
    return {"lyrics": lyrics}


def execute(command: Any, *, workspace_dir: WorkspaceDir | None = None) -> dict[str, Any]:
    name, raw = _envelope(command)
    data = dict(raw)
    full = data.pop("full", False)
    if type(full) is not bool:
        raise CompileError("compile_bad_envelope", "full")
    warnings: list[dict] = []
    if name == "scenes.template.compile":
        prepared = prepare_template(data, workspace_dir=workspace_dir)
        request, warnings = prepared["request"], prepared["warnings"]
    else:
        request = _prepare(name, data)
    bridged = spawn_bridge({"operation": name, "input": request})
    shaped = _shape(name, _bridge_result(bridged), warnings)
    if full is not True:
        shaped = compact_compile(name, shaped)
    return {"version": 1, "status": "completed", "operation": name, "result": shaped}


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
    size = {"type": "integer", "minimum": 64, "maximum": 7680}
    template_input = {
        "templateId": {"type": "string", "minLength": 1},
        "controls": {"type": "object", "additionalProperties": {"type": ["number", "string"]}},
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
        "inputSchema": _schema({**properties, "full": {"type": "boolean"}}, required),
    } for name, (properties, required) in specs.items()]


def command_handlers(workspace_dir: WorkspaceDir | None = None) -> dict[str, Callable[[Any], Any]]:
    """MCP handlers; ``workspace_dir`` resolves /api/v1/file sources for the alpha check (default: ./outputs)."""
    def handler(name: str) -> Callable[[Any], Any]:
        async def handle(arguments: Any) -> dict[str, Any]:
            from fastapi import HTTPException
            from starlette.concurrency import run_in_threadpool

            payload = arguments if isinstance(arguments, dict) else {}
            try:
                return await run_in_threadpool(execute, {**payload, "operation": name}, workspace_dir=workspace_dir)
            except CompileError as error:
                detail = {"code": error.code, "message": str(error), "retryable": False, **error.extra}
                raise HTTPException(422, detail) from error

        return handle

    return {name: handler(name) for name in OPERATIONS}


__all__ = [
    "CUTOUT_SLOTS",
    "CompileError",
    "canonical_slot",
    "command_catalog",
    "command_handlers",
    "execute",
    "has_transparency",
    "prepare_template",
    "slot_type",
    "spawn_bridge",
]

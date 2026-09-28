#!/usr/bin/env python3
"""Drive a 20s Video 2D scene through the versioned MCP envelopes. No GPU.

The envelopes are the arguments the MCP handlers accept (version 1 and input,
plus intent_id when that handler requires it). Handlers add the operation name.
scenes.video2d.edit is not on this branch, so finish is copied from the finish
catalog onto the document after compile.
"""
from __future__ import annotations

import argparse
import asyncio
import http.server
import inspect
import json
import mimetypes
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
APP = REPO / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

SCENE_SECONDS = 20
COMPILE_FPS = 24
FRAME = (480, 270)
WORKSPACE = "video2d-smoke"
INTENT = "video2d-smoke-export"
EXPORT_DEADLINE = 15 * 60
PREFERRED = ("documentary-history", "cinema-establishing")
TEXT_TEMPLATE = "chapter"
FINISH_ID = "oldDoc"
EFFECT_ID = "rain"
PIXEL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
DEFAULT_SHEET = Path("/tmp/hocus-mcp-video2d-m9-contact.png")
PLANNED = (
    "scenes.catalog",
    "scenes.template.compile",
    "scenes.text.template",
    "scenes.lyrics.import",
    "scenes.finish.catalog",
    "scenes.effects.apply",
    "scenes.video2d.validate",
    "scenes.video2d.preview",
    "scenes.document.save",
    "scenes.video2d.export",
    "scenes.video2d.export.receipt",
    "montages.save",
)
Handler = Callable[[Any], Any]


class SmokeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _published() -> list[dict[str, Any]]:
    from services.montage_commands import command_catalog as montages
    from services.scene2d_export import command_catalog as export_catalog
    from services.scene2d_validate import command_catalog as validate_catalog
    from services.scene_commands import command_catalog as effects
    from services.scene_documents import command_catalog as documents
    from services.video2d_catalogs import command_catalog as catalogs
    from services.video2d_catalogs import query_operation
    from services.video2d_compile import command_catalog as compile_catalog
    from services.video2d_preview import command_catalog as preview_catalog

    return [
        *effects(), *catalogs(), query_operation(), *compile_catalog(), *preview_catalog(),
        *validate_catalog(), *documents(), *export_catalog(), *montages(),
    ]


def _schema(name: str) -> dict[str, Any]:
    for item in _published():
        if item.get("name") == name:
            schema = item.get("inputSchema")
            return schema if isinstance(schema, dict) else {}
    return {}


def _input_required(name: str) -> list[str]:
    inner = (_schema(name).get("properties") or {}).get("input") or {}
    required = inner.get("required") if isinstance(inner, dict) else None
    return [key for key in required or [] if isinstance(key, str)]


def _top_required(name: str) -> list[str]:
    required = _schema(name).get("required") or []
    return [key for key in required if key not in {"version", "operation", "input"}]


def _sample_document() -> dict[str, Any]:
    width, height = FRAME
    return {
        "version": 1, "name": "smoke", "width": width, "height": height,
        "fps": COMPILE_FPS, "duration": SCENE_SECONDS, "layers": [],
    }


def sample_envelopes() -> dict[str, dict[str, Any]]:
    """Versioned MCP arguments for every planned call. Not executed."""
    document = _sample_document()
    width, height = FRAME
    return {
        "scenes.catalog": {"version": 1, "input": {"kind": "templates"}},
        "scenes.template.compile": {"version": 1, "input": {
            "templateId": PREFERRED[0], "duration": SCENE_SECONDS, "width": width, "height": height, "fps": COMPILE_FPS,
        }},
        "scenes.text.template": {"version": 1, "input": {"templateId": TEXT_TEMPLATE}},
        "scenes.lyrics.import": {"version": 1, "input": {"format": "plain", "text": "Harbour light"}},
        "scenes.finish.catalog": {"version": 1, "input": {}},
        "scenes.effects.apply": {"version": 1, "input": {"document": document, "cues": [{
            "id": "smoke-rain", "kind": EFFECT_ID, "start": 2, "end": 6,
        }]}},
        "scenes.video2d.validate": {"version": 1, "input": {"workspace": WORKSPACE, "document": document}},
        "scenes.video2d.preview": {"version": 1, "input": {"document": document, "times": [0, 1]}},
        "scenes.document.save": {"version": 1, "input": {"workspace": WORKSPACE, "document": document}},
        "scenes.video2d.export": {
            "version": 1, "intent_id": INTENT, "input": {"workspace": WORKSPACE, "document": document},
        },
        "scenes.video2d.export.receipt": {"version": 1, "input": {"workspace": WORKSPACE, "intent_id": INTENT}},
        "montages.save": {"version": 1, "input": {
            "workspace": WORKSPACE,
            "montage": {"version": 1, "name": "smoke", "clips": [{"source": "/api/v1/file/scene.scene.json"}]},
        }},
    }


def _envelope_problems(name: str, envelope: dict[str, Any] | None) -> list[str]:
    if not isinstance(envelope, dict):
        return [f"{name} has no sample envelope"]
    problems = []
    if envelope.get("version") != 1 or not isinstance(envelope.get("input"), dict):
        problems.append(f"{name} envelope is not version 1 with input")
    if "operation" in envelope:
        problems.append(f"{name} must leave the operation on the tool name")
    missing = [key for key in _input_required(name) if key not in envelope["input"]]
    if missing:
        problems.append(f"{name} missing input fields: {', '.join(missing)}")
    missing_top = [key for key in _top_required(name) if key not in envelope]
    if missing_top:
        problems.append(f"{name} missing envelope fields: {', '.join(missing_top)}")
    return problems


def dry_problems() -> list[str]:
    """Check that each planned call has a versioned envelope and a published operation."""
    known = {item.get("name") for item in _published()}
    samples = sample_envelopes()
    problems = []
    for name in PLANNED:
        if name not in known:
            problems.append(f"{name} is not published")
        problems.extend(_envelope_problems(name, samples.get(name)))
    return problems


def painter_reason() -> str | None:
    from services.video2d_preview import painter_block_reason
    return painter_block_reason()


def _smoke_error(error: Any) -> SmokeError:
    detail = getattr(error, "detail", error)
    if isinstance(detail, dict):
        code = str(detail.get("code") or getattr(error, "status_code", "failed"))
        return SmokeError(code, str(detail.get("message") or detail))
    return SmokeError(str(getattr(error, "status_code", "failed")), str(detail))


def invoke(handler: Handler, envelope: dict[str, Any]) -> dict[str, Any]:
    from fastapi import HTTPException

    try:
        result = handler(envelope)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
    except HTTPException as error:
        raise _smoke_error(error) from error
    if isinstance(result, dict) and result.get("status") == "failed":
        err = result.get("error") if isinstance(result.get("error"), dict) else {}
        raise SmokeError(str(err.get("code") or "failed"), str(err.get("message") or result))
    if not isinstance(result, dict):
        raise SmokeError("invalid_result", "handler did not return an object")
    return result


def _record(report: dict[str, Any], name: str) -> None:
    report["operations"].append(name)


def _new_report() -> dict[str, Any]:
    return {
        "operations": [], "notes": [], "validate_errors": [], "validate_warnings": [],
        "contact_sheet": "", "scene_file": "", "mp4": "", "mp4_reason": "", "montage_file": "",
        "template_id": "", "duration": SCENE_SECONDS,
    }


def workspace_resolver(root: Path) -> Callable[[str], str]:
    def workspace_dir(name: str) -> str:
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    return workspace_dir


def build_handlers(root: Path) -> dict[str, Handler]:
    from services.montage_commands import MontageCommands
    from services.montage_documents import MontageStore
    from services.scene2d_validate import command_handlers as validate_handlers
    from services.scene_commands import SceneCommands
    from services.scene_documents import command_handlers as document_handlers
    from services.video2d_catalogs import command_handlers as catalog_handlers
    from services.video2d_catalogs import query_handlers
    from services.video2d_compile import command_handlers as compile_handlers
    from services.video2d_preview import command_handlers as preview_handlers

    resolve = workspace_resolver(root)
    uploads = root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    store = MontageStore(resolve)
    montage = MontageCommands(store, start_export=lambda _body: {"job_id": "unused"}, get_export=lambda _job: {})
    handlers: dict[str, Handler] = {}
    handlers.update(catalog_handlers())
    handlers.update(query_handlers())
    handlers.update(compile_handlers())
    handlers.update(preview_handlers(workspace_dir=resolve))
    handlers.update(validate_handlers(resolve, lambda: str(uploads)))
    handlers.update(document_handlers(resolve))
    handlers.update(SceneCommands(resolve).handlers())
    handlers.update(montage.handlers())
    return handlers


def choose_template(entries: list[Any]) -> dict[str, Any]:
    by_id = {item.get("id"): item for item in entries if isinstance(item, dict)}
    for name in PREFERRED:
        chosen = by_id.get(name)
        if isinstance(chosen, dict):
            return chosen
    first = entries[0]
    if not isinstance(first, dict):
        raise SmokeError("catalog_empty", "templates")
    return first


def load_template(handlers: dict[str, Handler], report: dict[str, Any]) -> dict[str, Any]:
    result = invoke(handlers["scenes.catalog"], {"version": 1, "input": {"kind": "templates", "detail": True}})
    _record(report, "scenes.catalog")
    entries = result.get("result", {}).get("entries") or []
    if not entries:
        raise SmokeError("catalog_empty", "templates")
    return choose_template(entries)


def control_max(entry: dict[str, Any], key: str) -> float:
    controls = entry.get("controls")
    spec = controls.get(key) if isinstance(controls, dict) else None
    high = spec.get("max") if isinstance(spec, dict) else None
    if isinstance(high, bool) or not isinstance(high, (int, float)):
        return float(SCENE_SECONDS)
    return float(high)


def required_assets(entry: dict[str, Any]) -> dict[str, str]:
    assets = {}
    for slot in entry.get("slots") or []:
        if isinstance(slot, dict) and slot.get("required") and isinstance(slot.get("id"), str):
            assets[slot["id"]] = PIXEL
    return assets


def _compile_input(template_id: str, assets: dict[str, str], duration: float) -> dict[str, Any]:
    width, height = FRAME
    return {"version": 1, "input": {
        "templateId": template_id, "assets": assets, "duration": duration,
        "width": width, "height": height, "fps": COMPILE_FPS, "full": True,
    }}


def _compile_once(handlers: dict[str, Handler], template_id: str, assets: dict[str, str], duration: float) -> dict[str, Any]:
    result = invoke(handlers["scenes.template.compile"], _compile_input(template_id, assets, duration))
    document = result.get("result", {}).get("document")
    if not isinstance(document, dict):
        raise SmokeError("compile_bridge_failed", "compile did not return a document")
    return document


def compile_document(handlers: dict[str, Handler], entry: dict[str, Any], report: dict[str, Any]) -> tuple[dict[str, Any], str]:
    assets = required_assets(entry)
    limit = control_max(entry, "duration")
    template_id = str(entry.get("id") or "")
    try:
        document = _compile_once(handlers, template_id, assets, SCENE_SECONDS)
    except SmokeError as error:
        if error.code != "template_bad_control" or SCENE_SECONDS <= limit:
            raise
        document = _compile_once(handlers, template_id, assets, limit)
        document["duration"] = SCENE_SECONDS
        note = (
            f"{template_id} controls.duration.max is {limit:g}, so scenes.template.compile "
            f"rejected {SCENE_SECONDS}. Compiled at {limit:g} and set document duration to "
            f"{SCENE_SECONDS}. scenes.video2d.edit is not on this branch."
        )
    else:
        note = ""
    _record(report, "scenes.template.compile")
    return document, note


def add_texts(handlers: dict[str, Handler], document: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    width, height = FRAME
    result = invoke(handlers["scenes.text.template"], {"version": 1, "input": {
        "templateId": TEXT_TEMPLATE,
        "fields": {"kicker": "CHAPTER", "title": "Harbour"},
        "start": 14, "duration": 4, "width": width, "height": height, "full": True,
    }})
    _record(report, "scenes.text.template")
    incoming = result.get("result", {}).get("texts")
    if not isinstance(incoming, list):
        raise SmokeError("compile_bridge_failed", "text template did not return texts")
    texts = [item for item in document.get("texts") or [] if isinstance(item, dict)]
    known = {item.get("id") for item in texts}
    for cue in incoming:
        if isinstance(cue, dict) and cue.get("id") in known:
            raise SmokeError("duplicate_text", str(cue.get("id")))
    document["texts"] = [*texts, *incoming]
    return document


def add_lyrics(handlers: dict[str, Handler], document: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    result = invoke(handlers["scenes.lyrics.import"], {"version": 1, "input": {
        "format": "plain",
        "text": "The harbour keeps the light\nA quiet bell\nThen morning",
        "duration": 8,
        "full": True,
    }})
    _record(report, "scenes.lyrics.import")
    lyrics = result.get("result", {}).get("lyrics")
    if not isinstance(lyrics, dict):
        raise SmokeError("lyrics_bad_file", "lyrics import did not return lyrics")
    document["lyrics"] = lyrics
    return document


def finish_preset(handlers: dict[str, Handler], report: dict[str, Any]) -> dict[str, Any]:
    result = invoke(handlers["scenes.finish.catalog"], {"version": 1, "input": {"detail": True}})
    _record(report, "scenes.finish.catalog")
    entries = result.get("result", {}).get("entries") or []
    chosen = next((item for item in entries if isinstance(item, dict) and item.get("id") == FINISH_ID), None)
    if chosen is None:
        chosen = next((item for item in entries if isinstance(item, dict)), None)
    if not isinstance(chosen, dict):
        raise SmokeError("finish_missing", FINISH_ID)
    return {key: value for key, value in chosen.items() if key != "id"}


def assign_finish(handlers: dict[str, Handler], document: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    document["finish"] = finish_preset(handlers, report)
    report["notes"].append(
        "scenes.video2d.edit is not on this branch, so document finish was copied from "
        f"finish_presets.json ({FINISH_ID}) after compile."
    )
    return document


def apply_effect(handlers: dict[str, Handler], document: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    cue = {"id": "smoke-rain", "kind": EFFECT_ID, "start": 2, "end": 6, "sound": False}
    result = invoke(handlers["scenes.effects.apply"], {"version": 1, "input": {"document": document, "cues": [cue]}})
    _record(report, "scenes.effects.apply")
    updated = result.get("result", {}).get("document")
    if not isinstance(updated, dict):
        raise SmokeError("invalid_result", "effects apply did not return a document")
    return updated


def validate_scene(handlers: dict[str, Handler], document: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    result = invoke(handlers["scenes.video2d.validate"], {"version": 1, "input": {
        "workspace": WORKSPACE, "document": document, "full": True,
    }})
    _record(report, "scenes.video2d.validate")
    body = result.get("result") if isinstance(result.get("result"), dict) else {}
    errors = body.get("errors") if isinstance(body.get("errors"), list) else []
    warnings = body.get("warnings") if isinstance(body.get("warnings"), list) else []
    report["validate_errors"] = errors
    report["validate_warnings"] = warnings
    if errors:
        raise SmokeError("validate", json.dumps(errors, ensure_ascii=False)[:2000])
    normalized = body.get("document")
    if not isinstance(normalized, dict):
        raise SmokeError("validate", "validate did not return a document")
    return normalized


def preview_times(duration: float) -> list[float]:
    anchors = [0, 2, 5, 8, 12, 15, 18]
    times = [float(item) for item in anchors if 0 <= item <= duration]
    last = max(0.0, float(duration) - 0.05)
    if last not in times:
        times.append(last)
    return times[:8]


def write_sheet(result: dict[str, Any], path: Path, root: Path) -> str:
    from urllib.parse import unquote, urlsplit

    url = result.get("result", {}).get("url")
    if not isinstance(url, str) or "base64" in json.dumps(result.get("result")):
        raise SmokeError("preview_paint_failed", "preview did not return a workspace URL")
    parts = urlsplit(url)
    relative = unquote(parts.path).removeprefix("/api/v1/file/")
    workspace = WORKSPACE
    for item in parts.query.split("&"):
        if item.startswith("workspace="):
            workspace = unquote(item.split("=", 1)[1])
    source = root / workspace / relative
    raw = source.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SmokeError("preview_paint_failed", "contact sheet is not a PNG")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return str(path.resolve())


def preview_scene(handlers: dict[str, Handler], document: dict[str, Any], path: Path, report: dict[str, Any], root: Path) -> str:
    result = invoke(handlers["scenes.video2d.preview"], {"version": 1, "input": {
        "workspace": WORKSPACE,
        "document": document,
        "times": preview_times(float(document.get("duration") or SCENE_SECONDS)),
    }})
    _record(report, "scenes.video2d.preview")
    return write_sheet(result, path, root)


def save_scene(handlers: dict[str, Handler], document: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    result = invoke(handlers["scenes.document.save"], {"version": 1, "input": {
        "workspace": WORKSPACE, "document": document, "name": "video2d-smoke",
    }})
    _record(report, "scenes.document.save")
    saved = result.get("result")
    if not isinstance(saved, dict) or not saved.get("name"):
        raise SmokeError("invalid_result", "document save did not return a file name")
    return saved


def _dist_handler(directory: str) -> type[http.server.SimpleHTTPRequestHandler]:
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def serve_dist() -> tuple[http.server.ThreadingHTTPServer, str]:
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/javascript", ".mjs")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _dist_handler(str(REPO / "ui" / "dist")))
    threading.Thread(target=server.serve_forever, name="video2d-smoke-dist", daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def stop_server(server: http.server.ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def export_handlers(root: Path, app_url: str) -> dict[str, Handler]:
    from services.scene2d_export import Scene2DExportService
    from services.scene2d_export import command_handlers as scene_handlers
    from services.task_manager import TaskRegistry

    resolve = workspace_resolver(root)
    uploads = root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    service = Scene2DExportService(
        workspace_dir=resolve,
        registry_for=lambda name: TaskRegistry(resolve(name), interrupt_stale=False),
        app_url=app_url,
        uploads_dir=lambda: str(uploads),
    )
    return scene_handlers(service)


def export_task(handlers: dict[str, Handler], deadline: float) -> dict[str, Any] | None:
    envelope = {"version": 1, "input": {"workspace": WORKSPACE, "intent_id": INTENT}}
    next_note = time.monotonic()
    while time.monotonic() < deadline:
        viewed = invoke(handlers["scenes.video2d.export.receipt"], envelope)
        task = viewed.get("task") if isinstance(viewed.get("task"), dict) else {}
        status = task.get("status")
        if status in {"completed", "failed", "cancelled"}:
            return task
        if time.monotonic() >= next_note:
            _say(f"export {status or 'waiting'} {task.get('current', 0)}/{task.get('total', '?')}")
            next_note = time.monotonic() + 30
        time.sleep(2)
    return None


def task_reason(task: dict[str, Any] | None) -> str:
    if task is None:
        return "scenes.video2d.export exceeded 15 minutes"
    error = task.get("error") if isinstance(task.get("error"), dict) else {}
    return str(error.get("message") or task.get("message") or task.get("status") or "export failed")


def published_mp4(root: Path, task: dict[str, Any]) -> str:
    meta = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    output = meta.get("output") if isinstance(meta.get("output"), dict) else {}
    name = output.get("name")
    if not isinstance(name, str) or not name:
        return ""
    path = root / WORKSPACE / name
    if not path.is_file():
        return ""
    return str(path.resolve())


def cancel_export(handlers: dict[str, Handler]) -> None:
    try:
        invoke(handlers["scenes.video2d.export.cancel"], {"version": 1, "input": {
            "workspace": WORKSPACE, "intent_id": INTENT,
        }})
    except SmokeError:
        return


def _submit_export(handlers: dict[str, Handler], document: dict[str, Any]) -> None:
    invoke(handlers["scenes.video2d.export"], {
        "version": 1, "intent_id": INTENT, "input": {"workspace": WORKSPACE, "document": document},
    })


def export_scene(root: Path, document: dict[str, Any], report: dict[str, Any]) -> tuple[str, str]:
    reason = painter_reason()
    if reason:
        return "", reason
    server, app_url = serve_dist()
    try:
        handlers = export_handlers(root, app_url)
        _submit_export(handlers, document)
        _record(report, "scenes.video2d.export")
        task = export_task(handlers, time.monotonic() + EXPORT_DEADLINE)
        _record(report, "scenes.video2d.export.receipt")
        if task is None:
            cancel_export(handlers)
        if not task or task.get("status") != "completed":
            return "", task_reason(task)
        return published_mp4(root, task), ""
    except SmokeError as error:
        return "", f"{error.code}: {error}"
    finally:
        stop_server(server)


def montage_body(saved: dict[str, Any], mp4: str) -> tuple[dict[str, Any], str]:
    width, height = FRAME
    if mp4:
        source = f"/api/v1/file/{Path(mp4).name}?workspace={WORKSPACE}"
        note = "mp4 published by scenes.video2d.export"
    else:
        source = str(saved.get("url") or "")
        note = "mp4 was not produced; clip points at the saved scene document"
    montage = {
        "version": 1, "name": "Video 2D smoke", "width": width, "height": height, "fps": COMPILE_FPS,
        "notes": "" if mp4 else note,
        "clips": [{
            "id": "scene", "name": "smoke", "source": source,
            "origin": {"kind": "scene2d", "scene": saved.get("name"), "note": note},
        }],
    }
    return montage, note


def save_montage(handlers: dict[str, Handler], saved: dict[str, Any], mp4: str, report: dict[str, Any]) -> dict[str, Any]:
    montage, note = montage_body(saved, mp4)
    if not mp4:
        report["notes"].append(note)
    result = invoke(handlers["montages.save"], {"version": 1, "input": {"workspace": WORKSPACE, "montage": montage}})
    _record(report, "montages.save")
    body = result.get("result")
    if not isinstance(body, dict) or not body.get("file"):
        raise SmokeError("invalid_result", "montage save did not return a file name")
    return body


def run_smoke(root: Path, contact_sheet: Path | None = None) -> dict[str, Any]:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    sheet = Path(contact_sheet) if contact_sheet else DEFAULT_SHEET
    report = _new_report()
    handlers = build_handlers(root)
    entry = load_template(handlers, report)
    document, note = compile_document(handlers, entry, report)
    if note:
        report["notes"].append(note)
    document = add_texts(handlers, document, report)
    document = add_lyrics(handlers, document, report)
    document = assign_finish(handlers, document, report)
    document = apply_effect(handlers, document, report)
    document = validate_scene(handlers, document, report)
    report["template_id"] = str(entry.get("id") or "")
    report["duration"] = document.get("duration")
    report["contact_sheet"] = preview_scene(handlers, document, sheet, report, root)
    saved = save_scene(handlers, document, report)
    report["scene_file"] = str((root / WORKSPACE / str(saved["name"])).resolve())
    mp4, reason = export_scene(root, document, report)
    report["mp4"] = mp4
    report["mp4_reason"] = reason
    if reason:
        report["notes"].append(reason)
    montage = save_montage(handlers, saved, mp4, report)
    report["montage_file"] = str((root / WORKSPACE / str(montage["file"])).resolve())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke a Video 2D scene through MCP envelopes")
    parser.add_argument("--dry", action="store_true", help="Check envelopes without painting")
    parser.add_argument("--workspace", type=Path, default=Path("/tmp/hocus-mcp-video2d-m9"))
    parser.add_argument("--contact-sheet", type=Path, default=DEFAULT_SHEET)
    args = parser.parse_args(argv)
    if args.dry:
        problems = dry_problems()
        print(json.dumps({"problems": problems}, indent=2))
        return 1 if problems else 0
    report = run_smoke(args.workspace, args.contact_sheet)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not report["validate_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Contact-sheet preview for Video 2D (``scenes.video2d.preview``).

Paints the requested times with the Scene Animator export bridge
(``window.__scene2dExport`` on ``/scene2d-render.html``) and returns one PNG.
It does not write an MP4 or save the scene. Chromium is launched without a GPU
and the paint holds the ``scene2d-render`` CPU lane.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import mimetypes
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from services import resource_scheduler
from services.resource_scheduler import ResourceAcquireCancelled
from services.scene2d_export import _durable, _sequence_urls, validated_document
from services.world3d_export import _blocked_url, even_dim, playwright_module

OPERATION = "scenes.video2d.preview"
MAX_TIMES = 8
MAX_EDGE = 960
PAINT_TIMEOUT = 120.0
FIELDS = frozenset({"document", "times", "workspace"})
ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "ui"
DIST = UI_ROOT / "dist"
RENDER_HTML = DIST / "scene2d-render.html"
SCRIPT = UI_ROOT / "scripts" / "scene2d-contact-sheet.mjs"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_APP_URL = os.environ.get("HOCUS_APP_URL", "").strip().rstrip("/")

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


class PreviewError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


class _DistHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def log_message(self, format, *args):
        return


class _DistServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


def _detail(detail: Any, key: str, fallback: str) -> str:
    if not isinstance(detail, dict):
        return fallback
    value = detail.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback


def _workspace_name(value: Any) -> None:
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= 120:
        raise PreviewError("preview_bad_envelope", "workspace")


def _preview_input(data: Any) -> dict:
    if not isinstance(data, dict) or not {"document", "times"} <= set(data) <= FIELDS:
        raise PreviewError("preview_bad_envelope", "input must be document and times")
    if "workspace" in data:
        _workspace_name(data["workspace"])
    return data


def _input(command: Any) -> dict:
    if not isinstance(command, dict) or set(command) != {"version", "operation", "input"}:
        raise PreviewError("preview_bad_envelope", "Expected version, operation and input only")
    version = command.get("version")
    if type(version) is not int or version != 1 or command.get("operation") != OPERATION:
        raise PreviewError("preview_bad_envelope", f"Expected version 1 {OPERATION}")
    return _preview_input(command.get("input"))


def _document(raw: Any) -> dict:
    try:
        return validated_document(raw)
    except HTTPException as error:
        raise PreviewError(
            _detail(error.detail, "code", "invalid_document"),
            _detail(error.detail, "message", "Invalid Video 2D document"),
        ) from error


def _one_time(value: Any, duration: float) -> float:
    if isinstance(value, bool) or type(value) not in (int, float):
        raise PreviewError("preview_time_out_of_range", "times")
    number = float(value)
    if number != number or number < 0 or number > duration:
        raise PreviewError("preview_time_out_of_range", "times")
    return number


def _times(raw: Any, duration: float) -> list[float]:
    if not isinstance(raw, list) or not raw:
        raise PreviewError("preview_bad_times", "times")
    if len(raw) > MAX_TIMES:
        raise PreviewError("preview_too_many_times", "times")
    return [_one_time(item, duration) for item in raw]


def _edge(document: dict, key: str, default: int) -> float:
    if key not in document or document[key] is None:
        return float(default)
    value = document[key]
    if isinstance(value, bool) or type(value) not in (int, float) or not value > 0:
        raise PreviewError("preview_bad_document", key)
    return float(value)


def preview_frame_size(document: dict) -> tuple[int, int, int]:
    width = _edge(document, "width", 1280)
    height = _edge(document, "height", 720)
    scale = min(1.0, MAX_EDGE / max(width, height))
    fps = document.get("fps", 30)
    return even_dim(width * scale), even_dim(height * scale), int(fps)


def sheet_columns(count: int) -> int:
    if count <= 4:
        return count
    return 4


def prepare(command: Any) -> tuple[dict, list[float], tuple[int, int, int]]:
    data = _input(command)
    document = _document(data["document"])
    times = _times(data["times"], float(document["duration"]))
    return document, times, preview_frame_size(document)


def bind_preview_origin(url: str | None) -> None:
    """Use the live app origin so `/api/v1/file` and `/examples/` resolve."""
    global _APP_URL
    _APP_URL = (url or "").strip().rstrip("/")


def preview_origin() -> str:
    return _APP_URL or os.environ.get("HOCUS_APP_URL", "").strip().rstrip("/")


def _layer_urls(layer: dict) -> list[str]:
    urls = [str(item).strip() for item in _sequence_urls(layer) if str(item).strip()]
    source = str(layer.get("source") or "").strip()
    if source:
        urls.append(source)
    return urls


def _needs_app_origin(document: dict) -> bool:
    for layer in document.get("layers") or []:
        for url in _layer_urls(layer):
            lowered = url.lower()
            if lowered.startswith("/api/v1/") or lowered.startswith("/examples/"):
                return True
    return False


def _assert_preview_media(document: dict) -> None:
    for layer in document.get("layers") or []:
        if layer.get("type") in {"effect", "camera"} or layer.get("visible") is False:
            continue
        urls = _layer_urls(layer)
        if not urls:
            raise PreviewError("preview_missing_ref", f"Layer {layer.get('id')} needs durable workspace or example media")
        for url in urls:
            if _blocked_url(url) or not _durable(url):
                raise PreviewError("preview_missing_ref", f"Layer {layer.get('id')} needs durable workspace or example media")


def painter_block_reason() -> str | None:
    if not RENDER_HTML.is_file():
        return "ui/dist/scene2d-render.html is not built"
    module = playwright_module()
    if module is None or not shutil.which("node"):
        return "Playwright or node is not installed"
    from services.world3d_renderer_support import _browser_path
    browser = _browser_path(str(module))
    if not browser or not Path(browser).is_file():
        return "Playwright Chromium is not installed"
    return None


def _serve_dist() -> tuple[_DistServer, str]:
    server = _DistServer(("127.0.0.1", 0), _DistHandler)
    threading.Thread(target=server.serve_forever, name="scene2d-preview", daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def _stop_server(server: _DistServer) -> None:
    server.shutdown()
    server.server_close()


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()
    proc.wait(timeout=5)


def _run_node(payload: dict, timeout: float) -> bytes:
    if timeout <= 0:
        raise PreviewError("preview_timeout", "Contact sheet timed out")
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        proc = subprocess.Popen(
            ["node", str(SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=UI_ROOT,
            start_new_session=True,
        )
    except OSError as error:
        raise PreviewError("preview_paint_failed", "Could not start the contact-sheet painter") from error
    try:
        stdout, stderr = proc.communicate(text.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired as error:
        _kill_group(proc)
        raise PreviewError("preview_timeout", "Contact sheet timed out") from error
    if proc.returncode != 0 or not stdout.startswith(PNG_MAGIC):
        detail = (stderr or stdout or b"painter failed").decode("utf-8", "replace").strip()
        raise PreviewError("preview_paint_failed", detail[:500] or "painter failed")
    return stdout


def _paint_payload(document: dict, times: list[float], size: tuple[int, int, int], base: str) -> dict:
    return {
        "base": base,
        "document": document,
        "times": times,
        "width": size[0],
        "height": size[1],
        "fps": size[2],
        "columns": sheet_columns(len(times)),
    }


def _serve_and_paint(document: dict, times: list[float], size: tuple[int, int, int], deadline: float) -> bytes:
    origin = preview_origin()
    if origin:
        return _run_node(_paint_payload(document, times, size, origin), deadline - time.monotonic())
    server, base = _serve_dist()
    try:
        return _run_node(_paint_payload(document, times, size, base), deadline - time.monotonic())
    finally:
        _stop_server(server)


def _paint_on_lane(document: dict, times: list[float], size: tuple[int, int, int]) -> bytes:
    deadline = time.monotonic() + PAINT_TIMEOUT

    def cancelled() -> bool:
        return time.monotonic() >= deadline

    try:
        with resource_scheduler.coordinator.acquire(
            resource_scheduler.cpu_lane("scene2d-render"),
            task_id=f"video2d-preview-{uuid.uuid4().hex}",
            description="Video 2D contact sheet",
            cancelled=cancelled,
        ):
            return _serve_and_paint(document, times, size, deadline)
    except ResourceAcquireCancelled as error:
        raise PreviewError("preview_timeout", "Contact sheet timed out") from error


def paint_contact_sheet(document: dict, times: list[float], size: tuple[int, int, int]) -> bytes:
    _assert_preview_media(document)
    if _needs_app_origin(document) and not preview_origin():
        raise PreviewError("preview_painter_unavailable", "Workspace media preview needs the running app origin")
    reason = painter_block_reason()
    if reason:
        raise PreviewError("preview_painter_unavailable", reason)
    return _paint_on_lane(document, times, size)


def _result(png: bytes, times: list[float], size: tuple[int, int, int]) -> dict[str, Any]:
    return {
        "version": 1,
        "status": "completed",
        "operation": OPERATION,
        "result": {
            "mime": "image/png",
            "sha256": hashlib.sha256(png).hexdigest(),
            "png_base64": base64.b64encode(png).decode("ascii"),
            "times": times,
            "width": size[0],
            "height": size[1],
            "columns": sheet_columns(len(times)),
            "frameCount": len(times),
        },
    }


def execute(command: Any) -> dict[str, Any]:
    document, times, size = prepare(command)
    return _result(paint_contact_sheet(document, times, size), times, size)


def command_catalog() -> list[dict[str, Any]]:
    return [{
        "name": OPERATION,
        "description": (
            "Paint up to 8 times from a version 1 Video 2D document with the Scene Animator export "
            "painter (window.__scene2dExport on /scene2d-render.html) and return one contact-sheet PNG. "
            "Each time must be from 0 through the document duration. The long edge is capped at 960. "
            "Does not save the scene or write an MP4. CPU lane scene2d-render, no GPU. "
            "input.workspace is optional and does not change the sheet; callers that omit it keep working. "
            "preview_too_many_times, preview_time_out_of_range and preview_timeout are stable errors."
        ),
        "mutation": False,
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "input": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "document": {"type": "object"},
                        "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
                        "times": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": MAX_TIMES,
                            "items": {"type": "number", "minimum": 0},
                        },
                    },
                    "required": ["document", "times"],
                },
            },
            "required": ["version", "input"],
        },
    }]


def command_handlers(app_url: Callable[[], str] | None = None) -> dict[str, Callable[[Any], Any]]:
    async def handle(arguments: Any) -> dict[str, Any]:
        from starlette.concurrency import run_in_threadpool

        if app_url:
            bind_preview_origin(app_url())
        payload = arguments if isinstance(arguments, dict) else {}
        try:
            return await run_in_threadpool(execute, {**payload, "operation": OPERATION})
        except PreviewError as error:
            retryable = error.code == "preview_timeout"
            raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": retryable}) from error

    return {OPERATION: handle}


__all__ = [
    "OPERATION",
    "PreviewError",
    "bind_preview_origin",
    "command_catalog",
    "command_handlers",
    "execute",
    "paint_contact_sheet",
    "painter_block_reason",
    "prepare",
    "preview_frame_size",
    "preview_origin",
    "sheet_columns",
]

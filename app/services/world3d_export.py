"""Admit a frozen World3D snapshot and render it without the caller's browser tab.

The existing Video 3D document and export plan are the source of truth. Painting
reuses that renderer (headless Chromium is allowed). This module does not invent
a second compositor. Receipts prove admission; the canonical task reports
progress, cancel, retry and validated publication.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import threading
import time
import uuid
import zlib

from fastapi import HTTPException
from pydantic import ValidationError

from services.asset_manifest import publish_generation_sidecar
from services.media_refs import parse_media_ref
from services.scene_commands import DocumentInput, command_error as scene_error
from services.scene_recording import SceneRecordingTranscodeError, validate_scene_recording_output
from services.task_command_admission import TaskCommandConflict
from services.task_manager import get_cancellation_token, new_task_id


OPERATION = "scenes.world3d.export"
RECEIPT_OPERATION = "scenes.world3d.export.receipt"
CANCEL_OPERATION = "scenes.world3d.export.cancel"
WORKSPACE_RE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]{0,119})")
BLOCKED_URLS = ("blob:", "file:", "javascript:", "filesystem:")
MEDIA_KINDS = frozenset({"model3d", "image", "screen"})
COMMAND_KEYS = frozenset({"version", "operation", "intent_id", "input"})
INPUT_KEYS = frozenset({"workspace", "document", "refs"})
INTENT_RE = re.compile(r"[A-Za-z0-9._-]{1,160}")


class World3DExportCancelled(Exception):
    """The canonical task was cancelled while the worker still held partials."""


class World3DExportPending(RuntimeError):
    """Admission is durable, but a real headless render cannot run here."""


def http_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {
        "code": code, "message": message, "retryable": status >= 500,
        "recoverable": status >= 500 or code in {"intent_conflict", "real_render_pending"},
    })


def even_dim(value) -> int:
    number = round(float(value if value == value else 0))
    return max(2, number - (number % 2))


def export_size(width, height) -> tuple[int, int]:
    width = float(width or 0)
    height = float(height or 0)
    max_w, max_h = (1920, 1080) if width >= height else (1080, 1920)
    scale = min(1, max_w / max(1, width), max_h / max(1, height))
    return even_dim(width * scale), even_dim(height * scale)


def playback_speed(value) -> float:
    if isinstance(value, (int, float)) and value == value:
        return max(0.25, min(4.0, float(value)))
    return 1.0


def output_duration(document: dict) -> float:
    return float(document["duration"]) / playback_speed(document.get("playbackSpeed"))


def frame_count(duration: float, fps: int) -> int:
    return max(1, round(float(duration) * int(fps)))


def export_plan(document: dict) -> dict:
    duration = output_duration(document)
    fps = document.get("fps", 30)
    if fps not in (24, 30, 60):
        raise ValueError("Export fps must be 24, 30 or 60")
    width, height = export_size(document.get("width"), document.get("height"))
    return {"width": width, "height": height, "fps": fps, "duration": duration,
            "count": frame_count(duration, fps)}


def playwright_module() -> Path | None:
    path = Path(__file__).resolve().parents[2] / "ui" / "node_modules" / "playwright"
    entry = path / "index.mjs"
    return entry if entry.is_file() else None


# Drives the existing Video 3D stage.paint path in a process-owned Chromium.
# It is not a second compositor: overlay helpers are the same UI modules.
_OWNED_BROWSER_JS = """
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
const snapshot = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const staging = process.argv[3];
const appUrl = process.env.HOCUS_APP_URL;
if (!appUrl) process.exit(2);
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
const frames = `${staging}/frames`;
fs.mkdirSync(frames, { recursive: true });
try {
  await page.goto(new URL('/world3d-render.html', appUrl).href, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.__world3dExport, null, { timeout: 60000 });
  const plan = snapshot.plan;
  const doc = snapshot.document;
  await page.evaluate(({ document: scene, plan: size }) => window.__world3dExport.load(scene, size), { document: doc, plan });
  for (let index = 0; index < plan.count; index += 1) {
    const png = await page.evaluate(seconds => window.__world3dExport.frame(seconds), Math.min(plan.duration, index / plan.fps));
    const name = String(index + 1).padStart(6, '0');
    fs.writeFileSync(`${frames}/frame_${name}.png`, Buffer.from(png.split(',')[1], 'base64'));
    fs.writeFileSync(`${staging}/progress.json`, JSON.stringify({ current: index + 1, total: plan.count }));
  }
} finally {
  await page.evaluate(() => { window.__world3dExport?.dispose(); }).catch(() => {});
  await browser.close();
}
"""


def _wait_owned_browser(proc, cancelled) -> str:
    while proc.poll() is None:
        if cancelled():
            proc.terminate()
            raise World3DExportCancelled()
        time.sleep(0.1)
    _stdout, stderr = proc.communicate()
    return stderr or ""


def run_owned_browser(snapshot: dict, staging: Path, cancelled, *, app_url: str, module: Path) -> list[Path]:
    script = staging / "owned_browser.mjs"
    script.write_text(_OWNED_BROWSER_JS, encoding="utf-8")
    proc = subprocess.Popen(
        ["node", str(script), str(staging / "snapshot.json"), str(staging)],
        env={**os.environ, "HOCUS_APP_URL": app_url, "PLAYWRIGHT_MODULE": str(module)},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    stderr = _wait_owned_browser(proc, cancelled)
    if proc.returncode == 2:
        raise World3DExportPending("real-render pending: no application URL for the world3d stage")
    if proc.returncode != 0:
        raise RuntimeError(stderr.strip()[-1000:] or "Headless world3d export failed")
    frames = sorted((staging / "frames").glob("frame_*.png"))
    if not frames:
        raise RuntimeError("Headless world3d export produced no frames")
    return frames


def export_capabilities(app_url: str | None = None) -> dict:
    ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    playwright = playwright_module() is not None
    return {
        "ffmpeg": ffmpeg, "playwright": playwright,
        "realRender": "ready" if ffmpeg and playwright and renderer_available(app_url) else "pending",
        "renderer": "world3d-export-flow",
        "fps": [24, 30, 60], "maxDuration": 600, "maxVoicedDuration": 0,
    }


def renderer_available(app_url: str | None) -> bool:
    from services.world3d_renderer_support import renderer_available as available
    return available(app_url or os.environ.get("HOCUS_APP_URL", ""), playwright_module())


def write_png(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    row = b"\x00" + bytes(rgb) * width
    raw = row * height

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def mux_frame_sequence(frames: list[Path], destination: Path, *, fps: int, duration: float) -> Path:
    if not shutil.which("ffmpeg"):
        raise World3DExportPending("real-render pending: ffmpeg is not available")
    if not frames:
        raise RuntimeError("Export produced no frames")
    temporary = destination.with_name(f".{destination.stem}.{os.getpid()}.partial.mp4")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-v", "error", "-y", "-framerate", str(int(fps)),
        "-i", str(frames[0].parent / "frame_%06d.png"),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-threads", "1", "-t", f"{float(duration):.3f}", "-movflags", "+faststart", str(temporary),
    ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=1800, check=False,
        )
        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            detail = (result.stderr or "FFmpeg did not produce an MP4").strip()
            raise RuntimeError(detail[-1000:])
        expected = duration if float(duration) >= 0.5 else None
        validate_scene_recording_output(temporary, expected_duration=expected, expected_fps=fps)
        os.replace(temporary, destination)
        return destination
    except SceneRecordingTranscodeError as error:
        raise RuntimeError(str(error)) from error
    finally:
        temporary.unlink(missing_ok=True)


def _digest(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _envelope(command) -> dict:
    if not isinstance(command, dict) or set(command) != COMMAND_KEYS:
        raise http_error(422, "invalid_command", "Use version, operation, intent_id and input")
    intent = command.get("intent_id")
    if command.get("version") != 1 or command.get("operation") != OPERATION:
        raise http_error(422, "invalid_command", "Use version 1 scenes.world3d.export")
    if not isinstance(intent, str) or not 1 <= len(intent) <= 160 or intent != intent.strip():
        raise http_error(422, "invalid_command", "An exact intent_id is required")
    return command


def _input(value) -> dict:
    if not isinstance(value, dict) or set(value) - INPUT_KEYS:
        raise http_error(422, "invalid_command", "input may only include workspace, document and refs")
    workspace = value.get("workspace")
    if not isinstance(workspace, str) or not WORKSPACE_RE.fullmatch(workspace):
        raise http_error(422, "invalid_workspace", "Use an explicit valid output workspace")
    if "document" not in value:
        raise http_error(422, "invalid_document", "A frozen world3d document is required")
    return value


def _validated_document(raw) -> dict:
    if not isinstance(raw, dict):
        raise http_error(422, "invalid_document", "Use a version 1 world3d document")
    try:
        document = deepcopy(DocumentInput(document=raw).document)
    except (ValidationError, ValueError, TypeError) as error:
        raise http_error(422, "invalid_document", scene_error(error)) from error
    if "slots" not in document:
        raise http_error(422, "invalid_document", "Choose a Video3D scene")
    if document.get("fps") not in (24, 30, 60):
        raise http_error(422, "unsupported_capability", "Export fps must be 24, 30 or 60")
    return document


def _cue_sounds(cue) -> bool:
    if not isinstance(cue, dict) or not cue.get("sound"):
        return False
    try:
        return float(cue.get("volume") or 0) > 0
    except (TypeError, ValueError):
        return False


def _has_sound(document: dict) -> bool:
    if any(_cue_sounds(cue) for cue in document.get("sfx") or []):
        return True
    if any(_cue_sounds(cue) for cue in document.get("worldSfx") or []):
        return True
    if document.get("soundtrack"):
        return True
    return any(isinstance(slot, dict) and slot.get("speech") for slot in document.get("slots") or [])


def _blocked_url(value) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith(BLOCKED_URLS)


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def unsupported_capabilities(document: dict) -> list[str]:
    reasons = []
    if any(_blocked_url(item) for item in _walk_strings(document)):
        reasons.append("ephemeral_url")
    if _has_sound(document):
        reasons.append("voiced_duration" if output_duration(document) > 180 else "voiced_audio")
    for slot in document.get("slots") or []:
        media = slot.get("media") if isinstance(slot, dict) else None
        if media not in MEDIA_KINDS:
            reasons.append("unsupported_media")
            break
    return reasons


def _ref_from_url(slot: dict, url: str, workspace: str) -> dict:
    path, ref_workspace = parse_media_ref(url, workspace)
    filename = os.path.basename((path or "").replace("\\", "/"))
    if not filename:
        raise http_error(422, "missing_ref", "Each used slot needs a durable media ref")
    return {
        "slotId": slot["id"], "url": url, "kind": slot.get("media") or "model3d",
        "filename": filename, "workspace": ref_workspace or workspace,
    }


def _index_refs(refs) -> dict:
    if refs is None:
        refs = []
    if not isinstance(refs, list) or len(refs) > 64:
        raise http_error(422, "invalid_command", "refs must be a list of at most 64 durable media refs")
    by_slot = {}
    for item in refs:
        if not isinstance(item, dict) or not isinstance(item.get("slotId"), str):
            raise http_error(422, "invalid_command", "Each ref needs a slotId and url")
        if _blocked_url(item.get("url")):
            raise http_error(422, "unsupported_capability", "Ephemeral blob or file URLs cannot be exported")
        by_slot[item["slotId"]] = item
    return by_slot


def _slot_ref(slot: dict, by_slot: dict, workspace: str) -> dict | None:
    url = str(slot.get("sourceUrl") or "").strip()
    if not url:
        return None
    if _blocked_url(url):
        raise http_error(422, "unsupported_capability", "Ephemeral blob or file URLs cannot be exported")
    return by_slot.get(slot["id"]) or _ref_from_url(slot, url, workspace)


def _validated_refs(document: dict, refs, workspace: str) -> list[dict]:
    by_slot = _index_refs(refs)
    resolved = []
    for slot in document["slots"]:
        item = _slot_ref(slot, by_slot, workspace)
        if item is not None:
            resolved.append(item)
    return resolved


def build_snapshot(document: dict, refs: list[dict], workspace: str) -> dict:
    return {
        "workspace": workspace, "document": deepcopy(document), "refs": deepcopy(refs),
        "plan": export_plan(document),
    }


def freeze_export_command(command) -> dict:
    envelope = _envelope(command)
    payload = _input(envelope["input"])
    document = _validated_document(payload["document"])
    refs = _validated_refs(document, payload.get("refs"), payload["workspace"])
    reasons = unsupported_capabilities(document)
    if reasons:
        raise http_error(422, "unsupported_capability", "Unsupported export capability: " + ", ".join(reasons))
    snapshot = build_snapshot(document, refs, payload["workspace"])
    original = deepcopy(envelope)
    effective = {"version": 1, "operation": OPERATION,
                 "input": {"workspace": payload["workspace"], "snapshot": snapshot}}
    return {
        "original": original, "effective": effective,
        "fingerprint": _digest({"operation": OPERATION, "input": effective["input"]}),
        "fingerprint_version": 1,
    }


def command_catalog() -> list[dict]:
    intent = {"type": "string", "minLength": 1, "maxLength": 160}
    workspace = {"type": "string", "minLength": 1, "maxLength": 120}
    receipt_input = {"type": "object", "additionalProperties": False,
                     "properties": {"workspace": workspace, "intent_id": intent},
                     "required": ["workspace", "intent_id"]}
    export_input = {"type": "object", "additionalProperties": False,
                    "properties": {"workspace": workspace, "document": {"type": "object"},
                                   "refs": {"type": "array", "maxItems": 64}},
                    "required": ["workspace", "document"]}
    return [
        {"name": OPERATION, "version": 1, "supportedVersions": [1], "domain": "scenes", "mutation": True,
         "description": "Admit an immutable Video 3D snapshot and durable media refs as one canonical task. A server-owned worker renders with the existing world3d exporter (headless browser is allowed). Closing the UI does not cancel. Reuse intent_id only to recover the receipt; inspect its task for progress, cancel, retry and the validated MP4.",
         "inputSchema": {"type": "object", "additionalProperties": False,
                         "properties": {"version": {"type": "integer", "const": 1},
                                        "operation": {"const": OPERATION}, "intent_id": intent,
                                        "input": export_input},
                         "required": ["version", "operation", "intent_id", "input"]}},
        {"name": RECEIPT_OPERATION, "version": 1, "domain": "scenes", "mutation": False,
         "description": "Read the immutable World3D export admission and its current canonical task in the original workspace.",
         "inputSchema": {"type": "object", "additionalProperties": False,
                         "properties": {"version": {"type": "integer", "const": 1},
                                        "operation": {"const": RECEIPT_OPERATION}, "input": receipt_input},
                         "required": ["version", "operation", "input"]}},
        {"name": CANCEL_OPERATION, "version": 1, "domain": "scenes", "mutation": True,
         "description": "Cancel a World3D export by exact workspace and intent_id. Partials stay recoverable; the frozen document is kept.",
         "inputSchema": {"type": "object", "additionalProperties": False,
                         "properties": {"version": {"type": "integer", "const": 1},
                                        "operation": {"const": CANCEL_OPERATION}, "input": receipt_input},
                         "required": ["version", "operation", "input"]}},
    ]


def _tool_ids(arguments, required) -> dict:
    if (not isinstance(arguments, dict) or set(arguments) != {"version", "input"}
            or arguments.get("version") != 1 or not isinstance(arguments.get("input"), dict)
            or set(arguments["input"]) != required):
        raise http_error(422, "invalid_command", "Use version 1 with workspace and intent_id")
    return arguments["input"]


def command_handlers(service):
    def submit(arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"version", "intent_id", "input"}:
            raise http_error(422, "invalid_command", "Use version, intent_id and input for the export tool")
        return service.submit({**arguments, "operation": OPERATION})

    def receipt(arguments):
        payload = _tool_ids(arguments, {"workspace", "intent_id"})
        return service.receipt(payload["workspace"], payload["intent_id"])

    def cancel(arguments):
        payload = _tool_ids(arguments, {"workspace", "intent_id"})
        return service.cancel(payload["workspace"], payload["intent_id"])

    return {OPERATION: submit, RECEIPT_OPERATION: receipt, CANCEL_OPERATION: cancel}


def staging_dir(workspace_path: str, intent_id: str) -> Path:
    safe = bool(INTENT_RE.fullmatch(intent_id)) and intent_id not in {".", ".."} and ".." not in intent_id
    token = intent_id if safe else hashlib.sha256(intent_id.encode("utf-8")).hexdigest()[:32]
    path = Path(workspace_path) / ".world3d-export" / token
    path.mkdir(parents=True, exist_ok=True)
    return path


class World3DExportService:
    """Canonical admission plus a process-owned worker independent of the UI tab."""

    def __init__(self, *, workspace_dir, registry_for, renderer=None, app_url=None):
        self.workspace_dir = workspace_dir
        self.registry_for = registry_for
        self.renderer = renderer
        self.app_url = app_url if app_url is not None else os.environ.get("HOCUS_APP_URL", "")
        self.owner = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._workers: dict[str, threading.Thread] = {}

    def capabilities(self) -> dict:
        return export_capabilities(self.app_url)

    def _registry(self, workspace: str):
        if not isinstance(workspace, str) or not WORKSPACE_RE.fullmatch(workspace):
            raise http_error(422, "invalid_workspace", "Use an explicit valid output workspace")
        return self.registry_for(workspace)

    def _assert_refs(self, refs: list[dict], workspace: str) -> None:
        root = Path(self.workspace_dir(workspace))
        for ref in refs:
            name = ref.get("filename")
            if not name:
                continue
            if not (root / str(name)).is_file():
                raise http_error(409, "missing_ref", "Upload local scene resources before exporting")

    def submit(self, command) -> dict:
        try:
            frozen = freeze_export_command(command)
            workspace = frozen["effective"]["input"]["workspace"]
            self._assert_refs(frozen["effective"]["input"]["snapshot"]["refs"], workspace)
            registry = self._registry(workspace)
            previous = registry.command_admission(command["intent_id"])
            if previous is not None:
                return self._replay(registry, frozen, previous)
            return self._admit(registry, frozen, workspace)
        except TaskCommandConflict as error:
            raise http_error(409, "intent_conflict", str(error)) from error
        except (OSError, sqlite3.Error) as error:
            raise http_error(503, "storage_unavailable", "Command storage is unavailable; retry with the same intention") from error

    def _validate_replay(self, previous, frozen) -> None:
        if (previous["operation"] != frozen["original"]["operation"] or previous["digest"] != frozen["fingerprint"]
                or previous["fingerprint_version"] != frozen["fingerprint_version"]):
            raise TaskCommandConflict("intent_id was already used with different parameters or preconditions")

    def _replay(self, registry, frozen, previous) -> dict:
        self._validate_replay(previous, frozen)
        task = registry.get(previous["task_id"])
        if task and task["status"] in {"failed", "interrupted", "cancelled"}:
            registry.update(previous["task_id"], status="queued", phase="queued",
                            message="Retrying Video 3D export", error=None)
        self._dispatch(registry, previous["intent_id"])
        current = registry.command_admission(previous["intent_id"])
        return {"receipt": deepcopy(current["receipt"]), "replayed": True, "capabilities": self.capabilities()}

    def _task_fields(self, *, task_id, job_id, workspace, plan) -> dict:
        return {
            "id": task_id, "root_id": task_id, "kind": "video", "workflow": OPERATION,
            "title": "Video 3D export", "status": "queued", "phase": "queued",
            "message": "Queued for Video 3D export", "workspace": workspace,
            "backend_job_id": job_id, "current": 0, "total": plan["count"],
            "resource_requirements": ["local_cpu:ffmpeg"], "cancelable": True,
            "resumable": True, "recoverable": True,
            "metadata": {"operation": OPERATION},
        }

    def _admit(self, registry, frozen, workspace) -> dict:
        snapshot = frozen["effective"]["input"]["snapshot"]
        job_id = f"world3d-export-{uuid.uuid4().hex}"
        task_id = new_task_id("world3d-export")
        admitted = registry.admit_command_task(
            intent_id=frozen["original"]["intent_id"], operation=OPERATION,
            digest=frozen["fingerprint"], original=frozen["original"],
            effective=frozen["effective"], fingerprint_version=1,
            task_fields=self._task_fields(task_id=task_id, job_id=job_id, workspace=workspace, plan=snapshot["plan"]),
        )
        self._dispatch(registry, frozen["original"]["intent_id"])
        return {**admitted, "capabilities": self.capabilities()}

    def _dispatch(self, registry, intent_id: str) -> None:
        entry = registry.command_admission(intent_id)
        task = registry.get(entry["task_id"]) if entry else None
        if not entry or not task or task["status"] != "queued":
            return
        if entry["dispatch_owner"] is None:
            registry.claim_command_dispatch(intent_id, self.owner)
        with self._lock:
            existing = self._workers.get(intent_id)
            if existing is not None and existing.is_alive():
                return
            thread = threading.Thread(
                target=self._run_worker, args=(intent_id, entry["task_id"], task["workspace"]),
                name=f"world3d-export-{intent_id[:12]}", daemon=True,
            )
            self._workers[intent_id] = thread
            thread.start()

    def receipt(self, workspace: str, intent_id: str) -> dict:
        if not isinstance(intent_id, str) or not 1 <= len(intent_id) <= 160:
            raise http_error(422, "invalid_command", "An exact intent_id is required")
        try:
            registry = self._registry(workspace)
            entry = registry.command_admission(intent_id)
            if entry is None:
                raise http_error(404, "receipt_not_found", "No admission exists for this intention in this workspace")
            task = registry.get(entry["task_id"])
            return {"receipt": entry["receipt"], "task": task, "capabilities": self.capabilities()}
        except (OSError, sqlite3.Error) as error:
            raise http_error(503, "storage_unavailable", "Command storage is unavailable") from error

    def cancel(self, workspace: str, intent_id: str) -> dict:
        viewed = self.receipt(workspace, intent_id)
        task = viewed["task"]
        if not task:
            raise http_error(404, "receipt_not_found", "No admission exists for this intention in this workspace")
        if task["status"] == "completed":
            raise http_error(409, "already_completed", "A completed export cannot be cancelled")
        if task["status"] != "cancelled":
            try:
                self._registry(workspace).update(
                    task["id"], status="cancelled", phase="cancelling",
                    message="Export cancelled",
                )
            except ValueError as error:
                raise http_error(409, "cannot_cancel", str(error)) from error
        return self.receipt(workspace, intent_id)

    def _run_worker(self, intent_id: str, task_id: str, workspace: str) -> None:
        registry = self.registry_for(workspace)
        try:
            self._export(registry, intent_id, task_id, workspace)
        except World3DExportCancelled:
            self._finish(registry, task_id, "cancelled", phase="cancelled", message="Export cancelled")
        except World3DExportPending as error:
            self._finish(registry, task_id, "failed", phase="pending", message=str(error),
                         error={"code": "real_render_pending", "message": str(error)})
        except Exception as error:
            self._finish(registry, task_id, "failed", phase="failed",
                         message=str(error)[:500], error={"code": "export_failed", "message": str(error)[:500]})

    def _ensure_active(self, token, registry, task_id) -> None:
        task = registry.get(task_id) or {}
        if token.is_cancelled() or task.get("status") == "cancelled":
            raise World3DExportCancelled()

    def _progress(self, registry, task_id, current: int, total: int) -> None:
        registry.update(task_id, current=current, total=total,
                        message=f"Rendering frame {current}/{total}",
                        event_exclude_fields={"current", "message", "progress"})

    def _export(self, registry, intent_id, task_id, workspace) -> None:
        token = get_cancellation_token(registry.workspace_dir, task_id)
        self._ensure_active(token, registry, task_id)
        try:
            registry.update(task_id, status="running", phase="exporting", message="Exporting Video 3D")
        except ValueError as error:
            raise World3DExportCancelled() from error
        entry = registry.command_admission(intent_id)
        snapshot = deepcopy(entry["effective"]["input"]["snapshot"])
        staging = staging_dir(registry.workspace_dir, intent_id)
        (staging / "snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        frames = self._render_frames(snapshot, staging, token, registry, task_id)
        published = self._publish(snapshot, staging, frames, workspace, registry, task_id, token)
        self._finish(registry, task_id, "completed", phase="completed",
                     message="Published Video 3D MP4", result_refs=[published["name"]],
                     metadata={"operation": OPERATION, "output": published})

    def _owned_browser(self, snapshot, staging, progress, cancelled) -> list[Path]:
        module = playwright_module()
        if not self.app_url or module is None or not shutil.which("node"):
            raise World3DExportPending("real-render pending: playwright/ffmpeg headless export is not configured")
        frames = run_owned_browser(snapshot, staging, cancelled, app_url=self.app_url, module=module)
        progress(len(frames), snapshot["plan"]["count"])
        return frames

    def _render_frames(self, snapshot, staging, token, registry, task_id) -> list[Path]:
        renderer = self.renderer or self._owned_browser
        folder = staging / "frames"
        folder.mkdir(parents=True, exist_ok=True)

        def progress(current, total):
            self._ensure_active(token, registry, task_id)
            self._progress(registry, task_id, current, total)

        return list(renderer(snapshot, staging, progress, lambda: token.is_cancelled() or False))

    def _publish(self, snapshot, staging, frames, workspace, registry, task_id, token) -> dict:
        self._ensure_active(token, registry, task_id)
        if _has_sound(snapshot["document"]):
            raise RuntimeError("Voiced World3D export cannot publish a silent MP4")
        plan = snapshot["plan"]
        encoded = staging / "encoded.mp4"
        mux_frame_sequence(frames, encoded, fps=plan["fps"], duration=plan["duration"])
        self._ensure_active(token, registry, task_id)
        template = re.sub(r"[^A-Za-z0-9._-]+", "-", str(snapshot["document"].get("templateId") or "scene")).strip("-._")[:40] or "scene"
        name = f"{time.strftime('%Y-%m-%d-%Hh%Mm%Ss')}_world3d-{template}_{uuid.uuid4().hex[:6]}.mp4"
        output = Path(self.workspace_dir(workspace)) / name
        os.replace(encoded, output)
        sidecar = {
            "params": {
                "model_type": "scene-animator-3d", "generation_mode": "3d-scene-compositor",
                "scene": {"version": 1, "name": name, "width": plan["width"], "height": plan["height"],
                          "fps": plan["fps"], "duration": plan["duration"], "layers": []},
                "scene_recipe": {"engine": "world3d", "document": snapshot["document"], "refs": snapshot["refs"]},
                "width": plan["width"], "height": plan["height"], "fps": plan["fps"],
                "duration_seconds": plan["duration"],
            },
            "generation_mode": "video", "tool": "world3d-export", "output_filename": name,
        }
        publish_generation_sidecar(output, sidecar, workspace_id=workspace, tool="world3d-export",
                                   capability=OPERATION, actor="user")
        return {"name": name, "url": f"/api/v1/file/{name}", "workspace": workspace}

    def _finish(self, registry, task_id, status, **fields) -> None:
        task = registry.get(task_id)
        if task is None:
            return
        if task["status"] in {"completed", "cancelled"} and status == "failed":
            return
        try:
            registry.update(task_id, status=status, **fields)
        except ValueError:
            return


__all__ = [
    "CANCEL_OPERATION", "OPERATION", "RECEIPT_OPERATION", "World3DExportCancelled",
    "World3DExportPending", "World3DExportService", "build_snapshot", "command_catalog",
    "command_handlers", "even_dim", "export_capabilities", "export_plan", "export_size",
    "freeze_export_command", "http_error", "mux_frame_sequence", "playwright_module",
    "staging_dir", "unsupported_capabilities", "write_png",
]

"""Recoverable server-side export of Video 2D scenes (``scenes.video2d.export``).

It reuses the World3D admission/receipt/cancel machinery and its owned headless
browser, but drives ``/scene2d-render.html`` (the Scene Animator's own evaluator
and painter). Rendering uses a CPU lane, so it never waits for generation jobs
on the GPU. The scene's ``audioTracks`` (real workspace audio files) are mixed
into the published MP4. Screen-FX sounds are synthesized by the headless
page and mixed from ``staging/fx.wav`` when that file is present.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from services import resource_scheduler
from services.media_refs import parse_media_ref
from services.scene2d_schema import document_schema, fill_sfx_colors
from services.scene_commands import DocumentInput, command_error as scene_error
from services.export_receipts import project_export_receipt
from services.audio_mix import (  # noqa: F401 — re-exported for callers and tests of the 2D mixer
    DUCK_ATTACK, DUCK_MARGIN, DUCK_RELEASE, audio_seconds, duck_db, duck_expression, mix_audio_tracks, mux_wav_audio,
)
from services.world3d_export import (
    QUALITIES,
    World3DExportPending,
    World3DExportService,
    _blocked_url,
    _digest,
    _tool_ids,
    export_plan,
    http_error,
    mux_wav_audio,
    playwright_module,
    scene_render_device,
)

OPERATION = "scenes.video2d.export"
RECEIPT_OPERATION = "scenes.video2d.export.receipt"


CANCEL_OPERATION = "scenes.video2d.export.cancel"
WORKSPACE_RE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]{0,119})")
LAYER_TYPES = frozenset({"image", "video", "overlay", "effect", "camera"})
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"})
DURABLE_PREFIXES = ("/api/v1/file/", "/api/v1/uploads/", "/examples/")


def _envelope(command) -> dict:
    if not isinstance(command, dict) or set(command) != {"version", "operation", "intent_id", "input"}:
        raise http_error(422, "invalid_command", "Use version, operation, intent_id and input")
    intent = command.get("intent_id")
    if command.get("version") != 1 or command.get("operation") != OPERATION:
        raise http_error(422, "invalid_command", f"Use version 1 {OPERATION}")
    if not isinstance(intent, str) or not 1 <= len(intent) <= 160 or intent != intent.strip():
        raise http_error(422, "invalid_command", "An exact intent_id is required")
    payload = command.get("input")
    if not isinstance(payload, dict) or set(payload) - {"workspace", "document", "quality", "shutter"} or "document" not in payload:
        raise http_error(422, "invalid_command", "input must include workspace and document")
    if not isinstance(payload.get("workspace"), str) or not WORKSPACE_RE.fullmatch(payload["workspace"]):
        raise http_error(422, "invalid_workspace", "Use an explicit valid output workspace")
    return command


def validated_document(raw) -> dict:
    if not isinstance(raw, dict):
        raise http_error(422, "invalid_document", "Use a version 1 Video 2D document")
    try:
        document = deepcopy(DocumentInput(document=raw).document)
    except (ValidationError, ValueError, TypeError) as error:
        raise http_error(422, "invalid_document", scene_error(error)) from error
    if "layers" not in document or "slots" in document:
        raise http_error(422, "invalid_document", "Choose a Video 2D scene (layers); use scenes.world3d.export for Video 3D")
    if document.get("fps", 30) not in (24, 30, 60):
        raise http_error(422, "unsupported_capability", "Export fps must be 24, 30 or 60")
    fill_sfx_colors(document)
    for layer in document["layers"]:
        if layer.get("type") not in LAYER_TYPES:
            raise http_error(422, "unsupported_capability",
                             f"Layer {layer.get('id')}: headless Video 2D export supports image, video, overlay, effect and camera layers")
    return document


def _durable(url: str) -> bool:
    lowered = url.strip().lower()
    return lowered.startswith(DURABLE_PREFIXES) or lowered.startswith("data:image/")


def _sequence_urls(layer: dict) -> list[str]:
    sequence = layer.get("sequence")
    if not isinstance(sequence, dict):
        return []
    if sequence.get("kind") == "frames":
        return [str(source).strip() for source in sequence.get("sources") or [] if str(source).strip()]
    if sequence.get("kind") == "sheet":
        source = str(sequence.get("source") or "").strip()
        return [source] if source else []
    urls = [str(source).strip() for source in sequence.get("sources") or [] if str(source).strip()]
    source = str(sequence.get("source") or "").strip()
    if source:
        urls.append(source)
    return urls


def _media_name(path: str) -> str:
    """Workspace-relative name of a file URL; Series Lab keeps images in ``assets/<series>/``."""
    clean = (path or "").replace("\\", "/")
    for prefix in ("/api/v1/file/", "/api/v1/uploads/"):
        if clean.startswith(prefix):
            parts = [part for part in clean[len(prefix):].split("/") if part]
            if not parts or any(part in (".", "..") for part in parts):
                raise http_error(422, "missing_ref", "Use a media path inside the workspace")
            return "/".join(parts)
    return os.path.basename(clean)


def _append_visual_ref(refs: list, layer: dict, url: str, workspace: str, sequence: bool) -> None:
    label = "sequence" if sequence else "source"
    if not url or _blocked_url(url) or not _durable(url):
        raise http_error(422, "missing_ref", f"Layer {layer.get('id')} {label} needs durable workspace or example media")
    if url.lower().startswith("data:"):
        return
    record = {"layerId": layer["id"], "url": url, "kind": layer["type"], **({"sequence": True} if sequence else {})}
    if url.lower().startswith("/examples/"):
        path = unquote(urlsplit(url).path)
        if ".." in path.split("/") or "\\" in path:
            raise http_error(422, "missing_ref", "Use a valid bundled example URL")
        refs.append(record)
        return
    # Honor the URL's own workspace. Passing the export workspace into
    # parse_media_ref would hide gallery Uploads (`?workspace=__uploads__`)
    # and media picked from another workspace folder.
    path, scoped = parse_media_ref(url)
    record["filename"] = _media_name(path)
    if url.lower().startswith("/api/v1/uploads/") or scoped == "__uploads__":
        record["root"] = "uploads"
    else:
        record["workspace"] = scoped or workspace
    refs.append(record)


def _layer_media(refs: list, layer: dict, workspace: str) -> None:
    urls = _sequence_urls(layer)
    source = str(layer.get("source") or "").strip()
    if source:
        _append_visual_ref(refs, layer, source, workspace, False)
    elif not urls:
        raise http_error(422, "missing_ref", f"Layer {layer.get('id')} needs durable workspace or example media")
    for extra in urls:
        _append_visual_ref(refs, layer, extra, workspace, True)


def media_refs(document: dict, workspace: str) -> list[dict]:
    """Durable media referenced by visual layers, frame sequences and audio tracks."""
    refs = []
    for layer in document["layers"]:
        if layer.get("type") in {"effect", "camera"} or layer.get("visible") is False:
            continue
        _layer_media(refs, layer, workspace)
    for track in document.get("audioTracks") or []:
        name = os.path.basename(str((track or {}).get("filename") or ""))
        if not name or os.path.splitext(name)[1].lower() not in AUDIO_EXTENSIONS:
            raise http_error(422, "missing_ref", "Each audioTrack needs a workspace audio filename")
        refs.append({"audioTrackId": track.get("id"), "filename": name, "workspace": workspace, "kind": "audio"})
    return refs


def _export_plan(document: dict, payload: dict) -> dict:
    quality = payload.get("quality", "draft")
    shutter = payload.get("shutter")
    if shutter is not None and (isinstance(shutter, bool) or not isinstance(shutter, (int, float))):
        raise http_error(422, "invalid_command", "shutter must be a number of degrees between 0 and 360")
    try:
        return export_plan(document, quality if isinstance(quality, str) else "", None if shutter is None else float(shutter))
    except ValueError as error:
        raise http_error(422, "invalid_command", str(error)) from error


def freeze_export_command(command) -> dict:
    envelope = _envelope(command)
    payload = envelope["input"]
    document = validated_document(payload["document"])
    refs = media_refs(document, payload["workspace"])
    snapshot = {"workspace": payload["workspace"], "document": document, "refs": refs, "plan": _export_plan(document, payload)}
    effective = {"version": 1, "operation": OPERATION, "input": {"workspace": payload["workspace"], "snapshot": snapshot}}
    return {"original": deepcopy(envelope), "effective": effective,
            "fingerprint": _digest({"operation": OPERATION, "input": effective["input"]}), "fingerprint_version": 1}


def renderer_available(app_url: str | None, module) -> bool:
    from services.world3d_renderer_support import _browser_path
    entry = Path(__file__).resolve().parents[2] / "ui" / "dist" / "scene2d-render.html"
    if not app_url or not entry.is_file() or not module or not shutil.which("node"):
        return False
    browser = _browser_path(str(module))
    return bool(browser and Path(browser).is_file())


def _mix_wav(video: Path, wav: Path, duration: float) -> Path:
    return mux_wav_audio(video, wav, duration, label="Screen FX mix")


class Scene2DExportService(World3DExportService):
    """Video 2D scenes through the shared recoverable export flow."""

    operation = OPERATION
    title = "Video 2D"
    slug = "scene2d-export"
    staging_folder = ".scene2d-export"
    render_page = "/scene2d-render.html"
    render_bridge = "__scene2dExport"

    def __init__(self, *, workspace_dir, registry_for, renderer=None, app_url=None, uploads_dir=None):
        super().__init__(workspace_dir=workspace_dir, registry_for=registry_for, renderer=renderer,
                         app_url=app_url, uploads_dir=uploads_dir)

    def capabilities(self) -> dict:
        module = playwright_module()
        ready = bool(shutil.which("ffmpeg")) and module is not None and renderer_available(self.app_url, module)
        return {"version": 1, "operation": OPERATION, "realRender": "ready" if ready else "pending",
                "renderer": "scene2d-owned-browser", "fps": [24, 30, 60], "maxDuration": 600,
                "layerTypes": sorted(LAYER_TYPES), "audioTracks": True,
                "qualities": list(QUALITIES), "renderDevice": scene_render_device(),
                "motionBlur": {"shutterDegrees": [0, 360], "default": 180}}

    def freeze(self, command) -> dict:
        return freeze_export_command(command)

    def resource_lane(self):
        from services.scene_export_lane import scene2d_render_lane
        return scene2d_render_lane()

    def _assert_refs(self, refs: list[dict], workspace: str) -> None:
        workspace_root = Path(self.workspace_dir(workspace))
        uploads_root = Path(self.uploads_dir())
        for ref in refs:
            name = ref.get("filename")
            if not name:
                continue
            named = ref.get("workspace", workspace)
            if ref.get("root") == "uploads" or named == "__uploads__":
                root = uploads_root
            elif named == workspace:
                root = workspace_root
            elif isinstance(named, str) and WORKSPACE_RE.fullmatch(named):
                root = Path(self.workspace_dir(named))
            else:
                continue
            if not (root / str(name)).is_file():
                raise http_error(409, "missing_ref", f"Missing workspace media: {name}")

    def prepare_snapshot(self, snapshot: dict, cancelled) -> dict:
        return deepcopy(snapshot)

    def check_publish(self, snapshot: dict) -> None:
        return None

    def finish_media(self, snapshot: dict, staging: Path, encoded: Path) -> Path:
        duration = snapshot["plan"]["duration"]
        tracks = snapshot["document"].get("audioTracks") or []
        fx = staging / "fx.wav"
        extras = [fx] if fx.is_file() else []
        if extras and not tracks:
            return _mix_wav(encoded, fx, duration)
        if not tracks:
            return encoded
        return mix_audio_tracks(encoded, tracks, Path(self.workspace_dir(snapshot["workspace"])), duration, extras=extras,
                                duck=duck_db(snapshot["document"]))

    def output_name(self, snapshot: dict) -> str:
        label = re.sub(r"[^A-Za-z0-9._-]+", "-", str(snapshot["document"].get("name") or "scene")).strip("-._")[:40] or "scene"
        return f"{time.strftime('%Y-%m-%d-%Hh%Mm%Ss')}_video2d-{label}_{uuid.uuid4().hex[:6]}.mp4"

    def sidecar(self, snapshot: dict, name: str) -> dict:
        plan = snapshot["plan"]
        return {
            "params": {
                "model_type": "scene-animator", "generation_mode": "2d-scene-compositor",
                "scene": snapshot["document"], "scene_recipe": {"engine": "video2d", "refs": snapshot["refs"]},
                "width": plan["width"], "height": plan["height"], "fps": plan["fps"], "duration_seconds": plan["duration"],
            },
            "generation_mode": "video", "tool": self.slug, "output_filename": name,
        }

    def _owned_browser(self, snapshot, staging, progress, cancelled):
        if not renderer_available(self.app_url, playwright_module()):
            raise World3DExportPending("real-render pending: build the UI (scene2d-render.html) and install Playwright Chromium")
        return super()._owned_browser(snapshot, staging, progress, cancelled)


def command_catalog() -> list[dict]:
    intent = {"type": "string", "minLength": 1, "maxLength": 160}
    workspace = {"type": "string", "minLength": 1, "maxLength": 120}
    ids = {"type": "object", "additionalProperties": False, "properties": {"workspace": workspace, "intent_id": intent},
           "required": ["workspace", "intent_id"]}
    export_input = {"type": "object", "additionalProperties": False,
                    "properties": {"workspace": workspace, "document": document_schema(),
                                   "quality": {"enum": list(QUALITIES), "default": "draft",
                                               "description": "draft stays the current painter. final and master add motion blur and a slower encode. Video 2D also supersamples when the plan asks for it."},
                                   "shutter": {"type": "number", "minimum": 0, "maximum": 360,
                                               "description": "Motion blur shutter in degrees for final/master (default 180; 0 = sharp)."}},
                    "required": ["workspace", "document"]}

    def entry(name, mutation, description, properties, required):
        return {"name": name, "version": 1, "domain": "scenes", "mutation": mutation, "description": description,
                "inputSchema": {"type": "object", "additionalProperties": False,
                                "properties": {"version": {"type": "integer", "const": 1}, "operation": {"const": name}, **properties},
                                "required": ["version", "operation", *required]}}
    return [
        entry(OPERATION, True, "Render a version 1 Video 2D scene (layers with keyframes, camera, atmosphere, screen FX, kinetic "
              "texts and audioTracks) to MP4 on the server with the Scene Animator's own painter, on a CPU lane. "
              "audioMix {duckDb} dips every track that is not speech under the speech tracks (10 is a good start). Media must be "
              "durable workspace/example URLs. Returns a receipt; poll the receipt for the published MP4.",
              {"intent_id": intent, "input": export_input}, ["intent_id", "input"]),
        entry(RECEIPT_OPERATION, False,
              "Read a Video 2D export admission and its current canonical task. The returned receipt status follows "
              "that task. When the MP4 is published, artifacts is one {name, url, workspace}. The stored admission stays queued.",
              {"input": ids}, ["input"]),
        entry(CANCEL_OPERATION, True, "Cancel a Video 2D export by exact workspace and intent_id.", {"input": ids}, ["input"]),
    ]


def command_handlers(service: Scene2DExportService) -> dict:
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


__all__ = ["CANCEL_OPERATION", "OPERATION", "RECEIPT_OPERATION", "Scene2DExportService", "command_catalog",
           "command_handlers", "freeze_export_command", "media_refs", "mix_audio_tracks", "project_export_receipt",
           "validated_document"]

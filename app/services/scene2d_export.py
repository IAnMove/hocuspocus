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
from services.scene_commands import DocumentInput, command_error as scene_error
from services.world3d_export import (
    World3DExportPending,
    World3DExportService,
    _blocked_url,
    _digest,
    _tool_ids,
    export_plan,
    http_error,
    playwright_module,
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
    if not isinstance(payload, dict) or set(payload) - {"workspace", "document"} or "document" not in payload:
        raise http_error(422, "invalid_command", "input must include workspace and document only")
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
    for layer in document["layers"]:
        if layer.get("type") not in LAYER_TYPES:
            raise http_error(422, "unsupported_capability",
                             f"Layer {layer.get('id')}: headless Video 2D export supports image, video, overlay, effect and camera layers")
    return document


def _durable(url: str) -> bool:
    lowered = url.strip().lower()
    return lowered.startswith(DURABLE_PREFIXES) or lowered.startswith("data:image/")


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
    path, scoped = parse_media_ref(url, workspace)
    record["filename"] = os.path.basename((path or "").replace("\\", "/"))
    record["workspace"] = scoped or workspace
    refs.append(record)


def _layer_media(refs: list, layer: dict, workspace: str) -> None:
    sequence = layer.get("sequence") if isinstance(layer.get("sequence"), dict) else {}
    urls = list(sequence.get("sources") or [])
    if sequence.get("source"):
        urls.append(sequence.get("source"))
    for extra in urls:
        _append_visual_ref(refs, layer, str(extra or "").strip(), workspace, True)
    _append_visual_ref(refs, layer, str(layer.get("source") or "").strip(), workspace, False)


def media_refs(document: dict, workspace: str) -> list[dict]:
    """Durable media referenced by visual layers and audio tracks."""
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


def freeze_export_command(command) -> dict:
    envelope = _envelope(command)
    payload = envelope["input"]
    document = validated_document(payload["document"])
    refs = media_refs(document, payload["workspace"])
    snapshot = {"workspace": payload["workspace"], "document": document, "refs": refs, "plan": export_plan(document)}
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
    mixed = video.with_name("fx-mixed.mp4")
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(wav), "-filter_complex",
               f"[1:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0:{duration:.4f}[mix]",
               "-map", "0:v:0", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-t", f"{duration:.4f}", "-movflags", "+faststart", str(mixed)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
    if result.returncode != 0 or not mixed.is_file():
        raise RuntimeError(("Screen FX mix failed: " + (result.stderr or "")).strip()[-800:])
    return mixed


def mix_audio_tracks(video: Path, tracks: list[dict], workspace_root: Path, duration: float) -> Path:
    """Mix scene audio tracks (startTime, volume) under the silent render."""
    usable = []
    for track in tracks:
        source = workspace_root / os.path.basename(str(track.get("filename") or ""))
        start = float(track.get("startTime") or 0)
        if source.is_file() and 0 <= start < duration:
            usable.append((source, start, max(0.0, min(2.0, float(track.get("volume", 1) or 0)))))
    if not usable:
        return video
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(video)]
    parts, labels = [], []
    for index, (source, start, volume) in enumerate(usable, start=1):
        command += ["-i", str(source)]
        delay = int(round(start * 1000))
        parts.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,volume={volume:.4f},adelay={delay}|{delay}[a{index}]")
        labels.append(f"[a{index}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.97,apad,atrim=0:{duration:.4f}[mix]")
    mixed = video.with_name("mixed.mp4")
    command += ["-filter_complex", ";".join(parts), "-map", "0:v:0", "-map", "[mix]", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-t", f"{duration:.4f}", "-movflags", "+faststart", str(mixed)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
    if result.returncode != 0 or not mixed.is_file():
        raise RuntimeError(("Audio track mix failed: " + (result.stderr or "")).strip()[-800:])
    return mixed


class Scene2DExportService(World3DExportService):
    """Video 2D scenes through the shared recoverable export flow."""

    operation = OPERATION
    title = "Video 2D"
    slug = "scene2d-export"
    staging_folder = ".scene2d-export"
    render_page = "/scene2d-render.html"
    render_bridge = "__scene2dExport"

    def capabilities(self) -> dict:
        module = playwright_module()
        ready = bool(shutil.which("ffmpeg")) and module is not None and renderer_available(self.app_url, module)
        return {"version": 1, "operation": OPERATION, "realRender": "ready" if ready else "pending",
                "renderer": "scene2d-owned-browser", "fps": [24, 30, 60], "maxDuration": 600,
                "layerTypes": sorted(LAYER_TYPES), "audioTracks": True}

    def freeze(self, command) -> dict:
        return freeze_export_command(command)

    def resource_lane(self):
        return resource_scheduler.cpu_lane("scene2d-render")

    def _assert_refs(self, refs: list[dict], workspace: str) -> None:
        root = Path(self.workspace_dir(workspace))
        for ref in refs:
            name = ref.get("filename")
            if name and ref.get("workspace", workspace) == workspace and not (root / str(name)).is_file():
                raise http_error(409, "missing_ref", f"Missing workspace media: {name}")

    def prepare_snapshot(self, snapshot: dict, cancelled) -> dict:
        return deepcopy(snapshot)

    def check_publish(self, snapshot: dict) -> None:
        return None

    def finish_media(self, snapshot: dict, staging: Path, encoded: Path) -> Path:
        video = encoded
        fx = staging / "fx.wav"
        if fx.is_file():
            video = _mix_wav(video, fx, snapshot["plan"]["duration"])
        tracks = snapshot["document"].get("audioTracks") or []
        if not tracks:
            return video
        return mix_audio_tracks(video, tracks, Path(self.workspace_dir(snapshot["workspace"])), snapshot["plan"]["duration"])

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
                    "properties": {"workspace": workspace, "document": {"type": "object"}}, "required": ["workspace", "document"]}

    def entry(name, mutation, description, properties, required):
        return {"name": name, "version": 1, "domain": "scenes", "mutation": mutation, "description": description,
                "inputSchema": {"type": "object", "additionalProperties": False,
                                "properties": {"version": {"type": "integer", "const": 1}, "operation": {"const": name}, **properties},
                                "required": ["version", "operation", *required]}}
    return [
        entry(OPERATION, True, "Render a version 1 Video 2D scene (layers with keyframes, camera, atmosphere, screen FX, kinetic "
              "texts and audioTracks) to MP4 on the server with the Scene Animator's own painter, on a CPU lane. Media must be "
              "durable workspace/example URLs. Returns a receipt; poll the receipt for the published MP4.",
              {"intent_id": intent, "input": export_input}, ["intent_id", "input"]),
        entry(RECEIPT_OPERATION, False, "Read a Video 2D export admission and its current canonical task.", {"input": ids}, ["input"]),
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
           "command_handlers", "freeze_export_command", "media_refs", "mix_audio_tracks", "validated_document"]

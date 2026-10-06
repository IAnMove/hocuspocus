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
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException
from pydantic import ValidationError

from services.agent_activity import agent_attribution, requested_by
from services.asset_manifest import publish_generation_sidecar, sidecar_path
from services.audio_mix import mux_wav_audio  # noqa: F401 — the shared mixer, re-exported
from services.workspace_cleanup import keep_export_staging, release_export_staging
from services import resource_scheduler
from services.world3d_frame_encoder import write_png, write_prores_master  # noqa: F401 — compatible public exports
from services.world3d_media_cache import prepare_media_snapshot
from services.world3d_renderer_support import scene_render_device
from services.media_refs import parse_media_ref
from services.scene_commands import DocumentInput, command_error as scene_error
from services.scene_recording import SceneRecordingTranscodeError, validate_scene_recording_output
from services.task_command_admission import TaskCommandConflict
from services.task_manager import get_cancellation_token, new_task_id
from services.export_receipts import project_export_receipt, project_export_task
from services.export_output_name import OUTPUT_NAME_SCHEMA, name_snapshot, previous_path, publish_export_file
from services.media_publication import file_sha256, publication_lock, publication_transaction


OPERATION = "scenes.world3d.export"
RECEIPT_OPERATION = "scenes.world3d.export.receipt"
CANCEL_OPERATION = "scenes.world3d.export.cancel"
WORKSPACE_RE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]{0,119})")
BLOCKED_URLS = ("blob:", "file:", "javascript:", "filesystem:")
MEDIA_KINDS = frozenset({"model3d", "image", "screen"})
COMMAND_KEYS = frozenset({"version", "operation", "intent_id", "input"})
INPUT_KEYS = frozenset({"workspace", "document", "refs", "quality", "shutter", "prores", "output_name"})
INTENT_RE = re.compile(r"[A-Za-z0-9._-]{1,160}")
# Render and encode settings of each export quality level. Draft is the export as it was
# before levels existed: its plan carries no quality fields, so earlier intents replay.
# Final and master average subframes for motion blur; the shutter is in degrees of one frame (180 = half a frame).
QUALITY_PROFILES = {
    "draft": {"supersample": 1, "samples": 0, "subframes": 1, "shutter": 0, "crf": 18, "preset": "fast", "threads": "1"},
    "final": {"supersample": 1.5, "samples": 4, "subframes": 4, "shutter": 180, "crf": 14, "preset": "slow", "threads": "0"},
    "master": {"supersample": 2, "samples": 4, "subframes": 8, "shutter": 180, "crf": 12, "preset": "slow", "threads": "0"},
}
QUALITIES = tuple(QUALITY_PROFILES)
# The page mixes voices in one OfflineAudioContext, bounded like the browser export (mixSceneSpeech).
MAX_VOICED_SECONDS = 180


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


def export_size(width, height, quality: str = "draft") -> tuple[int, int]:
    """Clamp to 1080p on draft. Final and master keep the picture up to 4K and never upscale."""
    width = float(width or 0)
    height = float(height or 0)
    four_k = quality in {"final", "master"}
    if width >= height:
        max_w, max_h = (3840, 2160) if four_k else (1920, 1080)
    else:
        max_w, max_h = (2160, 3840) if four_k else (1080, 1920)
    scale = min(1, max_w / max(1, width), max_h / max(1, height))
    return even_dim(width * scale), even_dim(height * scale)


def h264_encode_level(width: int, height: int, fps: int) -> str | None:
    """x264 ``-level`` once the picture no longer fits level 4.2. 1080p returns None so the command stays as before.

    Level 5.1 (``avc1.640033``) covers 4K at 24 and 30 fps. Level 5.2 (``avc1.640034``) covers 4K at 60 fps.
    """
    blocks = ((int(width) + 15) // 16) * ((int(height) + 15) // 16)
    rate = blocks * int(fps)
    if blocks <= 8704 and rate <= 522240:
        return None
    if blocks <= 36864 and rate <= 983040:
        return "5.1"
    return "5.2"


def playback_speed(value) -> float:
    if isinstance(value, (int, float)) and value == value:
        return max(0.25, min(4.0, float(value)))
    return 1.0


def output_duration(document: dict) -> float:
    return float(document["duration"]) / playback_speed(document.get("playbackSpeed"))


def frame_count(duration: float, fps: int) -> int:
    return max(1, round(float(duration) * int(fps)))


def export_plan(document: dict, quality: str = "draft", shutter: float | None = None) -> dict:
    duration = output_duration(document)
    fps = document.get("fps", 30)
    if fps not in (24, 30, 60):
        raise ValueError("Export fps must be 24, 30 or 60")
    if quality not in QUALITY_PROFILES:
        raise ValueError(f"Export quality must be one of {', '.join(QUALITIES)}")
    width, height = export_size(document.get("width"), document.get("height"), quality)
    plan = {"width": width, "height": height, "fps": fps, "duration": duration,
            "count": frame_count(duration, fps)}
    if quality != "draft":
        profile = QUALITY_PROFILES[quality]
        plan.update(quality=quality, supersample=profile["supersample"], samples=profile["samples"])
        plan.update(_motion_blur(document, profile, shutter))
    elif shutter:
        raise ValueError("Motion blur needs quality final or master")
    return plan


def _motion_blur(document: dict, profile: dict, shutter: float | None) -> dict:
    """Subframes and shutter for one plan. Pixel worlds stay sharp: their art is drawn on a pixel grid."""
    angle = profile["shutter"] if shutter is None else float(shutter)
    if not 0 <= angle <= 360:
        raise ValueError("shutter must be between 0 and 360 degrees")
    if angle == 0 or document.get("pixelWorld"):
        return {"subframes": 1, "shutter": 0}
    return {"subframes": profile["subframes"], "shutter": angle}


def plan_quality(plan: dict) -> str:
    quality = plan.get("quality", "draft")
    return quality if quality in QUALITY_PROFILES else "draft"


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
async function launchRenderer() {
  if (process.env.HOCUS_SCENE_RENDER_DEVICE === 'cpu') {
    console.log('World3D CPU software renderer');
    return chromium.launch({ headless: true, args: [
      '--disable-gpu', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
    ] });
  }
  if (process.platform === 'linux') {
    let accelerated;
    try {
      accelerated = await chromium.launch({ headless: true, args: [
        '--enable-gpu', '--use-angle=vulkan', '--enable-features=Vulkan', '--disable-vulkan-surface',
      ] });
      const probe = await accelerated.newPage();
      const renderer = await probe.evaluate(() => {
        const gl = document.createElement('canvas').getContext('webgl2');
        const info = gl?.getExtension('WEBGL_debug_renderer_info');
        return info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : '';
      });
      await probe.close();
      if (renderer && !/swiftshader|llvmpipe|software/i.test(renderer)) {
        console.log(`World3D hardware renderer: ${renderer}`);
        return accelerated;
      }
    } catch (error) { console.log(`World3D GPU unavailable: ${error.message}`); }
    await accelerated?.close().catch(() => {});
  }
  return chromium.launch({ headless: true });
}
const browser = await launchRenderer();
const page = await browser.newPage();
const frames = `${staging}/frames`;
const bridge = process.env.HOCUS_RENDER_BRIDGE || '__world3dExport';
fs.mkdirSync(frames, { recursive: true });
try {
  await page.goto(new URL(process.env.HOCUS_RENDER_PAGE || '/world3d-render.html', appUrl).href, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(name => !!window[name], bridge, { timeout: 60000 });
  const plan = snapshot.plan;
  const doc = snapshot.document;
  await page.evaluate(({ document: scene, plan: size, bridge: name }) => window[name].load(scene, size), { document: doc, plan, bridge });
  // Geometry warnings first; the stage is a pure function of time, so the frames do not change.
  const geometry = await page.evaluate(name => (window[name].checkGeometry ? window[name].checkGeometry() : null), bridge).catch(() => null);
  if (geometry) fs.writeFileSync(`${staging}/geometry.json`, JSON.stringify(geometry));
  for (let index = 0; index < plan.count; index += 1) {
    const png = await page.evaluate(({ seconds, bridge: name }) => window[name].frame(seconds), { seconds: Math.min(plan.duration, index / plan.fps), bridge });
    const name = String(index + 1).padStart(6, '0');
    fs.writeFileSync(`${frames}/frame_${name}.png`, Buffer.from(png.split(',')[1], 'base64'));
    fs.writeFileSync(`${staging}/progress.json`, JSON.stringify({ current: index + 1, total: plan.count }));
  }
  const wav = await page.evaluate(name => (window[name].audio ? window[name].audio() : ''), bridge).catch(error => {
    fs.writeFileSync(`${staging}/audio-error.txt`, String(error?.message || error).slice(0, 800));
    return '';
  });
  if (typeof wav === 'string' && wav.startsWith('data:audio')) {
    fs.writeFileSync(`${staging}/fx.wav`, Buffer.from(wav.split(',')[1], 'base64'));
  }
} finally {
  await page.evaluate(name => { window[name]?.dispose(); }, bridge).catch(() => {});
  await browser.close();
}
"""


STALL_SECONDS_ENV = "HOCUS_RENDER_STALL_SECONDS"
DEFAULT_STALL_SECONDS = 600.0


def render_stall_seconds() -> float:
    """How long the headless renderer may go without a new frame before it is killed (10 min by default).

    A slow render keeps writing frames; a stuck WebGL page writes none. A 4K master
    frame takes seconds, so ten minutes without one means the page is not coming back.
    """
    try:
        value = float(os.environ.get(STALL_SECONDS_ENV) or DEFAULT_STALL_SECONDS)
    except ValueError:
        value = DEFAULT_STALL_SECONDS
    return value if value > 0 else DEFAULT_STALL_SECONDS


def _kill_tree(proc) -> None:
    """Stop the node script and the browser it launched (its process group on POSIX)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass
        proc.wait(timeout=5)


def _read_progress(staging: Path) -> tuple[int, int] | None:
    try:
        value = json.loads((staging / "progress.json").read_text(encoding="utf-8"))
        return int(value["current"]), int(value["total"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _wait_owned_browser(proc, cancelled, staging: Path | None = None, progress=None, stall_seconds: float | None = None) -> None:
    """Wait for the renderer, publishing each frame it writes; kill it when cancelled or when no frame comes for ``stall_seconds``."""
    limit = render_stall_seconds() if stall_seconds is None else stall_seconds
    last_change, seen = time.monotonic(), None
    try:
        while proc.poll() is None:
            if cancelled():
                raise World3DExportCancelled()
            current = _read_progress(staging) if staging is not None else None
            if current is not None and current != seen:
                seen, last_change = current, time.monotonic()
                if progress is not None:
                    progress(*current)
            if time.monotonic() - last_change > limit:
                frame = f"frame {seen[0]}/{seen[1]}" if seen else "no frame yet"
                raise RuntimeError(f"Headless render stalled: no new frame for {int(limit)} s ({frame})")
            time.sleep(0.1)
        final = _read_progress(staging) if staging is not None else None
        if final is not None and final != seen and progress is not None:
            progress(*final)
    finally:
        _kill_tree(proc)


def run_owned_browser(snapshot: dict, staging: Path, cancelled, *, app_url: str, module: Path,
                      page: str = "/world3d-render.html", bridge: str = "__world3dExport", progress=None) -> list[Path]:
    script = staging / "owned_browser.mjs"
    script.write_text(_OWNED_BROWSER_JS, encoding="utf-8")
    log_path = staging / "browser.log"
    # Output goes to a file: a chatty browser must not fill a pipe nobody drains and block the render.
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            ["node", str(script), str(staging / "snapshot.json"), str(staging)],
            env={**os.environ, "HOCUS_APP_URL": app_url, "PLAYWRIGHT_MODULE": str(module),
                 "HOCUS_RENDER_PAGE": page, "HOCUS_RENDER_BRIDGE": bridge,
                 "HOCUS_SCENE_RENDER_DEVICE": scene_render_device()},
            stdout=log, stderr=subprocess.STDOUT, text=True, start_new_session=(os.name == "posix"),
        )
    _wait_owned_browser(proc, cancelled, staging, progress)
    if proc.returncode == 2:
        raise World3DExportPending("real-render pending: no application URL for the world3d stage")
    if proc.returncode != 0:
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-1000:]
        except OSError:
            tail = ""
        raise RuntimeError(tail or "Headless world3d export failed")
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
        "renderDevice": scene_render_device(),
        "fps": [24, 30, 60], "maxDuration": 600, "maxVoicedDuration": MAX_VOICED_SECONDS,
        "qualities": list(QUALITIES), "motionBlur": {"shutterDegrees": [0, 360], "default": 180},
    }


def renderer_available(app_url: str | None) -> bool:
    from services.world3d_renderer_support import renderer_available as available
    return available(app_url or os.environ.get("HOCUS_APP_URL", ""), playwright_module())


def mux_frame_sequence(frames: list[Path], destination: Path, *, fps: int, duration: float,
                       quality: str = "draft", width: int | None = None, height: int | None = None) -> Path:
    from services.world3d_frame_encoder import mux_frame_sequence as encode
    return encode(frames, destination, fps=fps, duration=duration, quality=quality, width=width, height=height,
                  profiles=QUALITY_PROFILES, level_for=h264_encode_level,
                  validate_output=validate_scene_recording_output, pending_error=World3DExportPending)


def read_geometry_report(staging: Path) -> dict | None:
    """The render page's geometry warnings, bounded; a missing or malformed report is simply absent."""
    path = Path(staging) / "geometry.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8")) if path.is_file() and path.stat().st_size < 1_000_000 else None
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict) or report.get("verdict") not in ("ok", "watch", "fail"):
        return None
    warnings = [item for item in report.get("warnings") or [] if isinstance(item, dict)][:200]
    return {"verdict": report["verdict"], "samples": int(report.get("samples") or 0), "warnings": warnings}


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


def _reject_prores(value: dict) -> None:
    prores = value.get("prores", False)
    if not isinstance(prores, bool):
        raise http_error(422, "invalid_command", "prores must be true or false")
    if prores and value.get("quality", "draft") != "master":
        raise http_error(422, "invalid_command", "ProRes is only available on quality master")


def _input(value) -> dict:
    if not isinstance(value, dict) or set(value) - INPUT_KEYS:
        raise http_error(422, "invalid_command",
                         "input may only include workspace, document, refs, quality, shutter, prores and output_name")
    if value.get("quality", "draft") not in QUALITY_PROFILES:
        raise http_error(422, "invalid_command", f"quality must be one of {', '.join(QUALITIES)}")
    _reject_prores(value)
    shutter = value.get("shutter")
    if shutter is not None and (isinstance(shutter, bool) or not isinstance(shutter, (int, float)) or not 0 <= shutter <= 360):
        raise http_error(422, "invalid_command", "shutter must be a number of degrees between 0 and 360")
    if shutter and value.get("quality", "draft") == "draft":
        raise http_error(422, "invalid_command", "Motion blur needs quality final or master")
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
    # Match sceneVoiceTracks: painted, muted visemes need no audio encoder.
    for slot in document.get("slots") or []:
        speech = slot.get("speech") if isinstance(slot, dict) else None
        if not isinstance(speech, dict) or not speech.get("enabled"):
            continue
        clips = speech.get("clips") if "clips" in speech else [speech]
        if any(isinstance(clip, dict) and clip.get("audio") and clip.get("audible") is not False
               for clip in clips or []):
            return True
    return False


def _audio_url(holder) -> str:
    audio = holder.get("audio") if isinstance(holder, dict) else None
    return str(audio.get("url") or "").strip() if isinstance(audio, dict) else ""


def _audible_clips(slot) -> list:
    speech = slot.get("speech") if isinstance(slot, dict) else None
    if not isinstance(speech, dict) or not speech.get("enabled"):
        return []
    clips = speech.get("clips") if "clips" in speech else [speech]
    return [clip for clip in clips or [] if isinstance(clip, dict) and clip.get("audible") is not False]


def _audio_urls(document: dict) -> list[tuple[str, str]]:
    """``(track key, url)`` of the soundtrack and audible speech clips, as ``sceneVoiceTracks`` lists them."""
    found = [(f"soundtrack/{track.get('id')}", _audio_url(track)) for track in document.get("soundtrack") or []]
    for slot in document.get("slots") or []:
        found += [(f"{slot.get('id')}/{clip.get('id', 'voice')}", _audio_url(clip)) for clip in _audible_clips(slot)]
    return [(key, url) for key, url in found if url]


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
    if _has_sound(document) and output_duration(document) > MAX_VOICED_SECONDS:
        reasons.append("voiced_duration")
    for slot in document.get("slots") or []:
        media = slot.get("media") if isinstance(slot, dict) else None
        if media not in MEDIA_KINDS:
            reasons.append("unsupported_media")
            break
    return reasons


def _ref_from_url(slot: dict, url: str, workspace: str) -> dict:
    # Shipped template assets are served by the UI, not stored in a workspace.
    # Preserve the same URL the editor uses instead of inventing an output filename.
    if url.startswith("/examples/"):
        path = unquote(urlsplit(url).path)
        if ".." in path.split("/") or "\\" in path or "\x00" in path:
            raise http_error(422, "missing_ref", "Use a valid bundled example URL")
        return {"slotId": slot["id"], "url": url, "kind": slot.get("media") or "model3d"}
    # Honor the URL's own workspace. Passing the export workspace into
    # parse_media_ref would hide gallery Uploads (`?workspace=__uploads__`)
    # and media picked from another workspace folder.
    path, scoped = parse_media_ref(url)
    filename = os.path.basename((path or "").replace("\\", "/"))
    if not filename:
        raise http_error(422, "missing_ref", "Each used slot needs a durable media ref")
    record = {
        "slotId": slot["id"], "url": url, "kind": slot.get("media") or "model3d",
        "filename": filename,
    }
    if url.lower().startswith("/api/v1/uploads/") or scoped == "__uploads__":
        record["root"] = "uploads"
    else:
        record["workspace"] = scoped or workspace
    return record


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
    return resolved + _audio_refs(document, workspace)


def _audio_refs(document: dict, workspace: str) -> list[dict]:
    """Voice and soundtrack files are frozen like model refs, so admission checks that they exist."""
    refs = []
    for key, url in _audio_urls(document):
        if _blocked_url(url):
            raise http_error(422, "unsupported_capability", "Ephemeral blob or file URLs cannot be exported")
        record = _ref_from_url({"id": key, "media": "audio"}, url, workspace)
        record["audioId"] = record.pop("slotId")
        refs.append(record)
    return refs


def build_snapshot(document: dict, refs: list[dict], workspace: str, quality: str = "draft",
                   shutter: float | None = None, *, prores: bool = False) -> dict:
    plan = export_plan(document, quality, shutter)
    if prores:
        if quality != "master":
            raise ValueError("ProRes is only available on quality master")
        plan["prores"] = True
    return {
        "workspace": workspace, "document": deepcopy(document), "refs": deepcopy(refs),
        "plan": plan,
    }


def freeze_export_command(command) -> dict:
    envelope = _envelope(command)
    payload = _input(envelope["input"])
    document = _validated_document(payload["document"])
    refs = _validated_refs(document, payload.get("refs"), payload["workspace"])
    reasons = unsupported_capabilities(document)
    if reasons:
        raise http_error(422, "unsupported_capability", "Unsupported export capability: " + ", ".join(reasons))
    snapshot = build_snapshot(
        document, refs, payload["workspace"], payload.get("quality", "draft"), payload.get("shutter"),
        prores=payload.get("prores") is True,
    )
    name_snapshot(snapshot, payload, http_error)
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
                                   "refs": {"type": "array", "maxItems": 64},
                                   "quality": {"enum": list(QUALITIES), "default": "draft",
                                               "description": "draft: as before. final: 1.5x supersampling, 4x MSAA, motion blur of 4 subframes, crf 14. master: 2x supersampling, 4x MSAA, motion blur of 8 subframes, crf 12. Same output size; higher levels take longer."},
                                   "shutter": {"type": "number", "minimum": 0, "maximum": 360,
                                               "description": "Motion blur shutter in degrees of one frame for final/master (default 180; 0 = sharp). Pixel worlds stay sharp."},
                                   "prores": {"type": "boolean", "default": False,
                                              "description": "Optional ProRes 422 HQ master beside the H.264 delivery. Only quality master. Off unless true."},
                                   "output_name": OUTPUT_NAME_SCHEMA},
                    "required": ["workspace", "document"]}
    return [
        {"name": OPERATION, "version": 1, "supportedVersions": [1], "domain": "scenes", "mutation": True,
         "description": "Admit an immutable Video 3D snapshot and durable media refs as one canonical task. A server-owned worker renders with the existing world3d exporter (headless browser is allowed). Closing the UI does not cancel. Reuse intent_id only to recover the receipt; inspect its task for progress, cancel, retry and the validated MP4. output_name publishes it under a stable file name (set-crane-loop.mp4) that a later export with the same name replaces, keeping the replaced file as set-crane-loop.previous.mp4.",
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


def staging_token(intent_id: str) -> str:
    """The staging folder name of an intent: the intent itself when it is a safe name, else a digest."""
    safe = bool(INTENT_RE.fullmatch(intent_id)) and intent_id not in {".", ".."} and ".." not in intent_id
    return intent_id if safe else hashlib.sha256(intent_id.encode("utf-8")).hexdigest()[:32]


def staging_dir(workspace_path: str, intent_id: str, folder: str = ".world3d-export") -> Path:
    path = Path(workspace_path) / folder / staging_token(intent_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


class World3DExportService:
    """Canonical admission plus a process-owned worker independent of the UI tab.

    Subclasses reuse admission, receipts, cancellation and the owned browser by
    overriding the class attributes and the ``freeze``/``prepare_snapshot``/
    ``check_publish``/``output_name``/``sidecar``/``resource_lane`` hooks.
    """

    operation = OPERATION
    title = "Video 3D"
    slug = "world3d-export"
    staging_folder = ".world3d-export"
    render_page = "/world3d-render.html"
    render_bridge = "__world3dExport"

    def __init__(self, *, workspace_dir, registry_for, renderer=None, app_url=None, uploads_dir=None):
        self.workspace_dir = workspace_dir
        self.registry_for = registry_for
        self.renderer = renderer
        self.app_url = app_url if app_url is not None else os.environ.get("HOCUS_APP_URL", "")
        self.uploads_dir = uploads_dir or (lambda: os.path.join(os.getcwd(), "uploads"))
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
                raise http_error(409, "missing_ref", "Upload local scene resources before exporting")

    def submit(self, command) -> dict:
        try:
            frozen = self.freeze(command)
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
                            message=f"Retrying {self.title} export", error=None)
        self._dispatch(registry, previous["intent_id"])
        current = registry.command_admission(previous["intent_id"])
        return {"receipt": deepcopy(current["receipt"]), "replayed": True, "capabilities": self.capabilities()}

    def _task_fields(self, *, task_id, job_id, workspace, plan) -> dict:
        return {
            "id": task_id, "root_id": task_id, "kind": "video", "workflow": self.operation,
            "title": f"{self.title} export", "status": "queued", "phase": "queued",
            "message": f"Queued for {self.title} export", "workspace": workspace,
            "backend_job_id": job_id, "current": 0, "total": plan["count"],
            "resource_requirements": [self.resource_lane().key, "local_cpu:ffmpeg"], "cancelable": True,
            "resumable": True, "recoverable": True,
            "metadata": {"operation": self.operation, "quality": plan_quality(plan)},
        }

    def _admit(self, registry, frozen, workspace) -> dict:
        snapshot = frozen["effective"]["input"]["snapshot"]
        job_id = f"{self.slug}-{uuid.uuid4().hex}"
        task_id = new_task_id(self.slug)
        fields = self._task_fields(task_id=task_id, job_id=job_id, workspace=workspace, plan=snapshot["plan"])
        fields["metadata"].update(agent_attribution(self.operation, frozen["original"]["intent_id"]))
        admitted = registry.admit_command_task(
            intent_id=frozen["original"]["intent_id"], operation=self.operation,
            digest=frozen["fingerprint"], original=frozen["original"],
            effective=frozen["effective"], fingerprint_version=1,
            task_fields=fields,
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
                name=f"{self.slug}-{intent_id[:12]}", daemon=True,
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
            receipt = project_export_receipt(entry["receipt"], task, folder=self.workspace_dir(workspace))
            return {"receipt": receipt, "task": project_export_task(task, receipt), "capabilities": self.capabilities()}
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
            token = get_cancellation_token(registry.workspace_dir, task_id)
            self._ensure_active(token, registry, task_id)
            registry.update(task_id, status="waiting_resource", phase="waiting_resource", message="Waiting for the render lane")
            with resource_scheduler.coordinator.acquire(
                self.resource_lane(), task_id=task_id,
                description=f"{self.title} export", cancelled=lambda: token.is_cancelled()
                or (registry.get(task_id) or {}).get("status") == "cancelled",
            ):
                self._export(registry, intent_id, task_id, workspace)
        except (World3DExportCancelled, resource_scheduler.ResourceAcquireCancelled):
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
            registry.update(task_id, status="running", phase="exporting", message=f"Exporting {self.title}")
        except ValueError as error:
            raise World3DExportCancelled() from error
        entry = registry.command_admission(intent_id)
        snapshot = deepcopy(entry["effective"]["input"]["snapshot"])
        staging = staging_dir(registry.workspace_dir, intent_id, self.staging_folder)
        (staging / "snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        frames = self._render_frames(snapshot, staging, token, registry, task_id)
        # The saved scene file this document came from: the sidecar names it, and it gets a real preview (scene_links).
        from services.scene_links import preview_from_frames, saved_scene_for
        folder = self.workspace_dir(workspace)
        scene_file = saved_scene_for(folder, snapshot["document"])
        if scene_file:
            snapshot["sceneFile"] = scene_file
        published = self._publish(snapshot, staging, frames, workspace, registry, task_id, token)
        if scene_file:
            preview_from_frames(folder, scene_file, frames)
            published = {**published, "scene_file": scene_file}
        metadata = {"operation": self.operation, "quality": plan_quality(snapshot["plan"]), "output": published}
        geometry = read_geometry_report(staging)
        if geometry is not None:
            metadata["geometry"] = geometry
        self._finish(registry, task_id, "completed", phase="completed",
                     message=f"Published {self.title} MP4", result_refs=[published["name"]], metadata=metadata)
        # The frames and audio mix served their purpose; the MP4 is published and the snapshot says what was rendered.
        if not keep_export_staging():
            release_export_staging(staging)

    def _owned_browser(self, snapshot, staging, progress, cancelled) -> list[Path]:
        module = playwright_module()
        if not self.app_url or module is None or not shutil.which("node"):
            raise World3DExportPending("real-render pending: playwright/ffmpeg headless export is not configured")
        rendered = self.prepare_snapshot(snapshot, cancelled)
        (staging / "snapshot.json").write_text(json.dumps(rendered, ensure_ascii=False), encoding="utf-8")
        frames = run_owned_browser(rendered, staging, cancelled, app_url=self.app_url, module=module,
                                   page=self.render_page, bridge=self.render_bridge, progress=progress)
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
        self.check_publish(snapshot)
        plan = snapshot["plan"]
        encoded = staging / "encoded.mp4"
        mux_frame_sequence(
            frames, encoded, fps=plan["fps"], duration=plan["duration"], quality=plan_quality(plan),
            width=plan.get("width"), height=plan.get("height"),
        )
        encoded = self.finish_media(snapshot, staging, encoded)
        master = None
        if plan.get("prores"):
            master = staging / "master.mov"
            write_prores_master(frames, master, fps=plan["fps"], duration=plan["duration"])
        self._ensure_active(token, registry, task_id)
        name = snapshot.get("outputName") or self.output_name(snapshot)
        output = Path(self.workspace_dir(workspace)) / name
        identity = {"sha256": file_sha256(encoded)} if snapshot.get("outputName") else {}
        files = (output, previous_path(output), output.with_suffix(".mov"), previous_path(output.with_suffix(".mov")))
        paths = [path for media in files for path in (media, sidecar_path(media))]
        with publication_lock(output.parent), publication_transaction(paths):
            replaced = publish_export_file(encoded, output, master)
            sidecar = {**self.sidecar(snapshot, name), **requested_by((registry.get(task_id) or {}).get("metadata"))}
            publish_generation_sidecar(output, sidecar, workspace_id=workspace, tool=self.slug,
                                       capability=self.operation, actor="user")
        return {"name": name, "url": f"/api/v1/file/{name}", "workspace": workspace, **replaced, **identity}

    # -- hooks ------------------------------------------------------------------------
    def freeze(self, command) -> dict:
        return freeze_export_command(command)

    def resource_lane(self):
        if scene_render_device() == "cpu":
            return resource_scheduler.cpu_lane("world3d-render")
        return resource_scheduler.local_gpu_lane(0)

    def prepare_snapshot(self, snapshot: dict, cancelled) -> dict:
        return prepare_media_snapshot(snapshot, app_root=Path(__file__).resolve().parents[1],
                                      workspace_root=Path(self.workspace_dir(snapshot["workspace"])), cancelled=cancelled)

    def check_publish(self, snapshot: dict) -> None:
        if _has_sound(snapshot["document"]) and output_duration(snapshot["document"]) > MAX_VOICED_SECONDS:
            raise RuntimeError(f"Voiced World3D export supports up to {MAX_VOICED_SECONDS} output seconds")

    def finish_media(self, snapshot: dict, staging: Path, encoded: Path) -> Path:
        """Mux the page's audio mix. A voiced scene without it is never published as a silent MP4."""
        if not _has_sound(snapshot["document"]):
            return encoded
        wav = staging / "fx.wav"
        if not wav.is_file() or wav.stat().st_size <= 44:
            failure = staging / "audio-error.txt"
            reason = f": {failure.read_text(encoding='utf-8', errors='replace')}" if failure.is_file() else ""
            raise RuntimeError(f"Voiced World3D export produced no audio{reason}; a silent MP4 is not published")
        plan = snapshot["plan"]
        mixed = mux_wav_audio(encoded, wav, plan["duration"], label="World3D audio mix")
        try:
            validate_scene_recording_output(mixed, expected_duration=plan["duration"] if plan["duration"] >= 0.5 else None,
                                            expected_fps=plan["fps"], expected_audio=True)
        except SceneRecordingTranscodeError as error:
            raise RuntimeError(str(error)) from error
        return mixed

    def output_name(self, snapshot: dict) -> str:
        template = re.sub(r"[^A-Za-z0-9._-]+", "-", str(snapshot["document"].get("templateId") or "scene")).strip("-._")[:40] or "scene"
        return f"{time.strftime('%Y-%m-%d-%Hh%Mm%Ss')}_world3d-{template}_{uuid.uuid4().hex[:6]}.mp4"

    def sidecar(self, snapshot: dict, name: str) -> dict:
        plan = snapshot["plan"]
        params = {
            "model_type": "scene-animator-3d", "generation_mode": "3d-scene-compositor",
            "scene": {"version": 1, "name": name, "width": plan["width"], "height": plan["height"],
                      "fps": plan["fps"], "duration": plan["duration"], "layers": []},
            "scene_recipe": {"engine": "world3d", "document": snapshot["document"], "refs": snapshot["refs"]},
            "width": plan["width"], "height": plan["height"], "fps": plan["fps"],
            "duration_seconds": plan["duration"], "quality": plan_quality(plan),
            "shutter": plan.get("shutter", 0),
            **({"scene_file": snapshot["sceneFile"]} if snapshot.get("sceneFile") else {}),
        }
        if plan.get("prores"):
            params["prores"] = True
        return {
            "params": params,
            "generation_mode": "video", "tool": "world3d-export", "output_filename": name,
        }

    def _finish(self, registry, task_id, status, **fields) -> None:
        task = registry.get(task_id)
        if task is None:
            return
        if task["status"] in {"completed", "cancelled"} and status == "failed":
            return
        if isinstance(fields.get("metadata"), dict):
            # Keep what admission recorded (who asked for the export) beside the published output.
            fields["metadata"] = {**(task.get("metadata") or {}), **fields["metadata"]}
        try:
            registry.update(task_id, status=status, **fields)
        except ValueError:
            return


__all__ = [
    "CANCEL_OPERATION", "OPERATION", "QUALITIES", "QUALITY_PROFILES", "RECEIPT_OPERATION", "World3DExportCancelled",
    "World3DExportPending", "World3DExportService", "build_snapshot", "command_catalog",
    "command_handlers", "even_dim", "export_capabilities", "export_plan", "export_size",
    "freeze_export_command", "http_error", "mux_frame_sequence", "mux_wav_audio", "plan_quality", "playwright_module",
    "staging_dir", "staging_token", "unsupported_capabilities", "write_png", "write_prores_master",
]

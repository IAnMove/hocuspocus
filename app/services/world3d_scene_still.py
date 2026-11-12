"""Real stills of a working Video 3D scene: ``world3d.scene.preview {still: true}``.

The cheap preview paints flat boxes at 160 x 90; it cannot show whether a sitter's knees clear a table or a skirt covers
a lap. A still is a frame of the export's own renderer (the owned browser on ``/world3d-render.html``, the same path as
the card thumbnails and ``scenes.world3d.export``) at each asked time, ``LONG_SIDE`` pixels on the long side with the
scene's aspect: the models, their clips, faces, light and look as the MP4 will show them. It holds the export's render
lane (the CPU lane when the renderer is told to stay on CPU), waits at most ``LANE_WAIT_SECONDS`` for it and
``RENDER_SECONDS`` for the frames, and returns JPEGs. Nothing is written to the workspace.
"""
from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
import time
from pathlib import Path

from services import resource_scheduler
from services.world3d_export import (
    World3DExportCancelled,
    World3DExportPending,
    even_dim,
    output_duration,
    playwright_module,
    render_lane,
    run_owned_browser,
)

LONG_SIDE = 640
MAX_TIMES = 3
LANE_WAIT_SECONDS = 30.0
RENDER_SECONDS = 240.0
JPEG_QUALITY = 85
_SERVICE = None
RENDERER = None               # tests replace the browser: (snapshot, staging, cancelled) -> [png paths]


class StillUnavailable(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def bind_still_renderer(service) -> None:
    """The live Video 3D exporter (its app URL and snapshot preparation); bound once at start-up."""
    global _SERVICE
    if getattr(service, "operation", None) == "scenes.world3d.export":
        _SERVICE = service


def still_times(document: dict, times) -> list[float]:
    duration = output_duration(document)
    if times is None:
        return [round(duration / 2, 4)]
    if not isinstance(times, list) or not times or len(times) > MAX_TIMES or \
            not all(type(value) in (int, float) and 0 <= value <= duration for value in times):
        raise ValueError(f"times is a list of 1 to {MAX_TIMES} scene seconds from 0 to {duration:g} for a still")
    return [float(value) for value in times]


def still_plan(document: dict, times: list[float]) -> dict:
    width, height = float(document.get("width") or 1280), float(document.get("height") or 720)
    size = (LONG_SIDE, even_dim(LONG_SIDE * height / width)) if width >= height else (even_dim(LONG_SIDE * width / height), LONG_SIDE)
    fps = document.get("fps") if document.get("fps") in (24, 30, 60) else 30
    return {"width": size[0], "height": size[1], "fps": fps, "duration": output_duration(document), "count": len(times),
            "times": times, "supersample": 1, "samples": 2, "placeholders": True}


def scene_stills(workspace: str, document: dict, times=None, *, renderer=None) -> list[dict]:
    """``[{time, mimeType, data (base64 JPEG), sha256, width, height}]``. ``renderer(snapshot, staging, cancelled) ->
    [png paths]`` replaces the browser (tests)."""
    import base64
    chosen = still_times(document, times)
    snapshot = {"workspace": workspace, "document": document, "refs": [], "plan": still_plan(document, chosen)}
    paint = renderer or RENDERER or _browser()
    staging = Path(tempfile.mkdtemp(prefix="world3d-still-"))
    lane_deadline = time.monotonic() + LANE_WAIT_SECONDS
    try:
        with resource_scheduler.coordinator.acquire(render_lane(), task_id=f"world3d-still-{hashlib.sha256(staging.name.encode()).hexdigest()[:8]}",
                                                    description="Video 3D still", cancelled=lambda: time.monotonic() > lane_deadline):
            deadline = time.monotonic() + RENDER_SECONDS
            frames = paint(snapshot, staging, lambda: time.monotonic() > deadline)
        out = []
        for seconds, frame in zip(chosen, frames):
            data, width, height = _jpeg(Path(frame).read_bytes())
            out.append({"time": seconds, "mimeType": "image/jpeg", "data": base64.b64encode(data).decode("ascii"),
                        "sha256": hashlib.sha256(data).hexdigest(), "width": width, "height": height})
        return out
    except resource_scheduler.ResourceAcquireCancelled as error:
        raise StillUnavailable("busy", f"The render lane is busy (an export or a generation holds it) for more than {int(LANE_WAIT_SECONDS)} s; "
                                       "ask again later or use the cheap preview (still: false)") from error
    except World3DExportCancelled as error:
        raise StillUnavailable("timeout", f"The still did not render within {int(RENDER_SECONDS)} s") from error
    except (World3DExportPending, OSError, RuntimeError, IndexError) as error:
        raise StillUnavailable("render_failed", str(error)[-400:] or "The still render failed") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _browser():
    service = _SERVICE
    module = playwright_module()
    if service is None or not getattr(service, "app_url", "") or module is None or not shutil.which("node"):
        raise StillUnavailable("renderer_unavailable", "Real stills need the app's headless Video 3D renderer (Node, Playwright Chromium "
                                                       "and the built render page); use the cheap preview (still: false)")

    def paint(snapshot, staging, cancelled):
        import json
        prepared = service.prepare_snapshot(snapshot, cancelled)
        (staging / "snapshot.json").write_text(json.dumps(prepared, ensure_ascii=False), encoding="utf-8")
        return run_owned_browser(prepared, staging, cancelled, app_url=service.app_url, module=module)
    return paint


def _jpeg(png: bytes) -> tuple[bytes, int, int]:
    from PIL import Image
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "JPEG", quality=JPEG_QUALITY)
        return buffer.getvalue(), image.width, image.height


def still_view(workspace: str, scene_id: str, workspace_dir, times=None, expected_revision: int | None = None) -> dict:
    """The reply of ``world3d.scene.preview {still: true}``: one JPEG per time in ``images`` (the frames list carries
    their time, size and sha256, not the picture again)."""
    from services.world3d_scenes import World3DSceneError, _read
    record = _read(workspace, scene_id, workspace_dir)
    if expected_revision is not None and expected_revision != record["revision"]:
        raise World3DSceneError("revision_conflict", "Preview revision does not match the scene.", 409)
    try:
        stills = scene_stills(workspace, record["document"], times)
    except ValueError as error:
        raise World3DSceneError("invalid_times", str(error)) from error
    except StillUnavailable as error:
        raise World3DSceneError(f"still_{error.reason}", str(error), 503) from error
    return {"sceneId": scene_id, "revision": record["revision"], "templateId": record["templateId"], "still": True,
            "times": [item["time"] for item in stills],
            "frames": [{key: item[key] for key in ("time", "sha256", "width", "height")} for item in stills],
            "images": [{"mimeType": item["mimeType"], "data": item["data"]} for item in stills]}

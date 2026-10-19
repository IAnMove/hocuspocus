"""Our own picture of a Video 3D template card: the built shot at mid-shot, rendered on demand and cached.

A card's ``reference`` is a film still of the real technique; this is what OUR template looks like. The picture is
painted by the owned browser the 3D export uses (``run_owned_browser`` on ``/world3d-render.html``): one frame at half
the shot, with empty slots drawn as the editor draws its placeholders (``placeholders`` in the plan). It is cached under
the default workspace's ``.world3d-thumbs`` as ``<id>-<recipe>.webp``; the recipe hashes the compiled document with
``RENDER_RECIPE``, so a template renders once per version and a renderer change renders every card again.

One render runs at a time and holds the export's render lane, with short waits and a short timeout. When no picture
can be made now the caller gets ``ThumbnailUnavailable`` (HTTP 503 ``thumbnail_unavailable``, ``retryable``), never
a broken image. A card that shows optional example media this installation has not downloaded is refused before any
render with ``ThumbnailNeedsExamples`` (HTTP 409 ``examples_not_installed``): the browser would wait for files the
server cannot serve.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from services import resource_scheduler
from services.example_assets import ExampleAssets, example_assets
from services.production_scene3d import RENDER_RECIPE
from services.world3d_export import (
    World3DExportCancelled,
    World3DExportPending,
    even_dim,
    output_duration,
    playwright_module,
    render_lane,
    renderer_available,
    run_owned_browser,
)
from services.world3d_scenes import World3DSceneError, compile_template_document
from services.world3d_template_catalog import World3DTemplateError, require_card

FOLDER = ".world3d-thumbs"
LONG_SIDE = 640
# Bump when the thumbnail plan changes (size, supersampling, the time it shows): every cached picture renders again.
THUMBNAIL_RECIPE = 1
SUPERSAMPLE = 2
SAMPLES = 4
WEBP_QUALITY = 82
# A second request waits this long for the render in progress before it is told to come back.
LOCK_WAIT_SECONDS = 20.0
# A generation or an export may hold the render lane for minutes; a thumbnail does not queue behind it.
LANE_WAIT_SECONDS = 30.0
RENDER_TIMEOUT_SECONDS = 120.0
RETRY_AFTER_SECONDS = 5
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXAMPLES_PREFIX = "/examples/"


class ThumbnailUnavailable(Exception):
    """No picture can be made now; the same request may succeed later (HTTP 503, retryable)."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class ThumbnailNeedsExamples(Exception):
    """The card shows example media that is not installed here; it renders once its collections are downloaded (409)."""

    def __init__(self, collections: list[str], files: list[str]) -> None:
        self.collections = collections
        self.files = files
        what = ", ".join(collections) if collections else ", ".join(files[:3])
        super().__init__(f"This template shows example media that is not installed: download {what} from the shot library first")


@dataclass(frozen=True)
class Thumbnail:
    path: Path
    recipe: str
    cached: bool

    @property
    def media_type(self) -> str:
        return "image/webp" if self.path.suffix == ".webp" else "image/png"


def thumbnail_size(document: dict) -> tuple[int, int]:
    """640 on the long side with the document's aspect: 640x360 for a landscape card, 360x640 for a portrait one."""
    width = float(document.get("width") or 1280)
    height = float(document.get("height") or 720)
    if width >= height:
        return LONG_SIDE, even_dim(LONG_SIDE * height / width)
    return even_dim(LONG_SIDE * width / height), LONG_SIDE


def thumbnail_plan(document: dict) -> dict:
    """The owned browser's plan for one still at half the output duration, supersampled, placeholders drawn."""
    width, height = thumbnail_size(document)
    duration = output_duration(document)
    fps = document.get("fps") if document.get("fps") in (24, 30, 60) else 30
    return {"width": width, "height": height, "fps": fps, "duration": duration, "count": 1,
            "times": [round(duration / 2, 4)], "supersample": SUPERSAMPLE, "samples": SAMPLES, "placeholders": True}


def thumbnail_recipe(document: dict) -> str:
    """The cache key of a card's picture: its compiled document, the renderer recipe and the thumbnail plan version."""
    payload = json.dumps({"document": document, "render": RENDER_RECIPE, "thumbnail": THUMBNAIL_RECIPE},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def example_files(node) -> set[str]:
    """The ``/examples/…`` files a compiled document shows, without query strings."""
    if isinstance(node, str):
        return {node[len(EXAMPLES_PREFIX):].split("?", 1)[0]} if node.startswith(EXAMPLES_PREFIX) else set()
    values = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
    return set().union(*(example_files(value) for value in values))


def missing_examples(document: dict, assets: ExampleAssets) -> tuple[list[str], list[str]]:
    """The collections and files of the document's example media that this installation cannot serve."""
    missing = set()
    for name in example_files(document):
        try:
            if assets.cached(name) is not None:
                continue
        except KeyError:
            pass                                          # not in the manifest: no download serves it either
        missing.add(name)
    collections = sorted(name for name, pack in assets.collections.items() if missing & set(pack["files"]))
    return collections, sorted(missing)


def encode_thumbnail(frame: Path) -> tuple[bytes, str]:
    """The painted PNG as WebP when Pillow can write it, else the PNG itself. A frame that is not a picture fails."""
    data = Path(frame).read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("The renderer did not paint a PNG frame")
    try:
        from PIL import Image, features
    except ImportError:
        return data, ".png"
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if not features.check("webp"):
            return data, ".png"
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "WEBP", quality=WEBP_QUALITY, method=4)
    return buffer.getvalue(), ".webp"


def paint_still(snapshot: dict, staging: Path, cancelled, *, app_url: str, module: Path) -> Path:
    """The PNG of ``plan.times[0]``, painted by the export's owned browser (no geometry report, no sound)."""
    (staging / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    frames = run_owned_browser(snapshot, staging, cancelled, app_url=app_url, module=module)
    return frames[0]


class World3DThumbnails:
    """Render and cache card thumbnails. ``renderer(snapshot, staging, cancelled) -> png path`` replaces the browser."""

    def __init__(self, *, outputs_dir: Callable[[], str | os.PathLike],
                 app_url: Callable[[], str] = lambda: os.environ.get("HOCUS_APP_URL", ""),
                 renderer=None, compile_document: Callable[[str], dict] = compile_template_document,
                 lock_wait: float = LOCK_WAIT_SECONDS, lane_wait: float = LANE_WAIT_SECONDS,
                 timeout: float = RENDER_TIMEOUT_SECONDS, examples: ExampleAssets = example_assets) -> None:
        self.outputs_dir = outputs_dir
        self.examples = examples
        self.app_url = app_url
        self.renderer = renderer
        self.compile_document = compile_document
        self.lock_wait = lock_wait
        self.lane_wait = lane_wait
        self.timeout = timeout
        self.origin = ""
        self._lock = threading.Lock()

    def bind_origin(self, server) -> None:
        """The app's own listening socket, as the export binds it; never a client-controlled Host header."""
        if not self.origin and server:
            self.origin = f"http://127.0.0.1:{server[1]}"

    def render_url(self) -> str:
        return self.app_url() or self.origin

    def folder(self) -> Path:
        return Path(self.outputs_dir()) / FOLDER

    def thumbnail(self, template_id: str) -> Thumbnail:
        """The cached picture of one shipped or stage card, rendered first when this version has none."""
        document = self._document(self._card_id(template_id))
        recipe = thumbnail_recipe(document)
        cached = self._cached(template_id, recipe)
        if cached is not None:
            return Thumbnail(cached, recipe, True)
        collections, files = missing_examples(document, self.examples)
        if files:
            raise ThumbnailNeedsExamples(collections, files)
        if not self._lock.acquire(timeout=self.lock_wait):
            raise ThumbnailUnavailable("busy", "Another template thumbnail is rendering; ask again shortly")
        try:
            # The render this request waited for may have been this very picture.
            cached = self._cached(template_id, recipe)
            if cached is not None:
                return Thumbnail(cached, recipe, True)
            return Thumbnail(self._render(template_id, recipe, document), recipe, False)
        finally:
            self._lock.release()

    # -- steps --------------------------------------------------------------------------
    def _card_id(self, template_id: str) -> str:
        """Shipped and stage cards only: a personal template has no thumbnail, an id that cannot exist is unknown."""
        if not isinstance(template_id, str) or not ID_RE.fullmatch(template_id):
            raise World3DTemplateError("unknown_template", f"unknown_template:{template_id}", 404)
        return require_card(template_id)["id"]

    def _document(self, template_id: str) -> dict:
        try:
            return self.compile_document(template_id)
        except World3DSceneError as error:
            if error.code == "unknown_template":
                raise World3DTemplateError("unknown_template", f"unknown_template:{template_id}", 404) from error
            raise ThumbnailUnavailable("template_tool_unavailable", str(error)) from error

    def _cached(self, template_id: str, recipe: str) -> Path | None:
        for suffix in (".webp", ".png"):
            path = self.folder() / f"{template_id}-{recipe}{suffix}"
            if path.is_file() and path.stat().st_size > 0:
                return path
        return None

    def _render(self, template_id: str, recipe: str, document: dict) -> Path:
        self._check_renderer()
        try:
            lane = render_lane()
        except ValueError as error:
            raise ThumbnailUnavailable("renderer_unavailable", str(error)) from error
        snapshot = {"workspace": "default", "document": document, "refs": [], "plan": thumbnail_plan(document)}
        staging = self.folder() / ".staging" / uuid.uuid4().hex
        staging.mkdir(parents=True, exist_ok=True)
        lane_deadline = time.monotonic() + self.lane_wait
        try:
            with resource_scheduler.coordinator.acquire(
                lane, task_id=f"world3d-thumbnail-{template_id}", description=f"Video 3D thumbnail {template_id}",
                cancelled=lambda: time.monotonic() > lane_deadline,
            ):
                deadline = time.monotonic() + self.timeout
                frame = self._paint(snapshot, staging, lambda: time.monotonic() > deadline)
            return self._publish(Path(frame), template_id, recipe)
        except ThumbnailUnavailable:
            raise
        except resource_scheduler.ResourceAcquireCancelled as error:
            raise ThumbnailUnavailable("gpu_busy", "The render lane is busy (a generation or an export holds it); ask again later") from error
        except World3DExportCancelled as error:
            raise ThumbnailUnavailable("timeout", f"The thumbnail did not render within {int(self.timeout)} s") from error
        except World3DExportPending as error:
            raise ThumbnailUnavailable("renderer_unavailable", str(error)) from error
        except (OSError, RuntimeError, ValueError, IndexError) as error:
            raise ThumbnailUnavailable("render_failed", str(error)[-500:] or "The thumbnail render failed") from error
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _check_renderer(self) -> None:
        if self.renderer is not None:
            return
        url = self.render_url()
        if not url or playwright_module() is None or not shutil.which("node") or not renderer_available(url):
            raise ThumbnailUnavailable(
                "renderer_unavailable",
                "The headless Video 3D renderer is not available here: it needs Node, Playwright Chromium and the built render page",
            )

    def _paint(self, snapshot: dict, staging: Path, cancelled) -> Path:
        if self.renderer is not None:
            return self.renderer(snapshot, staging, cancelled)
        module = playwright_module()
        if module is None:
            raise ThumbnailUnavailable("renderer_unavailable", "Playwright is not installed with the UI")
        return paint_still(snapshot, staging, cancelled, app_url=self.render_url(), module=module)

    def _publish(self, frame: Path, template_id: str, recipe: str) -> Path:
        data, suffix = encode_thumbnail(frame)
        folder = self.folder()
        path = folder / f"{template_id}-{recipe}{suffix}"
        partial = folder / f".{path.name}.{uuid.uuid4().hex[:8]}.partial"
        partial.write_bytes(data)
        os.replace(partial, path)
        self._drop_stale(template_id, path)
        return path

    def _drop_stale(self, template_id: str, keep: Path) -> None:
        """Earlier versions of the same card. The pattern is exact: ``cine-dolly-zoom`` never drops ``-in``'s file."""
        pattern = re.compile(re.escape(template_id) + r"-[0-9a-f]{16}\.(?:webp|png)")
        for path in keep.parent.iterdir():
            if path != keep and pattern.fullmatch(path.name):
                path.unlink(missing_ok=True)


__all__ = [
    "FOLDER", "RETRY_AFTER_SECONDS", "Thumbnail", "ThumbnailNeedsExamples", "ThumbnailUnavailable", "World3DThumbnails",
    "encode_thumbnail", "example_files", "missing_examples", "paint_still", "thumbnail_plan", "thumbnail_recipe",
    "thumbnail_size",
]

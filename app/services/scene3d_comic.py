"""One operation for a comic-page chapter change: exit one panel, see the page, enter the next.

MCP, the Wizard and the Video 3D editor call ``scene3d.comic.transition``. Both scenes are saved
in the workspace. Export uses the Video 3D exporter when launch has bound it.
"""
from __future__ import annotations

import base64
import struct
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from fastapi import HTTPException
from PIL import Image

from services.scene3d_comic_cutout import cutout_is_empty, cutout_panel, finish_cutout
from services.video_editor import extract_frame
from services.world3d_scenes import World3DSceneError, publish_scene, run_template_tool, store_working_scene

_ASPECT = {"landscape": 16 / 9, "portrait": 9 / 16}
_TOLERANCE = 0.02
_EXPORTER = None


def bind_comic_exporter(exporter) -> None:
    """Tests pass a fake. ``None`` clears it. The live exporter is bound from the export router."""
    global _EXPORTER
    _EXPORTER = exporter


def bind_live_exporter(service) -> None:
    if getattr(service, "operation", None) == "scenes.world3d.export":
        bind_comic_exporter(_LiveExporter(service))


class _LiveExporter:
    """Submit both clips to the existing exporter and wait until each file exists. No short timeout."""

    def __init__(self, service) -> None:
        self._service = service

    def export_clip(self, workspace: str, document: dict, output_name: str) -> dict:
        intent = f"comic-{output_name}-{uuid.uuid4().hex[:10]}"
        command = {
            "version": 1, "operation": "scenes.world3d.export", "intent_id": intent,
            "input": {"workspace": workspace, "document": document, "quality": "draft", "output_name": output_name},
        }
        try:
            self._service.submit(command)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            raise World3DSceneError(str(detail.get("code") or "export_failed"), str(detail.get("message") or exc.detail), exc.status_code) from exc
        while True:
            viewed = self._service.receipt(workspace, intent)
            task = viewed.get("task") or {}
            status = task.get("status")
            if status == "completed":
                return _published(viewed.get("receipt") or {}, output_name, workspace)
            if status in {"failed", "cancelled", "interrupted"}:
                raise World3DSceneError("export_failed", str(task.get("error") or status), 502)
            time.sleep(0.5)


def comic_transition(data: dict, workspace_dir) -> dict:
    if data.get("montage") is not None:
        from services.scene3d_comic_montage import comic_from_montage
        return comic_from_montage(data, workspace_dir, comic_transition)
    workspace = str(data.get("workspace") or "")
    fmt, from_panel, to_panel, seed, specs = _request(data)
    exporting = data.get("export") is True
    if exporting and _EXPORTER is None:
        raise World3DSceneError("export_unavailable", "Video 3D export is not available on this server", 503)
    root = Path(workspace_dir(workspace))
    sources = [_locate(spec, root, index) for index, spec in enumerate(specs)]
    width, height = _same_frame(sources, fmt)
    exit_duration, enter_duration, hold = _timing(data)
    cells, page_png = _layout(fmt, len(specs), seed, from_panel, to_panel)
    root.mkdir(parents=True, exist_ok=True)
    page_url = _write_page(page_png, fmt, workspace, root)
    panels, warnings = _stage_panels(
        sources, cells, {from_panel, to_panel}, (width, height), workspace, root, workspace_dir,
    )
    built = run_template_tool("comic", _payload(
        fmt, width, height, page_url, panels, from_panel, to_panel, seed, exit_duration, enter_duration, hold,
    ))
    documents = [("exit", built.get("exit")), ("enter", built.get("enter"))]
    scenes = [_save(workspace, workspace_dir, role, document) for role, document in documents]
    clips = [_clip(workspace, role, document, scene) for (role, document), scene in zip(documents, scenes)] if exporting else []
    return {"status": "completed", "scenes": scenes, "clips": clips, "warnings": warnings, "layout": {"seed": seed, "cells": cells}}


def _request(data: dict):
    fmt = data.get("format")
    if fmt not in _ASPECT:
        raise World3DSceneError("invalid_format", "format is landscape or portrait")
    panels = data.get("panels")
    if not isinstance(panels, list) or not 3 <= len(panels) <= 6:
        raise World3DSceneError("panel_count", "panels must be three to six images or {video, at} frames")
    count = len(panels)
    from_panel = _index(data.get("from_panel", 0), "from_panel", count)
    to_panel = _index(data.get("to_panel", count - 1), "to_panel", count)
    if from_panel == to_panel:
        raise World3DSceneError("same_panel", "from_panel and to_panel must differ")
    return fmt, from_panel, to_panel, _seed(data.get("seed", 0)), [_spec(raw, index) for index, raw in enumerate(panels)]


def _index(value, name: str, count: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < count:
        raise World3DSceneError("panel_index", f"{name} must be an index of panels")
    return value


def _seed(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
        raise World3DSceneError("invalid_seed", "seed must be an integer from 0 to 1000000")
    return value


def _spec(raw, index: int) -> dict:
    if isinstance(raw, str) and raw.strip():
        return {"image": raw.strip()}
    if isinstance(raw, dict):
        cutout = raw.get("cutout")
        extra = {"cutout": cutout.strip()} if isinstance(cutout, str) and cutout.strip() else {}
        image = raw.get("image")
        video = raw.get("video")
        if isinstance(image, str) and image.strip():
            return {"image": image.strip(), **extra}
        if isinstance(video, str) and video.strip() and _seconds(raw.get("at")) is not None:
            return {"video": video.strip(), "at": _seconds(raw.get("at")), **extra}
    raise World3DSceneError("missing_source", f"panels[{index}] needs an image or a video and a time")


def _seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 86400:
        return None
    return float(value)


def _locate(spec: dict, root: Path, index: int) -> dict:
    image = _read_path(spec["image"], root) if "image" in spec else _read_path(spec["video"], root)
    if not image.is_file():
        raise World3DSceneError("missing_source", f"missing_source:panels[{index}]")
    cutout = _read_path(spec["cutout"], root) if spec.get("cutout") else None
    if spec.get("cutout") and (cutout is None or not cutout.is_file()):
        raise World3DSceneError("missing_source", f"missing_source:panels[{index}].cutout")
    return {**spec, "path": image, "cutout_path": cutout}


def _read_path(text: str, root: Path) -> Path:
    if text.startswith("/api/v1/file/"):
        name = unquote(urlsplit(text).path[len("/api/v1/file/"):])
        if not _basename(name):
            raise World3DSceneError("missing_source", f"missing_source:{name}")
        path = (root / name).resolve()
        if not _inside(root, path):
            raise World3DSceneError("missing_source", f"missing_source:{name}")
        return path
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate
    if not _basename(text):
        raise World3DSceneError("missing_source", f"missing_source:{text}")
    path = (root / text).resolve()
    if not _inside(root, path):
        raise World3DSceneError("missing_source", f"missing_source:{text}")
    return path


def _basename(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name and name not in {".", ".."}


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _same_frame(sources: list[dict], fmt: str) -> tuple[int, int]:
    sizes = [_image_size(item["path"]) if "image" in item else _video_size(item["path"]) for item in sources]
    width, height = sizes[0]
    if any(size != (width, height) for size in sizes) or not _aspect_ok(width, height, fmt):
        raise World3DSceneError("panel_aspect", "Every panel must match the video frame's aspect")
    return width, height


def _aspect_ok(width: int, height: int, fmt: str) -> bool:
    if width <= 0 or height <= 0:
        return False
    target = _ASPECT[fmt]
    return abs((width / height) - target) / target <= _TOLERANCE


def _image_size(path: Path) -> tuple[int, int]:
    blob = path.read_bytes()[:24]
    if blob.startswith(b"\x89PNG\r\n\x1a\n") and len(blob) >= 24:
        return struct.unpack(">II", blob[16:24])
    probed = _ffprobe_size(path)
    if probed:
        return probed
    raise World3DSceneError("missing_source", f"unreadable_image:{path.name}")


def _video_size(path: Path) -> tuple[int, int]:
    probed = _ffprobe_size(path)
    if not probed:
        raise World3DSceneError("missing_source", f"unreadable_video:{path.name}")
    return probed


def _ffprobe_size(path: Path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True, check=False,
    )
    parts = (proc.stdout or "").strip().split("x")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return None


def _layout(fmt: str, count: int, seed: int, from_panel: int, to_panel: int):
    import json
    built = run_template_tool("comic-layout", json.dumps({
        "format": fmt, "count": count, "seed": seed, "fromPanel": from_panel, "toPanel": to_panel,
    }))
    cells, png = built.get("cells"), built.get("png")
    if not isinstance(cells, list) or len(cells) != count or not isinstance(png, str):
        raise World3DSceneError("template_tool_failed", "The comic layout tool did not return a page")
    return cells, base64.b64decode(png)


def _write_page(png: bytes, fmt: str, workspace: str, root: Path) -> str:
    name = f"comic-page-{fmt}.png"
    (root / name).write_bytes(png)
    return _url(name, workspace)


def _stage_panels(sources, cells, heroes, frame_size, workspace, root, workspace_dir):
    """The cut panels stay at the source frame size. The other panels are cover-cropped to the cell."""
    staged, warnings = [], []
    for index, item in enumerate(sources):
        size = frame_size if index in heroes else _cell_size(cells[index], index)
        panel, warning = _stage_panel(item, index, size, workspace, root, workspace_dir)
        staged.append(panel)
        if warning:
            warnings.append(f"panels[{index}]: {warning}")
    return staged, warnings


def _cell_size(cell, index: int) -> tuple[int, int]:
    if not isinstance(cell, dict):
        raise World3DSceneError("template_tool_failed", f"comic layout cell {index} is not a picture size")
    width, height = cell.get("w"), cell.get("h")
    if isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, int) or not isinstance(height, int):
        raise World3DSceneError("template_tool_failed", f"comic layout cell {index} is not a picture size")
    if width < 2 or height < 2:
        raise World3DSceneError("template_tool_failed", f"comic layout cell {index} is not a picture size")
    return width, height


def _stage_panel(item: dict, index: int, size: tuple[int, int], workspace: str, root: Path, workspace_dir) -> tuple[dict, str | None]:
    name = f"comic-panel-{index}.png"
    dest = root / name
    if "video" in item:
        extract_frame(str(item["path"]), str(dest), item["at"])
        _cover(dest, dest, size)
    else:
        _cover(item["path"], dest, size)
    staged = {"url": _url(name, workspace)}
    warning = None
    cutout_src = item.get("cutout_path") or None
    if cutout_src is not None and cutout_is_empty(Path(cutout_src)):
        warning = f"{Path(cutout_src).name}: cutout unavailable (empty)"
        cutout_src = None
    elif cutout_src is None:
        made, warning = cutout_panel(dest, root / f"comic-cutout-src-{index}.png", workspace, workspace_dir)
        cutout_src = made
    if cutout_src is not None:
        cutout_name = f"comic-cutout-{index}.png"
        cutout_dest = root / cutout_name
        _cover(Path(cutout_src), cutout_dest, size)
        _keep_picture_color(cutout_dest, dest)
        try:
            finish_cutout(dest, cutout_dest)
        except Exception as exc:
            warning = f"{dest.name}: cutout unavailable ({exc})"
        else:
            staged["cutout"] = _url(cutout_name, workspace)
    return staged, warning


def _cover(source: Path, dest: Path, size: tuple[int, int]) -> None:
    width, height = size
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    if image.size == (width, height):
        if Path(source).resolve() != Path(dest).resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            image.save(dest)
        return
    scale = max(width / image.width, height / image.height)
    resized = image.resize((max(width, round(image.width * scale)), max(height, round(image.height * scale))), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    dest.parent.mkdir(parents=True, exist_ok=True)
    resized.crop((left, top, left + width, top + height)).save(dest)


def _keep_picture_color(cutout: Path, picture: Path) -> None:
    """A matte may recolor its edges. The cut matches only when the cutout uses the picture's colour."""
    with Image.open(picture) as opened:
        base = opened.convert("RGBA")
    with Image.open(cutout) as opened:
        mask = opened.convert("RGBA")
    if mask.size != base.size:
        return
    painted = base.copy()
    painted.putalpha(mask.getchannel("A"))
    painted.save(cutout)


def _url(name: str, workspace: str) -> str:
    return f"/api/v1/file/{quote(name)}?workspace={quote(workspace)}"


def _timing(data: dict) -> tuple[float, float, float]:
    exit_duration = _seconds_between(data.get("exit_duration", 1.8), "exit_duration", 0.8, 8)
    enter_duration = _seconds_between(data.get("enter_duration", 1.8), "enter_duration", 0.8, 8)
    hold = _seconds_between(data.get("hold", 0.4), "hold", 0, 2)
    if hold >= min(exit_duration, enter_duration):
        raise World3DSceneError("invalid_duration", "hold must be shorter than both halves")
    return exit_duration, enter_duration, hold


def _seconds_between(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= float(value) <= high:
        raise World3DSceneError("invalid_duration", f"{name} must be between {low:g} and {high:g} seconds")
    return float(value)


def _payload(fmt, width, height, page_url, panels, from_panel, to_panel, seed, exit_duration, enter_duration, hold) -> str:
    import json
    return json.dumps({
        "format": fmt, "width": width, "height": height, "pageUrl": page_url,
        "panels": panels, "fromPanel": from_panel, "toPanel": to_panel, "seed": seed,
        "exitDuration": exit_duration, "enterDuration": enter_duration, "hold": hold,
    })


def _save(workspace: str, workspace_dir, role: str, document) -> dict:
    if not isinstance(document, dict):
        raise World3DSceneError("template_tool_failed", "The comic template tool did not return a scene")
    stored = store_working_scene(workspace, document, workspace_dir, template_id=document.get("templateId"))
    published = publish_scene(workspace, stored["sceneId"], workspace_dir)
    return {
        "role": role, "sceneId": stored["sceneId"], "revision": published["revision"],
        "file": published["file"], "url": published.get("url"), "templateId": document.get("templateId"),
    }


def _clip(workspace: str, role: str, document, scene: dict) -> dict:
    exporter = _EXPORTER
    if exporter is None or not isinstance(document, dict):
        raise World3DSceneError("export_unavailable", "Video 3D export is not available on this server", 503)
    clip = exporter.export_clip(workspace, document, f"comic-panel-{role}")
    return {"role": role, "sceneId": scene["sceneId"], "name": clip.get("name"), "url": clip.get("url")}


def _published(receipt: dict, output_name: str, workspace: str) -> dict:
    artifacts = receipt.get("artifacts") or []
    if artifacts:
        return {"name": artifacts[0].get("name") or f"{output_name}.mp4", "url": artifacts[0].get("url") or ""}
    return {"name": f"{output_name}.mp4", "url": _url(f"{output_name}.mp4", workspace)}

"""Editable montages: a Video Editor timeline saved in a workspace.

A montage (``<name>.montage.json``) is the durable, server-side form of a Video
Editor project. It references clips, a soundtrack, timed audio cues and image
overlays that already live in the workspace; nothing is rendered or copied when
it is saved. Agents create and update montages through versioned commands and
people open the same file in the Video Editor, so a finished video stays
editable block by block and can be exported again after a retouch.

Clips may name their ``origin`` (for example the ``.scene.json`` a clip was
rendered from). The origin is provenance only: exporting a montage uses the
clip media exactly as referenced.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from services.video_editor_layers import LayerValidationError, clean_audio_cues, clean_duck, clean_overlays

SUFFIX = ".montage.json"
MAX_CLIPS = 100
MAX_BYTES = 2 * 1024 * 1024
WORKSPACE_RE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]{0,119})")
FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.montage\.json")
BLOCKED = ("blob:", "file:", "javascript:", "filesystem:", "data:")
ORIGIN_KINDS = frozenset({"scene2d", "scene3d", "generation", "upload", "render", "production"})
ORIGIN_TEXT = ("scene", "note", "meta", "derivedFrom", "productionId", "shotId", "takeId")
MAX_TAKES = 20
FPS = (24, 25, 30, 50, 60)


class MontageError(ValueError):
    """Invalid montage or command; the message is safe to show."""

    def __init__(self, message: str, *, status: int = 422, code: str = "invalid_montage") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _number(value: Any, label: str, low: float, high: float, default: float | None = None) -> float:
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        raise MontageError(f"{label} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MontageError(f"{label} must be a number") from exc
    if number != number or not low <= number <= high:
        raise MontageError(f"{label} must be between {low:g} and {high:g}")
    return number


def _source(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MontageError(f"{label} source is missing")
    if len(text) > 2000 or text.lower().startswith(BLOCKED):
        raise MontageError(f"{label} must reference durable workspace media, not a local or inline URL")
    return text


def _origin(raw: Any, label: str) -> dict[str, str] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("kind") not in ORIGIN_KINDS:
        raise MontageError(f"{label} origin needs a kind: {', '.join(sorted(ORIGIN_KINDS))}")
    origin = {"kind": str(raw["kind"])}
    for key in ORIGIN_TEXT:
        if raw.get(key) is not None:
            origin[key] = str(raw[key]).strip()[:500]
    return origin


def _take(raw: Any, label: str) -> dict[str, Any]:
    """An alternative for a clip: finished media, or a queued generation still pending."""
    if not isinstance(raw, dict):
        raise MontageError(f"{label} is invalid")
    take: dict[str, Any] = {"id": str(raw.get("id") or "").strip()[:160]}
    if not take["id"]:
        raise MontageError(f"{label} needs an id")
    pending = raw.get("pending")
    if isinstance(pending, dict):
        take["pending"] = {key: str(pending[key])[:160] for key in ("jobId", "intentId") if pending.get(key)}
        if "jobId" not in take["pending"]:
            raise MontageError(f"{label} pending take needs a jobId")
    else:
        take["source"] = _source(raw.get("source"), label)
    origin = _origin(raw.get("origin"), label)
    if origin:
        take["origin"] = origin
    for key in ("createdAt", "note"):
        if raw.get(key):
            take[key] = str(raw[key])[:300]
    return take


def _takes(raw: Any, label: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_TAKES:
        raise MontageError(f"{label} takes must be a list of at most {MAX_TAKES}")
    takes = [_take(item, f"{label} take {index + 1}") for index, item in enumerate(raw)]
    if len({take["id"] for take in takes}) != len(takes):
        raise MontageError(f"{label} take ids must be unique")
    return takes


_FRAME_KNOBS = (
    ("focusX", 0, 100),
    ("focusY", 0, 100),
    ("blurAmount", 0, 1),
    ("backgroundDim", 0, 1),
)


def _frame_fields(raw: dict, label: str) -> dict[str, Any]:
    fit = raw.get("fit", "fit")
    if fit not in ("fit", "fill", "blur"):
        raise MontageError(f"{label} fit must be fit, fill or blur")
    fields: dict[str, Any] = {"fit": fit}
    for key, low, high in _FRAME_KNOBS:
        if key not in raw or raw.get(key) is None:
            continue
        fields[key] = _number(raw.get(key), f"{label} {key}", low, high)
    return fields


def _clip(raw: Any, index: int) -> dict[str, Any]:
    label = f"Clip {index + 1}"
    if not isinstance(raw, dict):
        raise MontageError(f"{label} is invalid")
    trim_start = _number(raw.get("trimStart"), f"{label} trimStart", 0, 36000, 0)
    trim_end = _number(raw.get("trimEnd"), f"{label} trimEnd", 0, 36000, 0)
    if trim_end and trim_end <= trim_start:
        raise MontageError(f"{label} trimEnd must be after trimStart")
    clip = {
        "id": str(raw.get("id") or f"clip-{index + 1}").strip()[:160],
        "name": str(raw.get("name") or os.path.basename(str(raw.get("source") or "")) or label).strip()[:300],
        "source": _source(raw.get("source"), label),
        "trimStart": trim_start,
        "trimEnd": trim_end,
        "volume": _number(raw.get("volume"), f"{label} volume", 0, 2, 1),
        "muted": bool(raw.get("muted", False)),
        "transition": str(raw.get("transition") or "none").strip()[:40],
        "transitionDuration": _number(raw.get("transitionDuration"), f"{label} transitionDuration", 0.05, 5, 0.5),
        "transitionText": str(raw.get("transitionText") or "")[:500],
        "transitionTextSize": _number(raw.get("transitionTextSize"), f"{label} transitionTextSize", 50, 160, 100),
    }
    clip.update(_frame_fields(raw, label))
    origin = _origin(raw.get("origin"), label)
    if origin:
        clip["origin"] = origin
    takes = _takes(raw.get("takes"), label)
    if takes:
        clip["takes"] = takes
    if raw.get("lyric"):
        clip["lyric"] = str(raw["lyric"]).strip()[:500]
    return clip


def _soundtrack(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise MontageError("soundtrack must be an object or null")
    trim_start = _number(raw.get("trimStart"), "soundtrack trimStart", 0, 36000, 0)
    trim_end = _number(raw.get("trimEnd"), "soundtrack trimEnd", 0, 36000, 0)
    if trim_end and trim_end <= trim_start:
        raise MontageError("soundtrack trimEnd must be after trimStart")
    return {
        "name": str(raw.get("name") or "soundtrack")[:300],
        "source": _source(raw.get("source"), "soundtrack"),
        "trimStart": trim_start,
        "trimEnd": trim_end,
        "volume": _number(raw.get("volume"), "soundtrack volume", 0, 2, 1),
        "loop": bool(raw.get("loop", False)),
    }


def _camel_layers(overlays: list[dict], cues: list[dict]) -> tuple[list[dict], list[dict]]:
    camel_overlays = [{
        "id": item["id"], "name": item["name"], "source": item["source"], "start": item["start"], "end": item["end"],
        "x": item["x"], "y": item["y"], "width": item["width"], "opacity": item["opacity"],
        "fadeIn": item["fade_in"], "fadeOut": item["fade_out"],
    } for item in overlays]
    camel_cues = [{
        "id": item["id"], "name": item["name"], "source": item["source"], "start": item["start"],
        "volume": item["volume"], "trimStart": item["trim_start"], "trimEnd": item["trim_end"],
    } for item in cues]
    return camel_overlays, camel_cues


def _snake_overlays(raw: Any) -> Any:
    if not isinstance(raw, list):
        return raw
    return [{**item, "fade_in": item.get("fadeIn"), "fade_out": item.get("fadeOut")} if isinstance(item, dict) else item for item in raw]


def _snake_cues(raw: Any) -> Any:
    if not isinstance(raw, list):
        return raw
    return [{**item, "trim_start": item.get("trimStart"), "trim_end": item.get("trimEnd")} if isinstance(item, dict) else item for item in raw]


def _derived_from(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or raw.get("derivedFrom") is None:
        return None
    value = raw.get("derivedFrom")
    if not isinstance(value, dict):
        raise MontageError("derivedFrom must be an object")
    file = str(value.get("file") or "")
    if not FILE_RE.fullmatch(file):
        raise MontageError("derivedFrom file must be a montage filename")
    revision = int(_number(value.get("revision"), "derivedFrom revision", 1, 1_000_000))
    return {"file": file, "revision": revision}


def normalize_montage(raw: Any) -> dict[str, Any]:
    """Validate a montage document and return its canonical form (no revision)."""
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise MontageError("Use a version 1 montage document")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise MontageError("A montage needs a name")
    width = int(_number(raw.get("width"), "width", 240, 3840, 1920))
    height = int(_number(raw.get("height"), "height", 240, 3840, 1080))
    if width % 2 or height % 2:
        raise MontageError("width and height must be even")
    fps = raw.get("fps", 30)
    if fps not in FPS or isinstance(fps, bool):
        raise MontageError("fps must be one of 24, 25, 30, 50 or 60")
    clips = raw.get("clips")
    if not isinstance(clips, list) or not clips or len(clips) > MAX_CLIPS:
        raise MontageError(f"A montage needs between 1 and {MAX_CLIPS} clips")
    try:
        overlays = clean_overlays(_snake_overlays(raw.get("overlays")))
        cues = clean_audio_cues(_snake_cues(raw.get("audioCues")))
        duck = clean_duck(raw.get("duck"))
    except LayerValidationError as exc:
        raise MontageError(str(exc)) from exc
    for item in [*overlays, *cues]:
        _source(item["source"], item["id"])
    camel_overlays, camel_cues = _camel_layers(overlays, cues)
    document = {
        "version": 1, "kind": "montage", "name": name[:160], "width": width, "height": height, "fps": fps,
        "clips": [_clip(item, index) for index, item in enumerate(clips)],
        "soundtrack": _soundtrack(raw.get("soundtrack")),
        "audioCues": camel_cues, "overlays": camel_overlays, "duck": duck,
        "notes": str(raw.get("notes") or "")[:4000],
    }
    derived = _derived_from(raw)
    if derived:
        document["derivedFrom"] = derived
    if len(json.dumps(document, ensure_ascii=False)) > MAX_BYTES:
        raise MontageError("Montage exceeds 2 MB")
    return document


_EXPORT_KNOBS = (
    ("focusX", "focus_x"),
    ("focusY", "focus_y"),
    ("blurAmount", "blur_amount"),
    ("backgroundDim", "background_dim"),
)


def _export_clip(clip: dict[str, Any]) -> dict[str, Any]:
    body = {
        "name": clip["name"], "source": clip["source"], "trim_start": clip["trimStart"], "trim_end": clip["trimEnd"],
        "volume": clip["volume"], "muted": clip["muted"], "fit": clip["fit"], "transition": clip["transition"],
        "transition_duration": clip["transitionDuration"], "transition_text": clip["transitionText"],
        "transition_text_size": clip["transitionTextSize"],
    }
    for source_key, export_key in _EXPORT_KNOBS:
        if source_key in clip:
            body[export_key] = clip[source_key]
    return body


def export_body(document: dict[str, Any], workspace: str) -> dict[str, Any]:
    """Translate a montage into the Video Editor export request."""
    soundtrack = document.get("soundtrack")
    return {
        "name": document["name"], "workspace": workspace,
        "width": document["width"], "height": document["height"], "fps": document["fps"],
        "clips": [_export_clip(clip) for clip in document["clips"]],
        "soundtrack": {
            "name": soundtrack["name"], "source": soundtrack["source"], "trim_start": soundtrack["trimStart"],
            "trim_end": soundtrack["trimEnd"], "volume": soundtrack["volume"], "loop": soundtrack["loop"],
        } if soundtrack else None,
        "overlays": _snake_overlays(document.get("overlays") or []),
        "audio_cues": _snake_cues(document.get("audioCues") or []),
        "duck": document.get("duck") or 0,
    }


def montage_link(value: Any) -> dict[str, Any] | None:
    """The saved montage an export was made from (``{"file": "<name>.montage.json", "revision": n}``), or None.

    The export's sidecar keeps it (``params.video_editor.montage``) so the video opens its montage again."""
    if not isinstance(value, dict):
        return None
    file = value.get("file")
    if not isinstance(file, str) or not FILE_RE.fullmatch(file) or ".." in file:
        return None
    revision = value.get("revision")
    link: dict[str, Any] = {"file": file}
    if isinstance(revision, int) and not isinstance(revision, bool) and revision > 0:
        link["revision"] = revision
    return link


def slug_file(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")[:120] or "montage"
    return stem + SUFFIX


class MontageStore:
    """Atomic workspace files with a monotonically increasing revision."""

    def __init__(self, workspace_dir: Callable[[str], str]) -> None:
        self.workspace_dir = workspace_dir
        self._lock = threading.Lock()

    def _folder(self, workspace: str) -> Path:
        if not isinstance(workspace, str) or not WORKSPACE_RE.fullmatch(workspace):
            raise MontageError("Use an explicit valid workspace", code="invalid_workspace")
        return Path(self.workspace_dir(workspace))

    @staticmethod
    def _checked_file(file: str) -> str:
        if not isinstance(file, str) or not FILE_RE.fullmatch(file) or ".." in file:
            raise MontageError("Use an exact <name>.montage.json file", code="invalid_file")
        return file

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise MontageError("Montage not found", status=404, code="not_found") from exc
        except (OSError, ValueError) as exc:
            raise MontageError("Montage file is unreadable", status=409, code="unreadable") from exc

    def get(self, workspace: str, file: str) -> dict[str, Any]:
        path = self._folder(workspace) / self._checked_file(file)
        return {"file": path.name, "workspace": workspace, "montage": self._read(path), "url": self._url(path.name, workspace)}

    @staticmethod
    def _url(name: str, workspace: str) -> str:
        return "/api/v1/file/" + quote(name) + "?workspace=" + quote(workspace, safe="")

    def list(self, workspace: str) -> list[dict[str, Any]]:
        folder = self._folder(workspace)
        items = []
        for path in sorted(folder.glob("*" + SUFFIX), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            items.append({
                "file": path.name, "name": data.get("name") or path.name, "revision": data.get("revision", 1),
                "updatedAt": data.get("updatedAt"), "clips": len(data.get("clips") or []),
                "overlays": len(data.get("overlays") or []), "audioCues": len(data.get("audioCues") or []),
                "url": self._url(path.name, workspace),
            })
        return items

    def save(self, workspace: str, montage: Any, *, file: str | None = None,
             expected_revision: int | None = None) -> dict[str, Any]:
        document = normalize_montage(montage)
        folder = self._folder(workspace)
        name = self._checked_file(file) if file else slug_file(document["name"])
        path = folder / name
        with self._lock:
            current = self._read(path) if path.exists() else None
            revision = int(current.get("revision", 1)) if current else 0
            if expected_revision is not None and expected_revision != revision:
                raise MontageError(f"Montage changed (revision {revision}); reload before saving",
                                   status=409, code="revision_conflict")
            # Existing files require compare-and-swap; `file` alone must not overwrite.
            if current is not None and expected_revision is None:
                raise MontageError("A montage with this name exists; pass file and expected_revision to update it",
                                   status=409, code="exists")
            document.update({"revision": revision + 1, "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S")})
            folder.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, path)
        return {"file": path.name, "workspace": workspace, "revision": document["revision"],
                "url": self._url(path.name, workspace)}


__all__ = ["MAX_TAKES", "MontageError", "MontageStore", "SUFFIX", "export_body", "montage_link", "normalize_montage", "slug_file"]

"""Which saved scene document an export rendered, and a real preview for it from the export's own frames.

``scenes.document.save`` / ``world3d.scene.publish`` save a scene file and the
caller then exports the same document (``scenes.video2d.export``,
``scenes.world3d.export``): the Series render does it for every shot, and
agents export what they published. The export only receives the document, so
its video could not name the scene file, and an agent's scene file kept a
neutral placeholder as its preview (agents send no picture).

Every save now records the digest of the document as the exporter normalizes
it in a small per-workspace index (``.scene-digests-v1.json``). When an export
finishes, the same digest finds the saved file: the video's sidecar names it
(``params.scene_file``) and, when the file has no preview or only the
placeholder, the export's middle frame becomes its preview. A preview someone
saved from an editor is never replaced.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

INDEX = ".scene-digests-v1.json"
MAX_DIGESTS = 4000
MAX_FILES_PER_DIGEST = 4
PREVIEW_BOX = (640, 360)
_LOCK = threading.Lock()
_PLACEHOLDER: bytes | None = None


def document_digest(document: Any) -> str:
    """Digest of an exporter-normalized document (what an export snapshot holds)."""
    encoded = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def saved_digest(document: Any) -> str | None:
    """The digest an export of this saved document will have: normalized like ``scene*_export`` normalizes it."""
    from services.scene2d_schema import fill_sfx_colors
    from services.scene_commands import DocumentInput
    try:
        normalized = deepcopy(DocumentInput(document=document).document)
        if "layers" in normalized and "slots" not in normalized:
            fill_sfx_colors(normalized)
        return document_digest(normalized)
    except Exception:  # noqa: BLE001 - a document the exporter refuses is never exported
        return None


def _read_index(folder: Path) -> dict[str, list[str]]:
    try:
        value = json.loads((folder / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = value.get("files") if isinstance(value, dict) else None
    return {key: [name for name in names if isinstance(name, str)] for key, names in (files or {}).items()
            if isinstance(key, str) and isinstance(names, list)}


def remember_saved(folder: str | os.PathLike[str], document: Any, file: str) -> None:
    """Record that ``file`` holds ``document`` (best effort: a save never fails on the index)."""
    digest = saved_digest(document)
    if not digest or not isinstance(file, str) or not file:
        return
    root = Path(folder)
    try:
        with _LOCK:
            files = _read_index(root)
            names = [name for name in files.pop(digest, []) if name != file][-(MAX_FILES_PER_DIGEST - 1):]
            files[digest] = [*names, file]  # newest last, and the digest moves to the end
            while len(files) > MAX_DIGESTS:
                files.pop(next(iter(files)))
            temporary = root / f"{INDEX}.{os.getpid()}.tmp"
            temporary.write_text(json.dumps({"version": 1, "files": files}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(root / INDEX)
    except OSError:
        return


def saved_scene_for(folder: str | os.PathLike[str], document: Any) -> str | None:
    """The newest saved scene file that holds exactly this exported document, if it still exists."""
    root = Path(folder)
    try:
        names = _read_index(root).get(document_digest(document)) or []
    except (TypeError, ValueError):
        return None
    return next((name for name in reversed(names) if (root / name).is_file()), None)


def preview_path(folder: str | os.PathLike[str], file: str) -> Path:
    return Path(folder) / (os.path.splitext(file)[0] + ".preview.png")


def _placeholder_bytes() -> bytes:
    global _PLACEHOLDER
    if _PLACEHOLDER is None:
        from services.scene_documents import _placeholder_preview
        _PLACEHOLDER = base64.b64decode(_placeholder_preview().split(",", 1)[1])
    return _PLACEHOLDER


def needs_preview(folder: str | os.PathLike[str], file: str) -> bool:
    """No preview yet, or only the neutral placeholder an agent's save gets."""
    path = preview_path(folder, file)
    try:
        return not path.is_file() or (path.stat().st_size == len(_placeholder_bytes()) and path.read_bytes() == _placeholder_bytes())
    except OSError:
        return False


def preview_from_frames(folder: str | os.PathLike[str], file: str, frames: list[Path]) -> bool:
    """Give ``file`` the export's middle frame as its preview when it needs one. Returns True when written."""
    if not frames or not needs_preview(folder, file):
        return False
    from PIL import Image
    target = preview_path(folder, file)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with Image.open(frames[len(frames) // 2]) as frame:
            picture = frame.convert("RGB")
        picture.thumbnail(PREVIEW_BOX)
        picture.save(temporary, format="PNG")
        temporary.replace(target)
        return True
    except (OSError, ValueError):
        temporary.unlink(missing_ok=True)
        return False


__all__ = ["INDEX", "document_digest", "needs_preview", "preview_from_frames", "preview_path", "remember_saved",
           "saved_digest", "saved_scene_for"]

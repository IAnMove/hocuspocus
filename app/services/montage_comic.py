"""Comic panels of one montage: a second view, not a new comic document.

Each clip becomes one frame. The raw PNG and its printed twin are cached in the
workspace under ``.comic-panels/``, keyed by the source file (name, size and
mtime), the instant and the print version. The chosen instant is cached with
the same source identity and the trimmed range, so a second call does not
resample. The gallery and the asset catalog only list top-level files, so
these derivatives never show up as loose media. A caller reopens them by
asking for the montage again.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from services.montage_documents import MontageError, MontageStore

PRINT_VERSION = "paper-1"
CACHE_DIR = ".comic-panels"
MAX_BATCH = 24
_LOCK = threading.Lock()


def sample_times(start: float, end: float) -> list[float]:
    """Five instants across the middle 60% of [start, end], earliest first."""
    span = end - start
    if span <= 0:
        return [round(start, 3)]
    low = start + 0.2 * span
    high = start + 0.8 * span
    step = (high - low) / 4
    times = [round(low + step * index, 3) for index in range(5)]
    unique: list[float] = []
    for item in times:
        if not unique or item != unique[-1]:
            unique.append(item)
    return unique or [round(start + span / 2, 3)]


def laplacian_variance(path: Path) -> float:
    """Sharpness of a saved frame. A missing picture scores 0."""
    import cv2
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return 0.0
    return float(cv2.Laplacian(image, cv2.CV_64F).var())


def comic_panels(store: MontageStore, workspace: str, file: str, *, clip_ids: list | None = None,
                 frames: dict | None = None, clips: list | None = None, extract: Callable | None = None,
                 score: Callable | None = None, printer: Callable | None = None,
                 duration_of: Callable | None = None) -> dict[str, Any]:
    """One raw frame and one print per clip. At most 24 clips. A second call is a cache hit.

    ``clips`` are the editor's unsaved clips (id, source, trims, comic): a duplicated or replaced clip has
    its panel before the montage is saved. A clip whose media cannot be read gets ``error``, not a failed batch."""
    saved = store.get(workspace, file)
    chosen = _drafted(clips) if clips is not None else _selected(saved["montage"]["clips"], clip_ids)
    offsets = _offsets(frames, {clip["id"] for clip in chosen})
    root = Path(store.workspace_dir(workspace))
    tools = _tools(extract, score, printer, duration_of)
    with _LOCK:
        panels = [_safe_panel(clip, root, workspace, offsets, tools) for clip in chosen]
    return {"file": saved["file"], "panels": panels}


def _safe_panel(clip: dict, root: Path, workspace: str, offsets: dict[str, float], tools: dict) -> dict[str, Any]:
    try:
        return _panel(clip, root, workspace, offsets, tools)
    except MontageError as error:
        return {"clip_id": clip["id"], "error": str(error)}


def _drafted(clips: Any) -> list[dict]:
    """Validate the editor's clips: the fields a panel needs, nothing else."""
    if not isinstance(clips, list) or not 1 <= len(clips) <= MAX_BATCH:
        raise MontageError("clips must list between 1 and 24 clips", code="invalid_command")
    drafted: list[dict] = []
    for raw in clips:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            raise MontageError("each clip needs an id", code="invalid_command")
        if not isinstance(raw.get("source"), str) or not raw["source"].strip():
            raise MontageError(f"clip {raw['id']} needs a source", code="invalid_command")
        clip = {"id": raw["id"][:160], "source": raw["source"][:2000],
                "trimStart": _seconds(raw.get("trimStart", 0), "trimStart"),
                "trimEnd": _seconds(raw.get("trimEnd", 0), "trimEnd")}
        frame = (raw.get("comic") or {}).get("frame") if isinstance(raw.get("comic"), dict) else None
        if frame is not None:
            clip["comic"] = {"frame": _seconds(frame, "comic frame")}
        drafted.append(clip)
    if len({clip["id"] for clip in drafted}) != len(drafted):
        raise MontageError("clips must have unique ids", code="invalid_command")
    return drafted


def _tools(extract, score, printer, duration_of) -> dict[str, Callable]:
    if extract is None:
        from services.video_editor import extract_frame
        extract = extract_frame
    if score is None:
        score = laplacian_variance
    if printer is None:
        from services.scene3d_comic_paper import print_picture
        printer = print_picture
    if duration_of is None:
        from services.montage_shots import media_duration
        duration_of = media_duration
    return {"extract": extract, "score": score, "printer": printer, "duration_of": duration_of}


def _selected(clips: list[dict], clip_ids: list | None) -> list[dict]:
    if clip_ids is None:
        return list(clips[:MAX_BATCH])
    if not isinstance(clip_ids, list) or not 1 <= len(clip_ids) <= MAX_BATCH:
        raise MontageError("clip_ids must list between 1 and 24 clips", code="invalid_command")
    if any(not isinstance(item, str) or not item for item in clip_ids) or len(set(clip_ids)) != len(clip_ids):
        raise MontageError("clip_ids must be unique clip ids", code="invalid_command")
    by_id = {clip["id"]: clip for clip in clips}
    missing = [item for item in clip_ids if item not in by_id]
    if missing:
        raise MontageError(f"Unknown clip {missing[0]}", code="invalid_command")
    return [by_id[item] for item in clip_ids]


def _offsets(frames: dict | None, known: set[str]) -> dict[str, float]:
    if frames is None:
        return {}
    if not isinstance(frames, dict) or len(frames) > MAX_BATCH:
        raise MontageError("frames must map at most 24 clip ids to seconds", code="invalid_command")
    offsets: dict[str, float] = {}
    for key, value in frames.items():
        if not isinstance(key, str) or key not in known:
            raise MontageError("frames keys must be clip ids of this montage", code="invalid_command")
        offsets[key] = _seconds(value, f"frames {key}")
    return offsets


def _seconds(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MontageError(f"{label} must be a number", code="invalid_command")
    number = float(value)
    if number != number or not 0 <= number <= 36000:
        raise MontageError(f"{label} must be between 0 and 36000", code="invalid_command")
    return number


def _panel(clip: dict, root: Path, workspace: str, offsets: dict[str, float], tools: dict) -> dict[str, Any]:
    source = _source_file(root, str(clip.get("source") or ""))
    start, end = _bounds(clip, float(tools["duration_of"](source)))
    override = offsets.get(clip["id"])
    if override is None:
        comic = clip.get("comic") if isinstance(clip.get("comic"), dict) else {}
        if comic.get("frame") is not None:
            override = float(comic["frame"])
    if override is None:
        at, raw = _remembered(source, start, end, root, tools)
    else:
        at = _absolute(start, end, override)
        raw = _cached(root, source, at, "raw")
        _materialize(raw, lambda dest, at=at: _extract(tools["extract"], source, dest, at))
    printed = _cached(root, source, at, "print")
    _materialize(printed, lambda dest, raw=raw, at=at: _print(tools["printer"], raw, dest, source, at))
    width, height = _size(raw)
    return {"clip_id": clip["id"], "at": at, "frame": _url(raw, root, workspace), "print": _url(printed, root, workspace),
            "width": width, "height": height}


def _source_file(root: Path, source: str) -> Path:
    name = Path(source.split("?", 1)[0]).name
    path = root / name
    if not name or not path.is_file():
        raise MontageError(f"Clip media {name or 'file'} is not in the workspace", status=404, code="not_found")
    return path


def _bounds(clip: dict, duration: float) -> tuple[float, float]:
    start = max(0.0, float(clip.get("trimStart") or 0))
    end = float(clip.get("trimEnd") or 0)
    if duration > 0:
        start = min(start, duration)
    if end <= start:
        end = duration if duration > start else start + 0.04
    if duration > 0:
        end = min(end, max(duration, start))
    if end <= start:
        end = start + 0.04
    return start, end


def _absolute(start: float, end: float, offset: float) -> float:
    span = max(0.0, end - start)
    at = start + max(0.0, min(span, offset))
    if span > 0.08:
        at = min(at, end - 0.04)
    return round(at, 3)


def _remembered(source: Path, start: float, end: float, root: Path, tools: dict) -> tuple[float, Path]:
    """Reuse the sharpest instant when this source and trim were scored before."""
    choice = _choice_file(root, source, start, end)
    remembered = _read_choice(choice)
    if remembered is not None:
        raw = _cached(root, source, remembered, "raw")
        if raw.is_file() and raw.stat().st_size > 0:
            return remembered, raw
    at, raw = _sharpest(source, start, end, root, tools)
    _write_choice(choice, at)
    return at, raw


def _choice_file(root: Path, source: Path, start: float, end: float) -> Path:
    folder = root / CACHE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stat = source.stat()
    token = f"{PRINT_VERSION}|{source.name}|{stat.st_size}|{stat.st_mtime_ns}|{start:.3f}|{end:.3f}|choice"
    name = hashlib.sha256(token.encode()).hexdigest()[:32] + ".txt"
    return folder / name


def _read_choice(path: Path) -> float | None:
    if not path.is_file():
        return None
    try:
        number = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if number != number or not 0 <= number <= 36000:
        return None
    return round(number, 3)


def _write_choice(path: Path, at: float) -> None:
    temporary = path.with_name(path.stem + ".writing.txt")
    temporary.write_text(f"{at:.3f}\n", encoding="utf-8")
    os.replace(temporary, path)


def _sharpest(source: Path, start: float, end: float, root: Path, tools: dict) -> tuple[float, Path]:
    best_at, best_score, best_raw = start, None, None
    for at in sample_times(start, end):
        raw = _cached(root, source, at, "raw")
        _materialize(raw, lambda dest, at=at: _extract(tools["extract"], source, dest, at))
        value = float(tools["score"](raw))
        if best_score is None or value > best_score:
            best_at, best_score, best_raw = at, value, raw
    if best_raw is None:
        raise MontageError(f"Could not read a frame of {source.name}", code="invalid_montage")
    return best_at, best_raw


def _cached(root: Path, source: Path, at: float, kind: str) -> Path:
    folder = root / CACHE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stat = source.stat()
    token = f"{PRINT_VERSION}|{source.name}|{stat.st_size}|{stat.st_mtime_ns}|{at:.3f}|{kind}"
    name = hashlib.sha256(token.encode()).hexdigest()[:32] + ".png"
    return folder / name


def _materialize(dest: Path, produce: Callable[[Path], None]) -> None:
    if dest.is_file() and dest.stat().st_size > 0:
        return
    temporary = dest.with_name(dest.stem + ".writing.png")
    produce(temporary)
    if not temporary.is_file() or temporary.stat().st_size <= 0:
        raise MontageError("Could not write a comic frame", code="invalid_montage")
    os.replace(temporary, dest)


def _extract(extract: Callable, source: Path, dest: Path, at: float) -> None:
    try:
        extract(str(source), str(dest), at)
    except Exception as exc:
        raise MontageError(f"Could not read a frame of {source.name}", code="invalid_montage") from exc


def _print(printer: Callable, raw: Path, dest: Path, source: Path, at: float) -> None:
    from PIL import Image
    with Image.open(raw) as opened:
        width, height = opened.size
    seed = int(hashlib.sha256(f"{source.name}|{at:.3f}".encode()).hexdigest()[:8], 16)
    printer(raw, dest, seed, (0, 0, width, height, width, height))


def _size(path: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as opened:
        return int(opened.size[0]), int(opened.size[1])


def _url(path: Path, root: Path, workspace: str) -> str:
    relative = path.relative_to(root).as_posix()
    return "/api/v1/file/" + quote(relative, safe="/") + "?workspace=" + quote(workspace, safe="")


__all__ = ["CACHE_DIR", "PRINT_VERSION", "comic_panels", "laplacian_variance", "sample_times"]

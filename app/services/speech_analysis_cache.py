"""Atomic on-disk cache for vocal isolation and Rhubarb analysis."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from concurrent.futures import Future
from pathlib import Path

SCHEMA = 1
DEFAULT_MAX_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 64

_inflight_guard = threading.Lock()
_inflight: dict[str, Future] = {}
_pin_guard = threading.Lock()
_pins: dict[str, int] = {}
_store_lock = threading.Lock()


def cache_dir() -> Path:
    override = os.environ.get("SPEECH_ANALYSIS_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "cache" / "speech-analysis"


def reset_runtime_state() -> None:
    """Drop in-flight waiters. Cached files are left in place."""
    with _inflight_guard:
        _inflight.clear()
    with _pin_guard:
        _pins.clear()


def audio_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_identity(path: str | Path | None) -> list:
    if not path:
        return []
    candidate = Path(path)
    try:
        stat = candidate.stat()
    except OSError:
        return [str(candidate), "missing"]
    try:
        resolved = str(candidate.resolve())
    except OSError:
        resolved = str(candidate)
    return [resolved, stat.st_size, stat.st_mtime_ns]


def material_key(material: dict) -> str:
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def segment_window(duration: float) -> dict:
    """Window of the payload itself. Never a stitch of other analyses."""
    return {"start": 0.0, "duration": duration, "rate": 16000, "channels": 1, "width": 2}


def isolation_material(data: bytes, duration: float, model: dict) -> dict:
    return {
        "schema": SCHEMA,
        "kind": "isolation",
        "audio": audio_digest(data),
        "bytes": len(data),
        "segment": segment_window(duration),
        **model,
    }


def analysis_material(
    data: bytes,
    duration: float,
    isolate: bool,
    rhubarb: str | None,
    params: dict,
    isolation: dict | None = None,
) -> dict:
    material = {
        "schema": SCHEMA,
        "kind": "analysis",
        "audio": audio_digest(data),
        "bytes": len(data),
        "segment": segment_window(duration),
        "isolate": isolate,
        "rhubarb": file_identity(rhubarb),
        "params": params,
    }
    if isolation:
        material["isolation"] = isolation
    return material


def remember(material: dict, compute, suffix: str, *, root: Path | None = None) -> bytes:
    key = material_key(material)
    folder = root or cache_dir()
    _pin(key)
    try:
        hit = _load(folder, key, suffix)
        if hit is not None:
            return hit
        return _coalesce(folder, key, suffix, compute)
    finally:
        _unpin(key)


def _pin(key: str) -> None:
    with _pin_guard:
        _pins[key] = _pins.get(key, 0) + 1


def _unpin(key: str) -> None:
    with _pin_guard:
        remaining = _pins.get(key, 0) - 1
        if remaining > 0:
            _pins[key] = remaining
        else:
            _pins.pop(key, None)


def _protected() -> set[str]:
    with _pin_guard:
        pinned = {key for key, count in _pins.items() if count > 0}
    with _inflight_guard:
        return pinned | set(_inflight)


def _entry_path(folder: Path, key: str, suffix: str) -> Path:
    return folder / key[:2] / f"{key}{suffix}"


def _load(folder: Path, key: str, suffix: str) -> bytes | None:
    path = _entry_path(folder, key, suffix)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data or None


def _store(folder: Path, key: str, suffix: str, data: bytes) -> None:
    path = _entry_path(folder, key, suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _coalesce(folder: Path, key: str, suffix: str, compute) -> bytes:
    owner = False
    with _inflight_guard:
        pending = _inflight.get(key)
        if pending is None:
            pending = Future()
            _inflight[key] = pending
            owner = True
    if not owner:
        return pending.result()
    try:
        hit = _load(folder, key, suffix)
        payload = hit if hit is not None else _compute_and_store(folder, key, suffix, compute)
        pending.set_result(payload)
        return payload
    except BaseException as error:
        pending.set_exception(error)
        raise
    finally:
        with _inflight_guard:
            if _inflight.get(key) is pending:
                del _inflight[key]


def _compute_and_store(folder: Path, key: str, suffix: str, compute) -> bytes:
    payload = bytes(compute())
    if not payload:
        raise RuntimeError("Speech analysis produced an empty cache payload.")
    try:
        with _store_lock:
            _store(folder, key, suffix, payload)
            _evict(folder, keep={key})
    except OSError:
        pass
    return payload


def _list_entries(folder: Path) -> list[tuple[float, int, str, Path]]:
    found: list[tuple[float, int, str, Path]] = []
    if not folder.is_dir():
        return found
    for path in folder.glob("*/*"):
        name = path.name
        if not path.is_file() or name.startswith(".") or len(name) < 64:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        found.append((stat.st_mtime, stat.st_size, name[:64], path))
    return found


def _evict(folder: Path, keep: set[str]) -> None:
    max_bytes = int(os.environ.get("SPEECH_ANALYSIS_CACHE_MAX_BYTES", DEFAULT_MAX_BYTES))
    max_entries = int(os.environ.get("SPEECH_ANALYSIS_CACHE_MAX_ENTRIES", DEFAULT_MAX_ENTRIES))
    entries = sorted(_list_entries(folder))
    protected = _protected() | keep
    total = sum(item[1] for item in entries)
    count = len(entries)
    for _mtime, size, key, path in entries:
        if count <= max_entries and total <= max_bytes:
            return
        if key in protected:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        count -= 1
        try:
            path.parent.rmdir()
        except OSError:
            pass

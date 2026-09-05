"""CAS persistence, merge and resume for generation-record v1.

This is I/O for the projection, not a second media store or scheduler.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Mapping

from .generation_record import (
    PHYSICAL_STORE_BUCKET,
    TERMINAL_STATUSES,
    GenerationRecordError,
    _IDENTITY_KEYS,
    _MERGE_SKIP_EMPTY_LISTS,
    _clean,
    _identity_token,
    _iso,
    _json_copy,
    _lineage_list,
    _now_iso,
    _portable_filename,
    validate_generation_record,
)


def merge_generation_record(
    base: Mapping[str, Any],
    patch: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge ``patch`` onto ``base`` without wiping lineage via empty lists.

    Absent keys keep the base value. Empty ``parents`` / ``derivatives`` /
    ``transformations`` in the patch do not delete existing refs. Identity
    fields cannot be replaced.
    """
    current = validate_generation_record(base)
    incoming = dict(patch) if isinstance(patch, Mapping) else {}
    if not incoming:
        return current
    for key in _IDENTITY_KEYS:
        if key in incoming and incoming[key] not in (None, "", current.get(key)):
            raise GenerationRecordError(f"Refusing to replace generation identity {key}")
    merged = dict(current)
    lineage_patch = incoming.get("lineage") if isinstance(incoming.get("lineage"), Mapping) else None
    skip_generic = _IDENTITY_KEYS | {
        "lineage", "prompt_full", "prompt_original", "prompt_effective", "prompt_display",
    }
    for key, value in incoming.items():
        if key in skip_generic:
            continue
        merged[key] = value
    if incoming.get("prompt_original") is not None:
        merged["prompt_original"] = incoming["prompt_original"]
    if incoming.get("prompt_effective") is not None:
        merged["prompt_effective"] = incoming["prompt_effective"]
    elif incoming.get("prompt_full") is not None:
        merged["prompt_effective"] = incoming["prompt_full"]
    if incoming.get("prompt_full") is not None:
        merged["prompt_full"] = incoming["prompt_full"]
    if lineage_patch is not None:
        lineage = {
            "parents": list(current["lineage"].get("parents") or []),
            "derivatives": list(current["lineage"].get("derivatives") or []),
            "transformations": list(current["lineage"].get("transformations") or []),
        }
        for key in _MERGE_SKIP_EMPTY_LISTS:
            if key not in lineage_patch:
                continue
            extra = lineage_patch.get(key)
            if extra is None or extra == []:
                continue
            lineage[key] = _lineage_list([*lineage[key], *list(extra)])
        merged["lineage"] = lineage
    return validate_generation_record(merged)


def resume_generation_record(
    record: Mapping[str, Any],
    *,
    worker_alive: bool = False,
    at: Any = None,
) -> dict[str, Any]:
    """Continue from the last durable status after a process restart.

    Re-reading ``running`` or ``queued`` does not prove a worker is alive.
    When ``worker_alive`` is false, mark reconciliation/interrupted and keep
    the durable status. Success is never inferred.
    """
    current = validate_generation_record(record)
    if current["status"] in TERMINAL_STATUSES:
        return current
    if current["status"] in {"queued", "running"} and not worker_alive:
        current["reconciliation"] = {
            "needed": True,
            "reason": "interrupted",
            "at": _iso(at) or _now_iso(),
        }
        return validate_generation_record(current)
    return current


def _read_existing_document(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _assert_stable_identity(existing: Mapping[str, Any], normalized: Mapping[str, Any]) -> None:
    existing_generation_id = _clean(existing.get("generation_id"))
    existing_asset_id = _clean(existing.get("asset_id"))
    existing_workspace_id = _clean(existing.get("workspace_id"))
    if existing_generation_id and existing_generation_id != normalized["generation_id"]:
        raise GenerationRecordError(
            f"Refusing to replace generation identity {existing_generation_id!r}",
        )
    if existing_asset_id and existing_asset_id != normalized["asset_id"]:
        raise GenerationRecordError(
            f"Refusing to replace asset identity {existing_asset_id!r}",
        )
    if existing_workspace_id != _clean(normalized.get("workspace_id")):
        raise GenerationRecordError("cross-workspace adoption is not allowed")


def _next_revision(
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
    expected_revision: int | None,
) -> int:
    if existing is None:
        return 1
    file_rev = existing.get("revision")
    has_file_rev = isinstance(file_rev, int) and not isinstance(file_rev, bool) and file_rev >= 0
    file_rev = file_rev if has_file_rev else 0
    claimed = expected_revision if expected_revision is not None else incoming.get("revision")
    has_claimed = isinstance(claimed, int) and not isinstance(claimed, bool)
    if not has_claimed:
        if has_file_rev:
            raise GenerationRecordError("stale generation record revision")
        return 1
    if claimed != file_rev:
        raise GenerationRecordError(
            f"stale generation record revision {claimed} (current {file_rev})",
        )
    return file_rev + 1


def persist_generation_record(
    path: str | os.PathLike[str],
    record: Mapping[str, Any],
    *,
    expected_revision: int | None = None,
) -> Path:
    """Atomically replace one generation-record JSON file with CAS revision."""
    normalized = validate_generation_record(record)
    target = Path(path)
    existing = _read_existing_document(target)
    if existing:
        _assert_stable_identity(existing, normalized)
    normalized["revision"] = _next_revision(existing, normalized, expected_revision)
    payload = _json_copy(normalized)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def load_generation_record(
    path: str | os.PathLike[str],
    *,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Load one record. Collection membership is exact, including unscoped None."""
    target = Path(path)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationRecordError("Generation record is unreadable") from exc
    record = validate_generation_record(value)
    if _clean(record.get("workspace_id")) != _clean(workspace_id):
        raise GenerationRecordError("cross-workspace adoption is not allowed")
    return record


class GenerationRecordStore:
    """JSON files keyed by optional Workspace collection or physical folder."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self._lock = threading.RLock()

    def _path(
        self,
        workspace_id: str | None,
        generation_id: str,
        *,
        output_folder: str | None = None,
    ) -> Path:
        identifier = _identity_token(generation_id, "generation_id", required=True)
        collection = _identity_token(workspace_id, "workspace_id", required=False)
        if collection:
            folder = (self.root / collection).resolve()
        else:
            physical = _portable_filename(output_folder)
            if not physical:
                raise GenerationRecordError("output_folder is required")
            folder = (self.root / PHYSICAL_STORE_BUCKET / physical).resolve()
        root = self.root.resolve()
        if folder != root and root not in folder.parents:
            raise GenerationRecordError("workspace path escapes the store")
        return folder / f"{identifier}.json"

    def persist(self, record: Mapping[str, Any]) -> Path:
        normalized = validate_generation_record(record)
        with self._lock:
            return persist_generation_record(
                self._path(
                    normalized.get("workspace_id"),
                    normalized["generation_id"],
                    output_folder=normalized.get("output_folder"),
                ),
                normalized,
            )

    def load(
        self,
        generation_id: str,
        *,
        workspace_id: str | None = None,
        output_folder: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            return load_generation_record(
                self._path(workspace_id, generation_id, output_folder=output_folder),
                workspace_id=workspace_id,
            )

    def list(
        self,
        *,
        workspace_id: str | None = None,
        output_folder: str | None = None,
    ) -> list[dict[str, Any]]:
        if workspace_id:
            folder = self.root / _identity_token(workspace_id, "workspace_id", required=True)
            load_workspace = workspace_id
        else:
            physical = _portable_filename(output_folder)
            if not physical:
                raise GenerationRecordError("output_folder is required")
            folder = self.root / PHYSICAL_STORE_BUCKET / physical
            load_workspace = None
        records: list[dict[str, Any]] = []
        if not folder.is_dir():
            return records
        with self._lock:
            for path in sorted(folder.glob("*.json")):
                try:
                    record = load_generation_record(path, workspace_id=load_workspace)
                except GenerationRecordError:
                    continue
                records.append(record)
        records.sort(key=lambda item: str((item.get("timestamps") or {}).get("created_at") or ""))
        return records

    def resume(
        self,
        generation_id: str,
        *,
        workspace_id: str | None = None,
        output_folder: str | None = None,
        worker_alive: bool = False,
    ) -> dict[str, Any]:
        loaded = self.load(
            generation_id, workspace_id=workspace_id, output_folder=output_folder,
        )
        return resume_generation_record(loaded, worker_alive=worker_alive)

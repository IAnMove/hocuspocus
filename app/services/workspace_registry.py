"""Durable registry for explicit collaborative Workspace collections."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_SCHEMA = "hocuspocus.workspace-record"
SCHEMA_VERSION = 1
STORE_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _references(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        token = str(item or "").strip()
        if token and len(token) <= 240 and token not in result:
            result.append(token)
    return result


def _revision(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    try:
        return max(1, int(value))
    except (TypeError, ValueError, OverflowError):
        return 1


def _record(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": WORKSPACE_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "id": str(value.get("id") or "").strip(),
        "revision": _revision(value.get("revision")),
        "name": str(value.get("name") or "").strip(),
        "description": str(value.get("description") or "").strip(),
        "project_ids": _references(value.get("project_ids")),
        "asset_ids": _references(value.get("asset_ids")),
        "production_ids": _references(value.get("production_ids")),
        "created_at": value.get("created_at") or None,
        "updated_at": value.get("updated_at") or None,
    }


class WorkspaceRegistry:
    """Small atomic JSON store; physical output folders remain independent."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"version": STORE_VERSION, "workspaces": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Workspace registry is unreadable") from exc
        if not isinstance(value, dict) or not isinstance(value.get("workspaces"), dict):
            raise ValueError("Workspace registry has an invalid shape")
        return value

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            items = [_record(item) for item in self._load()["workspaces"].values() if isinstance(item, dict)]
        return sorted(items, key=lambda item: (str(item.get("updated_at") or ""), item["id"]), reverse=True)

    def get(self, workspace_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._load()["workspaces"].get(workspace_id)
            return _record(value) if isinstance(value, dict) else None

    def create(self, value: dict[str, Any]) -> dict[str, Any]:
        name = str(value.get("name") or "").strip()
        if not name:
            raise ValueError("Workspace name is required")
        if len(name) > 160:
            raise ValueError("Workspace name is too long")
        timestamp = _now()
        workspace_id = f"workspace_{uuid.uuid4().hex}"
        item = _record({**value, "id": workspace_id, "revision": 1, "created_at": timestamp, "updated_at": timestamp})
        with self._lock:
            store = self._load()
            store["workspaces"][workspace_id] = item
            self._write(store)
        return item

    def update(self, workspace_id: str, value: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            store = self._load()
            current = store["workspaces"].get(workspace_id)
            if not isinstance(current, dict):
                raise KeyError(workspace_id)
            expected = value.get("expected_revision")
            if expected is not None:
                if isinstance(expected, bool):
                    raise ValueError("expected_revision must be a positive integer")
                try:
                    expected_value = int(expected)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("expected_revision must be a positive integer") from exc
                if expected_value < 1:
                    raise ValueError("expected_revision must be a positive integer")
                if expected_value != _revision(current.get("revision")):
                    raise RuntimeError("Workspace changed since it was opened")
            name = str(value.get("name", current.get("name")) or "").strip()
            if not name:
                raise ValueError("Workspace name is required")
            if len(name) > 160:
                raise ValueError("Workspace name is too long")
            merged = {
                **current,
                **{key: value[key] for key in (
                    "name", "description", "project_ids", "asset_ids", "production_ids"
                ) if key in value},
                "id": workspace_id,
                "revision": _revision(current.get("revision")) + 1,
                "created_at": current.get("created_at"),
                "updated_at": _now(),
            }
            item = _record(merged)
            store["workspaces"][workspace_id] = item
            self._write(store)
            return item

    def delete(self, workspace_id: str) -> bool:
        with self._lock:
            store = self._load()
            if workspace_id not in store["workspaces"]:
                return False
            del store["workspaces"][workspace_id]
            self._write(store)
            return True


__all__ = ["SCHEMA_VERSION", "STORE_VERSION", "WORKSPACE_SCHEMA", "WorkspaceRegistry"]

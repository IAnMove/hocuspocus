"""Durable canonical task registry for Maestro workflows.

Domain engines keep their own editable checkpoints, but every meaningful
operation publishes a small, non-sensitive task snapshot here. SQLite gives
the footer one atomic source of truth while the append-only event table keeps
the history needed to diagnose retries, resource waits and provider calls.
"""

from __future__ import annotations

from contextlib import contextmanager
import copy
import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterator


TASK_DB_NAME = ".maestro-tasks-v1.sqlite3"
ACTIVE_STATUSES = frozenset({"created", "queued", "waiting_resource", "running"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
_ALLOWED_TRANSITIONS = {
    "created": {"queued", "waiting_resource", "running", "failed", "cancelled"},
    "queued": {"waiting_resource", "running", "failed", "cancelled", "interrupted"},
    "waiting_resource": {"queued", "running", "failed", "cancelled", "interrupted"},
    "running": {"queued", "waiting_resource", "completed", "failed", "cancelled", "interrupted"},
    "failed": {"queued", "running"},
    "interrupted": {"queued", "running", "cancelled"},
    "cancelled": {"queued", "running"},
    "completed": set(),
}

_registry_lock = threading.RLock()
_registries: dict[str, "TaskRegistry"] = {}
_context = threading.local()


def _now() -> float:
    return time.time()


def _bounded(value: Any, depth: int = 0) -> Any:
    """Make task metadata JSON-safe and bounded without retaining prompts."""
    if depth > 6:
        return None
    if isinstance(value, str):
        return value[:8000]
    if isinstance(value, list):
        return [_bounded(item, depth + 1) for item in value[:200]]
    if isinstance(value, dict):
        return {
            str(key)[:160]: _bounded(item, depth + 1)
            for key, item in list(value.items())[:200]
            if str(key).lower() not in {"prompt", "negative_prompt", "lyrics", "api_key", "token"}
        }
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2000]


def _json(value: Any) -> str:
    return json.dumps(_bounded(value), ensure_ascii=False, separators=(",", ":"))


def new_task_id(prefix: str = "task") -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in prefix).strip("-")
    return f"{safe or 'task'}-{uuid.uuid4().hex[:16]}"


def current_task_context() -> dict[str, str]:
    return copy.deepcopy(getattr(_context, "value", {}) or {})


@contextmanager
def task_context_scope(**values: Any) -> Iterator[dict[str, str]]:
    previous = current_task_context()
    merged = {**previous, **{
        str(key): str(value) for key, value in values.items() if value not in (None, "")
    }}
    _context.value = merged
    try:
        yield merged
    finally:
        _context.value = previous


def run_with_task_context(context: dict[str, Any], callback, *args, **kwargs):
    """Explicitly restore task correlation inside a newly-created thread."""
    with task_context_scope(**(context or {})):
        return callback(*args, **kwargs)


class TaskRegistry:
    def __init__(self, workspace_dir: str, *, interrupt_stale: bool = True):
        self.workspace_dir = os.path.realpath(os.path.abspath(workspace_dir))
        os.makedirs(self.workspace_dir, exist_ok=True)
        self.path = os.path.join(self.workspace_dir, TASK_DB_NAME)
        self._write_lock = threading.RLock()
        self._condition = threading.Condition(threading.RLock())
        self._initialize()
        if interrupt_stale:
            self.interrupt_unfinished()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    root_id TEXT NOT NULL,
                    parent_id TEXT,
                    workspace TEXT NOT NULL,
                    status TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    snapshot TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status_updated
                    ON tasks(status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_root_updated
                    ON tasks(root_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    root_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    type TEXT NOT NULL,
                    changes TEXT NOT NULL,
                    context TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    UNIQUE(task_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_task
                    ON task_events(task_id, sequence);
            """)

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        try:
            value = json.loads(row["snapshot"])
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    def _append_event(
        self,
        connection: sqlite3.Connection,
        task: dict,
        event_type: str,
        changes: dict,
        context: dict | None = None,
    ) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM task_events WHERE task_id = ?",
            (task["id"],),
        ).fetchone()
        sequence = int(row["next"] if row else 1)
        cursor = connection.execute(
            """INSERT INTO task_events
               (task_id, root_id, sequence, timestamp, type, changes, context)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                task["id"], task["root_id"], sequence, _now(), str(event_type)[:160],
                _json(changes), _json(context if context is not None else current_task_context()),
            ),
        )
        return int(cursor.lastrowid)

    def create(self, **fields: Any) -> dict:
        now = _now()
        task_id = str(fields.get("id") or new_task_id(str(fields.get("kind") or "task")))[:200]
        root_id = str(fields.get("root_id") or task_id)[:200]
        parent_id = str(fields.get("parent_id") or "")[:200] or None
        status = str(fields.get("status") or "queued")
        if status not in ALL_STATUSES:
            raise ValueError(f"Unsupported task status: {status}")
        current = fields.get("current", 0)
        total = fields.get("total", 0)
        try:
            progress = float(fields.get("progress"))
        except (TypeError, ValueError):
            progress = (float(current or 0) / float(total)) if float(total or 0) > 0 else 0.0
        task = {
            "id": task_id, "root_id": root_id, "parent_id": parent_id,
            "kind": str(fields.get("kind") or "workflow")[:120],
            "title": str(fields.get("title") or "Maestro task")[:500],
            "workflow": str(fields.get("workflow") or fields.get("kind") or "workflow")[:160],
            "status": status, "phase": str(fields.get("phase") or status)[:160],
            "message": str(fields.get("message") or "Queued")[:2000],
            "detail": str(fields.get("detail") or "")[:8000],
            "current": current or 0, "total": total or 0,
            "progress": max(0.0, min(1.0, progress)),
            "detail_current": fields.get("detail_current", 0) or 0,
            "detail_total": fields.get("detail_total", 0) or 0,
            "created_at": float(fields.get("created_at") or now),
            "queued_at": fields.get("queued_at") or (now if status == "queued" else None),
            "started_at": fields.get("started_at") or (now if status == "running" else None),
            "updated_at": now,
            "completed_at": fields.get("completed_at") or (now if status in TERMINAL_STATUSES else None),
            "provider": str(fields.get("provider") or "")[:160],
            "model": str(fields.get("model") or "")[:300],
            "server_origin": str(fields.get("server_origin") or "")[:1000],
            "resource_requirements": _bounded(fields.get("resource_requirements") or []),
            "acquired_resources": _bounded(fields.get("acquired_resources") or []),
            "attempt": max(1, int(fields.get("attempt") or 1)),
            "max_attempts": max(1, int(fields.get("max_attempts") or 1)),
            "token_usage": _bounded(fields.get("token_usage") or {
                "prompt": 0, "completion": 0, "total": 0, "calls": 0,
            }),
            "workspace": str(fields.get("workspace") or "default")[:300],
            "project_id": str(fields.get("project_id") or "")[:300],
            "entity_type": str(fields.get("entity_type") or "")[:160],
            "entity_id": str(fields.get("entity_id") or "")[:300],
            "backend_job_id": str(fields.get("backend_job_id") or "")[:300],
            "pipeline_id": str(fields.get("pipeline_id") or "")[:300],
            "external_request_id": str(fields.get("external_request_id") or "")[:500],
            "cancelable": bool(fields.get("cancelable", False)),
            "resumable": bool(fields.get("resumable", False)),
            "recoverable": bool(fields.get("recoverable", False)),
            "error": _bounded(fields.get("error")),
            "result_refs": _bounded(fields.get("result_refs") or []),
            "metadata": _bounded(fields.get("metadata") or {}),
        }
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._decode(connection.execute(
                "SELECT snapshot FROM tasks WHERE id = ?", (task_id,),
            ).fetchone())
            if existing is not None:
                connection.rollback()
                return existing
            connection.execute(
                """INSERT INTO tasks
                   (id, root_id, parent_id, workspace, status, kind, workflow, created_at, updated_at, snapshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, root_id, parent_id, task["workspace"], status, task["kind"],
                    task["workflow"], task["created_at"], now, _json(task),
                ),
            )
            self._append_event(connection, task, "task.created", task)
            connection.commit()
        self._notify()
        return copy.deepcopy(task)

    def get(self, task_id: str) -> dict | None:
        with self._connect() as connection:
            return self._decode(connection.execute(
                "SELECT snapshot FROM tasks WHERE id = ?", (str(task_id),),
            ).fetchone())

    def update(
        self,
        task_id: str,
        *,
        event_type: str = "task.updated",
        force: bool = False,
        **changes: Any,
    ) -> dict:
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._decode(connection.execute(
                "SELECT snapshot FROM tasks WHERE id = ?", (str(task_id),),
            ).fetchone())
            if task is None:
                connection.rollback()
                raise KeyError(f"Task not found: {task_id}")
            patch = _bounded(changes)
            next_status = str(patch.get("status") or task["status"])
            if next_status not in ALL_STATUSES:
                connection.rollback()
                raise ValueError(f"Unsupported task status: {next_status}")
            if next_status != task["status"] and not force:
                if next_status not in _ALLOWED_TRANSITIONS.get(task["status"], set()):
                    connection.rollback()
                    raise ValueError(f"Invalid task transition {task['status']} -> {next_status}")
            now = _now()
            if next_status == "queued" and task.get("status") != "queued":
                patch.setdefault("queued_at", now)
            if next_status == "running" and not task.get("started_at"):
                patch.setdefault("started_at", now)
            if next_status in TERMINAL_STATUSES:
                patch.setdefault("completed_at", now)
            elif next_status in ACTIVE_STATUSES:
                patch.setdefault("completed_at", None)
            if "current" in patch or "total" in patch:
                current = patch.get("current", task.get("current", 0)) or 0
                total = patch.get("total", task.get("total", 0)) or 0
                patch.setdefault("progress", float(current) / float(total) if float(total) > 0 else 0.0)
            if "progress" in patch:
                try:
                    patch["progress"] = max(0.0, min(1.0, float(patch["progress"])))
                except (TypeError, ValueError):
                    patch["progress"] = task.get("progress", 0.0)
            patch["updated_at"] = now
            task.update(patch)
            connection.execute(
                """UPDATE tasks SET root_id=?, parent_id=?, workspace=?, status=?, kind=?, workflow=?,
                   updated_at=?, snapshot=? WHERE id=?""",
                (
                    task["root_id"], task.get("parent_id"), task["workspace"], task["status"],
                    task["kind"], task["workflow"], now, _json(task), task["id"],
                ),
            )
            self._append_event(connection, task, event_type, patch)
            connection.commit()
        self._notify()
        return copy.deepcopy(task)

    def list(
        self,
        *,
        statuses: set[str] | None = None,
        root_id: str = "",
        limit: int = 200,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if statuses:
            valid = sorted(set(statuses) & ALL_STATUSES)
            if not valid:
                return []
            clauses.append(f"status IN ({','.join('?' for _ in valid)})")
            params.extend(valid)
        if root_id:
            clauses.append("root_id = ?")
            params.append(str(root_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(1000, int(limit or 200))))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT snapshot FROM tasks {where} ORDER BY updated_at DESC LIMIT ?", params,
            ).fetchall()
        return [task for row in rows if (task := self._decode(row)) is not None]

    def events(self, task_id: str = "", *, after: int = 0, limit: int = 500) -> list[dict]:
        clauses = ["event_id > ?"]
        params: list[Any] = [max(0, int(after or 0))]
        if task_id:
            clauses.append("task_id = ?")
            params.append(str(task_id))
        params.append(max(1, min(2000, int(limit or 500))))
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT event_id, task_id, root_id, sequence, timestamp, type, changes, context
                    FROM task_events WHERE {' AND '.join(clauses)} ORDER BY event_id LIMIT ?""",
                params,
            ).fetchall()
        result = []
        for row in rows:
            result.append({
                "event_id": row["event_id"], "task_id": row["task_id"], "root_id": row["root_id"],
                "sequence": row["sequence"], "timestamp": row["timestamp"], "type": row["type"],
                "changes": json.loads(row["changes"] or "{}"),
                "context": json.loads(row["context"] or "{}"),
            })
        return result

    def latest_event_id(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COALESCE(MAX(event_id), 0) AS value FROM task_events").fetchone()
        return int(row["value"] if row else 0)

    def _notify(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def wait_for_events(self, after: int, timeout: float = 15.0) -> list[dict]:
        events = self.events(after=after)
        if events:
            return events
        with self._condition:
            self._condition.wait(timeout=max(0.05, min(30.0, timeout)))
        return self.events(after=after)

    def interrupt_unfinished(self) -> int:
        interrupted = 0
        for task in self.list(statuses=set(ACTIVE_STATUSES), limit=1000):
            try:
                self.update(
                    task["id"], status="interrupted", phase="interrupted",
                    message="Backend restarted before this task reached a terminal state.",
                    recoverable=bool(task.get("recoverable") or task.get("resumable")),
                    event_type="task.interrupted", force=True,
                )
                interrupted += 1
            except (KeyError, ValueError, OSError, sqlite3.Error):
                continue
        return interrupted

    def delete(self, task_id: str) -> bool:
        task = self.get(task_id)
        if not task:
            return False
        if task.get("status") in ACTIVE_STATUSES:
            raise ValueError("Active tasks must be cancelled before dismissal")
        with self._write_lock, self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE id = ?", (str(task_id),))
        self._notify()
        return True

    def prune(self, *, terminal_before: float, keep: int = 1000) -> int:
        terminal = self.list(statuses=set(TERMINAL_STATUSES), limit=5000)
        stale = [
            task for index, task in enumerate(terminal)
            if index >= max(0, int(keep)) and float(task.get("updated_at") or 0) < terminal_before
        ]
        removed = 0
        for task in stale:
            removed += int(self.delete(task["id"]))
        return removed


def get_task_registry(workspace_dir: str) -> TaskRegistry:
    path = os.path.realpath(os.path.abspath(workspace_dir))
    with _registry_lock:
        registry = _registries.get(path)
        if registry is None:
            registry = TaskRegistry(path)
            _registries[path] = registry
        return registry


def forget_task_registry(workspace_dir: str) -> None:
    """Test/restart helper; SQLite connections are per-operation."""
    path = os.path.realpath(os.path.abspath(workspace_dir))
    with _registry_lock:
        _registries.pop(path, None)

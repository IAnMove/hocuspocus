"""Durable canonical task registry for Maestro workflows.

Domain engines keep their own editable checkpoints, but every meaningful
operation publishes a small, non-sensitive task snapshot here. SQLite gives
the footer one atomic source of truth while the retained event log keeps the
bounded history needed to diagnose retries, resource waits and provider calls.
"""

from __future__ import annotations

from contextlib import contextmanager
import copy
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterator, TypedDict


TASK_DB_NAME = ".maestro-tasks-v1.sqlite3"
TASK_RETENTION_MAX_AGE_ENV = "LOREFRAME_TASK_RETENTION_MAX_AGE_SECONDS"
TASK_RETENTION_MAX_TERMINAL_ENV = "LOREFRAME_TASK_RETENTION_MAX_TERMINAL_TASKS"
TASK_RETENTION_MAX_EVENTS_ENV = "LOREFRAME_TASK_RETENTION_MAX_EVENTS"
DEFAULT_TASK_RETENTION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
DEFAULT_TASK_RETENTION_MAX_TERMINAL_TASKS = 1_000
DEFAULT_TASK_RETENTION_MAX_EVENTS = 10_000
TASK_SCHEMA_VERSION = 2
_PRUNED_THROUGH_META_KEY = "events_pruned_through"
_SCHEMA_VERSION_META_KEY = "schema_version"
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

# These fields are maintained by the registry itself and must not turn an
# otherwise identical adapter sync into a new semantic task update.  The
# persisted ``updated_at`` is only a change-ordering/index field; it is not
# part of the task state delivered by an adapter.
_VOLATILE_UPDATE_FIELDS = frozenset({"updated_at"})

_registry_lock = threading.RLock()
_registries: dict[str, "TaskRegistry"] = {}
_context = threading.local()
_cancellation_tokens_lock = threading.RLock()
_cancellation_tokens: dict[tuple[str, str], "CancellationToken"] = {}


class CancellationToken:
    """A per-task cancellation signal shared by workers and provider clients.

    The task registry remains the durable source of truth, while this in-memory
    event gives an active HTTP stream a prompt, job-scoped wake-up.  Tokens are
    deliberately keyed by workspace and task id so cancelling one job cannot
    interrupt a concurrent job using the same provider.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.RLock()
        self._reason = ""

    def cancel(self, reason: str = "") -> None:
        with self._lock:
            if reason and not self._reason:
                self._reason = str(reason)
            self._event.set()

    def reset(self) -> None:
        with self._lock:
            self._reason = ""
            self._event.clear()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason


def _cancellation_token_key(workspace_dir: str, task_id: str) -> tuple[str, str]:
    return (os.path.realpath(os.path.abspath(str(workspace_dir))), str(task_id))


def get_cancellation_token(workspace_dir: str, task_id: str) -> CancellationToken:
    """Return the stable cancellation token for one canonical task."""
    key = _cancellation_token_key(workspace_dir, task_id)
    with _cancellation_tokens_lock:
        return _cancellation_tokens.setdefault(key, CancellationToken())


def current_task_cancellation_token() -> CancellationToken | None:
    """Resolve the token associated with the task in the current worker."""
    context = current_task_context()
    task_id = str(context.get("task_id") or "")
    workspace_dir = str(context.get("workspace_dir") or "")
    if not task_id or not workspace_dir:
        return None
    return get_cancellation_token(workspace_dir, task_id)


def _update_cancellation_token(workspace_dir: str, task_id: str, **changes: Any) -> None:
    """Mirror durable task transitions into the active worker's Event."""
    key = _cancellation_token_key(workspace_dir, task_id)
    status = str(changes.get("status") or "").lower()
    phase = str(changes.get("phase") or "").lower()
    should_cancel = status in {"cancelled", "interrupted"} or phase == "cancelling"
    with _cancellation_tokens_lock:
        token = _cancellation_tokens.get(key)
        if should_cancel and token is None:
            token = _cancellation_tokens.setdefault(key, CancellationToken())
        elif status in {"completed", "failed"}:
            # Successful/failed workers no longer need an in-memory signal.
            # The durable task snapshot remains the source of history.
            _cancellation_tokens.pop(key, None)
            return
    if should_cancel and token is not None:
        token.cancel(f"Task {task_id} cancellation requested")
    elif status == "queued" and phase != "cancelling" and token is not None:
        # Resume explicitly reopens the canonical task and gets a fresh signal.
        token.reset()


class TokenUsage(TypedDict):
    prompt: int
    completion: int
    total: int
    calls: int


def _now() -> float:
    return time.time()


def _env_non_negative_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return max(0.0, value) if value == value else float(default)


def _env_non_negative_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError, OverflowError):
        return int(default)
    return max(0, value)


def _normalize_token_usage(
    value: Any,
    *,
    fallback: Any = None,
) -> TokenUsage:
    """Return the canonical, non-negative integer token counters."""
    source = value if isinstance(value, dict) else {}
    previous = fallback if isinstance(fallback, dict) else {}

    def counter(name: str) -> int:
        raw = source[name] if name in source else previous.get(name, 0)
        try:
            return max(0, int(raw or 0))
        except (TypeError, ValueError, OverflowError):
            return 0

    return {
        "prompt": counter("prompt"),
        "completion": counter("completion"),
        "total": counter("total"),
        "calls": counter("calls"),
    }


_SENSITIVE_KEY_PARTS = (
    "api_key", "apikey", "access_token", "refresh_token", "authorization",
    "password", "passwd", "client_secret", "private_key", "cookie", "session",
)


def _is_sensitive_key(value: Any) -> bool:
    token = str(value or "").strip().casefold().replace("-", "_")
    return token == "token" or token.endswith("_token") or any(
        part in token for part in _SENSITIVE_KEY_PARTS
    )


def _redact_string(value: str) -> str:
    result = re.sub(
        r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", value,
    )
    return re.sub(
        r"(?i)([?&](?:token|api[_-]?key|access[_-]?token)=)[^&#\s]+",
        r"\1[REDACTED]", result,
    )


def redact_sensitive_data(value: Any, depth: int = 0) -> Any:
    """Recursively remove credentials before diagnostics or public metadata."""
    if depth > 8:
        return None
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, list):
        return [redact_sensitive_data(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(key)
            else redact_sensitive_data(item, depth + 1)
            for key, item in value.items()
        }
    return value


def _bounded(value: Any, depth: int = 0) -> Any:
    """Make task metadata JSON-safe and bounded without retaining prompts."""
    if depth > 6:
        return None
    if isinstance(value, str):
        return _redact_string(value)[:8000]
    if isinstance(value, list):
        return [_bounded(item, depth + 1) for item in value[:200]]
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:200]:
            safe_key = str(key)[:160]
            lowered = str(key).lower()
            if lowered == "token_usage":
                result[safe_key] = _normalize_token_usage(item)
            elif lowered not in {"prompt", "negative_prompt", "lyrics"} and not _is_sensitive_key(lowered):
                result[safe_key] = _bounded(item, depth + 1)
        return result
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
                    UNIQUE(task_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_task
                    ON task_events(task_id, sequence);
                CREATE TABLE IF NOT EXISTS task_registry_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            self._migrate_task_events_to_durable_log(connection)
            self._record_schema_version(connection)

    @staticmethod
    def _record_schema_version(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT value FROM task_registry_meta WHERE key = ?",
            (_SCHEMA_VERSION_META_KEY,),
        ).fetchone()
        try:
            existing = max(0, int(row["value"])) if row else 0
        except (TypeError, ValueError, OverflowError):
            existing = 0
        if existing > TASK_SCHEMA_VERSION:
            raise RuntimeError(
                f"Task database schema {existing} is newer than supported version "
                f"{TASK_SCHEMA_VERSION}"
            )
        if existing == TASK_SCHEMA_VERSION:
            return
        connection.execute(
            """INSERT INTO task_registry_meta(key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (_SCHEMA_VERSION_META_KEY, str(TASK_SCHEMA_VERSION)),
        )

    @staticmethod
    def _migrate_task_events_to_durable_log(connection: sqlite3.Connection) -> None:
        """Remove the legacy cascade so deletion tombstones survive reloads."""
        if not connection.execute("PRAGMA foreign_key_list(task_events)").fetchall():
            return
        connection.execute("BEGIN IMMEDIATE")
        try:
            # Another process may have completed the migration while this
            # connection waited for the SQLite write lock.
            foreign_keys = connection.execute(
                "PRAGMA foreign_key_list(task_events)"
            ).fetchall()
            if not foreign_keys:
                connection.commit()
                return

            # SQLite cannot drop a foreign key in place. Rebuild the event log
            # transactionally, preserving event IDs so Last-Event-ID cursors
            # remain valid across an application upgrade.
            connection.execute("DROP INDEX IF EXISTS idx_task_events_task")
            connection.execute("""
                CREATE TABLE task_events_durable_migration (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    root_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    type TEXT NOT NULL,
                    changes TEXT NOT NULL,
                    context TEXT NOT NULL,
                    UNIQUE(task_id, sequence)
                )
            """)
            connection.execute("""
                INSERT INTO task_events_durable_migration
                    (event_id, task_id, root_id, sequence, timestamp, type, changes, context)
                SELECT event_id, task_id, root_id, sequence, timestamp, type, changes, context
                FROM task_events
            """)
            connection.execute("DROP TABLE task_events")
            connection.execute(
                "ALTER TABLE task_events_durable_migration RENAME TO task_events"
            )
            connection.execute("""
                CREATE INDEX idx_task_events_task
                    ON task_events(task_id, sequence)
            """)
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        try:
            value = json.loads(row["snapshot"])
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(value, dict):
            return None
        value["token_usage"] = _normalize_token_usage(value.get("token_usage"))
        return value

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
            "token_usage": _normalize_token_usage(fields.get("token_usage")),
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
        _update_cancellation_token(self.workspace_dir, task_id, status=status, phase=task["phase"])
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
            raw_token_usage = changes.get("token_usage") if "token_usage" in changes else None
            patch = _bounded(changes)
            if "token_usage" in changes:
                patch["token_usage"] = _normalize_token_usage(
                    raw_token_usage,
                    fallback=task.get("token_usage"),
                )
            next_status = str(patch.get("status") or task["status"])
            if next_status not in ALL_STATUSES:
                connection.rollback()
                raise ValueError(f"Unsupported task status: {next_status}")
            if "status" in patch:
                patch["status"] = next_status
            if next_status != task["status"] and not force:
                if next_status not in _ALLOWED_TRANSITIONS.get(task["status"], set()):
                    connection.rollback()
                    raise ValueError(f"Invalid task transition {task['status']} -> {next_status}")
            now = _now()
            if next_status == "queued" and task.get("status") != "queued":
                patch.setdefault("queued_at", now)
            if next_status == "running" and not task.get("started_at"):
                patch.setdefault("started_at", now)
            if next_status in TERMINAL_STATUSES and (
                task.get("status") not in TERMINAL_STATUSES or not task.get("completed_at")
            ):
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

            # Compare the normalized patch with the current snapshot before
            # touching timestamps or the append-only log.  Adapter callers
            # can include registry-owned fields such as updated_at, and a
            # forced/event-typed sync is still a no-op when no semantic field
            # changed.  This keeps force useful for transition validation
            # without making it an unconditional event switch.
            semantic_patch = {
                key: value for key, value in patch.items()
                if key not in _VOLATILE_UPDATE_FIELDS
            }
            changed_patch = {
                key: value for key, value in semantic_patch.items()
                if task.get(key) != value
            }
            if not changed_patch:
                connection.rollback()
                # A process-local token may have been recreated after the
                # durable snapshot reached ``cancelling``. Mirror that state
                # even though it must not append another durable event.
                _update_cancellation_token(
                    self.workspace_dir,
                    task_id,
                    status=task.get("status"),
                    phase=task.get("phase"),
                )
                return copy.deepcopy(task)

            task.update(changed_patch)
            task["updated_at"] = now
            connection.execute(
                """UPDATE tasks SET root_id=?, parent_id=?, workspace=?, status=?, kind=?, workflow=?,
                   updated_at=?, snapshot=? WHERE id=?""",
                (
                    task["root_id"], task.get("parent_id"), task["workspace"], task["status"],
                    task["kind"], task["workflow"], now, _json(task), task["id"],
                ),
            )
            self._append_event(connection, task, event_type, changed_patch)
            connection.commit()
        _update_cancellation_token(self.workspace_dir, task_id, **patch)
        self._notify()
        return copy.deepcopy(task)

    def list(
        self,
        *,
        statuses: set[str] | None = None,
        root_id: str = "",
        limit: int = 200,
    ) -> list[dict]:
        requested_statuses = set(ALL_STATUSES)
        if statuses:
            requested_statuses = set(statuses) & ALL_STATUSES
            if not requested_statuses:
                return []

        active_statuses = sorted(requested_statuses & ACTIVE_STATUSES)
        terminal_statuses = sorted(requested_statuses & TERMINAL_STATUSES)
        terminal_limit = max(1, min(1000, int(limit or 200)))

        def query_for(status_group: list[str], *, row_limit: int | None = None):
            if not status_group:
                return []
            clauses = [f"status IN ({','.join('?' for _ in status_group)})"]
            params: list[Any] = list(status_group)
            if root_id:
                clauses.append("root_id = ?")
                params.append(str(root_id))
            limit_sql = ""
            if row_limit is not None:
                limit_sql = " LIMIT ?"
                params.append(row_limit)
            return connection.execute(
                f"""SELECT id, updated_at, snapshot FROM tasks
                    WHERE {' AND '.join(clauses)}
                    ORDER BY updated_at DESC, id ASC{limit_sql}""",
                params,
            ).fetchall()

        with self._connect() as connection:
            # Active work must never disappear behind recent history.  The
            # caller's limit is therefore a history budget: all requested
            # active rows are returned, plus at most that many terminal rows.
            # Keep both reads in one SQLite snapshot so a concurrent status
            # transition cannot fall into the gap between the two queries.
            connection.execute("BEGIN")
            rows = query_for(active_statuses)
            rows.extend(query_for(terminal_statuses, row_limit=terminal_limit))

        deduplicated: dict[str, tuple[float, dict]] = {}
        for row in rows:
            task = self._decode(row)
            if task is None:
                continue
            deduplicated[str(row["id"])] = (float(row["updated_at"]), task)
        ordered = sorted(
            deduplicated.values(),
            key=lambda item: (-item[0], str(item[1].get("id") or "")),
        )
        return [task for _updated_at, task in ordered]

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
            sequence = connection.execute(
                "SELECT COALESCE(seq, 0) AS value FROM sqlite_sequence WHERE name = 'task_events'",
            ).fetchone()
        return max(
            int(row["value"] if row else 0),
            int(sequence["value"] if sequence else 0),
        )

    def schema_version(self) -> int:
        with self._connect() as connection:
            return self._meta_int(connection, _SCHEMA_VERSION_META_KEY)

    @staticmethod
    def _meta_int(connection: sqlite3.Connection, key: str, default: int = 0) -> int:
        row = connection.execute(
            "SELECT value FROM task_registry_meta WHERE key = ?", (key,),
        ).fetchone()
        try:
            return max(0, int(row["value"])) if row else int(default)
        except (TypeError, ValueError, OverflowError):
            return int(default)

    def cursor_requires_resync(self, after: int) -> bool:
        """Return whether ``after`` predates an event retention boundary.

        The boundary is durable because deleting all rows from an AUTOINCREMENT
        event table otherwise loses the information needed to distinguish a
        current empty log from a cursor that skipped pruned history.
        """
        try:
            cursor = max(0, int(after or 0))
        except (TypeError, ValueError, OverflowError):
            cursor = 0
        with self._connect() as connection:
            pruned_through = self._meta_int(connection, _PRUNED_THROUGH_META_KEY)
        return cursor < pruned_through

    def resync_required_event(self, after: int) -> dict:
        """Build a transient SSE marker for a cursor that missed retention."""
        try:
            cursor = max(0, int(after or 0))
        except (TypeError, ValueError, OverflowError):
            cursor = 0
        latest = self.latest_event_id()
        return {
            "event_id": latest,
            "task_id": "",
            "root_id": "",
            "sequence": 0,
            "timestamp": _now(),
            "type": "resync_required",
            "changes": {
                "after": cursor,
                "latest_event_id": latest,
                "resync_required": True,
            },
            "context": {},
        }

    def snapshot(
        self,
        *,
        statuses: set[str] | None = None,
        root_id: str = "",
        limit: int = 200,
    ) -> tuple[list[dict], int]:
        """Read tasks and their event high-water mark without a writer gap.

        Every production mutation uses this registry's write lock. Holding it
        across both reads guarantees that an event committed after the task
        snapshot has an id greater than the returned cursor and will therefore
        be replayed by SSE.
        """
        with self._write_lock:
            tasks = self.list(statuses=statuses, root_id=root_id, limit=limit)
            return tasks, self.latest_event_id()

    def _notify(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def wait_for_events(self, after: int, timeout: float = 15.0) -> list[dict]:
        with self._condition:
            # Query while holding the same condition used by _notify. This
            # closes the commit-between-query-and-wait window that could make
            # a live SSE client wait for the full keepalive timeout.
            events = self.events(after=after)
            if events:
                return events
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
        task_id = str(task_id)
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = self._decode(connection.execute(
                "SELECT snapshot FROM tasks WHERE id = ?", (task_id,),
            ).fetchone())
            if not task:
                connection.rollback()
                return False
            if task.get("status") in ACTIVE_STATUSES:
                connection.rollback()
                raise ValueError("Active tasks must be cancelled before dismissal")

            deleted_at = _now()
            self._append_event(
                connection,
                task,
                "task.deleted",
                {
                    "deleted": True,
                    "tombstone": True,
                    "task_id": task["id"],
                    "root_id": task["root_id"],
                    "status": task["status"],
                    "deleted_at": deleted_at,
                },
            )
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            connection.commit()
        self._notify()
        return True

    def prune(
        self,
        *,
        terminal_before: float | None = None,
        keep: int | None = None,
        max_age_seconds: float | None = None,
        max_events: int | None = None,
        dry_run: bool = False,
    ) -> int | dict:
        """Apply bounded retention without dropping recovery-critical state.

        Active tasks and the newest terminal task are always retained. Older
        terminal snapshots can be removed by age or by
        the terminal count budget; their ``task.deleted`` tombstones remain in
        the event log until the independent event budget removes them. Once
        event rows are removed, the durable cursor boundary makes old SSE
        clients request a fresh snapshot instead of silently missing history.

        ``LOREFRAME_TASK_RETENTION_MAX_AGE_SECONDS``,
        ``LOREFRAME_TASK_RETENTION_MAX_TERMINAL_TASKS`` and
        ``LOREFRAME_TASK_RETENTION_MAX_EVENTS`` provide process-wide defaults.
        ``dry_run`` returns the planned counts and changes nothing.
        """
        now = _now()
        if max_age_seconds is None:
            max_age_seconds = _env_non_negative_float(
                TASK_RETENTION_MAX_AGE_ENV,
                DEFAULT_TASK_RETENTION_MAX_AGE_SECONDS,
            )
        else:
            max_age_seconds = max(0.0, float(max_age_seconds))
        cutoff = float(terminal_before) if terminal_before is not None else now - max_age_seconds
        keep_count = (
            _env_non_negative_int(
                TASK_RETENTION_MAX_TERMINAL_ENV,
                DEFAULT_TASK_RETENTION_MAX_TERMINAL_TASKS,
            )
            if keep is None else max(0, int(keep))
        )
        event_limit = (
            _env_non_negative_int(TASK_RETENTION_MAX_EVENTS_ENV, DEFAULT_TASK_RETENTION_MAX_EVENTS)
            if max_events is None else max(0, int(max_events))
        )

        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT snapshot FROM tasks
                   WHERE status IN (?, ?, ?, ?)
                   ORDER BY updated_at DESC, id ASC""",
                tuple(sorted(TERMINAL_STATUSES)),
            ).fetchall()
            terminal = [task for row in rows if (task := self._decode(row)) is not None]

            protected_ids = {terminal[0]["id"]} if terminal else set()
            active_count = int(connection.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE status IN (?, ?, ?, ?)",
                tuple(sorted(ACTIVE_STATUSES)),
            ).fetchone()["count"])
            stale = [
                task for index, task in enumerate(terminal)
                if task["id"] not in protected_ids
                and (
                    float(task.get("updated_at") or 0) < cutoff
                    or index >= keep_count
                )
            ]

            event_rows = connection.execute(
                "SELECT event_id, timestamp FROM task_events ORDER BY event_id DESC",
            ).fetchall()
            event_delete_ids = [
                int(row["event_id"])
                for index, row in enumerate(event_rows)
                if index >= event_limit or float(row["timestamp"] or 0) < cutoff
            ]
            plan = {
                "tasks": len(stale),
                "events": len(event_delete_ids),
                "protected_active": active_count,
                "protected_latest_terminal": len(protected_ids),
                "terminal_before": cutoff,
                "max_terminal_tasks": keep_count,
                "max_events": event_limit,
            }
            if dry_run:
                connection.rollback()
                return plan

            for task in stale:
                deleted_at = _now()
                self._append_event(
                    connection,
                    task,
                    "task.deleted",
                    {
                        "deleted": True,
                        "tombstone": True,
                        "task_id": task["id"],
                        "root_id": task["root_id"],
                        "status": task["status"],
                        "deleted_at": deleted_at,
                    },
                )
                connection.execute("DELETE FROM tasks WHERE id = ?", (task["id"],))

            # Delete in chunks so a large retention pass stays below SQLite's
            # bound-parameter limit while keeping the operation transactional.
            for offset in range(0, len(event_delete_ids), 500):
                chunk = event_delete_ids[offset:offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                connection.execute(
                    f"DELETE FROM task_events WHERE event_id IN ({placeholders})",
                    chunk,
                )
            if event_delete_ids:
                previous = self._meta_int(connection, _PRUNED_THROUGH_META_KEY)
                connection.execute(
                    """INSERT INTO task_registry_meta(key, value) VALUES (?, ?)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                    (_PRUNED_THROUGH_META_KEY, str(max(previous, max(event_delete_ids)))),
                )
            connection.commit()

        if stale or event_delete_ids:
            self._notify()
        return len(stale)


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
    with _cancellation_tokens_lock:
        for key in [candidate for candidate in _cancellation_tokens if candidate[0] == path]:
            _cancellation_tokens.pop(key, None)

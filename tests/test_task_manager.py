import sqlite3
import json
import time

from services.task_manager import (
    TASK_SCHEMA_VERSION,
    TaskRegistry,
    redact_sensitive_data,
    task_context_scope,
)


def test_identical_syncs_are_semantic_noops_and_terminal_transition_is_once(
    tmp_path, monkeypatch,
):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    task = registry.create(
        id="task-idempotent", kind="video", title="Render", status="queued",
        current=0, total=1,
    )
    # Keep the acceptance loop focused on idempotency rather than paying the
    # cost of opening a fresh SQLite handle for every one of 10,000 no-ops.
    connection = sqlite3.connect(registry.path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    # This test asserts event/write cardinality, not SQLite durability. Avoid
    # paying filesystem fsync latency 10,000 times in the acceptance loop.
    connection.execute("PRAGMA synchronous=OFF")
    monkeypatch.setattr(registry, "_connect", lambda: connection)
    notifications = []
    monkeypatch.setattr(registry, "_notify", lambda: notifications.append(True))
    before_sync = registry.latest_event_id()

    running_patch = {
        "status": "running",
        "phase": "rendering",
        "current": 1,
        "total": 1,
        "updated_at": 123.0,
    }
    for _ in range(10_000):
        registry.update(
            task["id"],
            event_type="adapter.synced",
            force=True,
            **running_patch,
        )

    running_events = registry.events(task["id"])
    assert [event["sequence"] for event in running_events] == [1, 2]
    assert running_events[-1]["type"] == "adapter.synced"
    assert registry.latest_event_id() == before_sync + 1
    assert len(notifications) == 1

    registry.update(
        task["id"],
        status="completed",
        phase="completed",
        current=1,
        total=1,
        event_type="task.finished",
        force=True,
    )
    # A repeated terminal sync must not refresh completed_at or append a
    # second transition event.
    registry.update(
        task["id"],
        status="completed",
        phase="completed",
        current=1,
        total=1,
        event_type="adapter.synced",
        force=True,
    )

    events = registry.events(task["id"])
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert events[-1]["type"] == "task.finished"
    completed = registry.get(task["id"])
    assert completed["status"] == "completed"
    assert completed["completed_at"] == events[-1]["changes"]["completed_at"]
    assert len(notifications) == 2
    connection.close()


def test_updated_at_only_patch_returns_existing_snapshot_without_event_or_notify(
    tmp_path, monkeypatch,
):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    task = registry.create(id="task-volatile", kind="llm", title="Plan", status="running")
    before = registry.get(task["id"])
    before_events = registry.events(task["id"])
    notifications = []
    monkeypatch.setattr(registry, "_notify", lambda: notifications.append(True))

    returned = registry.update(
        task["id"], updated_at=999_999.0, event_type="adapter.synced", force=True,
    )

    assert returned == before
    assert registry.get(task["id"]) == before
    assert registry.events(task["id"]) == before_events
    assert notifications == []


def test_task_registry_persists_ordered_events_and_transitions(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    task = registry.create(
        id="task-one", kind="image", title="Generate image", workflow="story",
        status="queued", workspace="default", current=0, total=2,
    )
    registry.update(task["id"], status="running", phase="requesting", current=1)
    completed = registry.update(
        task["id"], status="completed", phase="completed", current=2,
        result_refs=[{"kind": "image", "name": "frame.png"}],
    )

    assert completed["progress"] == 1
    assert completed["completed_at"] >= completed["started_at"]
    assert TaskRegistry(str(tmp_path), interrupt_stale=False).get(task["id"])["status"] == "completed"
    events = registry.events(task["id"])
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert [event["type"] for event in events] == ["task.created", "task.updated", "task.updated"]


def test_restart_marks_unfinished_task_interrupted_and_recoverable(tmp_path):
    first = TaskRegistry(str(tmp_path), interrupt_stale=False)
    first.create(
        id="task-running", kind="video", title="Render", status="running",
        recoverable=True, workspace="default",
    )

    second = TaskRegistry(str(tmp_path), interrupt_stale=True)

    task = second.get("task-running")
    assert task["status"] == "interrupted"
    assert task["recoverable"] is True
    assert second.events("task-running")[-1]["type"] == "task.interrupted"


def test_task_context_is_explicit_and_redacts_sensitive_metadata(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    with task_context_scope(request_id="request-1", task_id="task-context"):
        task = registry.create(
            id="task-context", kind="llm", title="Plan", status="queued",
            metadata={
                "prompt": "secret",
                "safe": "visible",
                "token_usage": {"prompt": "7", "completion": 3, "total": 10, "calls": 1},
            },
        )

    assert task["metadata"] == {
        "safe": "visible",
        "token_usage": {"prompt": 7, "completion": 3, "total": 10, "calls": 1},
    }
    assert registry.events("task-context")[0]["context"]["request_id"] == "request-1"


def test_sensitive_redaction_covers_nested_provider_keys_headers_and_urls():
    value = redact_sensitive_data({
        "minimax_api_key": "secret-key",
        "nested": {"Authorization": "Bearer abc.def", "safe": "visible"},
        "url": "https://example.test/file?token=secret&ok=1",
    })
    assert value["minimax_api_key"] == "[REDACTED]"
    assert value["nested"]["Authorization"] == "[REDACTED]"
    assert value["nested"]["safe"] == "visible"
    assert "secret" not in value["url"]


def test_token_usage_is_normalized_on_create_update_and_reload(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    created = registry.create(
        id="task-tokens", kind="llm", title="Plan", status="running",
        token_usage={"prompt": "11", "completion": -4, "total": 11.8, "calls": "1"},
    )

    assert created["token_usage"] == {
        "prompt": 11, "completion": 0, "total": 11, "calls": 1,
    }

    updated = registry.update(
        "task-tokens",
        token_usage={"completion": "9", "total": "20", "calls": "2"},
        event_type="task.tokens",
    )
    assert updated["token_usage"] == {
        "prompt": 11, "completion": 9, "total": 20, "calls": 2,
    }

    reloaded = TaskRegistry(str(tmp_path), interrupt_stale=False).get("task-tokens")
    assert reloaded["token_usage"] == updated["token_usage"]
    assert registry.events("task-tokens")[-1]["changes"]["token_usage"] == updated["token_usage"]


def test_active_tasks_cannot_be_dismissed(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    registry.create(id="task-active", kind="llm", title="Plan", status="queued")
    last_event_id = registry.latest_event_id()

    try:
        registry.delete("task-active")
    except ValueError as exc:
        assert "cancelled" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("active task was deleted")

    assert registry.get("task-active")["status"] == "queued"
    assert registry.events(after=last_event_id) == []


def test_delete_emits_durable_tombstone_replayable_after_last_event_id(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    registry.create(
        id="task-dismissed", kind="image", title="Finished image",
        status="completed", root_id="root-image",
    )
    last_event_id = registry.latest_event_id()

    assert registry.delete("task-dismissed") is True
    assert registry.get("task-dismissed") is None
    assert registry.list() == []

    replay = registry.events(after=last_event_id)
    assert len(replay) == 1
    tombstone = replay[0]
    assert tombstone["event_id"] > last_event_id
    assert tombstone["task_id"] == "task-dismissed"
    assert tombstone["root_id"] == "root-image"
    assert tombstone["sequence"] == 2
    assert tombstone["type"] == "task.deleted"
    changes = dict(tombstone["changes"])
    deleted_at = changes.pop("deleted_at")
    assert changes == {
        "deleted": True,
        "tombstone": True,
        "task_id": "task-dismissed",
        "root_id": "root-image",
        "status": "completed",
    }
    assert deleted_at > 0
    assert registry.wait_for_events(last_event_id, timeout=0.05) == replay

    reloaded = TaskRegistry(str(tmp_path), interrupt_stale=False)
    assert reloaded.get("task-dismissed") is None
    assert reloaded.latest_event_id() == tombstone["event_id"]
    assert reloaded.events(after=last_event_id) == replay
    assert reloaded.events("task-dismissed")[-1] == tombstone


def test_existing_foreign_key_event_log_is_migrated_without_changing_cursors(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    registry.create(
        id="task-legacy", kind="video", title="Legacy task", status="completed",
    )
    original_events = registry.events("task-legacy")
    original_cursor = registry.latest_event_id()

    with sqlite3.connect(registry.path, isolation_level=None) as connection:
        connection.executescript("""
            BEGIN IMMEDIATE;
            DROP INDEX idx_task_events_task;
            ALTER TABLE task_events RENAME TO task_events_durable_source;
            CREATE TABLE task_events (
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
            INSERT INTO task_events
                (event_id, task_id, root_id, sequence, timestamp, type, changes, context)
            SELECT event_id, task_id, root_id, sequence, timestamp, type, changes, context
            FROM task_events_durable_source;
            DROP TABLE task_events_durable_source;
            CREATE INDEX idx_task_events_task ON task_events(task_id, sequence);
            COMMIT;
        """)

    reloaded = TaskRegistry(str(tmp_path), interrupt_stale=False)
    with sqlite3.connect(reloaded.path) as connection:
        assert connection.execute("PRAGMA foreign_key_list(task_events)").fetchall() == []
        first_schema = connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        first_metadata = connection.execute(
            "SELECT key, value FROM task_registry_meta ORDER BY key"
        ).fetchall()
    assert reloaded.events("task-legacy") == original_events
    assert reloaded.latest_event_id() == original_cursor
    assert reloaded.schema_version() == TASK_SCHEMA_VERSION

    migrated_twice = TaskRegistry(str(tmp_path), interrupt_stale=False)
    with sqlite3.connect(migrated_twice.path) as connection:
        assert connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall() == first_schema
        assert connection.execute(
            "SELECT key, value FROM task_registry_meta ORDER BY key"
        ).fetchall() == first_metadata
    assert migrated_twice.events("task-legacy") == original_events
    assert migrated_twice.latest_event_id() == original_cursor

    assert migrated_twice.delete("task-legacy") is True
    tombstones = migrated_twice.events(after=original_cursor)
    assert [event["type"] for event in tombstones] == ["task.deleted"]

    restarted = TaskRegistry(str(tmp_path), interrupt_stale=False)
    assert restarted.events(after=original_cursor) == tombstones


def test_compatibility_adapter_can_attach_an_existing_task_to_its_parent(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    registry.create(id="task-parent", kind="series", title="Episode", status="running")
    registry.create(id="task-child", kind="video", title="Shot", status="running")

    child = registry.update(
        "task-child", root_id="task-parent", parent_id="task-parent",
        event_type="adapter.synced", force=True,
    )

    assert child["root_id"] == "task-parent"
    assert child["parent_id"] == "task-parent"
    assert [task["id"] for task in registry.list(root_id="task-parent")] == [
        "task-child", "task-parent",
    ]


def test_prune_keeps_active_latest_terminal_and_tombstone(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    active = registry.create(id="task-active", kind="video", status="running")
    old = registry.create(
        id="task-old", kind="video", status="completed", root_id="workflow",
    )
    latest = registry.create(
        id="task-latest", kind="video", status="completed", root_id="workflow",
    )

    with sqlite3.connect(registry.path) as connection:
        connection.execute(
            "UPDATE tasks SET updated_at = 1, snapshot = ? WHERE id = ?",
            (json.dumps({**old, "updated_at": 1}), old["id"]),
        )

    removed = registry.prune(
        terminal_before=time.time() - 1,
        keep=100,
        max_events=100,
    )

    assert removed == 1
    assert registry.get(active["id"])["status"] == "running"
    assert registry.get(latest["id"])["status"] == "completed"
    assert registry.get(old["id"]) is None
    tombstone = registry.events(old["id"])[-1]
    assert tombstone["type"] == "task.deleted"
    assert tombstone["changes"]["tombstone"] is True


def test_prune_dry_run_reports_without_deleting(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    old = registry.create(id="task-dry-run", kind="image", status="completed")
    with sqlite3.connect(registry.path) as connection:
        connection.execute(
            "UPDATE tasks SET updated_at = 1, snapshot = ? WHERE id = ?",
            (json.dumps({**old, "updated_at": 1}), old["id"]),
        )

    plan = registry.prune(terminal_before=time.time() - 1, keep=0, dry_run=True)

    assert plan["tasks"] == 0  # the newest terminal snapshot is protected
    assert plan["protected_latest_terminal"] == 1
    assert registry.get(old["id"]) is not None


def test_pruned_cursor_requires_resync_but_retained_cursor_does_not(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    task = registry.create(id="task-events", kind="llm", status="running")
    registry.update(task["id"], message="step 1")
    registry.update(task["id"], message="step 2")
    before_prune = registry.latest_event_id()

    registry.prune(
        terminal_before=time.time() - 1,
        keep=1000,
        max_events=1,
    )

    retained = registry.events()
    assert len(retained) == 1
    assert retained[0]["event_id"] == before_prune
    assert registry.latest_event_id() == before_prune
    assert registry.cursor_requires_resync(before_prune - 2) is True
    assert registry.cursor_requires_resync(before_prune) is False
    marker = registry.resync_required_event(before_prune - 2)
    assert marker["type"] == "resync_required"
    assert marker["changes"]["resync_required"] is True

    reloaded = TaskRegistry(str(tmp_path), interrupt_stale=False)
    assert reloaded.cursor_requires_resync(before_prune - 2) is True
    assert reloaded.cursor_requires_resync(before_prune) is False
    reloaded.update(task["id"], message="step 3")
    continued = reloaded.events(after=before_prune)
    assert [event["changes"]["message"] for event in continued] == ["step 3"]


def test_prune_terminal_count_keeps_newest_snapshots(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    tasks = [
        registry.create(id=f"task-terminal-{index}", kind="video", status="completed")
        for index in range(3)
    ]
    with sqlite3.connect(registry.path) as connection:
        for index, task in enumerate(tasks, start=1):
            snapshot = {**task, "updated_at": float(index)}
            connection.execute(
                "UPDATE tasks SET updated_at = ?, snapshot = ? WHERE id = ?",
                (float(index), json.dumps(snapshot), task["id"]),
            )

    removed = registry.prune(terminal_before=0, keep=2, max_events=100)

    assert removed == 1
    assert registry.get(tasks[0]["id"]) is None
    assert registry.get(tasks[1]["id"])["status"] == "completed"
    assert registry.get(tasks[2]["id"])["status"] == "completed"

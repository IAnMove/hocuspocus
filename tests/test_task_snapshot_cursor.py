"""Atomic snapshot/cursor boundary for the Activity SSE bootstrap."""

import threading

from services.task_manager import TaskRegistry


def test_snapshot_cursor_cannot_skip_a_concurrent_event(tmp_path, monkeypatch):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    registry.create(id="task-race", kind="test", status="queued", message="Queued")
    initial_cursor = registry.latest_event_id()
    snapshot_read = threading.Event()
    release_snapshot = threading.Event()
    writer_started = threading.Event()
    writer_finished = threading.Event()
    original_list = registry.list

    def paused_list(**kwargs):
        tasks = original_list(**kwargs)
        snapshot_read.set()
        assert release_snapshot.wait(2)
        return tasks

    monkeypatch.setattr(registry, "list", paused_list)
    result = {}

    def read_snapshot():
        result["value"] = registry.snapshot(statuses={"queued", "running"})

    def write_update():
        writer_started.set()
        registry.update("task-race", status="running", message="Running")
        writer_finished.set()

    reader = threading.Thread(target=read_snapshot)
    writer = threading.Thread(target=write_update)
    reader.start()
    assert snapshot_read.wait(2)
    writer.start()
    assert writer_started.wait(2)
    assert not writer_finished.wait(0.05)

    release_snapshot.set()
    reader.join(2)
    writer.join(2)
    assert not reader.is_alive()
    assert not writer.is_alive()

    tasks, cursor = result["value"]
    assert cursor == initial_cursor
    assert tasks[0]["status"] == "queued"
    replay = registry.events(after=cursor)
    assert len(replay) == 1
    assert replay[0]["changes"]["status"] == "running"

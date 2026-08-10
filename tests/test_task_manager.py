from services.task_manager import TaskRegistry, task_context_scope


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
            metadata={"prompt": "secret", "safe": "visible"},
        )

    assert task["metadata"] == {"safe": "visible"}
    assert registry.events("task-context")[0]["context"]["request_id"] == "request-1"


def test_active_tasks_cannot_be_dismissed(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    registry.create(id="task-active", kind="llm", title="Plan", status="queued")

    try:
        registry.delete("task-active")
    except ValueError as exc:
        assert "cancelled" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("active task was deleted")


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

"""Regression tests for canonical task-list recovery semantics."""

import itertools

from app.services import task_manager
from app.services.task_manager import ALL_STATUSES, TaskRegistry


def _use_deterministic_clock(monkeypatch, start: int = 1_000):
    ticks = itertools.count(start)
    monkeypatch.setattr(task_manager, "_now", lambda: float(next(ticks)))


def test_all_listing_keeps_old_active_task_beyond_terminal_history_limit(
    tmp_path,
    monkeypatch,
):
    _use_deterministic_clock(monkeypatch)
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    registry.create(
        id="active-before-history",
        kind="series",
        title="Old active render",
        status="running",
        workspace="default",
    )
    for index in range(325):
        registry.create(
            id=f"terminal-{index:03d}",
            kind="video",
            title=f"Completed clip {index}",
            status="completed",
            workspace="default",
        )

    listed = registry.list(statuses=set(ALL_STATUSES), limit=300)

    assert len(listed) == 301
    assert sum(task["status"] == "completed" for task in listed) == 300
    assert listed[-1]["id"] == "active-before-history"
    assert len({task["id"] for task in listed}) == len(listed)
    assert [task["updated_at"] for task in listed] == sorted(
        (task["updated_at"] for task in listed),
        reverse=True,
    )

    # The guarantee comes from SQLite state, not an in-memory side channel.
    reopened = TaskRegistry(str(tmp_path), interrupt_stale=False)
    persisted = reopened.list(statuses=set(ALL_STATUSES), limit=300)
    assert [task["id"] for task in persisted].count("active-before-history") == 1
    assert len(persisted) == 301


def test_mixed_status_and_root_filters_keep_all_matching_active_tasks(
    tmp_path,
    monkeypatch,
):
    _use_deterministic_clock(monkeypatch)
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    registry.create(
        id="root-a-running",
        root_id="root-a",
        kind="series",
        title="Running A",
        status="running",
    )
    registry.create(
        id="root-a-queued",
        root_id="root-a",
        kind="series",
        title="Queued A",
        status="queued",
    )
    registry.create(
        id="root-b-running",
        root_id="root-b",
        kind="series",
        title="Running B",
        status="running",
    )
    registry.create(
        id="root-a-failed-old",
        root_id="root-a",
        kind="series",
        title="Failed A old",
        status="failed",
    )
    registry.create(
        id="root-a-failed-new",
        root_id="root-a",
        kind="series",
        title="Failed A new",
        status="failed",
    )
    registry.create(
        id="root-a-completed",
        root_id="root-a",
        kind="series",
        title="Completed A",
        status="completed",
    )
    registry.create(
        id="root-b-failed",
        root_id="root-b",
        kind="series",
        title="Failed B",
        status="failed",
    )

    listed = registry.list(
        statuses={"running", "queued", "failed"},
        root_id="root-a",
        limit=1,
    )

    assert {task["id"] for task in listed} == {
        "root-a-running",
        "root-a-queued",
        "root-a-failed-new",
    }
    assert len(listed) == 3
    assert all(task["root_id"] == "root-a" for task in listed)
    assert all(task["status"] in {"running", "queued", "failed"} for task in listed)
    assert [task["updated_at"] for task in listed] == sorted(
        (task["updated_at"] for task in listed),
        reverse=True,
    )


def test_terminal_only_filter_still_uses_limit_and_invalid_filter_is_empty(
    tmp_path,
    monkeypatch,
):
    _use_deterministic_clock(monkeypatch)
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    for index in range(4):
        registry.create(
            id=f"failed-{index}",
            kind="llm",
            title=f"Failed plan {index}",
            status="failed",
        )
    registry.create(
        id="active",
        kind="llm",
        title="Active plan",
        status="running",
    )

    listed = registry.list(statuses={"failed"}, limit=2)

    assert [task["id"] for task in listed] == ["failed-3", "failed-2"]
    assert registry.list(statuses={"not-a-status"}, limit=2) == []

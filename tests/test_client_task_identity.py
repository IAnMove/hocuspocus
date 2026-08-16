"""Frontend task ids must not collide with backend adapter namespaces."""

from services.task_identity import (
    CLIENT_TASK_PREFIX,
    CLIENT_TASK_SUFFIX_MAX_LENGTH,
    canonical_client_task_id,
    canonical_client_task_identity,
)
from services.task_manager import TaskRegistry


def test_backend_ids_are_remapped_to_the_client_namespace():
    assert canonical_client_task_id("task-generation-demo") == "task-client-task-generation-demo"
    assert canonical_client_task_id("task-director-demo") == "task-client-task-director-demo"
    assert canonical_client_task_id("task-series-render-demo") == "task-client-task-series-render-demo"


def test_existing_client_ids_remain_compatible_without_duplicate_prefixes():
    assert canonical_client_task_id("task-client-task-generation-demo") == "task-client-task-generation-demo"
    assert canonical_client_task_id("task-client-task-client-demo") == "task-client-demo"


def test_frontend_id_normalization_is_safe_unique_and_bounded():
    assert canonical_client_task_id("  render/demo?frame=1  ") == "task-client-render-demo-frame-1"
    assert len(canonical_client_task_id("x" * 1000)) == len(CLIENT_TASK_PREFIX) + CLIENT_TASK_SUFFIX_MAX_LENGTH
    assert canonical_client_task_id(None) != canonical_client_task_id(None)


def test_client_cannot_choose_another_tasks_root():
    task_id, root_id = canonical_client_task_identity({
        "id": "activity-demo",
        "root_id": "task-generation-demo",
    })
    assert task_id == "task-client-activity-demo"
    assert root_id == task_id


def test_backend_snapshot_and_events_survive_same_text_client_upsert(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    backend_id = "task-generation-demo"
    backend = registry.create(
        id=backend_id,
        root_id=backend_id,
        kind="generation",
        workflow="generation",
        status="completed",
        message="Backend finished",
    )
    backend_events = registry.events(backend_id)

    client_id, client_root_id = canonical_client_task_identity({
        "id": backend_id,
        "root_id": backend_id,
    })
    client = registry.create(
        id=client_id,
        root_id=client_root_id,
        kind="foreground",
        workflow="frontend",
        status="running",
        message="Frontend activity",
    )

    assert client["id"] == "task-client-task-generation-demo"
    assert client["root_id"] == client["id"]
    assert registry.get(backend_id) == backend
    assert registry.events(backend_id) == backend_events
    assert {task["id"] for task in registry.list(statuses={"running", "completed"})} == {
        backend_id,
        client_id,
    }

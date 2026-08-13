from contextlib import contextmanager
import threading
import time

from app.services import llm_service


class _RecordingCoordinator:
    def __init__(self):
        self.requests = []

    @contextmanager
    def acquire(self, lane, **kwargs):
        self.requests.append((lane, kwargs))
        yield lane


class _CancelledCoordinator:
    @contextmanager
    def acquire(self, lane, **kwargs):
        from app.services.resource_scheduler import ResourceAcquireCancelled

        assert kwargs["cancelled"]()
        raise ResourceAcquireCancelled("cancelled in test")
        yield lane


def test_singleton_cuda_request_is_identified_as_local_llm_owner(monkeypatch):
    from app.services import resource_scheduler

    coordinator = _RecordingCoordinator()
    monkeypatch.setattr(resource_scheduler, "coordinator", coordinator)
    monkeypatch.setattr(llm_service, "_provider", "local")
    monkeypatch.setattr(llm_service, "_device", "cuda")
    monkeypatch.setattr(llm_service, "_model_id", "test-model")

    scheduled = llm_service._scheduled_llm_request(lambda: "done")

    assert scheduled() == "done"
    lane, request = coordinator.requests[0]
    assert lane.key == "local_gpu:0"
    assert request["description"] == "Local LLM completion · test-model"


def test_generate_and_streaming_use_the_same_scheduler_wrapper():
    # trace_llm_call is the outer wrapper; the scheduling wrapper must be the
    # next layer for both public request paths.
    assert llm_service.generate.__wrapped__.__wrapped__.__name__ == "generate"
    assert (
        llm_service.generate_streaming.__wrapped__.__wrapped__.__name__
        == "generate_streaming"
    )


def test_local_load_translates_cancelled_wait_to_interrupted(monkeypatch):
    from app.services import resource_scheduler

    monkeypatch.setattr(resource_scheduler, "coordinator", _CancelledCoordinator())
    monkeypatch.setattr(
        llm_service, "_current_task_cancel_callback", lambda: (lambda: True),
    )
    called = []
    scheduled = llm_service._scheduled_llm_load(
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    try:
        scheduled("test-model", "cpu")
    except InterruptedError as exc:
        assert "cancelled in test" in str(exc)
    else:  # pragma: no cover - explicit assertion message
        raise AssertionError("cancelled load did not raise InterruptedError")
    assert called == []


def test_canonical_cancelling_phase_interrupts_llm_wait(tmp_path):
    from app.services.task_manager import get_task_registry, task_context_scope

    registry = get_task_registry(str(tmp_path))
    registry.create(
        id="task-series-plan-cancel",
        root_id="task-series-plan-cancel",
        workspace="default",
        kind="llm-planning",
        workflow="series-plan",
        title="Series planning",
        status="running",
        phase="cancelling",
        message="Waiting for the active LLM call to stop",
    )
    with task_context_scope(
        task_id="task-series-plan-cancel",
        workspace_dir=str(tmp_path),
    ):
        cancelled = llm_service._current_task_cancel_callback()

    assert cancelled is not None
    assert cancelled() is True


def test_request_retries_lane_if_singleton_routing_changes_while_waiting(monkeypatch):
    from app.services import resource_scheduler

    class _RoutingChangeCoordinator(_RecordingCoordinator):
        @contextmanager
        def acquire(self, lane, **kwargs):
            self.requests.append((lane, kwargs))
            if len(self.requests) == 1:
                with llm_service._lock:
                    llm_service._provider = "remote"
                    llm_service._remote_url = "https://second.example/v1"
                    llm_service._model_id = "second-model"
                    llm_service._device = "remote"
            yield lane

    coordinator = _RoutingChangeCoordinator()
    monkeypatch.setattr(resource_scheduler, "coordinator", coordinator)
    monkeypatch.setattr(llm_service, "_provider", "remote")
    monkeypatch.setattr(llm_service, "_remote_url", "https://first.example/v1")
    monkeypatch.setattr(llm_service, "_model_id", "first-model")
    monkeypatch.setattr(llm_service, "_device", "remote")
    called = []
    scheduled = llm_service._scheduled_llm_request(
        lambda: called.append(llm_service._model_id) or "done",
    )

    assert scheduled() == "done"
    assert called == ["second-model"]
    assert [request[0].key for request in coordinator.requests] == [
        "remote:https://first.example",
        "remote:https://second.example",
    ]


def test_request_can_be_cancelled_while_waiting_for_singleton_lock(monkeypatch):
    from app.services import resource_scheduler

    coordinator = _RecordingCoordinator()
    cancel = threading.Event()
    result = []
    monkeypatch.setattr(resource_scheduler, "coordinator", coordinator)
    monkeypatch.setattr(
        llm_service, "_current_task_cancel_callback", lambda: cancel.is_set,
    )
    scheduled = llm_service._scheduled_llm_request(
        lambda: result.append("entered"),
    )

    llm_service._lock.acquire()
    try:
        def run():
            try:
                scheduled()
            except InterruptedError:
                result.append("cancelled")

        worker = threading.Thread(target=run)
        worker.start()
        time.sleep(0.03)
        cancel.set()
        worker.join(1)
        assert not worker.is_alive()
    finally:
        llm_service._lock.release()

    assert result == ["cancelled"]
    assert coordinator.requests == []

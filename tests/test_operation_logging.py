from __future__ import annotations

import json
import logging

from services.director.planners.base import BasePlanner
from services.operation_logging import log_operation, operation_scope
from services.task_manager import TaskRegistry


class _Planner(BasePlanner):
    skill_type = "test-planner"

    def plan(self, **kwargs):
        return kwargs


def _payloads(caplog):
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name.startswith("loreframe.operations")
    ]


def test_operation_error_contains_activity_pipeline_workspace_and_redacts(caplog):
    logger = logging.getLogger("loreframe.operations.test")
    caplog.set_level(logging.INFO, logger=logger.name)

    with operation_scope(
        activity_id="activity-1",
        pipeline_id="pipeline-1",
        workspace="workspace-1",
        task_id="task-1",
    ):
        log_operation(
            logger,
            logging.ERROR,
            "test.failed",
            "Operation failed",
            error=RuntimeError("boom"),
            api_key="must-not-leak",
        )

    payload = _payloads(caplog)[-1]
    assert payload["activity_id"] == "activity-1"
    assert payload["pipeline_id"] == "pipeline-1"
    assert payload["workspace"] == "workspace-1"
    assert payload["task_id"] == "task-1"
    assert payload["error"] == {"type": "RuntimeError", "message": "boom"}
    assert payload["api_key"] == "[REDACTED]"


def test_planner_repair_failure_inherits_operation_correlation(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="loreframe.operations.planner")
    planner = _Planner(llm_generate=lambda **_kwargs: "malformed")
    monkeypatch.setattr(planner, "_parse_json_response", lambda _value: None)

    with operation_scope(
        activity_id="activity-plan",
        pipeline_id="pipeline-plan",
        workspace="series-a",
        task_id="task-plan",
    ):
        assert planner._call_llm_json("request", "system", streaming=False) == []

    terminal = next(
        payload for payload in reversed(_payloads(caplog))
        if payload["event"] == "planner.json_parse_failed"
    )
    assert terminal["activity_id"] == "activity-plan"
    assert terminal["pipeline_id"] == "pipeline-plan"
    assert terminal["workspace"] == "series-a"
    assert terminal["task_id"] == "task-plan"


def test_task_registry_logs_an_interrupted_checkpoint_failure(
    tmp_path, caplog, monkeypatch,
):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    task = {
        "id": "task-stale",
        "root_id": "activity-stale",
        "workspace": "workspace-stale",
        "status": "running",
    }
    monkeypatch.setattr(registry, "list", lambda **_kwargs: [task])
    monkeypatch.setattr(
        registry,
        "update",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("locked")),
    )
    caplog.set_level(logging.ERROR, logger="loreframe.operations.tasks")

    assert registry.interrupt_unfinished() == 0

    payload = _payloads(caplog)[-1]
    assert payload["event"] == "task.interrupt_failed"
    assert payload["activity_id"] == "activity-stale"
    assert payload["workspace"] == "workspace-stale"
    assert payload["task_id"] == "task-stale"

"""A Video 3D export a restart interrupted is listed in jobs.leftovers and resumes as the same task."""
from __future__ import annotations

from services.durable_generation_queue import DurableGenerationQueue
from services.job_leftovers import JobLeftovers
from services.scene_export_leftovers import SceneExportLeftovers
from tests.test_world3d_export import WORKSPACE, _command, _paint, _service, _wait


def _interrupted_export(tmp_path, intent_id):
    calls = []

    def failing(snapshot, staging, progress, cancelled):
        calls.append("first run")
        return _paint(snapshot, staging, progress, cancelled, fail=True)

    before_restart = _service(tmp_path, renderer=failing)
    admitted = before_restart.submit(_command(intent_id))
    registry = before_restart._registry(WORKSPACE)
    task_id = admitted["receipt"]["taskIds"][0]
    _wait(registry, task_id, {"failed"})
    # What the restart leaves behind for an export that was running.
    registry.update(task_id, status="interrupted", phase="interrupted", force=True)
    return task_id


def _leftovers(tmp_path, renderer):
    service = _service(tmp_path, renderer=renderer)
    exports = SceneExportLeftovers(services=[service], list_workspaces=lambda: [{"name": WORKSPACE}],
                                   registry_for=service._registry)
    queue = DurableGenerationQueue(str(tmp_path / "queue.json"))
    return JobLeftovers(queue=queue, jobs={}, exports=exports), service


def test_an_interrupted_export_is_listed_and_resumed_as_the_same_task(tmp_path):
    task_id = _interrupted_export(tmp_path, "export-after-restart")
    calls = []

    def renderer(snapshot, staging, progress, cancelled):
        calls.append("resumed")
        return _paint(snapshot, staging, progress, cancelled)

    leftovers, service = _leftovers(tmp_path, renderer)
    listed = leftovers.list_response()["result"]["jobs"]
    assert [(job["job_id"], job["intent_id"], job["status"], job["operation"]) for job in listed] == [
        (task_id, "export-after-restart", "interrupted", "scenes.world3d.export")]

    resumed = leftovers.resume_response("export-after-restart")["result"]
    assert resumed == {"job_id": task_id, "intent_id": "export-after-restart", "status": "queued", "started": True}
    completed = _wait(service._registry(WORKSPACE), task_id, {"completed", "failed"})
    assert completed["status"] == "completed" and calls == ["resumed"]
    assert leftovers.list_response()["result"]["jobs"] == []


def test_discarding_an_interrupted_export_cancels_it(tmp_path):
    task_id = _interrupted_export(tmp_path, "export-to-drop")
    leftovers, service = _leftovers(tmp_path, _paint)
    result = leftovers.discard_response("export-to-drop")["result"]
    assert result == {"job_id": task_id, "intent_id": "export-to-drop", "discarded": True, "status": "discarded"}
    assert service._registry(WORKSPACE).get(task_id)["status"] == "cancelled"
    assert leftovers.list_response()["result"]["jobs"] == []

"""Both Video 2D and Video 3D export receipts follow the canonical task."""
from __future__ import annotations

from services.export_receipts import project_export_receipt


def test_world3d_style_task_projects_status_and_artifact():
    stored = {"version": 1, "status": "queued", "artifacts": [], "result": {"job_id": "j", "status": "queued"}}
    task = {"status": "completed", "workspace": "promo", "result_refs": ["shot.mp4"],
            "metadata": {"operation": "scenes.world3d.export", "output": {"name": "shot.mp4", "url": "/api/v1/file/shot.mp4?workspace=promo", "workspace": "promo"}}}
    projected = project_export_receipt(stored, task)
    assert projected["status"] == "completed" and projected["result"]["status"] == "completed"
    assert projected["artifacts"] == [{"name": "shot.mp4", "url": "/api/v1/file/shot.mp4?workspace=promo", "workspace": "promo"}]
    assert stored["status"] == "queued" and stored["artifacts"] == []


def test_world3d_service_receipt_uses_projection():
    import inspect
    from services.world3d_export import World3DExportService
    assert "project_export_receipt" in inspect.getsource(World3DExportService.receipt)


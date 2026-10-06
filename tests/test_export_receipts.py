"""Both Video 2D and Video 3D export receipts follow the canonical task."""
from __future__ import annotations

from services.export_receipts import project_export_receipt, project_export_task
import hashlib
import pytest


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


@pytest.mark.parametrize('current,previous,available,superseded', [
    (b'original', None, True, False), (b'new', b'original', True, True),
    (b'newest', b'new', False, True), (None, None, False, True),
])
def test_named_receipt_never_links_to_another_exports_bytes(tmp_path, current, previous, available, superseded):
    if current is not None:
        (tmp_path / 'loop.mp4').write_bytes(current)
    if previous is not None:
        (tmp_path / 'loop.previous.mp4').write_bytes(previous)
    output = {'name': 'loop.mp4', 'url': '/api/v1/file/loop.mp4', 'workspace': 'promo',
              'sha256': hashlib.sha256(b'original').hexdigest()}
    task = {'status': 'completed', 'workspace': 'promo', 'metadata': {'output': output}}
    artifact = project_export_receipt({'status': 'queued'}, task, folder=tmp_path)['artifacts'][0]
    assert artifact.get('superseded', False) is superseded
    assert artifact.get('available', True) is available
    if available:
        assert (tmp_path / artifact['name']).read_bytes() == b'original'
        assert artifact['url'].startswith('/api/v1/file/' + artifact['name'])
    else:
        assert artifact['url'] is None
    assert task['metadata']['output'] == output


@pytest.mark.parametrize('previous,expected', [(b'original', ['loop.previous.mp4']), (b'new', [])])
def test_superseded_task_fallback_does_not_return_current_alias(tmp_path, previous, expected):
    (tmp_path / 'loop.mp4').write_bytes(b'newest')
    (tmp_path / 'loop.previous.mp4').write_bytes(previous)
    task = {'status': 'completed', 'workspace': 'promo', 'result_refs': ['loop.mp4'],
            'metadata': {'output': {'name': 'loop.mp4', 'url': '/api/v1/file/loop.mp4', 'workspace': 'promo',
                                    'sha256': hashlib.sha256(b'original').hexdigest()}}}
    receipt = project_export_receipt({'status': 'queued'}, task, folder=tmp_path)
    projected = project_export_task(task, receipt)
    assert projected['result_refs'] == expected
    assert projected['metadata']['output'] == receipt['artifacts'][0]
    assert task['result_refs'] == ['loop.mp4']

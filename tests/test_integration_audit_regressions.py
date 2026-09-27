"""Integration regressions with fake providers and real canonical persistence."""
import json
import time
from pathlib import Path
from unittest.mock import patch

from tests import test_wizard_workflow_executor as wf
from tests import test_core_runtime as core_tests
from services import core_generation_commands, core_remote_image
from services.world3d_export import export_plan
from routers.wizard_workflow_executor import create_wizard_workflow_executor_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def test_completed_image_advances_without_a_client_reconcile(tmp_path):
    executor, native, _, _ = wf._executor(tmp_path)
    app = FastAPI()
    app.include_router(create_wizard_workflow_executor_router(executor, list_workspaces=lambda: [wf.WORKSPACE], interval=0.01))
    with TestClient(app) as client:
        workflow = client.post('/api/v1/wizard/workflows/executor', json=wf._start_body()).json()['workflow']
        wf._complete(native, wf.WORKSPACE, workflow['steps'][0]['taskId'], ['poster.png'])
        deadline = time.monotonic() + 2
        current = executor.get(wf.WORKSPACE, workflow['workflowId'])['workflow']
        # Dispatch is admitted before its receipt is checkpointed. Wait for
        # the public workflow to attach that receipt, not a fake's call list.
        while not current['steps'][1]['taskId'] and time.monotonic() < deadline:
            time.sleep(0.01)
            current = executor.get(wf.WORKSPACE, workflow['workflowId'])['workflow']
        assert current['steps'][1]['taskId']
        assert len(native.dispatch_calls) == 2
        wf._complete(native, wf.WORKSPACE, current['steps'][1]['taskId'], ['upscaled.png'])
        deadline = time.monotonic() + 2
        while executor.get(wf.WORKSPACE, workflow['workflowId'])['workflow']['state'] != 'completed' and time.monotonic() < deadline:
            time.sleep(0.01)
        assert executor.get(wf.WORKSPACE, workflow['workflowId'])['workflow']['state'] == 'completed'


def test_resuming_failed_step_dispatches_a_new_attempt(tmp_path):
    executor, native, _, _ = wf._executor(tmp_path)
    with wf._app(executor, tmp_path) as client:
        current = client.post('/api/v1/wizard/workflows/executor', json=wf._start_body()).json()['workflow']
        task_id = current['steps'][0]['taskId']
        native.registry(wf.WORKSPACE).update(task_id, status='failed', force=True)
        client.post('/api/v1/wizard/workflows/executor/reconcile', json={'workspace': wf.WORKSPACE})
        resumed = client.post('/api/v1/wizard/workflows/executor/resume', json={'workspace': wf.WORKSPACE, 'workflowId': current['workflowId']})
        assert resumed.status_code == 200, resumed.text
        client.post('/api/v1/wizard/workflows/executor/reconcile', json={'workspace': wf.WORKSPACE})
        current = client.get('/api/v1/wizard/workflows/executor/' + current['workflowId'], params={'workspace': wf.WORKSPACE}).json()['workflow']
        print(json.dumps({'case': 'resume_failed', 'dispatches': len(native.dispatch_calls),
                          'state_after_resume': current['state'], 'same_failed_task': current['steps'][0]['taskId'] == task_id}))
        assert len(native.dispatch_calls) == 2, 'Resume reuses the failed admission and never dispatches another attempt'


@pytest.mark.parametrize('terminal', ['completed', 'cancelled', 'failed', 'interrupted', 'running'])
def test_replay_of_terminal_core_job_does_not_call_provider_again(tmp_path, monkeypatch, terminal):
    monkeypatch.chdir(tmp_path)
    Path('outputs').mkdir()
    case = core_tests.CoreRuntimeTests()
    case.setUp()
    job_id = None
    try:
        fake = {'name': 'minimax.jpg', 'path': 'minimax.jpg', 'prompt': 'a lantern', 'aspect_ratio': '1:1'}
        with patch('services.core_remote_image.generate_image', return_value=fake) as provider, patch('services.execution_mode.validate_remote_provider'), patch('services.core_remote_image.threading.Thread', core_tests.ImmediateThread):
            command = case._studio_image_command('audit-completed-replay')
            first = case.client.post('/api/v1/generation/commands', json=command)
            assert first.status_code == 200, first.text
            job_id = first.json()['receipt']['result']['job_id']
            receipt = core_generation_commands.service().receipt('default', command['intent_id'])
            assert receipt['task']['status'] == 'completed'
            registry = core_generation_commands.registry_for('default')
            registry.update(receipt['task']['id'], status=terminal, force=True)
            # Same persisted completed task; only process-owned job memory is gone.
            core_remote_image._JOBS.pop(job_id)
            replay = case.client.post('/api/v1/generation/commands', json=command)
            assert replay.status_code == 200, replay.text
            assert replay.json()['replayed'] is True
            expected = 'interrupted' if terminal == 'running' else terminal
            assert case.client.get(f'/api/v1/status/{job_id}').json()['status'] == expected
            print(json.dumps({'case': 'paid_replay', 'terminal_before_replay': receipt['task']['status'],
                              'replayed': replay.json()['replayed'], 'provider_call_count': provider.call_count}))
            assert provider.call_count == 1, 'Replaying an already completed intent executes the remote provider again'
    finally:
        case.tearDown()
        if job_id:
            core_remote_image._JOBS.pop(job_id, None)


def test_server_export_preserves_accepted_24fps():
    plan = export_plan({'duration': 2, 'fps': 24, 'width': 640, 'height': 360})
    print(json.dumps({'case': '24fps', 'requested_fps': 24, 'plan': plan}))
    assert plan['fps'] == 24
    assert plan['count'] == 48


def test_supervisor_recovers_existing_workflow_on_startup(tmp_path):
    import asyncio
    executor, native, _, _ = wf._executor(tmp_path)
    workflow = asyncio.run(executor.start(wf._start_body()))['workflow']
    wf._complete(native, wf.WORKSPACE, workflow['steps'][0]['taskId'], ['poster.png'])
    restarted, _, _, _ = wf._executor(tmp_path, native)
    app = FastAPI()
    app.include_router(create_wizard_workflow_executor_router(restarted, list_workspaces=lambda: [wf.WORKSPACE], interval=0.01))
    with TestClient(app):
        deadline = time.monotonic() + 2
        while len(native.dispatch_calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(native.dispatch_calls) == 2
        time.sleep(0.04)
        assert len(native.dispatch_calls) == 2

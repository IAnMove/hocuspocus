"""Transport retries must reuse queue admission, including across a restart."""
import asyncio
import hashlib
import json
import sqlite3

import pytest
from routers.wangp_mcp import RequestJournal, create_wangp_mcp_router


class Request:
    headers = {'authorization': 'Bearer test-token'}
    url = type('URL', (), {'scheme': 'http', 'netloc': 'localhost:42000'})()
    def __init__(self, value): self.value = value
    async def json(self): return self.value


def test_application_handlers_find_endpoints_in_included_routers():
    from fastapi import APIRouter, FastAPI
    from services.wangp_agent_adapters import application_handlers
    app, router = FastAPI(), APIRouter()
    def assets(**kwargs): return {'assets': []}
    def asset(asset_id): return {'id': asset_id}
    def collections(): return {'collections': []}
    async def create(request): return await request.json()
    async def update(workspace_id, request): return await request.json()
    async def analyze(request): return {'text': 'Observed'}
    for path, method, handler in [('/api/v1/assets', 'GET', assets), ('/api/v1/assets/{asset_id}', 'GET', asset),
        ('/api/v1/workspace-collections', 'GET', collections), ('/api/v1/workspace-collections', 'POST', create),
        ('/api/v1/workspace-collections/{workspace_id}', 'PUT', update), ('/api/v1/llm/generate', 'POST', analyze)]:
        router.add_api_route(path, handler, methods=[method])
    app.include_router(router)
    handlers = application_handlers(app)
    assert handlers['collections']() == {'collections': []}
    assert handlers['assets']({}) == {'assets': []}
    assert asyncio.run(handlers['analyze'](Request({}))) == {'text': 'Observed'}


def endpoint(path, handler):
    router = create_wangp_mcp_router(handlers={'generate': handler}, journal_path=path, token_getter=lambda: 'test-token')
    return next(route.endpoint for route in router.routes if route.path.endswith('/mcp') and 'POST' in route.methods)


def http_app(path, handler):
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_wangp_mcp_router(handlers={'generate': handler}, journal_path=path, token_getter=lambda: 'test-token'))
    return app


def test_generate_schema_requires_a_direct_generation_mode():
    from routers.wangp_mcp import GENERATION_MODES, tool_definitions

    generate = next(tool for tool in tool_definitions() if tool['name'] == 'generate')
    params = generate['inputSchema']['properties']['params']
    assert params['required'] == ['generation_mode']
    assert tuple(GENERATION_MODES) == ('image', 'video', 'audio', 'avatar')
    assert params['properties']['generation_mode']['enum'] == list(GENERATION_MODES)
    assert 'image_mode' in params['properties']['generation_mode']['description']
    assert params['properties']['image_mode'] == {
        'type': 'integer',
        'minimum': 0,
        'description': 'Optional native output selector; it must agree with generation_mode.',
    }


@pytest.mark.parametrize('mode', ('image', 'video', 'audio', 'avatar'))
def test_generate_accepts_each_generic_generation_mode(tmp_path, mode):
    calls = []
    path = tmp_path / 'journal.db'
    params = {'model_type': 'fake', 'prompt': 'literal prompt', 'generation_mode': mode}

    async def submit(request):
        calls.append(await request.json())
        return {'job_id': f'{mode}-job', 'status': 'queued'}

    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': f'mode-{mode}', 'params': params}}}
    response = asyncio.run(endpoint(path, submit)(Request(message)))
    payload = json.loads(response.body)
    assert payload['result']['isError'] is False
    assert calls[0]['generation_mode'] == mode
    assert calls[0]['prompt'] == 'literal prompt'
    assert calls[0]['image_mode'] == (1 if mode == 'image' else 0)
    expected_digest = hashlib.sha256(json.dumps(['generate', params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT digest FROM requests WHERE id=?', (f'mode-{mode}',)).fetchone()[0] == expected_digest


@pytest.mark.parametrize(('mode', 'image_mode'), (('image', 2), ('video', 0), ('audio', 0), ('avatar', 0)))
def test_generate_accepts_coherent_explicit_native_image_mode(tmp_path, mode, image_mode):
    calls = []

    async def submit(request):
        calls.append(await request.json())
        return {'job_id': f'{mode}-explicit-job', 'status': 'queued'}

    path = tmp_path / 'journal.db'
    params = {'model_type': 'fake', 'prompt': 'literal prompt', 'generation_mode': mode, 'image_mode': image_mode}
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': f'explicit-{mode}', 'params': params}}}
    from fastapi.testclient import TestClient
    with TestClient(http_app(path, submit)) as client:
        response = client.post('/api/v1/wangp/mcp', headers={'Authorization': 'Bearer test-token'}, json=message)
    assert response.json()['result']['isError'] is False
    assert calls[0]['image_mode'] == image_mode


def test_duplicate_rpc_after_restart_is_one_job(tmp_path):
    calls = []
    async def submit(request):
        calls.append(await request.json())
        return {'job_id': 'canonical-1', 'status': 'queued'}
    path = tmp_path / 'journal.db'
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': 'edit-1', 'params': {'model_type': 'sensenova_u1_5_8b_mot', 'prompt': 'Write exactly "mañana"', 'generation_mode': 'image'}}}}
    first = asyncio.run(endpoint(path, submit)(Request(message)))
    second = asyncio.run(endpoint(path, submit)(Request(message)))
    assert first.body == second.body
    assert len(calls) == 1
    assert calls[0]['prompt'] == 'Write exactly "mañana"'
    assert calls[0]['provenance']['command']['command_id'] == 'edit-1'


def test_historical_replay_without_mode_bypasses_new_validation(tmp_path):
    params = {'model_type': 'legacy-model', 'prompt': 'Keep this literal: mañana'}
    digest = hashlib.sha256(json.dumps(['generate', params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    journal = RequestJournal(tmp_path / 'journal.db')
    journal.reserve('legacy-1', digest)
    historical = {'job_id': 'legacy-job', 'status': 'completed', 'error': None}
    journal.finish('legacy-1', historical)

    calls = []
    async def submit(request):
        calls.append(await request.json())
        raise AssertionError('a historical replay must not invoke the handler')

    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': 'legacy-1', 'params': params}}}
    from fastapi.testclient import TestClient
    with TestClient(http_app(journal.path, submit)) as client:
        response = client.post('/api/v1/wangp/mcp', headers={'Authorization': 'Bearer test-token'}, json=message)
    payload = response.json()
    value = json.loads(payload['result']['content'][0]['text'])
    assert payload['result']['isError'] is False
    assert value == historical
    assert calls == []


def test_new_generate_requires_mode_without_consuming_request_id(tmp_path):
    calls = []
    async def submit(request):
        calls.append(await request.json())
        return {'job_id': 'should-not-run'}

    path = tmp_path / 'journal.db'
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': 'missing-mode', 'params': {'model_type': 'image-model', 'prompt': 'literal', 'image_mode': 1}}}}
    from fastapi.testclient import TestClient
    with TestClient(http_app(path, submit)) as client:
        response = client.post('/api/v1/wangp/mcp', headers={'Authorization': 'Bearer test-token'}, json=message)
    payload = response.json()
    assert payload['result']['isError'] is True
    assert 'generation_mode' in payload['result']['content'][0]['text']
    assert calls == []
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM requests WHERE id=?', ('missing-mode',)).fetchone()[0] == 0


def test_rejected_missing_mode_request_id_can_be_corrected_once(tmp_path):
    calls = []

    async def submit(request):
        calls.append(await request.json())
        return {'job_id': 'corrected-job', 'status': 'queued', 'error': None}

    path = tmp_path / 'journal.db'
    base_params = {'model_type': 'image-model', 'prompt': 'literal'}
    missing = {
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'tools/call',
        'params': {'name': 'generate', 'arguments': {'request_id': 'correctable', 'params': base_params}},
    }
    corrected_params = {**base_params, 'generation_mode': 'image'}
    corrected = {
        **missing,
        'id': 2,
        'params': {'name': 'generate', 'arguments': {'request_id': 'correctable', 'params': corrected_params}},
    }
    replay = {**corrected, 'id': 3}

    from fastapi.testclient import TestClient
    with TestClient(http_app(path, submit)) as client:
        headers = {'Authorization': 'Bearer test-token'}
        rejected = client.post('/api/v1/wangp/mcp', headers=headers, json=missing).json()
        admitted = client.post('/api/v1/wangp/mcp', headers=headers, json=corrected).json()
        repeated = client.post('/api/v1/wangp/mcp', headers=headers, json=replay).json()

    assert rejected['result']['isError'] is True
    assert admitted['result']['isError'] is False
    assert repeated['result'] == admitted['result']
    assert len(calls) == 1
    assert calls[0]['image_mode'] == 1
    expected_digest = hashlib.sha256(json.dumps(['generate', corrected_params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with sqlite3.connect(path) as db:
        row = db.execute('SELECT digest, result FROM requests WHERE id=?', ('correctable',)).fetchone()
    assert row[0] == expected_digest
    assert json.loads(row[1]) == {'job_id': 'corrected-job', 'status': 'queued', 'error': None}


def test_new_generate_rejects_unknown_mode_without_consuming_request_id(tmp_path):
    path = tmp_path / 'journal.db'
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': 'bad-mode', 'params': {'model_type': 'image-model', 'prompt': 'literal', 'generation_mode': 'image_guided'}}}}
    from fastapi.testclient import TestClient
    with TestClient(http_app(path, lambda _: {'job_id': 'should-not-run'})) as client:
        response = client.post('/api/v1/wangp/mcp', headers={'Authorization': 'Bearer test-token'}, json=message)
    payload = response.json()
    assert payload['result']['isError'] is True
    assert 'must be one of' in payload['result']['content'][0]['text']
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM requests WHERE id=?', ('bad-mode',)).fetchone()[0] == 0


@pytest.mark.parametrize(
    ('mode', 'image_mode', 'expected_fragment'),
    (
        ('image', 0, 'requires'),
        ('video', 1, 'requires'),
        ('video', -1, 'non-negative integer'),
        ('video', True, 'non-negative integer'),
        ('video', 1.0, 'non-negative integer'),
        ('image', '1', 'non-negative integer'),
    ),
)
def test_new_generate_rejects_invalid_native_image_mode(tmp_path, mode, image_mode, expected_fragment):
    path = tmp_path / 'journal.db'
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': f'conflict-{mode}', 'params': {'model_type': 'fake', 'prompt': 'literal', 'generation_mode': mode, 'image_mode': image_mode}}}}
    from fastapi.testclient import TestClient
    with TestClient(http_app(path, lambda _: {'job_id': 'should-not-run'})) as client:
        response = client.post('/api/v1/wangp/mcp', headers={'Authorization': 'Bearer test-token'}, json=message)
    payload = response.json()
    assert payload['result']['isError'] is True
    assert expected_fragment in payload['result']['content'][0]['text']
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] == 0


def test_status_and_error_values_set_is_error_only_for_actual_failures(tmp_path):
    outcomes = [
        ({'status': 'running', 'error': None}, False),
        ({'status': 'completed', 'error': None}, False),
        ({'status': 'failed', 'error': None}, True),
        ({'status': 'completed', 'error': 'provider failed'}, True),
        ({'status': 'completed', 'error': None, 'status_code': 400}, True),
        ({'status': 'completed', 'error': None, 'status_code': 399}, False),
    ]
    calls = []

    async def submit(request):
        calls.append(await request.json())
        return outcomes[len(calls) - 1][0]

    path = tmp_path / 'journal.db'
    from fastapi.testclient import TestClient
    with TestClient(http_app(path, submit)) as client:
        for index, (expected_value, expected_error) in enumerate(outcomes):
            message = {'jsonrpc': '2.0', 'id': index, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': f'status-{index}', 'params': {'model_type': 'fake', 'prompt': f'prompt-{index}', 'generation_mode': 'video'}}}}
            response = client.post('/api/v1/wangp/mcp', headers={'Authorization': 'Bearer test-token'}, json=message)
            payload = response.json()
            value = json.loads(payload['result']['content'][0]['text'])
            assert value == expected_value
            assert payload['result']['isError'] is expected_error

    assert len(calls) == len(outcomes)


def test_conflicting_digest_is_rejected_without_second_handler_call(tmp_path):
    calls = []

    async def submit(request):
        calls.append(await request.json())
        return {'job_id': 'canonical-1', 'status': 'queued'}

    path = tmp_path / 'journal.db'
    post = endpoint(path, submit)
    base = {'model_type': 'fake', 'prompt': 'first', 'generation_mode': 'video'}
    first = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': 'conflict-1', 'params': base}}}
    second = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': 'conflict-1', 'params': {**base, 'prompt': 'different'}}}}
    assert json.loads(asyncio.run(post(Request(first))).body)['result']['isError'] is False
    response = json.loads(asyncio.run(post(Request(second))).body)
    assert response['result']['isError'] is True
    assert 'different parameters' in response['result']['content'][0]['text']
    assert len(calls) == 1


def test_uncertain_admission_cannot_be_replayed(tmp_path):
    journal = RequestJournal(tmp_path / 'journal.db')
    assert journal.reserve('a', 'payload-1') is None
    with pytest.raises(ValueError, match='already reserved'):
        RequestJournal(journal.path).reserve('a', 'payload-1')
    with pytest.raises(ValueError, match='different parameters'):
        journal.reserve('a', 'payload-2')


def test_notifications_acknowledged_and_cross_origin_rejected(tmp_path):
    post = endpoint(tmp_path / 'journal.db', lambda _: {})
    request = Request({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    assert asyncio.run(post(request)).status_code == 202
    request.headers = {'authorization': 'Bearer test-token', 'origin': 'https://foreign.invalid'}
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        asyncio.run(post(request))
    assert caught.value.status_code == 403


def test_external_provenance_survives_normalization_and_preserves_context(tmp_path):
    from services.generation_provenance import normalize_submission_provenance
    calls = []
    async def submit(request):
        body = await request.json()
        calls.append(normalize_submission_provenance(body['provenance'], trusted_tool=request.trusted_tool))
        return {'job_id': 'task-a'}
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'generate', 'arguments': {'request_id': 'a', 'params': {'model_type': 'fake', 'prompt': 'literal', 'generation_mode': 'video', 'provenance': {'workspace_id': 'collection-a', 'project_id': 'project-a', 'command': {'run_id': 'run-a', 'job_id': 'spoof'}}}}}}
    asyncio.run(endpoint(tmp_path / 'journal.db', submit)(Request(message)))
    assert calls == [{'actor': 'user', 'tool': 'external_agent', 'capability': 'generate', 'workspace_id': 'collection-a', 'project_id': 'project-a', 'command': {'command_id': 'a', 'run_id': 'run-a'}}]
    assert normalize_submission_provenance({'tool': 'external_agent'})['tool'] == 'studio'


@pytest.mark.parametrize('path', ('/api/v1/mcp', '/api/v1/wangp/mcp'))
def test_mcp_is_reachable_before_spa_mount(tmp_path, path):
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(create_wangp_mcp_router(handlers={}, journal_path=tmp_path / 'requests.db', token_getter=lambda: 'test-token'))
    app.mount('/', StaticFiles(directory=tmp_path), name='spa')
    with TestClient(app) as client:
        response = client.post(path, headers={'Authorization': 'Bearer test-token'}, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'})
        assert response.status_code == 200
        assert response.json()['result']['protocolVersion'] == '2025-03-26'
        assert response.json()['result']['serverInfo']['name'] == 'hocuspocus'
        stream = client.get(path)
        assert stream.status_code == 405
        assert stream.headers['allow'] == 'POST'


def test_canonical_and_legacy_urls_share_tools_and_request_journal(tmp_path):
    from fastapi.testclient import TestClient

    calls = []

    async def submit(request):
        calls.append(await request.json())
        return {'job_id': 'task-a'}

    headers = {'Authorization': 'Bearer test-token'}
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'generate', 'arguments': {'request_id': 'same-intent', 'params': {
            'model_type': 'fake', 'prompt': 'literal', 'generation_mode': 'image',
        }},
    }}
    with TestClient(http_app(tmp_path / 'journal.db', submit)) as client:
        replies, catalogs = [], []
        for path in ('/api/v1/wangp/mcp', '/api/v1/mcp'):
            listed = client.post(path, headers=headers, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
            assert listed.status_code == 200
            catalogs.append(listed.json()['result'])
            reply = client.post(path, headers=headers, json=message)
            assert reply.status_code == 200
            replies.append(reply.json()['result'])
            denied = client.post(path, headers={**headers, 'Origin': 'https://foreign.invalid'}, json=message)
            assert denied.status_code == 403
        assert catalogs[0] == catalogs[1]
        assert replies[0] == replies[1]
        assert not replies[0]['isError']
        assert json.loads(replies[0]['content'][0]['text']) == {'job_id': 'task-a'}
        assert len(calls) == 1

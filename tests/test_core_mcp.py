"""Core MCP must match the shared transport and canonical catalog contract."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.assets import create_assets_router
from routers.core_mcp import create_core_mcp_router
from routers.wangp_mcp import tool_definitions
from services.mcp_access import McpAccess


@pytest.fixture
def client(tmp_path):
    for folder in ('sample', 'other', 'uploads'):
        (tmp_path / folder).mkdir()
    for folder, name in [('sample', 'one.png'), ('sample', 'two.mp4'), ('other', 'one.png')]:
        (tmp_path / folder / name).write_bytes(b'isolated catalog fixture')
    app = FastAPI()
    app.include_router(create_assets_router(
        list_workspaces=lambda: [{'name': 'sample'}, {'name': 'other'}],
        workspace_dir=lambda name: str(tmp_path / name), uploads_dir=lambda: str(tmp_path / 'uploads'),
    ))
    @app.get('/api/v1/workspace-collections')
    async def collections():
        return {'collections': [{'workspace_id': 'collection-id', 'revision': 2}]}
    app.include_router(create_core_mcp_router(McpAccess(tmp_path / 'private.json', env_token=lambda: 'isolated-test-token')))
    with TestClient(app, headers={'Authorization': 'Bearer isolated-test-token'}) as test_client:
        yield test_client


def rpc(client, method, params=None, endpoint='/api/v1/mcp'):
    body = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        body['params'] = params
    return client.post(endpoint, json=body)


def test_only_callable_legacy_tools_are_published():
    assert [tool['name'] for tool in tool_definitions({'assets'}, [])] == ['assets']
    assert tool_definitions(set(), []) == []


def test_all_advertised_core_tools_are_callable(client):
    tools = rpc(client, 'tools/list').json()['result']['tools']
    assert {tool['name'] for tool in tools} == {'models', 'processors', 'status', 'assets', 'collections'}
    for tool in tools:
        args = {'job_id': 'known-job'} if tool['name'] == 'status' else {}
        result = rpc(client, 'tools/call', {'name': tool['name'], 'arguments': args}).json()['result']
        assert result['isError'] is False
        assert isinstance(json.loads(result['content'][0]['text']), dict)
    collections = rpc(client, 'tools/call', {'name': 'collections'}).json()['result']
    assert json.loads(collections['content'][0]['text'])['collections'][0]['workspace_id'] == 'collection-id'


@pytest.mark.parametrize('endpoint', ['/api/v1/mcp', '/api/v1/wangp/mcp'])
def test_core_handshake_notifications_batches_and_parse_errors(client, endpoint):
    initialized = rpc(client, 'initialize', endpoint=endpoint).json()['result']
    assert initialized['serverInfo']['name'] == 'hocuspocus-core'
    notification = {'jsonrpc': '2.0', 'method': 'notifications/initialized'}
    response = client.post(endpoint, json=notification)
    assert response.status_code == 202 and response.content == b''
    response = client.post(endpoint, json=[notification, {'jsonrpc': '2.0', 'id': 'p', 'method': 'ping'}])
    assert response.json() == [{'jsonrpc': '2.0', 'id': 'p', 'result': {}}]
    assert client.post(endpoint, json=[]).status_code == 400
    assert client.post(endpoint, json=[notification] * 33).status_code == 400
    invalid = client.post(endpoint, content='{', headers={'Content-Type': 'application/json'})
    assert invalid.status_code == 400 and invalid.json()['error']['code'] == -32700
    assert client.post(endpoint, json=42).json()['error']['code'] == -32600
    assert client.get(endpoint).status_code == 405


@pytest.mark.parametrize('params', [['bad'], 'bad', {'name': 'assets', 'arguments': ['bad']}, {'name': 'organize'}, {'name': 'analyze'}])
def test_invalid_core_tool_calls_are_errors_without_crashing(client, params):
    response = rpc(client, 'tools/call', params)
    assert response.status_code == 200
    assert response.json()['result']['isError'] is True


def test_core_assets_use_canonical_ids_filters_and_pagination(client):
    arguments = {'workspace': 'sample', 'kind': 'image', 'search': 'one', 'limit': 1, 'offset': 0}
    def assets(args):
        result = rpc(client, 'tools/call', {'name': 'assets', 'arguments': args}).json()['result']
        assert result['isError'] is False
        return json.loads(result['content'][0]['text'])
    first = assets(arguments)
    canonical = client.get('/api/v1/assets', params=arguments).json()
    assert first == canonical
    assert first['total'] == 1 and len(first['assets']) == 1
    assert first['assets'][0]['id']
    assert first['assets'][0]['url'] == '/api/v1/file/one.png?workspace=sample'
    second = assets({**arguments, 'offset': 1})
    assert second['total'] == 1 and second['assets'] == []


@pytest.mark.parametrize('arguments', [{'limit': True}, {'limit': 1.5}, {'offset': -1}, {'limit': 501}, {'kind': []}, {'workspace': 'unknown'}])
def test_invalid_asset_filters_are_explicit_errors(client, arguments):
    result = rpc(client, 'tools/call', {'name': 'assets', 'arguments': arguments}).json()['result']
    assert result['isError'] is True


@pytest.mark.parametrize('body', [
    {'name': 'assets', 'params': {'workspace': 'sample'}},
    {'method': 'assets', 'params': {'workspace': 'sample'}},
    {'params': {'name': 'assets', 'workspace': 'sample'}},
])
def test_legacy_read_envelopes_preserve_workspace(client, body):
    response = client.post('/api/v1/mcp', json=body)
    assert response.status_code == 200
    assert response.json()['total'] == 2
    assert all('workspace=sample' in asset['url'] for asset in response.json()['assets'])


@pytest.mark.parametrize('body', [
    {'name': 'generate', 'params': {}},
    {'method': 'generate', 'params': {}},
    {'params': {'name': 'generate'}},
])
def test_legacy_mutations_keep_capability_denial(client, body, monkeypatch):
    from fastapi import HTTPException
    def deny(capability):
        assert capability == 'wangp_local'
        raise HTTPException(409, {'code': 'feature_unavailable'})
    monkeypatch.setattr('routers.core_mcp.require_capability_http', deny)
    response = client.post('/api/v1/mcp', json=body)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'feature_unavailable'


def test_versioned_tools_precede_legacy_without_changing_schemas():
    operation = {'name': 'commands.example', 'description': 'Example', 'mutation': True,
                 'inputSchema': {'type': 'object', 'properties': {'operation': {'type': 'string'}, 'intent_id': {'type': 'string'}}, 'required': ['operation', 'intent_id']}}
    tools = tool_definitions({'assets', 'commands.example'}, [operation])
    assert [tool['name'] for tool in tools] == ['commands.example', 'assets']
    assert tools[0]['inputSchema']['required'] == ['intent_id']
    assert 'commands.receipt' in tools[0]['description']

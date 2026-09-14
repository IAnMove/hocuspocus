import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.mcp_access import create_mcp_access_router
from routers.wangp_mcp import create_wangp_mcp_router
from services.mcp_access import McpAccess


MCP_ENDPOINTS = ('/api/v1/mcp', '/api/v1/wangp/mcp')


def client_for(tmp_path, environment=lambda: '', profile='full'):
    access = McpAccess(tmp_path / 'private.json', env_token=environment)
    app = FastAPI()
    app.include_router(create_mcp_access_router(access))
    if profile == 'core':
        from routers.core_mcp import create_core_mcp_router
        app.include_router(create_core_mcp_router(access))
    else:
        app.include_router(create_wangp_mcp_router(handlers={}, token_getter=access.token, journal_path=str(tmp_path / 'journal.db')))
    return access, TestClient(app, base_url='http://127.0.0.1:8080')


@pytest.mark.parametrize('endpoint', MCP_ENDPOINTS)
@pytest.mark.parametrize('profile', ('full', 'core'))
def test_toggle_token_rotation_revocation_and_private_storage(tmp_path, endpoint, profile):
    access, client = client_for(tmp_path, profile=profile)
    headers = {'Origin': 'http://127.0.0.1:8080'}
    status = client.get('/api/v1/settings/mcp').json()
    assert not status['enabled']
    assert status['endpoint'] == '/api/v1/mcp'
    created = client.put('/api/v1/settings/mcp', json={'enabled': True}, headers=headers)
    assert created.status_code == 200
    token = created.json()['token']
    assert len(token) >= 40
    assert 'token' not in client.get('/api/v1/settings/mcp').json()
    assert created.headers['cache-control'] == 'no-store'
    if os.name != 'nt':
        assert access.path.stat().st_mode & 0o777 == 0o600
    def ping(key):
        return client.post(endpoint, headers={'Authorization': 'Bearer ' + key}, json={'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})
    assert ping(token).status_code == 200
    assert McpAccess(access.path, env_token=lambda: '').token() == token
    replacement = client.put('/api/v1/settings/mcp', json={'enabled': True, 'rotate': True}, headers=headers).json()['token']
    assert ping(token).status_code == 401
    assert ping(replacement).status_code == 200
    client.put('/api/v1/settings/mcp', json={'enabled': False}, headers=headers)
    assert ping(replacement).status_code == 503


def test_cannot_issue_credentials_cross_origin_or_via_rebinding(tmp_path):
    _, client = client_for(tmp_path)
    for headers in ({}, {'Origin': 'https://attacker.example'}, {'Origin': 'http://attacker.example', 'Host': 'attacker.example'}):
        assert client.put('/api/v1/settings/mcp', json={'enabled': True}, headers=headers).status_code == 403


def test_env_precedence_toggle_and_no_environment_secret_disclosure(tmp_path):
    access, client = client_for(tmp_path, lambda: 'existing-env-secret')
    headers = {'Origin': 'http://127.0.0.1:8080'}
    assert access.token() == 'existing-env-secret'
    result = client.put('/api/v1/settings/mcp', json={'enabled': True}, headers=headers)
    assert 'existing-env-secret' not in result.text
    assert client.put('/api/v1/settings/mcp', json={'enabled': True, 'rotate': True}, headers=headers).status_code == 409
    assert client.put('/api/v1/settings/mcp', json={'enabled': False}, headers=headers).status_code == 200
    assert not access.token()


@pytest.mark.parametrize('endpoint', MCP_ENDPOINTS)
def test_shared_lan_mcp_uses_its_own_token_without_unlocking_other_apis(tmp_path, monkeypatch, endpoint):
    from services.lan_auth import LanAuthMiddleware
    monkeypatch.setenv('PINOKIO_SHARE_LOCAL', 'true')
    monkeypatch.setenv('LOREFRAME_LAN_AUTH', 'true')
    monkeypatch.setenv('LOREFRAME_LAN_TOKEN', 'a-separate-lan-token-of-at-least-24-characters')
    access = McpAccess(tmp_path / 'access.json', env_token=lambda: '')
    token = access.update(True)['token']
    app = FastAPI()
    app.add_middleware(LanAuthMiddleware)
    app.include_router(create_mcp_access_router(access))
    app.include_router(create_wangp_mcp_router(handlers={}, token_getter=access.token, journal_path=str(tmp_path / 'journal.db')))
    client = TestClient(app, base_url='http://192.168.1.87:8080')
    message = {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}
    assert client.post(endpoint, json=message).status_code == 401
    assert client.post(endpoint, json=message, headers={'Authorization': 'Bearer ' + token}).status_code == 200
    assert client.get('/api/v1/settings/mcp', headers={'Authorization': 'Bearer ' + token}).status_code == 401
    access.update(False)
    assert client.post(endpoint, json=message, headers={'Authorization': 'Bearer ' + token}).status_code == 503

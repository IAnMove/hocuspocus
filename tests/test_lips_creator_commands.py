"""MCP, Wizard HTTP and the editor use the same workspace mouth library."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from routers.lips_creator import create_lips_creator_router
from routers.wangp_mcp import create_wangp_mcp_router
from services.character_kit_library import patch_character_kit, read_character_kit_library, LIPS_CREATOR_LIBRARY_FILENAME
from services.lips_creator_commands import command_catalog, command_handlers, execute_command


def client_for(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    app = FastAPI()
    app.include_router(create_lips_creator_router(root), prefix="/api/v1/character-kits")
    app.include_router(create_wangp_mcp_router(handlers=command_handlers(root), command_operations=command_catalog(),
        journal_path=str(tmp_path / "journal.json"), token_getter=lambda: "test-token"))
    return TestClient(app), root


def call(client, name, data, intent=None, *, mcp=False):
    arguments = {"version": 1, "input": {"workspace": "a", **data}, **({"intent_id": intent} if intent else {})}
    if mcp:
        response = client.post('/api/v1/mcp', headers={"Authorization": "Bearer test-token"}, json={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": name, "arguments": arguments}})
        assert response.status_code == 200
        return response.json()["result"]["structuredContent"]
    response = client.post('/api/v1/character-kits/lips-creator/commands', json={"operation": name, **arguments})
    assert response.status_code == 200, response.text
    return response.json()


def test_discover_create_plan_capture_review_map_and_link_over_mcp_and_wizard(tmp_path):
    client, root = client_for(tmp_path)
    tools = client.post('/api/v1/mcp', headers={"Authorization": "Bearer test-token"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
    assert {tool['name'] for tool in tools} == {entry['name'] for entry in command_catalog()}
    create_tool = next(tool for tool in tools if tool['name'] == 'lips.create')
    assert 'inspect lips.receipt' in create_tool['description']
    assert 'commands.receipt' not in create_tool['description']
    assert next(tool for tool in tools if tool['name'] == 'lips.delete')['annotations']['destructiveHint'] is True
    result = call(client, 'lips.create', {"name": "Ruby", "pack_id": "ruby", "description": "Burgundy cartoon lips"}, 'create', mcp=True)
    assert result['result']['library']['revision'] == 1
    plan = call(client, 'lips.generation.plan', {"pack_id": "ruby"}, mcp=True)['result']
    assert len(plan['requests']) == 9
    assert all(item['reference'] is None and 'Burgundy cartoon lips' in item['prompt'] and 'entirely from the description' in item['prompt'] for item in plan['requests'])
    assert read_character_kit_library(root('a'))['kits'] == {}
    assert call(client, 'lips.list', {"workspace": "b"}, mcp=True)['result']['library']['kits'] == {}
    # Capture one mouth, then map every sound to it: this is valid even with fewer drawings.
    asset = {"id": "mouth", "name": "Ruby resting lips", "source": "/api/v1/uploads/ruby.png", "alphaStatus": "transparent", "reviewState": "approved"}
    captured = call(client, 'lips.capture', {"pack_id": "ruby", "base_revision": 1, "state": "pressed", "asset": asset}, 'capture')['result']['library']
    assert captured['kits']['ruby']['mouth'] == {}
    assert captured['kits']['ruby']['mouthCandidates']['pressed']['reviewState'] == 'pending'
    accepted = call(client, 'lips.accept', {"pack_id": "ruby", "base_revision": 2, "states": ['pressed']}, 'approve', mcp=True)['result']['library']
    assert accepted['kits']['ruby']['mouth']['pressed']['reviewState'] == 'approved'
    mapping = {sound: 'pressed' for sound in ['rest', 'M', 'A', 'E', 'I', 'O', 'U', 'F', 'L']}
    call(client, 'lips.update', {"pack_id": "ruby", "base_revision": 3, "changes": {"mouthMapping": mapping}}, 'map')
    character = {"version": 1, "id": "actor", "name": "Actor", "style": "cutout", "base": {**asset, "id": "base", "name": "Actor", "source": '/api/v1/uploads/actor.png', "kind": "image"},
                 "poses": {}, "mouth": {}, "eyes": {}, "anchors": {"base": {"mouth": {"offsetX": 8, "offsetY": -20, "scale": .12, "rotation": 0}}}, "provenance": [{"method": "original"}]}
    original = patch_character_kit(root('a'), 'actor', character, base_revision=0)['kits']['actor']
    linked = call(client, 'lips.apply', {"pack_id": "ruby", "character_id": "actor", "base_revision": 1}, 'link', mcp=True)['result']['library']['kits']['actor']
    for key in ['base', 'name', 'style', 'anchors']:
        assert linked[key] == original[key]
    assert linked['mouthMapping'] == mapping
    assert linked['mouth']['pressed']['source'] == asset['source']
    receipt = call(client, 'lips.receipt', {"operation": 'lips.apply', "intent_id": 'link'}, mcp=True)
    assert receipt['result']['character_id'] == 'actor'


def test_transport_retry_and_concurrent_create_are_one_effect_even_after_restart(tmp_path):
    client, root = client_for(tmp_path)
    args = {"version": 1, "intent_id": "same", "input": {"workspace": "a", "pack_id": "ruby", "name": "Ruby"}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: execute_command('lips.create', deepcopy(args), root), range(2)))
    assert sorted(reply.get('replayed', False) for reply in replies) == [False, True]
    assert read_character_kit_library(root('a'), library_filename=LIPS_CREATOR_LIBRARY_FILENAME)['revision'] == 1
    restarted, _ = client_for(tmp_path)
    assert call(restarted, 'lips.create', {"pack_id": 'ruby', "name": 'Ruby'}, 'same', mcp=True)['replayed'] is True
    conflict = call(restarted, 'lips.create', {"pack_id": 'ruby', "name": 'Different'}, 'same', mcp=True)
    assert conflict['status'] == 'failed'


def test_regeneration_preserves_approved_mouth_and_stale_revision_or_opaque_accept_fails(tmp_path):
    client, root = client_for(tmp_path)
    call(client, 'lips.create', {"name": "Ruby", "pack_id": "ruby"}, 'create')
    asset = {"id": "mouth", "name": "Ruby", "source": "/api/v1/uploads/ruby.png", "alphaStatus": "transparent"}
    call(client, 'lips.capture', {"pack_id": "ruby", "base_revision": 1, "state": 'wide', "asset": asset}, 'capture')
    call(client, 'lips.accept', {"pack_id": "ruby", "base_revision": 2, "states": ['wide']}, 'accept')
    plan = call(client, 'lips.generation.plan', {"pack_id": 'ruby', "states": ['wide']}, mcp=True)['result']
    assert [request['state'] for request in plan['requests']] == ['wide']
    next_asset = {**asset, "source": '/api/v1/uploads/new.png', "alphaStatus": 'opaque'}
    captured = call(client, 'lips.capture', {"pack_id": "ruby", "base_revision": 3, "state": 'wide', "asset": next_asset}, 'regenerate')['result']['library']
    assert captured['kits']['ruby']['mouth']['wide']['source'] == asset['source']
    failed = call(client, 'lips.accept', {"pack_id": "ruby", "base_revision": 4, "states": ['wide']}, 'opaque', mcp=True)
    assert failed['status'] == 'failed' and 'background' in failed['error']['message']
    stale = call(client, 'lips.update', {"pack_id": "ruby", "base_revision": 1, "changes": {"name": 'Wrong'}}, 'stale', mcp=True)
    assert stale['status'] == 'failed'
    assert read_character_kit_library(root('a'), library_filename=LIPS_CREATOR_LIBRARY_FILENAME)['revision'] == 4


@pytest.mark.parametrize('arguments', [
    {'version': True, 'input': {'workspace': 'a'}}, {'version': 1, 'input': {'workspace': '../a'}},
    {'version': 1, 'input': {'workspace': 'a', 'surprise': True}}, {'version': 1, 'input': {}},
])
def test_bad_read_inputs_fail_without_creating_workspace(tmp_path, arguments):
    client, _ = client_for(tmp_path)
    response = client.post('/api/v1/character-kits/lips-creator/commands', json={"operation": 'lips.list', **arguments})
    assert response.status_code == 422
    assert not (tmp_path / 'a').exists()

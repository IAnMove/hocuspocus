import base64
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.scene_commands import create_scene_commands_router
from services.scene_commands import SceneCommands
from services.scene_library import save_world3d


def document():
    return SceneCommands(None).execute({'version': 1, 'operation': 'scenes.effects.showcase',
                                      'input': {'dimension': '3d', 'collection': 'anime'}})['result']['document']


def payload():
    return {'workspace': 'my-film', 'document': document(), 'name': '../My shot',
            'preview': 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\npreview').decode()}


def test_saved_scene_roundtrip_has_workspace_identity_and_immutable_revisions(tmp_path):
    body = payload()
    first = save_world3d(body, lambda workspace: tmp_path / workspace)
    second = save_world3d(body, lambda workspace: tmp_path / workspace)
    assert first['name'] != second['name']
    assert first['name'].endswith('.world3d.scene.json')
    assert first['url'].endswith('?workspace=my-film')
    assert first['thumbnail_url'].endswith('?workspace=my-film')
    assert json.loads((tmp_path / 'my-film' / first['name']).read_text()) == body['document']
    assert len(list((tmp_path / 'my-film').iterdir())) == 4


@pytest.mark.parametrize('patch', [{'workspace': '../elsewhere'}, {'workspace': ''}, {'preview': 'data:image/png;base64,bad'}, {'document': {'version': 1}}])
def test_invalid_saves_leave_no_outputs(tmp_path, patch):
    with pytest.raises(ValueError):
        save_world3d({**payload(), **patch}, lambda workspace: tmp_path / workspace)
    assert not list(tmp_path.iterdir())


def test_reject_transient_assets_and_wrong_document_kind(tmp_path):
    body = payload()
    body['document']['slots'][0]['sourceUrl'] = 'blob:temporary-browser-model'
    with pytest.raises(ValueError, match='Upload'):
        save_world3d(body, lambda workspace: tmp_path / workspace)
    body['document']['slots'][0]['sourceUrl'] = ''
    body['document']['worldSfx'] = [{
        'id': 'tv', 'kind': 'media_portal', 'start': 0, 'end': 2,
        'sourceUrl': 'blob:http://localhost/portal',
    }]
    with pytest.raises(ValueError, match='Upload'):
        save_world3d(body, lambda workspace: tmp_path / workspace)
    body['document'].pop('slots')
    body['document']['layers'] = []
    with pytest.raises(ValueError, match='Video3D'):
        save_world3d(body, lambda workspace: tmp_path / workspace)


def test_portal_media_with_uploaded_url_can_be_saved(tmp_path):
    body = payload()
    body['document']['worldSfx'] = [{
        'id': 'tv', 'kind': 'media_portal', 'start': 0, 'end': 2,
        'position': {'x': 0, 'y': 1.15, 'z': 0}, 'rotation': {'x': 0, 'y': 0, 'z': 0},
        'scale': 1.7, 'intensity': 1, 'color': '#3da5ff', 'seed': 1, 'sound': False, 'volume': 0.25,
        'sourceUrl': '/api/v1/uploads/portal.png',
    }]
    saved = save_world3d(body, lambda workspace: tmp_path / workspace)
    stored = json.loads((tmp_path / 'my-film' / saved['name']).read_text())
    assert stored['worldSfx'][0]['sourceUrl'] == '/api/v1/uploads/portal.png'


def test_apply_strips_blob_portal_so_the_scene_can_be_saved(tmp_path):
    service = SceneCommands(lambda workspace: tmp_path / workspace)
    doc = document()
    prepared = service.execute({
        'version': 1, 'operation': 'scenes.effects.apply',
        'input': {'document': doc, 'worldCues': [{
            'id': 'tv', 'kind': 'media_portal', 'start': 0, 'end': 2,
            'sourceUrl': 'blob:http://localhost/portal',
        }]},
    })['result']['document']
    assert not prepared['worldSfx'][0].get('sourceUrl')
    saved = save_world3d({**payload(), 'document': prepared}, lambda workspace: tmp_path / workspace)
    stored = json.loads((tmp_path / 'my-film' / saved['name']).read_text())
    assert stored['worldSfx'][0]['kind'] == 'media_portal'
    assert 'blob:' not in json.dumps(stored)


def test_native_route_does_not_require_or_overwrite_legacy_layers(tmp_path):
    app = FastAPI()
    app.include_router(create_scene_commands_router(SceneCommands(lambda workspace: tmp_path / workspace)))
    client = TestClient(app)
    assert client.post('/api/v1/scenes/world3d', json=payload()).status_code == 200
    assert client.post('/api/v1/scenes/world3d', json=[]).status_code == 422

import copy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.scene_commands import create_scene_commands_router
from routers.wangp_mcp import create_wangp_mcp_router
from services.scene_commands import CATALOG, PRESETS, SceneCommands, command_catalog


@pytest.fixture
def service(tmp_path):
    return SceneCommands(lambda workspace: tmp_path / workspace)


def showcase(service, dimension='3d'):
    return service.execute({'version': 1, 'operation': 'scenes.effects.showcase', 'input': {'dimension': dimension}})['result']['document']


def test_both_templates_use_all_catalog_effects_and_are_replayable(service):
    for dimension in ('2d', '3d'):
        doc = showcase(service, dimension)
        assert doc['duration'] == 168
        assert len(doc['sfx']) == 56
        assert all(cue['sound'] and cue['label'] for cue in doc['sfx'])
        assert doc == showcase(service, dimension)
        assert ('slots' in doc) == (dimension == '3d')


def test_apply_replaces_exact_cue_preserving_scene_and_caller(service):
    original = showcase(service)
    before = copy.deepcopy(original)
    cue = {**original['sfx'][3], 'color': '#123456'}
    command = {'version': 1, 'operation': 'scenes.effects.apply', 'input': {'document': original, 'cues': [cue]}}
    first = service.execute(command)
    assert original == before
    assert first == service.execute(command)
    actual = first['result']['document']
    assert len(actual['sfx']) == 56
    assert actual['sfx'][3] == cue
    assert actual['slots'] == original['slots']
    assert not first['result']['saved'] and not first['result']['exported']


@pytest.mark.parametrize('patch', [{'kind': 'invented'}, {'end': 0}, {'start': float('nan')}, {'seed': True}, {'sound': 'yes'}, {'volume': 2}])
def test_reject_invalid_effects_before_changing_document(service, patch):
    original = showcase(service)
    cue = {**original['sfx'][0], **patch}
    with pytest.raises(ValueError):
        service.execute({'version': 1, 'operation': 'scenes.effects.apply', 'input': {'document': original, 'cues': [cue]}})


def test_http_and_mcp_return_identical_documents_without_browser(service, tmp_path):
    app = FastAPI()
    app.include_router(create_scene_commands_router(service))
    app.include_router(create_wangp_mcp_router(handlers=service.handlers(), token_getter=lambda: 'test-token',
                                             journal_path=str(tmp_path / 'journal.db'), command_operations=command_catalog()))
    client = TestClient(app)
    command = {'version': 1, 'operation': 'scenes.effects.showcase', 'input': {'dimension': '2d'}}
    http = client.post('/api/v1/scenes/commands', json=command)
    assert http.status_code == 200
    mcp = client.post('/api/v1/wangp/mcp', headers={'Authorization': 'Bearer test-token'}, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': command['operation'], 'arguments': {'version': 1, 'input': command['input']}}})
    assert mcp.status_code == 200
    assert not mcp.json()['result']['isError']
    assert mcp.json()['result']['structuredContent'] == http.json()
    schema = client.get('/api/v1/scenes/commands').json()
    assert len(schema['operations']) == 5


def test_world_cues_upsert_on_video3d_and_reject_2d(service):
    world = showcase(service, '3d')
    cue = {'id': 'portal-1', 'kind': 'portal', 'start': 0, 'end': 2, 'position': {'x': 0, 'y': 1, 'z': -1}, 'sound': True}
    first = service.execute({'version': 1, 'operation': 'scenes.effects.apply', 'input': {'document': world, 'worldCues': [cue]}})
    assert first['result']['document']['worldSfx'][0]['kind'] == 'portal'
    assert first['result']['document']['sfx'] == world['sfx']
    assert first == service.execute({'version': 1, 'operation': 'scenes.effects.apply', 'input': {'document': world, 'worldCues': [cue]}})
    catalog = service.execute({'version': 1, 'operation': 'scenes.effects.catalog', 'input': {}})['result']
    assert catalog['coordinates']['world'] == 'meters'
    assert 'portal' in catalog['worldKinds']
    assert 'energy_beam' in catalog['worldKinds']
    beam = {'id': 'beam-1', 'kind': 'energy_beam', 'start': 0, 'end': 2, 'anchor': {'slotId': 'subject_1'}, 'target': {'slotId': 'subject_2'}}
    beamed = service.execute({'version': 1, 'operation': 'scenes.effects.apply', 'input': {'document': world, 'worldCues': [beam]}})['result']['document']
    assert beamed['worldSfx'][0]['target']['slotId'] == 'subject_2'
    flat = showcase(service, '2d')
    with pytest.raises(ValueError, match='Video3D'):
        service.execute({'version': 1, 'operation': 'scenes.effects.apply', 'input': {'document': flat, 'worldCues': [cue]}})


def test_replace_one_sfx_track_preserves_the_other(service):
    world = showcase(service, '3d')
    portal = {'id': 'portal-1', 'kind': 'portal', 'start': 0, 'end': 2, 'position': {'x': 0, 'y': 1, 'z': -1},
              'rotation': {'x': 0, 'y': 90, 'z': 0}}
    with_portal = service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                                   'input': {'document': world, 'worldCues': [portal]}})['result']['document']
    assert with_portal['worldSfx'][0]['rotation']['y'] == 90
    spark = {'id': 'spark-1', 'kind': 'sparks', 'start': 0, 'end': 2}
    screen_only = service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                                   'input': {'document': with_portal, 'cues': [spark], 'replace': True}})['result']['document']
    assert [cue['id'] for cue in screen_only['sfx']] == ['spark-1']
    assert screen_only['worldSfx'][0]['kind'] == 'portal'
    assert screen_only['worldSfx'][0]['rotation']['y'] == 90
    circle = {'id': 'circle-1', 'kind': 'magic_circle', 'start': 0, 'end': 2}
    world_only = service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                                  'input': {'document': screen_only, 'worldCues': [circle], 'replace': True}})['result']['document']
    assert [cue['id'] for cue in world_only['sfx']] == ['spark-1']
    assert [cue['id'] for cue in world_only['worldSfx']] == ['circle-1']


def test_catalog_lists_all_world_kinds(service):
    ops = {item['name']: item for item in command_catalog()}
    assert 'worldKinds' in ops['scenes.effects.catalog']['description']
    assert 'energy_beam' in ops['scenes.effects.catalog']['description']
    assert 'explosion' in ops['scenes.effects.catalog']['description']
    assert 'media_portal' in ops['scenes.effects.catalog']['description']
    kinds = service.execute({'version': 1, 'operation': 'scenes.effects.catalog', 'input': {}})['result']['worldKinds']
    assert 'energy_beam' in kinds
    assert 'anime_aura' in kinds
    assert 'explosion' in kinds
    assert 'media_portal' in kinds
    assert 'fire' in kinds


def test_speech_rejects_paths_and_unknown_character_before_analysis(service):
    doc = showcase(service)
    doc['slots'][0]['sourceUrl'] = '/api/v1/file/actor.glb?workspace=default'
    data = {'document': doc, 'slot_id': 'subject_1', 'clip_id': 'hello', 'workspace': 'default',
            'audio_filename': '../../secret.wav', 'text': 'Hello, literally.', 'start': 0, 'end': 2}
    with pytest.raises(ValueError, match='filename'):
        service.execute({'version': 1, 'operation': 'scenes.speech.prepare', 'input': data})
    data['slot_id'] = 'missing'
    with pytest.raises(ValueError, match='exact 3D'):
        service.execute({'version': 1, 'operation': 'scenes.speech.prepare', 'input': data})


def test_shared_catalog_remains_a_packaged_resource():
    path = Path(__file__).parents[1] / 'app/shared/scene_effects.json'
    assert len(json.loads(path.read_text())) == 56


def test_code_rain_takes_its_own_default_size_and_keeps_a_given_one(service):
    original = showcase(service)
    rain = next(cue for cue in original['sfx'] if cue['kind'] == 'code_rain')
    assert rain['size'] == 3 and rain['color'] == '#39ff6a', 'the showcase uses the glyph height, not a burst size'
    assert all(cue['size'] == 95 for cue in original['sfx'] if 'size' not in PRESETS[cue['kind']])
    cues = [{'id': 'rain', 'kind': 'code_rain', 'start': 0, 'end': 6}, {'id': 'big', 'kind': 'code_rain', 'start': 0, 'end': 6, 'size': 8},
            {'id': 'burst', 'kind': 'sparks', 'start': 0, 'end': 1}]
    applied = service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                               'input': {'document': original, 'cues': cues, 'replace': True}})['result']['document']
    sizes = {cue['id']: cue['size'] for cue in applied['sfx']}
    assert (sizes['rain'], sizes['big'], sizes['burst']) == (3, 8, 65)


def test_cinematic_effects_take_their_catalog_size_and_placement_and_keep_given_ones(service):
    pack = [item['id'] for item in CATALOG if item['collection'] == 'cinematic']
    assert pack == ['candlelight', 'vignette', 'film_grain', 'light_rays', 'glitch', 'canvas']
    showcase_cues = {cue['kind']: cue for cue in showcase(service)['sfx']}
    assert {kind: showcase_cues[kind]['size'] for kind in pack} == {'candlelight': 45, 'vignette': 60, 'film_grain': 100,
                                                                    'light_rays': 120, 'glitch': 6, 'canvas': 100}
    rays = showcase_cues['light_rays']
    assert (rays['x'], rays['y'], rays['rotation'], rays['color']) == (28, 0, 62, '#ffd27a')
    cues = [{'id': 'rays', 'kind': 'light_rays', 'start': 0, 'end': 6},
            {'id': 'aimed', 'kind': 'light_rays', 'start': 0, 'end': 6, 'x': 80, 'y': 5, 'rotation': 120, 'size': 90},
            {'id': 'candle', 'kind': 'candlelight', 'start': 0, 'end': 6, 'x': 30, 'y': 40},
            {'id': 'edges', 'kind': 'vignette', 'start': 0, 'end': 6, 'intensity': 1.4}]
    applied = service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                               'input': {'document': showcase(service), 'cues': cues, 'replace': True}})['result']['document']
    placed = {cue['id']: (cue['x'], cue['y'], cue['size'], cue['rotation'], cue['intensity'], cue['color']) for cue in applied['sfx']}
    assert placed == {'rays': (28, 0, 120, 62, 1, '#ffd27a'), 'aimed': (80, 5, 90, 120, 1, '#ffd27a'),
                      'candle': (30, 40, 45, 0, 1, '#ffb35c'), 'edges': (50, 50, 60, 0, 1.4, '#000000')}


def test_speech_append_preserves_previous_voice_and_rejects_overlap():
    from services.scene_speech_command import with_speech_clip
    original = {'audio': {'filename': 'first.wav'}, 'cues': [], 'start': 0, 'end': 2, 'offset': 0, 'gain': 1}
    clip = {'id': 'second', 'start': 3, 'end': 5}
    updated = with_speech_clip(original, clip, 6)
    assert updated['clips'][0]['audio'] == original['audio']
    assert len(with_speech_clip(updated, clip, 6)['clips']) == 2
    with pytest.raises(ValueError, match='overlap'):
        with_speech_clip(original, {**clip, 'start': 1}, 6)
    assert 'clips' not in original


def test_retro_showcase_is_screen_only_and_thirty_seconds(service):
    scene = service.execute({'version': 1, 'operation': 'scenes.effects.showcase',
                             'input': {'collection': 'retro', 'dimension': '2d'}})['result']['document']
    assert scene['duration'] == 30 and len(scene['sfx']) == 10
    assert [cue['kind'] for cue in scene['sfx']] == [
        'psx', 'n64', 'nes', 'snes', 'gameboy', 'gameboy_color', 'genesis', 'vhs', 'crt', 'c64']
    catalog = service.execute({'version': 1, 'operation': 'scenes.effects.catalog', 'input': {}})['result']
    assert 'psx' not in catalog['worldKinds']
    assert any(item['id'] == 'psx' for item in catalog['effects'])


def test_anime_showcase_uses_42_seconds_and_preserves_longer_authored_scenes(service):
    command = {'version': 1, 'operation': 'scenes.effects.showcase', 'input': {'collection': 'anime'}}
    scene = service.execute(command)['result']['document']
    assert scene['duration'] == 42 and len(scene['sfx']) == 14
    scene['duration'] = 72
    command['input']['document'] = scene
    assert service.execute(command)['result']['document']['duration'] == 72


@pytest.mark.parametrize('collection,seconds', [('anime', 42), ('retro', 30), ('all', 168)])
def test_default_2d_showcase_has_no_longer_background_tail(service, collection, seconds):
    scene = service.execute({'version': 1, 'operation': 'scenes.effects.showcase',
                             'input': {'dimension': '2d', 'collection': collection}})['result']['document']
    assert scene['duration'] == seconds
    assert scene['layers'][0]['animation']['duration'] == seconds
    scene['layers'][0]['animation']['duration'] = 120
    preserved = service.execute({'version': 1, 'operation': 'scenes.effects.showcase',
                                 'input': {'document': scene, 'collection': collection}})['result']['document']
    assert preserved['layers'] == scene['layers']


@pytest.mark.parametrize('kind', ['smoke', 'sparks'])
def test_soft_spatial_effects_roundtrip_through_commands(service, kind):
    doc = showcase(service)
    doc['environment'] = {'reflectiveFloor': True, 'platform': True, 'bloom': .48}
    doc['slots'][0]['appearance'] = {'start': 1, 'duration': .8, 'color': '#83e8ff'}
    cue = {'id': kind, 'kind': kind, 'start': 0, 'end': 3}
    result = service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                              'input': {'document': doc, 'worldCues': [cue]}})['result']['document']
    assert result['environment'] == doc['environment']
    assert result['slots'][0]['appearance'] == doc['slots'][0]['appearance']
    assert result['worldSfx'][0]['kind'] == kind


def test_additive_world_apply_keeps_explosion_and_portal_media(service):
    doc = showcase(service)
    blast = {'id': 'blast', 'kind': 'explosion', 'start': 1.05, 'end': 3.4,
             'position': {'x': 0, 'y': .42, 'z': -.15}, 'scale': 1.8, 'color': '#ff6a32',
             'intensity': 1.35, 'sound': True, 'volume': .4}
    with_blast = service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                                  'input': {'document': doc, 'worldCues': [blast]}})['result']['document']
    assert with_blast['worldSfx'][0]['kind'] == 'explosion'
    portal = {'id': 'tv', 'kind': 'media_portal', 'start': 0, 'end': 3,
              'sourceUrl': '/examples/tv-head-face.png'}
    both = service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                            'input': {'document': with_blast, 'worldCues': [portal]}})['result']['document']
    kinds = {cue['kind'] for cue in both['worldSfx']}
    assert kinds == {'explosion', 'media_portal'}
    media = next(cue for cue in both['worldSfx'] if cue['kind'] == 'media_portal')
    assert media['sourceUrl'] == '/examples/tv-head-face.png'
    again = service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                             'input': {'document': both, 'worldCues': [
                                 {'id': 'ring', 'kind': 'shockwave', 'start': 1, 'end': 2}]}})
    assert again == service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                                    'input': {'document': both, 'worldCues': [
                                        {'id': 'ring', 'kind': 'shockwave', 'start': 1, 'end': 2}]}})
    assert {cue['kind'] for cue in again['result']['document']['worldSfx']} == {
        'explosion', 'media_portal', 'shockwave'}
    assert next(cue for cue in again['result']['document']['worldSfx']
                if cue['kind'] == 'media_portal')['sourceUrl'] == '/examples/tv-head-face.png'


@pytest.mark.parametrize('url', [
    'JavaScript:alert(1)',
    'blob:http://localhost/abc',
    'file:///tmp/portal.png',
    'filesystem:http://localhost/tmp',
])
def test_world_portal_media_strips_transient_urls(service, url):
    doc = showcase(service)
    cue = {'id': 'tv', 'kind': 'media_portal', 'start': 0, 'end': 2,
           'sourceUrl': url}
    result = service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                              'input': {'document': doc, 'worldCues': [cue]}})['result']['document']
    assert result['worldSfx'][0]['kind'] == 'media_portal'
    assert not result['worldSfx'][0].get('sourceUrl')


def test_a_laser_cue_starts_at_its_origin_and_other_kinds_refuse_one(service):
    doc = showcase(service, '2d')
    laser = {'id': 'shot', 'kind': 'laser', 'start': 0, 'end': 1, 'x': 90, 'y': 20,
             'from': {'x': 95, 'y': 46, 'layerId': 'kit-guard-pose-base'}}
    apply = lambda document, cues: service.execute({'version': 1, 'operation': 'scenes.effects.apply',
                                                    'input': {'document': document, 'cues': cues}})['result']['document']
    applied = apply(doc, [laser])
    assert next(cue for cue in applied['sfx'] if cue['id'] == 'shot')['from'] == {'x': 95.0, 'y': 46.0, 'layerId': 'kit-guard-pose-base'}
    assert all('from' not in cue for cue in applied['sfx'] if cue['id'] != 'shot'), 'no empty from on the other cues'
    again = apply(applied, [{'id': 'bolt', 'kind': 'lightning', 'start': 1, 'end': 2, 'from': {'x': 10, 'y': -20}}])
    kept = {cue['id']: cue.get('from') for cue in again['sfx'] if cue['id'] in ('shot', 'bolt')}
    assert kept == {'shot': {'x': 95.0, 'y': 46.0, 'layerId': 'kit-guard-pose-base'}, 'bolt': {'x': 10.0, 'y': -20.0}}, 'an additive apply keeps it'
    for bad in ({'id': 'x', 'kind': 'sparks', 'start': 0, 'end': 1, 'from': {'x': 10, 'y': 20}},
                {'id': 'x', 'kind': 'laser', 'start': 0, 'end': 1, 'from': {'x': 10, 'y': 900}}):
        with pytest.raises(ValueError):
            apply(doc, [bad])
    schema = next(item for item in command_catalog() if item['name'] == 'scenes.effects.apply')['inputSchema']
    assert 'from' in json.dumps(schema)

"""A stage-* id opens the mold staged on two-shot, as the editor stages it, everywhere a template id is taken."""
import copy
from pathlib import Path

import pytest
from fastapi import HTTPException
from services.production_scene3d import compile_document, resolve_media, validate_scene3d_shot
from services.series_shot3d import open_shot_scene
from services.set_molds import resolve_mold
from services.world3d_scenes import compile_template_document, inspect_scene, instantiate_template
from services.world3d_stage_documents import resolve_production_stage, stage, stage_camera, stage_document
from services.world3d_template_commands import execute_command

NODE = pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / 'ui/node_modules').is_dir(), reason='UI compiler dependencies are not installed')
BASE = {'duration': 6, 'slots': [
    {'id': 'subject_1', 'slot': 'subject_1', 'position': [0, 0, 0], 'rotationY': 0, 'media': 'model3d'},
    {'id': 'subject_2', 'slot': 'subject_2', 'position': [1, 0, 0], 'rotationY': 0, 'media': 'model3d'},
    {'id': 'background', 'slot': 'background', 'media': 'image', 'position': [0, 0, -6], 'rotationY': 0},
    {'id': 'poster', 'slot': 'prop', 'media': 'image', 'position': [0, 0, 0], 'rotationY': 0}]}


def _camera(mold, name):
    return next(camera for camera in mold['cameras'] if camera['id'] == name)


@NODE
def test_a_stage_document_is_the_mold_staged_on_two_shot_as_the_editor_stages_it():
    document = compile_template_document('stage-calle')
    room = resolve_production_stage({'template': 'stage-calle'})
    staged = compile_document({'key': 'k', 'scene3d': {**room, 'cast': {'subject_1': '/api/v1/file/a.glb?workspace=t'}}}, 6)
    for key in ('room', 'dressing', 'environment', 'camera', 'light', 'worldSfx'):
        assert document[key] == staged[key], key
    assert document['templateId'] == 'stage-calle' and document['room']['mold']['kind'] == 'exterior' and document['light']['color'] == '#fff4dc'
    mold = resolve_mold('calle')
    assert [slot['slot'] for slot in document['slots']] == ['subject_1', 'subject_2']
    assert document['slots'][0]['position'] == mold['marks'][0]['position'] and document['slots'][1]['rotationY'] == pytest.approx(3.14159, abs=1e-4)
    dust = document['worldSfx'][0]
    assert dust['kind'] == 'dust' and (dust['start'], dust['end']) == (0, document['duration']) and dust['scale'] == 5.33 and dust['intensity'] < 0.5
    again = compile_template_document('stage-calle')
    assert again == document and again is not document


def test_another_camera_or_size_is_honoured_and_a_mold_may_switch_the_ambient_life_off():
    document = stage_document('stage-sala', BASE, size='large', camera='ots_a')
    mold = resolve_mold('sala', 'large')
    assert document['room'] == {'mold': mold, 'skin': mold['defaultSkin'], 'camera': 'ots_a'}
    assert document['camera'] == {'family': 'fixed', 'eye': _camera(mold, 'ots_a')['position'], 'look': _camera(mold, 'ots_a')['lookAt'], 'fov': 50}
    assert document['dressing'] == 'none' and document['environment']['floorStyle'] == 'none'
    assert [slot['id'] for slot in document['slots']] == ['subject_1', 'subject_2', 'poster']
    assert document['slots'][2] == {**BASE['slots'][3], 'surface': 'cutout', 'imageLook': {'grounded': True}}
    assert BASE['slots'][0]['position'] == [0, 0, 0], 'the base document is left alone'
    kept = stage_document('stage-sala', {**BASE, 'worldSfx': [{'id': 'rain', 'kind': 'rain', 'start': 0, 'end': 6}]})
    assert [cue['id'] for cue in kept['worldSfx']] == ['rain', 'room-dust']
    quiet = stage(copy.deepcopy(BASE), {'mold': {**resolve_mold('sala'), 'ambient': False}, 'skin': {}, 'camera': 'two_shot'})
    assert 'worldSfx' not in quiet and quiet['light']['color'] == '#fff6e5'
    with pytest.raises(ValueError, match='unknown room camera'):
        stage_document('stage-sala', BASE, camera='drone')
    with pytest.raises(ValueError, match='unknown size'):
        stage_document('stage-sala', BASE, size='huge')
    with pytest.raises(ValueError, match='unknown mold'):
        stage_document('stage-nowhere', BASE)


@NODE
def test_get_instantiate_and_apply_query_take_a_stage_id(tmp_path):
    workspace_dir = lambda name: str(tmp_path / name)
    got = execute_command('world3d.templates.get', {'version': 1, 'input': {'workspace': 'studio', 'template_id': 'stage-plaza'}}, workspace_dir)
    assert got['result']['card']['id'] == 'stage-plaza' and got['result']['document']['templateId'] == 'stage-plaza'
    assert [item['id'] for item in got['result']['objects']] == ['subject_1', 'subject_2']
    scene = instantiate_template('studio', 'stage-sala', workspace_dir)
    assert scene['templateId'] == 'stage-sala' and scene['traits']['worldSfx'] == ['dust'] and scene['document']['room']['mold']['id'] == 'sala'
    assert inspect_scene('studio', scene['sceneId'], workspace_dir)['document']['camera']['family'] == 'fixed'
    applied = execute_command('world3d.scene.apply_query', {'version': 1, 'intent_id': 'stage-query',
                              'input': {'workspace': 'studio', 'query': 'azotea'}}, workspace_dir)
    assert applied['result']['chosenId'] == 'stage-azotea' and applied['result']['scene']['document']['room']['mold']['kind'] == 'exterior'
    with pytest.raises(HTTPException) as refused:
        execute_command('world3d.templates.get', {'version': 1, 'input': {'workspace': 'studio', 'template_id': 'stage-nowhere'}}, workspace_dir)
    assert refused.value.status_code == 404


def test_the_production_spec_takes_a_stage_id_and_resolves_it_before_the_browser(tmp_path):
    shot = {'key': 'k', 'kind': 'scene3d', 't0': 0,
            'scene3d': {'template': 'stage-plaza', 'roomCamera': 'ots_a', 'size': 'large', 'cast': {'subject_1': 'hero.glb'}}}
    validate_scene3d_shot(shot)
    validate_scene3d_shot({**shot, 'scene3d': {'template': 'stage-sala'}})
    for bad in ({'template': 'stage-nowhere'}, {'template': 'stage-sala', 'roomCamera': 'drone'}, {'template': 'stage-sala', 'size': 'huge'}):
        with pytest.raises(ValueError):
            validate_scene3d_shot({**shot, 'scene3d': bad})
    (tmp_path / 'hero.glb').write_bytes(b'glTF')
    resolved = resolve_media(shot['scene3d'], stills={}, root=tmp_path, workspace='w')
    mold = resolve_mold('plaza', 'large')
    assert resolved['template'] == 'two-shot' and resolved['roomCamera'] == 'ots_a' and 'size' not in resolved
    assert resolved['background'] == {'room': {'mold': mold, 'skin': mold['defaultSkin'], 'camera': 'ots_a'}}
    assert resolved['cast']['subject_1']['source'] == '/api/v1/file/hero.glb?workspace=w'
    assert shot['scene3d']['template'] == 'stage-plaza', 'the spec is left alone'
    painted = {'wall_back': {'image': {'asset': '/api/v1/file/w.png?workspace=w'}}}
    sets = {'office': {'room': {'mold': resolve_mold('despacho'), 'skin': painted, 'camera': 'close_1'}, 'objects': []}}
    skinned = resolve_media({'template': 'stage-despacho', 'background': 'office', 'cast': {'subject_1': 'hero.glb'}}, stills={}, root=tmp_path,
                            workspace='w', sets=sets)
    assert skinned['template'] == 'two-shot' and skinned['background']['room']['skin'] == painted and 'roomCamera' not in skinned
    assert skinned['background']['room']['camera'] == 'close_1', 'a sets room keeps its skin and its camera'


@NODE
def test_the_node_compiler_stages_a_stage_id_with_its_camera_and_dust():
    document = compile_document({'key': 'k', 'scene3d': {'template': 'stage-azotea', 'roomCamera': 'wide',
                                 'cast': {'subject_1': '/api/v1/file/a.glb?workspace=t'}}}, 8)
    mold = resolve_mold('azotea')
    assert document['camera']['eye'] == _camera(mold, 'wide')['position'] and document['duration'] == 8
    assert document['room']['mold']['kind'] == 'exterior' and document['light']['color'] == '#9fb4e0'
    assert [cue['kind'] for cue in document['worldSfx']] == ['dust']


@NODE
def test_a_series_3d_shot_opens_its_scene_on_a_stage_id_with_its_camera(tmp_path):
    workspace_dir = lambda name: str(tmp_path / name)
    shot = {'id': 's1', 'productionMethod': 'animation_3d',
            'scene3d': {'template': 'stage-filas', 'roomCamera': 'ots_b', 'cast': [{'characterId': 'ana', 'objectId': 'subject_1'}]}}
    scene = open_shot_scene(lambda name, arguments: execute_command(name, arguments, workspace_dir), 'studio', 'job-s1', shot, 7.5,
                            lambda code, message, status: RuntimeError(f'{code}: {message}'), root=str(tmp_path / 'studio'))
    document = inspect_scene('studio', scene['sceneId'], workspace_dir)['document']
    assert document['templateId'] == 'stage-filas' and document['room']['mold']['id'] == 'filas' and document['duration'] == 7.5
    assert document['worldSfx'][0]['end'] == 7.5, 'the dust is retimed with the shot'
    assert document['camera']['eye'] == _camera(resolve_mold('filas'), 'ots_b')['position']
    assert stage_camera({'template': 'two-shot', 'roomCamera': 'ots_b'}) is None

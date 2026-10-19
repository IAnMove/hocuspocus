"""Shape molds are places without a name; four of them are open to the sky."""
import asyncio

import pytest
from services.set_commands import command_catalog, command_handlers
from services.set_molds import CAMERAS, light_presets, load_mold, resolve_mold, surface_sizes, validate_mold

SHAPES = {'sala', 'sala_ventana', 'mostrador', 'filas', 'pasillo', 'umbral', 'escalera', 'calle', 'plaza', 'orilla', 'escenario_publico',
          'vehiculo', 'azotea'}
EXTERIORS = {'calle', 'plaza', 'orilla', 'azotea'}
FURNITURE = {'escalera': {'step', 'landing'}, 'filas': {'bench'}, 'mostrador': {'counter'}, 'escenario_publico': {'platform', 'audience'},
             'azotea': {'parapet'}, 'vehiculo': {'seat', 'dashboard'}, 'umbral': {'jamb'}}


def test_the_thirteen_shapes_are_titled_in_both_languages_and_lit_for_their_kind():
    for id_ in SHAPES:
        mold = load_mold(id_)
        assert set(mold['title']) == {'es', 'en'} and all(mold['title'].values()), id_
        assert mold['kind'] == ('exterior' if id_ in EXTERIORS else 'interior'), id_
        assert mold['lights'] in light_presets()[mold['kind']], id_
        assert {'speaker_a', 'speaker_b', 'entrance'} <= {mark['id'] for mark in mold['marks']}, id_
        assert {camera['id'] for camera in mold['cameras']} == set(CAMERAS), id_
        assert FURNITURE.get(id_, set()) <= {block['kind'] for block in mold['blocks']}, id_
    assert {mark['pose'] for mark in load_mold('filas')['marks'] if mark['id'].startswith('speaker')} == {'sit'}
    assert {mark['pose'] for mark in load_mold('vehiculo')['marks'] if mark['id'] != 'entrance'} == {'sit'}
    assert {mark['id'] for mark in load_mold('plaza')['marks']} == {'speaker_a', 'speaker_b', 'third', 'fourth', 'entrance'}
    assert light_presets()['exterior'].keys() == {'daylight', 'dusk', 'night_sky'}


def test_exteriors_have_no_ceiling_fewer_walls_and_the_view_on_the_back_wall():
    for id_ in EXTERIORS:
        for size in ('small', 'medium', 'large'):
            mold = resolve_mold(id_, size)
            assert 'ceiling' not in mold['surfaces'] and 'ceiling' not in surface_sizes(mold), (id_, size)
            assert 'back' in mold['walls'] and len(mold['walls']) < 4, id_
            assert 'wall_back' in mold['defaultSkin'], id_
    assert load_mold('calle')['walls'] == ['back', 'left', 'right']
    assert load_mold('plaza')['walls'] == ['back'] == load_mold('orilla')['walls'] == load_mold('azotea')['walls']
    assert 'ceiling' in surface_sizes(resolve_mold('sala'))


def test_eyelines_put_a_left_and_b_right_of_the_two_shot():
    for id_ in SHAPES:
        mold = resolve_mold(id_)
        camera = next(entry for entry in mold['cameras'] if entry['id'] == 'two_shot')
        marks = {mark['id']: mark for mark in mold['marks']}
        eye = camera['position']
        forward = [b - a for a, b in zip(eye, camera['lookAt'])]
        right = [-forward[2], 0, forward[0]]
        across = lambda mark: sum((p - e) * r for p, e, r in zip(mark['position'], eye, right))
        assert across(marks['speaker_a']) < across(marks['speaker_b']), id_
        assert (marks['speaker_a']['facing'], marks['speaker_b']['facing']) == (0, 180), id_


def test_validate_mold_enforces_the_kind_rules():
    calle, sala = load_mold('calle'), load_mold('sala')
    with pytest.raises(ValueError, match='no ceiling'):
        validate_mold({**calle, 'surfaces': [*calle['surfaces'], 'ceiling']})
    without_back = {key: value for key, value in calle['defaultSkin'].items() if key != 'wall_back'}
    with pytest.raises(ValueError, match='back wall'):
        validate_mold({**calle, 'walls': ['left', 'right'], 'surfaces': [s for s in calle['surfaces'] if s != 'wall_back'], 'defaultSkin': without_back})
    with pytest.raises(ValueError, match='exterior lights'):
        validate_mold({**calle, 'lights': 'office_day'})
    with pytest.raises(ValueError, match='interior lights'):
        validate_mold({**sala, 'lights': 'daylight'})
    roofless = {key: value for key, value in sala['defaultSkin'].items() if key != 'ceiling'}
    with pytest.raises(ValueError, match='requires a ceiling'):
        validate_mold({**sala, 'surfaces': [s for s in sala['surfaces'] if s != 'ceiling'], 'defaultSkin': roofless})
    with pytest.raises(ValueError, match='ambient'):
        validate_mold({**sala, 'ambient': 'no'})
    with pytest.raises(ValueError, match='interior or exterior'):
        validate_mold({**sala, 'kind': 'garden'})
    assert validate_mold({**sala, 'ambient': False})['ambient'] is False


def test_the_catalog_lists_kind_and_title_for_every_mold():
    result = asyncio.run(command_handlers()['scene3d.sets.catalog']({'version': 1, 'input': {}}))['result']
    kinds = {mold['id']: mold['kind'] for mold in result['molds']}
    assert kinds['plaza'] == 'exterior' and kinds['sala'] == 'interior' and kinds['cocina'] == 'interior'
    assert all(set(mold['title']) == {'es', 'en'} for mold in result['molds'])
    description = command_catalog()[0]['description']
    assert 'exterior' in description and 'kind' in description and 'title' in description


def test_every_exterior_preset_has_a_sky_and_no_light_carries_it():
    presets = light_presets()
    assert presets['skies'].keys() == presets['exterior'].keys()
    for sky in presets['skies'].values():
        assert set(sky) == {'zenith', 'horizon'} and all(value.startswith('#') and len(value) == 7 for value in sky.values())
    for kind in ('interior', 'exterior'):
        for light in presets[kind].values():
            assert set(light) == {'color', 'intensity', 'direction'}

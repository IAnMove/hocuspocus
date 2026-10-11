"""Every mold is a stage card whose traits are measured from the mold, never written by hand."""
from collections import Counter

from services.set_molds import catalog, load_mold, resolve_mold
from services.world3d_stage_cards import card, is_stage, measure, stage_card, stage_cards, trait_words
from services.world3d_template_catalog import builtin_card, builtin_cards, search_templates
from services.world3d_template_vocabulary import SHOT_SIZES, USES

CAMERAS = ['two_shot', 'ots_a', 'ots_b', 'wide', 'close_1', 'close_2', 'entrance']


def test_one_card_per_mold_with_the_derived_traits():
    cards = stage_cards()
    assert [item['id'] for item in cards] == [f"stage-{mold['id']}" for mold in catalog()]
    for item in cards:
        assert item['kind'] == 'stage' and item['place'] == item['id'].removeprefix('stage-') and item['cameras'] == CAMERAS, item['id']
        assert item['family'] == 'stage' and item['category'] == 'cinema' and item['setting'] in ('interior', 'exterior')
        assert item['shot'] in SHOT_SIZES and (item['shot'] == 'plate') == (item['distance'] is None) and item['distance'] > 0
        assert item['moves'] == [] and item['moving'] == ['effects'] and item['still'] is False
        assert item['uses'] and set(item['uses']) <= set(USES) and {'talk', 'figure'} <= set(item['uses'])
        assert item['subjects'] == 2 == sum(1 for role in item['roles'] if role in ('subject_1', 'subject_2'))
        assert item['roles'][:2] == ['subject_1', 'subject_2'] and set(item['roles'][2:]) <= {'prop'} and item['props'] == len(item['roles']) - 2
        assert [slot['id'] for slot in item['required']] == ['subject_1', 'subject_2'] and all(slot['media'] == 'model3d' for slot in item['required'])
        assert (item['format'], item['width'], item['height'], item['duration']) == ('landscape', 1280, 720, 6)
        assert item['tags'] == ['stage'] and item['source'] == 'builtin' and item['dependencies'] == [] and item['authoredFor'] == 'model'
        assert item['floor'] == 'tiles' and item['travel'] is False and item['reference'] is None and item['preview'] is None
        assert item['lineEs'] and item['lineEn'] and 'two_shot' in item['lineEn'] and not item['lineEs'].endswith('...')
    for key in ('titleEs', 'titleEn'):
        assert all(count == 1 for count in Counter(item[key] for item in builtin_cards()).values()), key
    assert builtin_cards.cache_info().maxsize == 1
    assert builtin_card('stage-sala') is stage_card('stage-sala')
    assert sum(1 for item in builtin_cards() if item.get('kind') == 'stage') == len(cards) == 28


def test_shot_sizes_are_measured_from_the_default_camera_to_the_first_mark():
    cocina = resolve_mold('cocina')
    cameras = {camera['id']: camera for camera in cocina['cameras']}
    assert measure(cameras['two_shot'], cocina['marks'][0]) == ('wide', 3.5)
    near = measure(cameras['close_1'], cocina['marks'][0])
    assert near[1] < 3.5 and near[0] != 'far'
    assert (stage_card('stage-cocina')['shot'], stage_card('stage-cocina')['distance']) == ('wide', 3.5)
    assert stage_card('stage-vehiculo')['distance'] < stage_card('stage-plaza')['distance']
    assert 'dialogue' in stage_card('stage-mostrador')['uses'] and 'dialogue' in stage_card('stage-escenario_publico')['uses']


def test_trait_words_name_seated_speakers_entrances_and_crowds():
    assert trait_words(load_mold('filas')) == ['seated', 'entrance', 'crowd']
    assert trait_words(load_mold('escenario_publico')) == ['entrance', 'crowd']
    assert trait_words(load_mold('plaza')) == ['entrance', 'crowd'], 'four speaking marks hold a crowd'
    assert trait_words(load_mold('sala')) == ['entrance']
    assert trait_words(load_mold('despacho')) == ['seated'], 'its door mark is not an entrance mark'
    assert stage_card('stage-vehiculo')['traitWords'] == ['seated', 'entrance']


def test_a_mold_without_ambient_life_is_a_still_card():
    quiet = card({**load_mold('sala'), 'ambient': False})
    assert quiet['moving'] == [] and quiet['still'] is True and 'dialogue' in quiet['uses']


def test_lines_tell_the_shape_who_fits_and_the_cameras():
    sala, filas = stage_card('stage-sala'), stage_card('stage-filas')
    assert sala['lineEs'].startswith('Sala: interior sin muebles; 3 marcas, de pie, con entrada; plano general desde two_shot.')
    assert filas['lineEn'].startswith('Rows: interior with benches, a desk; 3 marks, 2 seated, with an entrance; wide shot from two_shot.')
    assert 'entrance' not in stage_card('stage-despacho')['lineEn'].split('Cameras')[0]


def test_stage_cards_are_searchable_with_the_rest():
    assert search_templates('escenario con público', limit=3)[0]['id'] == 'stage-escenario_publico'
    assert search_templates('azotea', limit=3)[0]['id'] == 'stage-azotea'
    assert search_templates('sala', limit=5)[0]['id'] == 'stage-sala'
    assert search_templates('plano de dos', limit=3)[0]['id'] == 'two-shot', 'the stages do not outrank the shot they are built on'


def test_every_furniture_block_has_words_in_both_languages():
    from services.world3d_stage_cards import BLOCK_WORDS
    kinds = {block["kind"] for mold in catalog() for block in mold.get("blocks", [])}
    assert kinds <= set(BLOCK_WORDS), sorted(kinds - set(BLOCK_WORDS))


def test_only_an_existing_mold_makes_a_stage_id():
    """``stage-crane`` is a shipped concert scene, not the mold ``crane``: it compiles as the scene it is."""
    assert builtin_card("stage-crane")["kind"] == "scene" and not is_stage("stage-crane")
    assert is_stage("stage-bar") and is_stage("stage-cabina_avion")
    assert not any(is_stage(value) for value in ("stage-", "stage-nope", "stage-../bar", "stage-Bar", None, "bar"))
    stages = {stage["id"] for stage in stage_cards()}
    assert not stages & {item["id"] for item in builtin_cards() if item.get("kind") != "stage"}, "a mold shadows a shipped card"
    assert all(is_stage(stage_id) for stage_id in stages)

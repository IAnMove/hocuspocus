import copy
import json
from pathlib import Path

import pytest

from services.series_library import (
    SeriesConflictError, create_series_episode, create_series_project,
    normalize_series_project, series_for_episode_snapshot,
)
from services.series_production import (
    attach_series_import, is_series_generated_shot, normalize_production_methods,
    refresh_episode_references, series_shot_method,
)
from services.series_reference_router import route_shot_references
from services.series_render import apply_series_shot_duration


def project():
    path = Path(__file__).parents[1] / 'docs/series-lab/example-series-library-v1.json'
    return normalize_series_project(json.loads(path.read_text())['seriesById']['series_signal'], 'series_signal', 'default')


def test_production_permissions_persist_and_do_not_silently_allow_other_methods():
    series = project()
    assert series['allowedProductionMethods'] == ['generated_video']
    series['allowedProductionMethods'] = ['animation_2d', 'imported_video']
    saved = normalize_series_project(series, series['id'], 'default')
    assert saved['allowedProductionMethods'] == series['allowedProductionMethods']
    assert series_shot_method(saved, {}) == 'animation_2d'
    with pytest.raises(ValueError, match='not permitted'):
        series_shot_method(saved, {'productionMethod': 'generated_video', 'order': 1})
    assert is_series_generated_shot(saved, {}) is False
    assert is_series_generated_shot(
        {'allowedProductionMethods': ['generated_video']}, {'productionMethod': 'imported_video'}
    ) is False
    assert is_series_generated_shot(
        {'allowedProductionMethods': ['generated_video']}, {'productionMethod': 'generated_video'}
    ) is True
    episode = next(iter(saved['episodesById'].values()))
    episode['shots'][0].pop('productionMethod', None)
    persisted = normalize_series_project(saved, saved['id'], 'default')
    assert persisted['episodesById'][episode['id']]['shots'][0]['productionMethod'] == 'animation_2d'
    for invalid in ([], ['unknown'], 'animation_2d'):
        with pytest.raises(ValueError):
            normalize_production_methods(invalid)


def test_reference_import_updates_exact_owner_and_existing_episode_can_adopt_it():
    series = create_series_project('default')
    series['canon'].update(worldSummary='Original lore', approval='approved', revision=2)
    series['characters'] = [{'id':'character_a', 'name':'Ada', 'approval':'approved', 'referenceAssetIds':[], 'wardrobeVariants':[]}]
    series['locations'] = [{'id':'location_a', 'name':'Lab', 'approval':'approved', 'referenceAssetIds':[], 'variants':[]}]
    episode = create_series_episode(series)
    series['episodesById'][episode['id']] = episode
    asset = {'id':'asset_portrait', 'workspaceId':'default', 'kind':'character', 'uri':'assets/a/portrait.png',
             'ownerType':'character', 'ownerId':'character_a', 'isDerivedThumbnail':False, 'metadata':{'referenceRole':'primary_portrait'}}
    attach_series_import(series, asset)
    assert series['characters'][0]['primaryReferenceAssetId'] == asset['id']
    assert series['canon']['approval'] == 'draft'
    with pytest.raises(ValueError, match='Approve'):
        refresh_episode_references(series, episode['id'], series['revision'])
    series['canon']['approval'] = series['characters'][0]['approval'] = 'approved'
    series['characters'][0]['name'] = 'Later name'
    series['canon']['worldSummary'] = 'Later lore'
    updated = refresh_episode_references(series, episode['id'], series['revision'])
    updated_episode = updated['episodesById'][episode['id']]
    frozen = series_for_episode_snapshot(updated, updated_episode)
    assert frozen['characters'][0]['name'] == 'Ada'
    assert frozen['canon']['worldSummary'] == 'Original lore'
    assert frozen['characters'][0]['primaryReferenceAssetId'] == asset['id']
    assert episode['canonSnapshot']['characters'][0]['referenceAssetIds'] == []
    manifest = route_shot_references(frozen, updated_episode, {
        'id':'shot_a', 'visibleCharacterIds':['character_a'], 'speakingCharacterIds':['character_a'],
        'primarySpeakerId':'character_a', 'renderStrategy':'references',
    })
    assert asset['id'] in [item['assetId'] for item in manifest['selected']]
    with pytest.raises(SeriesConflictError):
        refresh_episode_references(updated, episode['id'], series['revision'])


def test_reference_refresh_keeps_takes_and_rejects_active_render():
    series = project()
    episode = next(iter(series['episodesById'].values()))
    shot = episode['shots'][0]
    previous = copy.deepcopy(shot['attempts'])
    series['canon']['approval'] = 'approved'
    for other in episode['shots']:
        for attempt in other['attempts']:
            attempt['status'] = 'completed'
    updated = refresh_episode_references(series, episode['id'], series['revision'])
    assert updated['episodesById'][episode['id']]['shots'][0]['attempts'] == shot['attempts']
    assert len(previous) == len(shot['attempts'])
    shot['attempts'].append({'id':'busy', 'status':'running'})
    with pytest.raises(SeriesConflictError, match='finish'):
        refresh_episode_references(series, episode['id'], series['revision'])


@pytest.mark.parametrize('method', ['animation_2d', 'animation_3d', 'imported_video'])
def test_imported_finished_take_is_verified_append_only_and_keeps_method(method, monkeypatch):
    series = project()
    series['allowedProductionMethods'] = [method]
    episode = next(iter(series['episodesById'].values()))
    shot = episode['shots'][0]
    shot['productionMethod'] = method
    for attempt in shot['attempts']:
        attempt['status'] = 'completed'
    shot['approvedAttemptId'] = shot['attempts'][0]['id']
    previous = copy.deepcopy(shot['attempts'])
    approved = shot.get('approvedAttemptId')
    asset = {'id':'asset_external', 'kind':'video', 'uri':'assets/take.mp4', 'workspaceId':'default',
             'ownerType':'shot', 'ownerId':shot['id'], 'isDerivedThumbnail':False, 'metadata':{'lipSyncUpdate':True}}
    monkeypatch.setattr('services.video_editor.probe_media', lambda path: {'duration':60, 'width':1280, 'height':720})
    attach_series_import(series, asset, as_take=True, source_path='verified.mp4')
    updated = episode['shots'][0]
    assert updated['attempts'][:-1] == previous
    assert updated.get('approvedAttemptId') == approved
    take = updated['attempts'][-1]
    assert take['status'] == 'completed' and take['model'] == method
    assert take['outputAssetIds'] == [asset['id']]
    assert take['id'] != approved and take.get('reviewDecision') != 'approved'
    assert asset['metadata']['lipSyncUpdate'] is True
    assert asset['ownerType'] == 'attempt' and asset['ownerId'] == take['id']
    normalize_series_project(series, series['id'], 'default')
    monkeypatch.setattr('services.video_editor.probe_media', lambda path: {'duration':.01})
    with pytest.raises(ValueError, match='shorter'):
        attach_series_import(series, {**asset, 'ownerType':'shot', 'ownerId':shot['id']}, as_take=True, source_path='short.mp4')


def test_native_animation_duration_is_not_requantized_to_h3():
    shot = {'productionMethod':'animation_2d', 'durationSeconds':23.4, 'dialogueDuration':{'old':True}}
    apply_series_shot_duration({}, shot)
    assert shot['durationSeconds'] == 23.4
    assert 'dialogueDuration' not in shot

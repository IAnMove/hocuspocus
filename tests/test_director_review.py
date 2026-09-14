import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.director_review import create_director_review_router
from services import director_pipeline as pipeline
from services.director_review import save_review


def fixture(tmp_path):
    state = {"pipeline_id": "review-test", "status": "completed", "clips": [
        {"index": 0, "video_filename": "new.mp4", "video_attempts": [
            {"id": "old-id", "filename": "old.mp4"}, {"id": "new-id", "filename": "new.mp4"}],
         "video_prompt": "literal prompt", "tag": None},
        {"index": 1, "video_filename": "approved.mp4", "tag": "good"},
    ]}
    path = tmp_path / f"{pipeline._PIPELINE_FILE_PREFIX}review-test.json"
    path.write_text(json.dumps(state))
    for name in ("old.mp4", "new.mp4", "approved.mp4"):
        (tmp_path / name).write_bytes(b"media placeholder for persistence-only test")
    return path, state


def test_review_persists_exact_take_tag_and_notes_and_preserves_other_shots(tmp_path):
    path, state = fixture(tmp_path)
    app = FastAPI()
    app.include_router(create_director_review_router(lambda name: str(tmp_path)))
    response = TestClient(app).put('/api/v1/director/pipelines/review-test/review', json={
        'workspace': 'test', 'commands': [
            {'type': 'select_take', 'pipelineId': 'review-test', 'clipIndex': 0, 'filename': 'old.mp4', 'takeId': 'old-id'},
            {'type': 'tag_clip', 'pipelineId': 'review-test', 'clipIndex': 0, 'tag': 'good'},
            {'type': 'note_clip', 'pipelineId': 'review-test', 'clipIndex': 0, 'notes': '  literal\nnotes  '},
        ],
    })
    assert response.status_code == 200, response.text
    saved = json.loads(path.read_text())
    assert saved['clips'][0]['selected_video_filename'] == 'old.mp4'
    assert saved['clips'][0]['review_notes'] == '  literal\nnotes  '
    assert {item['filename'] for item in saved['clips'][0]['video_attempts']} == {'old.mp4', 'new.mp4'}
    for original in state['clips'][0]['video_attempts']:
        actual = next(item for item in saved['clips'][0]['video_attempts'] if item['filename'] == original['filename'])
        assert {key: actual[key] for key in original} == original
    assert {key: saved['clips'][1][key] for key in state['clips'][1]} == state['clips'][1]


def test_review_rejects_invalid_batch_without_partial_save(tmp_path):
    path, _ = fixture(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save_review(str(tmp_path), 'review-test', [
            {'type': 'note_clip', 'pipelineId': 'review-test', 'clipIndex': 0, 'notes': 'should roll back'},
            {'type': 'select_take', 'pipelineId': 'review-test', 'clipIndex': 0, 'filename': '../elsewhere.mp4'},
        ])
    assert path.read_bytes() == before


def test_review_obeys_pipeline_busy_guard(tmp_path):
    fixture(tmp_path)
    pipeline._pipeline_operations.add('review-test')
    try:
        with pytest.raises(pipeline.PipelineBusyError):
            save_review(str(tmp_path), 'review-test', [])
    finally:
        pipeline._pipeline_operations.discard('review-test')


def test_switching_an_approved_take_updates_h3_selection_without_approving_it(tmp_path):
    path, state = fixture(tmp_path)
    state['clips'][0].update(tag='good', h3_segments=[{'filename': 'new.mp4', 'stale': True}])
    path.write_text(json.dumps(state))
    save_review(str(tmp_path), 'review-test', [
        {'type': 'select_take', 'pipelineId': 'review-test', 'clipIndex': 0, 'filename': 'old.mp4'},
    ])
    saved = json.loads(path.read_text())
    assert saved['clips'][0]['tag'] is None
    assert saved['clips'][0]['h3_segments'][0]['filename'] == 'old.mp4'
    assert saved['clips'][0]['h3_segments'][0]['stale'] is False
    assert 'old.mp4' in saved['output_files']


def _sidecar_history(tmp_path):
    state = {"pipeline_id": "review-test", "status": "completed", "clips": [
        {"index": 0, "video_filename": "new.mp4", "video_prompt": "literal prompt", "tag": None},
    ]}
    path = tmp_path / f"{pipeline._PIPELINE_FILE_PREFIX}review-test.json"
    path.write_text(json.dumps(state))
    (tmp_path / "new.mp4").write_bytes(b"current take")
    (tmp_path / "old.mp4").write_bytes(b"recovered take")
    (tmp_path / "old.mp4.meta.json").write_text(json.dumps({
        "output_filename": "old.mp4",
        "director_pipeline_id": "review-test",
        "director_clip_index": 0,
        "created_at": 1,
        "params": {"_director_clip_index": 0, "prompt": "older take"},
    }))
    return path


def test_review_can_select_a_sidecar_take_missing_from_the_checkpoint(tmp_path):
    path = _sidecar_history(tmp_path)
    saved = save_review(str(tmp_path), "review-test", [
        {"type": "select_take", "pipelineId": "review-test", "clipIndex": 0, "filename": "old.mp4"},
        {"type": "tag_clip", "pipelineId": "review-test", "clipIndex": 0, "tag": "good"},
    ])
    names = {item["filename"] for item in saved["clips"][0]["video_attempts"]}
    assert names == {"old.mp4", "new.mp4"}
    assert saved["clips"][0]["selected_video_filename"] == "old.mp4"
    assert saved["clips"][0]["tag"] == "good"
    disk = json.loads(path.read_text())
    assert disk["clips"][0]["selected_video_filename"] == "old.mp4"
    assert {item["filename"] for item in disk["clips"][0]["video_attempts"]} == names


def test_review_notes_keep_recovered_takes_in_the_saved_pipeline(tmp_path):
    _sidecar_history(tmp_path)
    saved = save_review(str(tmp_path), "review-test", [
        {"type": "note_clip", "pipelineId": "review-test", "clipIndex": 0, "notes": "keep history"},
    ])
    names = {item["filename"] for item in saved["clips"][0]["video_attempts"]}
    assert names == {"old.mp4", "new.mp4"}
    assert saved["clips"][0]["review_notes"] == "keep history"
    assert saved["clips"][0]["video_filename"] == "new.mp4"


def test_review_cannot_select_a_sidecar_from_another_production(tmp_path):
    path = _sidecar_history(tmp_path)
    sidecar = tmp_path / 'old.mp4.meta.json'
    metadata = json.loads(sidecar.read_text())
    metadata['director_pipeline_id'] = 'another-production'
    sidecar.write_text(json.dumps(metadata))
    before = path.read_bytes()
    with pytest.raises(ValueError, match='existing take'):
        save_review(str(tmp_path), 'review-test', [
            {'type': 'select_take', 'pipelineId': 'review-test', 'clipIndex': 0, 'filename': 'old.mp4'},
        ])
    assert path.read_bytes() == before


def test_invalid_review_does_not_persist_hydrated_history_or_partial_notes(tmp_path):
    path = _sidecar_history(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='Invalid review decision'):
        save_review(str(tmp_path), 'review-test', [
            {'type': 'note_clip', 'pipelineId': 'review-test', 'clipIndex': 0, 'notes': 'not committed'},
            {'type': 'tag_clip', 'pipelineId': 'review-test', 'clipIndex': 0, 'tag': 'invalid'},
        ])
    assert path.read_bytes() == before


def test_review_notes_keep_a_stale_selected_take_stale(tmp_path):
    path, state = fixture(tmp_path)
    state['clips'][0].update(
        selected_video_filename='old.mp4',
        video_filename='old.mp4',
        video_stale=True,
        tag='good',
    )
    path.write_text(json.dumps(state))
    loaded = pipeline.load_pipeline_state(str(tmp_path), 'review-test')
    assert loaded['clips'][0]['video_stale'] is True
    assert loaded['clips'][0]['selected_video_filename'] == 'old.mp4'
    save_review(str(tmp_path), 'review-test', [
        {'type': 'note_clip', 'pipelineId': 'review-test', 'clipIndex': 0, 'notes': 'keep stale'},
    ])
    saved = json.loads(path.read_text())
    assert saved['clips'][0]['video_stale'] is True
    assert saved['clips'][0]['selected_video_filename'] == 'old.mp4'
    assert saved['clips'][0]['review_notes'] == 'keep stale'
    assert saved['clips'][0]['tag'] == 'good'


def test_desk_notes_persist_can_restate_an_existing_stale_approval(tmp_path):
    path, state = fixture(tmp_path)
    state['clips'][0].update(
        selected_video_filename='old.mp4',
        video_filename='old.mp4',
        video_stale=True,
        tag='good',
    )
    path.write_text(json.dumps(state))
    save_review(str(tmp_path), 'review-test', [
        {'type': 'select_take', 'pipelineId': 'review-test', 'clipIndex': 0, 'filename': 'old.mp4', 'takeId': 'old-id'},
        {'type': 'tag_clip', 'pipelineId': 'review-test', 'clipIndex': 0, 'tag': 'good'},
        {'type': 'note_clip', 'pipelineId': 'review-test', 'clipIndex': 0, 'notes': 'rerun the start frame'},
    ])
    saved = json.loads(path.read_text())
    assert saved['clips'][0]['review_notes'] == 'rerun the start frame'
    assert saved['clips'][0]['tag'] == 'good'
    assert saved['clips'][0]['video_stale'] is True
    assert saved['clips'][0]['selected_video_filename'] == 'old.mp4'


def test_review_cannot_newly_approve_a_stale_take(tmp_path):
    path, state = fixture(tmp_path)
    state['clips'][0].update(
        selected_video_filename='old.mp4',
        video_filename='old.mp4',
        video_stale=True,
        tag=None,
    )
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises(ValueError, match='completed current take'):
        save_review(str(tmp_path), 'review-test', [
            {'type': 'select_take', 'pipelineId': 'review-test', 'clipIndex': 0, 'filename': 'old.mp4'},
            {'type': 'tag_clip', 'pipelineId': 'review-test', 'clipIndex': 0, 'tag': 'good'},
            {'type': 'note_clip', 'pipelineId': 'review-test', 'clipIndex': 0, 'notes': 'should roll back'},
        ])
    assert path.read_bytes() == before

"""Viggle's admission, provenance and audio behavior without model weights."""
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from services.wangp_submission import prepare_viggle_recast, preserve_source_audio, resolve_wangp_media, viggle_parameters
from services.wangp_submission import prepare_generation_inputs


def test_legacy_image_opt_in_resolves_ordered_canonical_references_only(tmp_path):
    uploads, workspace = tmp_path / 'uploads', tmp_path / 'outputs'
    uploads.mkdir(); workspace.mkdir()
    (uploads / 'same image.png').write_bytes(b'frame')
    (workspace / 'same image.png').write_bytes(b'identity')
    body = {'image_mode': 1, 'canonical_image_refs': True,
            'image_refs': ['/api/v1/uploads/same%20image.png', '/api/v1/file/same%20image.png?workspace=demo'],
            'video_guide': '/api/v1/uploads/unrelated.mp4'}
    prepare_generation_inputs(body, {'image_outputs': True}, 'demo', uploads_dir=uploads, workspace_dir=workspace)
    assert [Path(value).read_bytes() for value in body['image_refs']] == [b'frame', b'identity']
    assert 'canonical_image_refs' not in body
    assert body['video_guide'] == '/api/v1/uploads/unrelated.mp4'


@pytest.mark.parametrize('reference', [
    '/api/v1/file/same.png?workspace=other', '/api/v1/uploads/%2E%2E/outside.png',
    '/api/v1/uploads/same.png', 'https://example.com/same.png', '/api/v1/uploads/escape.png',
])
def test_canonical_image_opt_in_rejects_foreign_missing_and_escaped_media(tmp_path, reference):
    uploads, workspace = tmp_path / 'uploads', tmp_path / 'outputs'
    uploads.mkdir(); workspace.mkdir()
    (workspace / 'same.png').write_bytes(b'must not substitute')
    outside = tmp_path / 'outside.png'
    outside.write_bytes(b'outside')
    (uploads / 'escape.png').symlink_to(outside)
    body = {'image_mode': 1, 'canonical_image_refs': True, 'image_refs': [reference]}
    with pytest.raises(ValueError):
        prepare_generation_inputs(body, {'image_outputs': True}, 'demo', uploads_dir=uploads, workspace_dir=workspace)


def test_legacy_references_are_unchanged_without_opt_in_and_video_cannot_opt_in(tmp_path):
    body = {'image_refs': ['legacy.png'], 'video_guide': 'unchanged.mp4'}
    prepare_generation_inputs(body, {}, 'demo', uploads_dir=tmp_path, workspace_dir=tmp_path)
    assert body == {'image_refs': ['legacy.png'], 'video_guide': 'unchanged.mp4'}
    with pytest.raises(ValueError, match='image generation'):
        prepare_generation_inputs({'canonical_image_refs': True, 'image_mode': 0, 'image_refs': []},
                                  {}, 'demo', uploads_dir=tmp_path, workspace_dir=tmp_path)


@pytest.mark.parametrize('stated, expected_mode, expected_length', [
    ({}, 1, 1),                                  # gen-01: the body said only generation_mode=image
    ({'image_mode': 0, 'video_length': 81}, 1, 1),  # a contradictory 0 is read as the image request it sits in
    ({'image_mode': None}, 1, 1),
    ({'image_mode': 1, 'video_length': 1}, 1, 1),
    ({'image_mode': 2, 'video_length': 3}, 2, 3),   # a stated image mode of 2 is kept as it is
    ({'image_mode': 3, 'video_length': 1}, 3, 1),    # any positive mode is an image for WanGP (image_mode > 0)
    ({'image_mode': True}, 1, 1),                    # not a number: the image request wins
    ({'image_mode': '0'}, 1, 1),
])
def test_an_image_request_always_carries_the_selectors_wangp_reads(tmp_path, stated, expected_mode, expected_length):
    body = {'generation_mode': 'image', 'prompt': 'a barn', **stated}
    prepare_generation_inputs(body, {}, 'demo', uploads_dir=tmp_path, workspace_dir=tmp_path)
    assert (body['image_mode'], body['video_length']) == (expected_mode, expected_length)


def test_the_image_selectors_are_in_place_before_the_checks_that_read_them(tmp_path):
    # The prepared-image check refuses image inputs unless image_mode is 1 or 2: it must see the normalised body.
    body = {'generation_mode': 'image', 'prompt': 'a barn'}
    prepare_generation_inputs(body, {'wangp_1272': True, 'image_outputs': True}, 'demo', uploads_dir=tmp_path,
                              workspace_dir=tmp_path, prepared_images=True)
    assert body['image_mode'] == 1


@pytest.mark.parametrize('body', [
    {'generation_mode': 'video', 'video_length': 49},
    {'generation_mode': 'audio', 'image_mode': 0, 'video_length': 0},
    {'prompt': 'no mode stated', 'video_length': 81},
])
def test_other_requests_keep_their_own_image_mode_and_length(tmp_path, body):
    before = dict(body)
    prepare_generation_inputs(body, {}, 'demo', uploads_dir=tmp_path, workspace_dir=tmp_path)
    assert body == before


def test_viggle_maps_one_edited_frame_and_keeps_source_identity():
    params = viggle_parameters({'prompt': 'Not used', 'num_inference_steps': 99, 'seed': 41}, video='/v.mp4', reference='/edited.png', width=1920, height=1080, duration=9.625)
    assert params['video_length'] == 231
    assert params['num_inference_steps'] == 3
    assert params['image_refs'] == ['/edited.png']
    assert params['video_guide'] == params['viggle_source_video'] == '/v.mp4'
    assert params['seed'] == 41
    assert params['prompt_enhancer'] == ''
    assert (params['sample_solver'], params['flow_shift'], params['guidance_scale']) == ('euler', 3, 1)
    assert (params['sliding_window_size'], params['sliding_window_overlap']) == (124, 18)


@pytest.mark.parametrize('duration', [0, -1, float('nan'), float('inf')])
def test_invalid_video_duration_never_enters_queue(duration):
    with pytest.raises(ValueError):
        viggle_parameters({}, video='v', reference='i', width=32, height=32, duration=duration)


def test_explicit_asset_roots_do_not_alias_same_named_files(tmp_path):
    uploads, workspace = tmp_path / 'uploads', tmp_path / 'outputs'
    uploads.mkdir(); workspace.mkdir()
    (uploads / 'same.png').write_bytes(b'upload')
    (workspace / 'same.png').write_bytes(b'output')
    def resolve(value):
        return resolve_wangp_media(value, 'demo', uploads_dir=uploads, workspace_dir=workspace)
    assert Path(resolve('/api/v1/uploads/same.png')).read_bytes() == b'upload'
    assert Path(resolve('/api/v1/file/same.png?workspace=demo')).read_bytes() == b'output'
    for value in ('same.png', '/api/v1/file/same.png?workspace=other', '/api/v1/uploads/../outside.png', 'https://example.com/same.png'):
        with pytest.raises(ValueError):
            resolve(value)


def make_video(path, audio=False):
    command = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=64x64:r=24:d=0.5']
    if audio:
        command += ['-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.5']
    subprocess.run(command + ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)], check=True, capture_output=True)


def audio_streams(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_streams', '-of', 'json', str(path)]))['streams']


@pytest.mark.parametrize('source_audio', [True, False])
def test_source_audio_mode_preserves_silence_instead_of_model_sound(tmp_path, source_audio):
    source, output = tmp_path / 'source.mp4', tmp_path / 'result.mp4'
    make_video(source, audio=source_audio)
    make_video(output, audio=True)
    preserve_source_audio(output, source)
    assert bool(audio_streams(output)) is source_audio
    assert not list(tmp_path.glob('.*mux*'))


def test_preparation_rejects_an_unrelated_aspect_ratio(tmp_path):
    source, reference = tmp_path / 'source.mp4', tmp_path / 'edited.png'
    make_video(source)
    Image.new('RGB', (128, 64)).save(reference)
    with pytest.raises(ValueError, match='aspect ratio'):
        prepare_viggle_recast({'video_path': str(source), 'ref_image_path': str(reference)}, lambda value, _: value, tmp_path / 'uploads')


def test_recast_sidecar_preserves_canonical_asset_roots(tmp_path):
    from services.wangp_submission import wangp_media_url
    uploads, workspace = tmp_path / 'uploads', tmp_path / 'outputs'
    uploads.mkdir(); workspace.mkdir()
    source, reference = uploads / 'source.mp4', workspace / 'edited frame.png'
    make_video(source)
    Image.new('RGB', (64, 64)).save(reference)
    url = lambda path: wangp_media_url(path, 'demo workspace', uploads_dir=uploads, workspace_dir=workspace)
    params = prepare_viggle_recast({'video_path': str(source), 'ref_image_path': str(reference)}, lambda value, _: value, uploads, url)
    assert params['edit_video_url'] == '/api/v1/uploads/source.mp4'
    assert params['edit_recast_ref_url'] == '/api/v1/file/edited%20frame.png?workspace=demo+workspace'
    assert resolve_wangp_media(params['edit_recast_ref_url'], 'demo workspace', uploads_dir=uploads, workspace_dir=workspace) == str(reference)

"""Exercise the actual worker with a recorded admission and a provider stand-in.

No model is loaded and the stand-in bytes are not claimed to be decoded media.
"""
import ast
import copy
import os
from pathlib import Path
import sys
import time
import traceback
from types import SimpleNamespace

import pytest

from services.job_lifecycle import new_media_files
from tests.test_studio_sfx_commands import command, setup_service
from tests.test_image_generation_commands import _run


@pytest.fixture(scope='module')
def worker_source():
    source = Path(__file__).parents[1] / 'app' / '_launch_runtime.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    worker = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == '_run_sfx_generation')
    return ast.Module(body=[worker], type_ignores=[]), str(source)


@pytest.mark.parametrize('guided,output_name', [(False, None), (True, None), (False, 'rain-on-glass'), (True, 'rain-on-glass.wav')])
def test_admitted_worker_uses_exact_inputs_without_download_or_reprobe(
    tmp_path, monkeypatch, worker_source, guided, output_name,
):
    native, service, runtime, _weights = setup_service(tmp_path)
    request = command()
    if output_name:
        request['input']['output_name'] = output_name
    request['input']['params'].update({
        'guidance_scale': 3.5, 'sfx_text_weight': 0.7,
        'MMAudio_neg_prompt': '  Speech\nMusic  ',
    })
    if guided:
        source = tmp_path / 'source' / 'guide.mp4'
        source.parent.mkdir()
        source.write_bytes(b'inspected video fixture')
        request['input']['params']['video_guide'] = '/api/v1/file/guide.mp4?workspace=source'
        monkeypatch.setattr('services.studio_sfx_resources.probe_media', lambda _path: {
            'duration': 6.25, 'width': 640, 'height': 360,
        })
    _run(service.submit(request))
    job = native.dispatch_calls[0]
    job['out_dir'] = str(tmp_path / 'native-output')
    raw_params = copy.deepcopy(job['params'])
    calls, sidecars, completed, probes = [], [], [], []

    def generate(**kwargs):
        calls.append(kwargs)
        Path(kwargs['save_path']).write_bytes(b'provider stand-in; not real media')

    def finish(_job, status, **kwargs):
        completed.append((status, kwargs))
        return status == 'completed'

    def forbidden_download(**_kwargs):
        pytest.fail('An admitted SFX command must never provision models')

    wgp = runtime['wgp']
    wgp.server_config = {}
    wgp.save_path = str(tmp_path / 'unused')
    wgp.MMAUDIO_PERSIST_RAM = 'ram'
    wgp.get_mmaudio_settings = lambda *_args, **_kwargs: (True, None, 'none', 'large_44k_v2', 'weights')
    wgp.download_mmaudio = forbidden_download
    wgp.get_available_filename = lambda directory, name, force_extension=None: os.path.join(
        directory, os.path.splitext(name)[0] + (force_extension or os.path.splitext(name)[1]))
    wgp.format_time = str
    monkeypatch.setitem(sys.modules, 'postprocessing.mmaudio.mmaudio', SimpleNamespace(video_to_audio=generate))
    monkeypatch.setitem(sys.modules, 'decord', SimpleNamespace(VideoReader=lambda path: probes.append(path)))
    scope = {
        'os': os, 'time': time, 'copy': copy, 'traceback': traceback, 'wgp': wgp,
        '_task_registry': native.registry,
        'is_cancel_requested': lambda _job: False,
        'update_job': lambda *_args, **_kwargs: True,
        'finish_job': finish,
        'record_job_outputs': lambda target, files: target.update(outputs=files),
        'new_media_files': new_media_files,
        '_publish_generation_sidecar_for_studio_job': lambda _job, path, metadata: sidecars.append((path, copy.deepcopy(metadata))),
    }
    module, filename = worker_source
    exec(compile(module, filename, 'exec'), scope)
    assert scope['_run_sfx_generation'](job, raw_params, time.time()) is True
    assert len(calls) == 1
    call = calls[0]
    assert call['prompt'] == request['input']['params']['prompt']
    assert call['negative_prompt'] == '  Speech\nMusic  '
    assert call['duration'] == (6.25 if guided else 3)
    assert call['audio_file_only'] is not guided
    assert call['video'] == (str(source) if guided else None)
    assert (call['num_steps'], call['cfg_strength'], call['text_weight'], call['seed']) == (25, 3.5, 0.7, 42)
    assert probes == []
    assert len(sidecars) == 1
    output, metadata = sidecars[0]
    assert output.endswith('.mp4' if guided else '.wav')
    stem = Path(output).stem
    assert stem == 'rain-on-glass' if output_name else stem.startswith('sfx_Rain_against_glass')
    assert metadata['params'] == raw_params == job['params']
    assert metadata['upload_filenames'] == ({'video_guide': 'guide.mp4'} if guided else {})
    assert completed[0][0] == 'completed'

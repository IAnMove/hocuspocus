"""Shared local-image batch admission for props and room skins."""
from __future__ import annotations

import time
from types import SimpleNamespace

from services.game_tools import _job_id, _wait_job, _require_files, _split_clocks
from services.set_molds import defaults


def require_result(reply):
    if reply.get('_is_error') or reply.get('status') == 'failed':
        raise ValueError(str(reply.get('error') or 'tool failed'))
    return reply.get('result', reply)


def image_model(call) -> str:
    config = defaults()
    options = require_result(call('media.options', {'version': 1, 'input': {}}))
    installed = {row['id'] for row in options.get('local', {}).get('image', [])}
    order = config['imageModelOrder'] if config['imageModel'] == 'fastest_installed_qwen21_turbo' else [config['imageModel']]
    for model in order:
        if model in installed:
            return model
    raise ValueError('Install a Qwen Image 2.1 model before generating sets or props')


def generate_batch(call, workspace: str, requests: list[dict], intent: str) -> list[dict]:
    """Admit all pictures before waiting, allowing the shared queue to batch them."""
    if not requests:
        return []
    model = image_model(call)
    admitted = []
    for index, request in enumerate(requests):
        tag = f'{intent}-{index}'
        params = {**defaults()['imageParams'][model], 'model_type': model, 'seed': request.get('seed', index+1), 'prompt': request['prompt'],
                  'negative_prompt': request.get('negative', ''), 'resolution': request['resolution'],
                  'batch_size': request.get('candidates', 1)}
        if not defaults()['imageNegativePrompt'][model]:
            params['prompt'] += f". Avoid {params['negative_prompt']}." if params['negative_prompt'] else ''
            params['negative_prompt'] = ''
        if request.get('refs'):
            params.update(image_refs=request['refs'], video_prompt_type='I')
        if request.get('guide'):
            params.update(image_guide=request['guide'], image_mask=request['mask'], video_prompt_type='VAG', model_mode=0)
        started = time.monotonic()
        reply = call('generation.image', {'version': 2, 'intent_id': tag, 'input': {'workspace': workspace, 'output_name': tag, 'params': params}})
        admitted.append((tag, _job_id(reply), started, params))
    output = []
    for tag, job, started, params in admitted:
        result = _wait_job(SimpleNamespace(call=call, cancelled=lambda: False), job, tag)
        output.append({'files': _require_files(result), 'provenance': {**params, 'model': model, 'job_id': job,
            'seconds': round(time.monotonic()-started, 3), **_split_clocks(result)}})
    return output

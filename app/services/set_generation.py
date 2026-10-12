"""Shared local-image batch admission for props and room skins."""
from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

from services.game_tools import GameToolError, _job_id, _wait_job, _require_files, _split_clocks
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


def _admit(call, workspace: str, params: dict, tag: str) -> str:
    reply = call('generation.image', {'version': 2, 'intent_id': tag, 'input': {'workspace': workspace, 'output_name': tag, 'params': params}})
    return _job_id(reply)


def _wait(call, workspace: str, params: dict, tag: str, job: str) -> tuple[str, str, dict]:
    """The finished job. Intent ids are deterministic, so after a restart the journal answers with the id of a job
    that died with the old process: that request is admitted once more under a fresh intent (a nonce, so a later
    restart cannot replay the retry either) and a second loss is ``job_lost``."""
    ctx = SimpleNamespace(call=call, cancelled=lambda: False)
    try:
        return tag, job, _wait_job(ctx, job, tag)
    except GameToolError as error:
        if error.code != 'not_found':
            raise
    retry = f'{tag}-r{uuid.uuid4().hex[:6]}'
    job = _admit(call, workspace, params, retry)
    try:
        return retry, job, _wait_job(ctx, job, retry)
    except GameToolError as error:
        if error.code != 'not_found':
            raise
        raise GameToolError('job_lost', f'{tag}: the image job was lost twice; run it again') from error


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
            # Keep the positive prompt literal; unsupported negatives must not become subjects.
            params['negative_prompt'] = ''
        if request.get('refs'):
            params.update(image_refs=request['refs'], video_prompt_type='I')
        if request.get('guide'):
            params.update(image_guide=request['guide'], image_mask=request['mask'], video_prompt_type='VAG', model_mode=0)
        started = time.monotonic()
        admitted.append((tag, _admit(call, workspace, params, tag), started, params))
    output = []
    for tag, job, started, params in admitted:
        _, job, result = _wait(call, workspace, params, tag, job)
        output.append({'files': _require_files(result), 'provenance': {**params, 'model': model, 'job_id': job,
            'seconds': round(time.monotonic()-started, 3), **_split_clocks(result)}})
    return output

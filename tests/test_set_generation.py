"""Skin and prop pictures survive a job that died with the previous server process (pilot: 404 in 30 s)."""
import pytest

from services.game_tools import GameToolError
from services.set_generation import generate_batch

LOCAL_404 = {'_is_error': True, 'error': {'code': 'failed', 'message': 'Job not found', 'status': 404}}
MCP_404 = {'version': 1, 'status': 'failed', 'error': {'code': 'invalid_command', 'message': 'Job not found', 'retryable': False}}


def _server(lost, missing=LOCAL_404):
    """A journal that answers a known intent with its old job id, and a queue that forgot the ``lost`` jobs."""
    journal, admitted = {}, []

    def call(name, args):
        if name == 'media.options':
            return {'local': {'image': [{'id': 'qwen_image_21_turbo'}]}}
        if name == 'generation.image':
            admitted.append(args)
            job = journal.setdefault(args['intent_id'], f'job-{len(journal)+1}')
            return {'receipt': {'result': {'job_id': job}}}
        assert name == 'jobs.wait'
        job = args['input']['job_id']
        return missing if job in lost else {'job_id': job, 'status': 'completed', 'output_files': [f'{job}.png']}
    return call, admitted


@pytest.mark.parametrize('missing', [LOCAL_404, MCP_404])
def test_a_replayed_intent_whose_job_died_is_admitted_once_more(missing):
    call, admitted = _server({'job-1'}, missing)
    rows = generate_batch(call, 'pilot2', [{'prompt': 'terracotta tiles', 'resolution': '1024x1024', 'seed': 4}], 'skin-abc-floor-heal-0')
    first, retry = admitted
    assert rows[0]['files'] == ['job-2.png'] and rows[0]['provenance']['job_id'] == 'job-2'
    assert first['intent_id'] == 'skin-abc-floor-heal-0-0' and retry['intent_id'].startswith('skin-abc-floor-heal-0-0-r')
    assert retry['input']['output_name'] == retry['intent_id'], 'the output is named after the intent that made it'
    assert retry['input']['params'] == first['input']['params'], 'the same request, seed included'


def test_a_job_lost_twice_is_job_lost():
    call, admitted = _server({'job-1', 'job-2'})
    with pytest.raises(GameToolError) as caught:
        generate_batch(call, 'pilot2', [{'prompt': 'oak', 'resolution': '1024x1024'}], 'skin-abc-floor')
    assert caught.value.code == 'job_lost' and len(admitted) == 2


def test_a_failed_job_is_not_asked_for_again():
    def call(name, args):
        if name == 'media.options':
            return {'local': {'image': [{'id': 'qwen_image_21_turbo'}]}}
        if name == 'generation.image':
            calls.append(args)
            return {'job_id': 'job-1'}
        return {'job_id': 'job-1', 'status': 'failed', 'error': {'code': 'oom', 'message': 'model file not found'}}
    calls = []
    with pytest.raises(GameToolError) as caught:
        generate_batch(call, 'pilot2', [{'prompt': 'oak', 'resolution': '1024x1024'}], 'skin-abc-floor')
    assert caught.value.code == 'failed' and len(calls) == 1


def test_production_set_pictures_ask_with_a_new_intent_after_a_restart(tmp_path):
    """``production.image`` intents carry the set's attempt count, so a resumed run never replays a dead job;
    only the skin's own heal passes (``generate_batch``) use fixed intents."""
    from services.music_production import Production
    from services.production_models import _set_jobs
    intents = []

    def mcp(name, args):
        if name == 'media.options':
            return {'local': {'image': [{'id': 'qwen_image_21_turbo'}]}}
        intents.append(args['intent_id'])
        return {'receipt': {'result': {'job_id': f'job-{len(intents)}'}}}
    spec = {'sets': {'kitchen': {'kind': 'room', 'mold': 'cocina', 'skin': {'floor': {'texture': 'terracotta tiles'}}}},
            'style': {'image': 'paper'}}
    make = lambda: Production('ws', 'p', workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    first = make()
    _set_jobs(first, spec)
    first.save()
    _set_jobs(make(), spec)                     # the server restarted before the floor was built
    assert len(intents) == 2 and intents[0] != intents[1]

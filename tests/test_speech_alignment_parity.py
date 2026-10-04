"""The browser, MCP window and Wizard scene command share one phonetic policy."""
import asyncio
import base64
from contextlib import contextmanager
import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.scene3d_speech import create_scene3d_speech_router
from services import phoneme_analysis, phoneme_commands, phoneme_runtime, scene3d_speech, speech_alignment
from services.scene_commands import SceneCommands
from services.speech_file_commands import command_handlers, _window_wav
from tests.test_speech_file_commands import voice_file, envelope


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(create_scene3d_speech_router(), prefix='/speech-test')
    return TestClient(app)


@pytest.mark.parametrize('installed,engine,selected,fallback', [
    (True, 'auto', 'phoneme', None), (False, 'auto', 'rhubarb', 'phoneme_not_installed'),
    (True, 'phoneme', 'phoneme', None), (True, 'rhubarb', 'rhubarb', None),
])
def test_three_paths_share_audio_transcript_engine_and_source_clock(tmp_path, monkeypatch, client, installed, engine, selected, fallback):
    source = voice_file(tmp_path)
    monkeypatch.setattr(phoneme_runtime, 'capabilities', lambda: {'installed': installed})
    monkeypatch.setattr(phoneme_runtime, 'install', lambda: pytest.fail('Implicit download'))
    calls = []

    def analyzer(pcm, **options):
        calls.append((hashlib.sha256(pcm).hexdigest(), options))
        return {'mouthCues': [{'start': .1, 'end': .8, 'value': 'E'}], 'duration': 1,
                'recognizer': 'wav2vec2-phoneme' if selected == 'phoneme' else 'phonetic',
                'phonemes': [{'start': .1, 'end': .8, 'emission_end': .3, 'phoneme': 'ɔ'}]}

    monkeypatch.setattr(phoneme_analysis, 'analyze_voice', analyzer)
    monkeypatch.setattr(scene3d_speech, 'analyze_voice', analyzer)
    local = _window_wav(source, .5, 1)
    options = {'dialogue': 'four', 'language': 'en', 'engine': engine}
    ui = client.post('/speech-test/speech/analyze?isolate_vocals=true',
                     json={'wavBase64': base64.b64encode(local).decode(), **options}).json()
    mcp = asyncio.run(command_handlers(lambda _: tmp_path)['audio.mouth_cues'](
        envelope(start=.5, isolate_vocals=True, **options)))['result']
    doc = {'version': 1, 'units': 'meters', 'up': 'y', 'duration': 2, 'camera': {}, 'light': {},
           'slots': [{'id': 'hero', 'media': 'model3d', 'sourceUrl': '/hero.glb',
                      'speech': {'version': 1, 'cues': [], 'morph': True, 'style': 'toon-bold', 'face': {'center': [.1, .2, .3]}}}]}
    wizard = SceneCommands(workspace_dir=lambda _: tmp_path).execute({
        'version': 1, 'operation': 'scenes.speech.prepare', 'input': {'document': doc,
        'slot_id': 'hero', 'clip_id': 'line', 'workspace': 'song', 'audio_filename': source.name,
        'text': 'four', 'language': 'en', 'engine': engine, 'isolate_vocals': True, 'start': .25, 'end': 1.25, 'offset': .5}})
    speech = wizard['result']['document']['slots'][0]['speech']
    clip = speech['clips'][0]
    assert ui['engine'] == mcp['engine'] == selected
    assert ui['driver'] == mcp['driver'] == clip['driver'] == selected + '-vocals'
    assert ui['fallbackReason'] == mcp['fallbackReason'] == clip['analysisFallback'] == fallback
    assert clip['analysisEngine'] == engine and clip['language'] == 'en'
    assert mcp['mouthCues'] == [{'start': .6, 'end': 1.3, 'value': 'E'}]
    assert clip['cues'] == [{'start': .6, 'end': 1.3, 'viseme': 'O'}]
    assert mcp['phonemes'][0]['emission_end'] == .8
    assert len(calls) == 3 and all(call == calls[0] for call in calls)
    assert speech['morph'] is True and speech['face'] == doc['slots'][0]['speech']['face']
    assert 'clips' not in doc['slots'][0]['speech']


def test_explicit_missing_phonemes_never_fall_back_or_install(monkeypatch, client):
    from tests.test_scene3d_speech import wav
    monkeypatch.setattr(phoneme_runtime, 'capabilities', lambda: {'installed': False})
    monkeypatch.setattr(phoneme_runtime, 'install', lambda: pytest.fail('Implicit download'))
    monkeypatch.setattr(scene3d_speech, 'analyze_voice', lambda *a, **k: pytest.fail('Silent fallback'))
    response = client.post('/speech-test/speech/analyze?engine=phoneme', content=wav(), headers={'Content-Type': 'audio/wav'})
    assert response.status_code == 503 and 'Install the phoneme engine' in response.json()['detail']


def test_installation_status_and_explicit_install_share_ui_mcp_service(monkeypatch, client):
    monkeypatch.setattr(phoneme_runtime, 'capabilities', lambda: {'installed': False})
    calls = []
    monkeypatch.setattr(phoneme_runtime, 'install', lambda: calls.append('install') or {'installed': True})
    setup = phoneme_commands.command_handlers(lambda _: None)[phoneme_commands.SETUP]
    for install in (False, True):
        command = {'version': 1, 'input': {'install': install}}
        ui = client.post('/speech-test/speech/phonemes/setup', json=command)
        mcp = asyncio.run(setup(command))
        assert ui.status_code == 200 and ui.json() == mcp
    assert calls == ['install', 'install']
    assert client.post('/speech-test/speech/phonemes/setup', json={'version': True, 'input': {}}).status_code == 422


def test_shared_analysis_acquires_cpu_lane_and_never_retries_another_engine(monkeypatch):
    from tests.test_scene3d_speech import wav
    monkeypatch.setattr(phoneme_runtime, 'capabilities', lambda: {'installed': True})
    seen = []

    @contextmanager
    def acquire(lane, **kwargs):
        seen.append(lane)
        yield

    monkeypatch.setattr(speech_alignment.resource_scheduler.coordinator, 'acquire', acquire)
    monkeypatch.setattr(scene3d_speech, 'analyze_voice', lambda *a, **k: pytest.fail('Wrong engine'))
    def broken(*args, **kwargs):
        raise scene3d_speech.SpeechAnalysisUnavailable('alignment failed')
    monkeypatch.setattr(phoneme_analysis, 'analyze_voice', broken)
    with pytest.raises(scene3d_speech.SpeechAnalysisUnavailable, match='alignment failed'):
        speech_alignment.analyze_voice(wav())
    assert seen == [speech_alignment.resource_scheduler.cpu_lane('speech-analysis')]


def test_adding_a_turn_preserves_the_legacy_voice_analysis_settings():
    from services.scene_speech_command import with_speech_clip
    prior = {'audio': {'filename': 'voice.wav'}, 'cues': [], 'start': 0, 'end': 1,
             'driver': 'phoneme-vocals', 'analysisEngine': 'auto', 'analysisFallback': None,
             'text': 'Four', 'language': 'en'}
    document = with_speech_clip(prior, {'id': 'next', 'start': 1, 'end': 2}, 2)
    assert document['clips'][0] == {**prior, 'id': 'legacy-voice'}
    assert 'clips' not in prior

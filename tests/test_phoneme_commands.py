import json
import subprocess

import pytest

from services import phoneme_commands as commands
from services import phoneme_runtime, phoneme_analysis
from services.scene3d_speech import SpeechAnalysisUnavailable
from tests.test_speech_file_commands import voice_file, envelope


def test_uninstalled_runtime_refuses_inference_and_never_downloads(tmp_path, monkeypatch):
    source = voice_file(tmp_path)
    window, _, root = commands.freeze_window(envelope(), lambda _: tmp_path)
    monkeypatch.setattr(phoneme_runtime, 'capabilities', lambda: {'installed': False})
    monkeypatch.setattr(phoneme_runtime, 'install', lambda: pytest.fail('Implicit install'))
    with pytest.raises(SpeechAnalysisUnavailable):
        commands.analyze_window(window, source, root)


def test_window_keeps_source_clock_and_transcript_sensitive_cache(tmp_path, monkeypatch):
    from services import speech_analysis_cache
    monkeypatch.setenv('SPEECH_ANALYSIS_CACHE_DIR', str(tmp_path / 'cache'))
    speech_analysis_cache.reset_runtime_state()
    source = voice_file(tmp_path)
    monkeypatch.setattr(phoneme_runtime, 'capabilities', lambda: {'installed': True})
    calls = []
    def worker(pcm, dialogue, language):
        calls.append((dialogue, language))
        return json.dumps({'mouthCues': [{'start': .1, 'end': .9, 'value': 'E'}],
                           'phonemes': [{'start': .1, 'end': .9, 'emission_end': .3, 'phoneme': 'ɔ'}], 'duration': 1}).encode()
    monkeypatch.setattr(phoneme_analysis, '_worker', worker)
    window, _, root = commands.freeze_window(envelope(start=1, dialogue='four', language='en'), lambda _: tmp_path)
    result = commands.analyze_window(window, source, root)
    assert result['phonemes'][0]['start'] == pytest.approx(1.1)
    assert result['phonemes'][0]['emission_end'] == pytest.approx(1.3)
    assert result['mouthCues'][0] == {'start': 1.1, 'end': 1.9, 'value': 'E'}
    assert json.loads((root / result['file']).read_text())['phonemes'] == result['phonemes']
    assert commands.analyze_window(window, source, root)['file'] == result['file']
    other, _, _ = commands.freeze_window(envelope(start=1, dialogue='more', language='en'), lambda _: tmp_path)
    assert commands.analyze_window(other, source, root)['file'] != result['file']
    assert calls == [('four', 'en'), ('more', 'en')]


def test_worker_cannot_use_cuda_or_inherit_mcp_secret(monkeypatch):
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES', '0')
    monkeypatch.setenv('HOCUS_MCP_TOKEN', 'private-test-value')
    seen = []
    def run(argv, **options):
        seen.append(options)
        assert argv[-1] == 'services.phoneme_worker'
        assert options['env']['CUDA_VISIBLE_DEVICES'] == ''
        assert 'HOCUS_MCP_TOKEN' not in options['env']
        assert json.loads(options['input'])['language'] == 'en-us'
        return subprocess.CompletedProcess(argv, 0, b'{}', b'')
    monkeypatch.setattr(phoneme_analysis.subprocess, 'run', run)
    assert phoneme_analysis._worker(b'pcm', 'four', 'en') == b'{}'
    assert len(seen) == 1


@pytest.mark.parametrize('payload', [{'version': True, 'input': {}}, {'version': 1, 'input': {'install': 1}}, {'version': 1, 'input': {'path': '/tmp'}}])
def test_install_requires_exact_explicit_boolean(payload):
    with pytest.raises(ValueError):
        commands._setup_input(payload)


def test_native_audio_boundary_registers_both_commands(tmp_path):
    from services.song_analysis import command_catalog, command_handlers
    names = {x['name'] for x in command_catalog()}
    assert {commands.CUES, commands.SETUP} <= names
    assert {commands.CUES, commands.SETUP} <= command_handlers(lambda _: tmp_path).keys()

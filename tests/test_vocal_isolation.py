from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
from services import vocal_isolation as vocals
from services.scene3d_speech import SpeechAnalysisUnavailable
from services.speech_analysis_cache import reset_runtime_state
from services.vocal_isolation_worker import installed_separator
from services.vocal_isolation_worker import inference_input
import io
import wave


@pytest.fixture(autouse=True)
def _speech_analysis_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEECH_ANALYSIS_CACHE_DIR", str(tmp_path / "speech-cache"))
    reset_runtime_state()
    yield
    reset_runtime_state()


def wav(seconds=1):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b'\0\0' * int(seconds * 16000))
    return output.getvalue()



def test_absent_model_rejects_without_starting_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(vocals, 'MODEL_DIR', tmp_path)
    monkeypatch.setattr(vocals.subprocess, 'run', lambda *a, **k: pytest.fail('Must not start inference or download'))
    assert vocals.isolation_capability()['available'] is False
    with pytest.raises(SpeechAnalysisUnavailable, match='already be installed'):
        vocals.isolate_voice(wav())


def test_worker_is_cpu_offline_and_preserves_timing(monkeypatch):
    monkeypatch.setattr(vocals, 'isolation_capability', lambda: {'available': True})
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert kwargs['env']['CUDA_VISIBLE_DEVICES'] == '-1'
        assert kwargs['env']['HF_HUB_OFFLINE'] == '1'
        assert kwargs['timeout'] == 900
        Path(args[3]).write_bytes(Path(args[2]).read_bytes())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(vocals.subprocess, 'run', run)
    source = wav(1.123)
    assert vocals.isolate_voice(source) == source
    assert not Path(calls[0][2]).exists()


def test_timeout_releases_lock_and_cleans_own_files(monkeypatch):
    monkeypatch.setattr(vocals, 'isolation_capability', lambda: {'available': True})
    folders = []
    def run(args, **kwargs):
        folders.append(Path(args[2]).parent)
        raise subprocess.TimeoutExpired(args, 900)
    monkeypatch.setattr(vocals.subprocess, 'run', run)
    for _ in range(2):
        with pytest.raises(SpeechAnalysisUnavailable, match='15 minutes'):
            vocals.isolate_voice(wav())
    assert len(folders) == 2 and all(not folder.exists() for folder in folders)


def test_concurrent_separation_cannot_load_second_model(monkeypatch):
    monkeypatch.setattr(vocals, 'isolation_capability', lambda: {'available': True})
    assert vocals._LOCK.acquire(blocking=False)
    try:
        with pytest.raises(SpeechAnalysisUnavailable, match='Another'):
            vocals.isolate_voice(wav())
    finally:
        vocals._LOCK.release()


def test_separator_never_uses_online_catalog_or_downloads(tmp_path):
    class Base:
        def list_supported_model_files(self):
            pytest.fail('Online model discovery is forbidden')
    name = vocals.MODEL_NAME
    for extension in ('.ckpt', '.yaml'):
        (tmp_path / (name + extension)).write_text('installed')
    separator = installed_separator(Base, tmp_path, name)()
    result = separator.download_model_files(name + '.ckpt')
    assert result[1] == 'MDXC' and result[3] == str(tmp_path / (name + '.ckpt'))
    with pytest.raises(RuntimeError, match='disabled'):
        separator.download_file_if_not_exists('https://example.invalid', 'unused')
    with pytest.raises(ValueError):
        separator.download_model_files('different.ckpt')


def test_short_inputs_are_padded_without_overwriting_original(tmp_path):
    source = tmp_path / 'voice.wav'
    original = wav(.5)
    source.write_bytes(original)
    padded = Path(inference_input(source, tmp_path))
    assert padded != source and source.read_bytes() == original
    with wave.open(str(padded), 'rb') as audio:
        assert audio.getnframes() == 3 * 16000
        assert audio.getframerate() == 16000
    source.write_bytes(wav(6))
    assert inference_input(source, tmp_path) == str(source)

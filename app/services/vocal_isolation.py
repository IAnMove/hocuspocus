"""Optional installed-only RoFormer speech analysis, isolated from the GPU runtime."""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from services.scene3d_speech import SpeechAnalysisUnavailable, validate_voice_wav
from services.speech_analysis_cache import file_identity, isolation_material, remember

MODEL_NAME = 'model_bs_roformer_ep_317_sdr_12.9755'
MODEL_DIR = Path(__file__).resolve().parents[1] / 'ckpts' / 'roformer'
ISOLATION_PARAMS = {
    'device': 'cpu', 'segmentSize': 256, 'overlap': 2, 'pitchShift': 0,
    'stem': 'Vocals', 'batchSize': 1,
}
_LOCK = threading.BoundedSemaphore(1)


def isolation_capability():
    installed = all((MODEL_DIR / (MODEL_NAME + ext)).is_file() for ext in ('.ckpt', '.yaml'))
    separator = importlib.util.find_spec('audio_separator') is not None
    available = installed and separator
    if available:
        reason = 'ready'
    elif not installed:
        reason = 'optional_model_missing'
    else:
        reason = 'audio_separator_missing'
    return {'available': available, 'model': 'BS-RoFormer', 'device': 'cpu',
            'maxSeconds': 90, 'downloads': False, 'reason': reason}


def isolation_key_material() -> dict:
    return {
        'model': MODEL_NAME,
        'modelFiles': [file_identity(MODEL_DIR / (MODEL_NAME + ext)) for ext in ('.ckpt', '.yaml')],
        'params': {**ISOLATION_PARAMS, 'separator': _separator_version()},
    }


def isolate_voice(data: bytes) -> bytes:
    duration = validate_voice_wav(data)
    material = isolation_material(data, duration, isolation_key_material())
    return remember(material, lambda: _isolate_uncached(data, duration), '.wav')


def _separator_version() -> str:
    try:
        from importlib.metadata import version
        return version('audio-separator')
    except Exception:
        return 'missing'


def _isolate_uncached(data: bytes, duration: float) -> bytes:
    capability = isolation_capability()
    if not capability['available']:
        raise SpeechAnalysisUnavailable(
            'Optional BS-RoFormer model and audio-separator must already be installed. '
            f"No files were downloaded ({capability['reason']}).")
    if not _LOCK.acquire(blocking=False):
        raise SpeechAnalysisUnavailable('Another vocal isolation is running. Try again shortly.')
    try:
        return _run_isolation_worker(data, duration)
    finally:
        _LOCK.release()


def _run_isolation_worker(data: bytes, duration: float) -> bytes:
    with tempfile.TemporaryDirectory(prefix='hocuspocus-vocals-') as folder:
        source, target = Path(folder) / 'source.wav', Path(folder) / 'voice.wav'
        source.write_bytes(data)
        environment = {**os.environ, 'CUDA_VISIBLE_DEVICES': '-1', 'HF_HUB_OFFLINE': '1',
                       'TRANSFORMERS_OFFLINE': '1', 'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2'}
        try:
            diagnostic = Path(folder) / 'worker.log'
            with diagnostic.open('wb') as log:
                done = subprocess.run([sys.executable, str(Path(__file__).with_name('vocal_isolation_worker.py')),
                                       str(source), str(target), str(MODEL_DIR), MODEL_NAME],
                                      env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=log, timeout=900, check=False,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SpeechAnalysisUnavailable('Local vocal isolation failed or exceeded 15 minutes. Existing lip cues are unchanged.') from error
        if done.returncode or not target.is_file() or target.stat().st_size > 3_000_000:
            _log_isolation_failure(diagnostic)
            raise SpeechAnalysisUnavailable('Local vocal isolation failed. Check the installed model and audio-separator; no downloads were attempted.')
        result = target.read_bytes()
        if abs(validate_voice_wav(result) - duration) > 1 / 16000:
            raise SpeechAnalysisUnavailable('Isolated voice changed the source timing.')
        return result


def _log_isolation_failure(diagnostic: Path) -> None:
    with diagnostic.open('rb') as log:
        log.seek(max(0, diagnostic.stat().st_size - 8000))
        logging.getLogger(__name__).warning('Local vocal isolation worker failed: %s', log.read().decode(errors='replace'))

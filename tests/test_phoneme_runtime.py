import hashlib
import importlib.util
import sys
from types import SimpleNamespace

import pytest

from services import phoneme_runtime as runtime


def test_install_verifies_pinned_weights_before_enabling_runtime(tmp_path, monkeypatch):
    data = b'pinned-test-weights'
    monkeypatch.setattr(runtime, 'DOWNLOAD_BYTES', len(data))
    monkeypatch.setattr(runtime, 'WEIGHT_SHA', hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(importlib.util, 'find_spec', lambda _: object())
    calls = []
    def download(repo, name, **options):
        calls.append((repo, name, options['revision']))
        (options['local_dir'] / name).write_bytes(data)
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(hf_hub_download=download))
    assert not runtime.capabilities(tmp_path)['installed']
    assert runtime.install(tmp_path)['installed']
    assert len(calls) == len(runtime.FILES)
    assert all(repo == runtime.REPO and revision == runtime.REVISION for repo, _, revision in calls)
    assert runtime.install(tmp_path)['installed']
    assert len(calls) == len(runtime.FILES)


def test_corrupt_weights_do_not_mark_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, 'find_spec', lambda _: object())
    def download(repo, name, **options):
        (options['local_dir'] / name).write_bytes(b'corrupt')
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(hf_hub_download=download))
    with pytest.raises(RuntimeError, match='checksum'):
        runtime.install(tmp_path)
    assert not (tmp_path / 'verified.json').exists()
    assert not runtime.capabilities(tmp_path)['installed']

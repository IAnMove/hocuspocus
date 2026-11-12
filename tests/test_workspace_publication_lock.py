"""Windows publication contention waits; invalid handles still fail immediately."""
import errno
import importlib
import sys
from types import SimpleNamespace
import pytest


def test_windows_lock_waits_beyond_ten_retries(tmp_path, monkeypatch):
    module = importlib.import_module('services.workspace_store_lock')
    attempts = []

    def locking(_fd, mode, _length):
        attempts.append(mode)
        if mode != 0 and len(attempts) <= 12:
            raise OSError(errno.EACCES, 'lock held by another publisher')

    monkeypatch.setattr(module, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setitem(sys.modules, 'msvcrt', SimpleNamespace(LK_LOCK=1, LK_NBLCK=2, LK_UNLCK=0, locking=locking))
    monkeypatch.setattr(module, 'time', SimpleNamespace(sleep=lambda _seconds: None), raising=False)
    with module.workspace_store_lock(tmp_path / '.publication'):
        assert len(attempts) == 13
    assert attempts[-1] == 0


def test_windows_lock_does_not_retry_an_invalid_handle(tmp_path, monkeypatch):
    module = importlib.import_module('services.workspace_store_lock')

    def locking(*_args):
        raise OSError(errno.EBADF, 'invalid handle')

    monkeypatch.setattr(module, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setitem(sys.modules, 'msvcrt', SimpleNamespace(LK_LOCK=1, LK_NBLCK=2, LK_UNLCK=0, locking=locking))
    with pytest.raises(OSError) as error:
        with module.workspace_store_lock(tmp_path / '.publication'):
            pytest.fail('invalid handle acquired a lock')
    assert error.value.errno == errno.EBADF

"""Production links import on Windows and serialize writers across processes."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest


APP = Path(__file__).resolve().parents[1] / "app"


def test_import_without_fcntl():
    code = """
import builtins
original = builtins.__import__
def windows_import(name, *args, **kwargs):
    if name == 'fcntl':
        raise ModuleNotFoundError("No module named 'fcntl'")
    return original(name, *args, **kwargs)
builtins.__import__ = windows_import
from services.production_project_link import resolve_production_project
assert callable(resolve_production_project)
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=APP,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_windows_lock_releases_after_body_error(tmp_path, monkeypatch):
    link = importlib.import_module("services.production_project_link")
    locks = importlib.import_module("services.workspace_store_lock")
    calls = []

    def locking(fd, mode, length):
        calls.append((mode, length, os.lseek(fd, 0, os.SEEK_CUR)))

    monkeypatch.setattr(locks, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(
        LK_LOCK=1, LK_NBLCK=2, LK_UNLCK=0, locking=locking))
    with pytest.raises(RuntimeError, match="body failed"):
        with link._exclusive(str(tmp_path)):
            raise RuntimeError("body failed")
    assert calls in ([(1, 1, 0), (0, 1, 0)], [(2, 1, 0), (0, 1, 0)])
    assert (tmp_path / (link.LINK_FILENAME + ".lock")).is_file()


def test_acquisition_failure_releases_thread_lock(tmp_path, monkeypatch):
    link = importlib.import_module("services.production_project_link")
    original = link.workspace_store_lock
    entered = threading.Event()

    def fail(_path):
        raise OSError("lock unavailable")

    monkeypatch.setattr(link, "workspace_store_lock", fail)
    with pytest.raises(OSError, match="lock unavailable"):
        with link._exclusive(str(tmp_path)):
            pytest.fail("a failed lock must not admit a writer")
    monkeypatch.setattr(link, "workspace_store_lock", original)

    def retry():
        with link._exclusive(str(tmp_path)):
            entered.set()

    thread = threading.Thread(target=retry, daemon=True)
    thread.start()
    thread.join(timeout=3)
    assert entered.is_set(), "a failed acquisition leaked the thread lock"


def test_real_process_lock_serializes_writers(tmp_path):
    from services.production_project_link import _exclusive

    marker = tmp_path / "entered"
    code = """
import sys
from pathlib import Path
from services.production_project_link import _exclusive
print('ready', flush=True)
with _exclusive(sys.argv[1]):
    Path(sys.argv[2]).write_text('entered')
"""
    child = None
    try:
        with _exclusive(str(tmp_path)):
            child = subprocess.Popen([sys.executable, "-c", code, str(tmp_path), str(marker)],
                                     cwd=APP, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True)
            assert child.stdout.readline().strip() == "ready"
            with pytest.raises(subprocess.TimeoutExpired):
                child.communicate(timeout=0.2)
            assert not marker.exists()
        _, errors = child.communicate(timeout=10)
        assert child.returncode == 0, errors
        assert marker.read_text() == "entered"
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate(timeout=10)

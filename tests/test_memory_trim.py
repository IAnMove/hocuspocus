"""Freed model memory goes back to the system instead of piling up in malloc arenas."""
import sys
import threading

import pytest

from services import memory_trim


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="glibc malloc_trim")
def test_memory_freed_on_a_worker_thread_is_returned(monkeypatch):
    monkeypatch.delenv("HOCUS_MALLOC_TRIM", raising=False)
    if memory_trim._trim_function() is None:
        pytest.skip("not glibc")
    held = []

    def job():
        # Many 8 MiB buffers, like weights below the mmap threshold, freed on the same thread.
        held.extend(bytearray(8 * 2**20) for _ in range(48))
        held.clear()

    thread = threading.Thread(target=job)
    thread.start()
    thread.join()
    before = memory_trim._resident_bytes()
    memory_trim.trim_process_heap("a test")
    assert memory_trim._resident_bytes() <= before


def test_trimming_can_be_turned_off_and_is_a_no_op_without_glibc(monkeypatch):
    calls = []
    monkeypatch.setattr(memory_trim, "_trim_function", lambda: calls.append(1) or None)
    monkeypatch.setenv("HOCUS_MALLOC_TRIM", "0")
    assert memory_trim.trim_process_heap() == 0 and calls == []
    monkeypatch.delenv("HOCUS_MALLOC_TRIM")
    assert memory_trim.trim_process_heap() == 0 and calls == [1]


def test_a_large_release_is_logged(monkeypatch, capsys):
    sizes = iter([5 * 2**30, 2 * 2**30])
    monkeypatch.setattr(memory_trim, "_trim_function", lambda: (lambda pad: 1))
    monkeypatch.setattr(memory_trim, "_resident_bytes", lambda: next(sizes))
    monkeypatch.delenv("HOCUS_MALLOC_TRIM", raising=False)
    assert memory_trim.trim_process_heap("releasing the model") == 3 * 2**30
    assert "Returned 3.0 GiB to the system after releasing the model" in capsys.readouterr().out

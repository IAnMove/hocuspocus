"""Give freed heap memory back to the system after a model or a job lets go of it.

Each generation job runs on its own thread, and glibc gives busy threads their
own malloc arenas. Weights copied into an arena stay resident after the model
is released: an idle server held 35 GiB of freed arena heaps (1,000 regions
of up to 64 MiB) after a night of TTS, music and image jobs, and a later load
was OOM-killed at 50 GB. ``malloc_trim(0)`` returns the free pages; loading a
2.4 GB weights file on a thread and freeing it left RSS at 2.46 GiB, and the
trim brought it back to 0.45 GiB.

Linux with glibc only. Elsewhere, or with ``HOCUS_MALLOC_TRIM=0``, it does nothing.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import threading
import time
from typing import Any

LOG_THRESHOLD_BYTES = 256 * 2**20

_lock = threading.Lock()
_resolved = False
_malloc_trim: Any = None


def _trim_function() -> Any:
    global _resolved, _malloc_trim
    if not _resolved:
        _resolved = True
        if sys.platform.startswith("linux"):
            try:
                libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
            except OSError:
                libc = None
            function = getattr(libc, "malloc_trim", None) if libc is not None else None
            if function is not None:
                function.argtypes = [ctypes.c_size_t]
                function.restype = ctypes.c_int
                _malloc_trim = function
    return _malloc_trim


def _resident_bytes() -> int | None:
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


def trim_process_heap(reason: str = "") -> int:
    """Return free malloc pages to the system. The result is the RSS drop in bytes."""
    if os.environ.get("HOCUS_MALLOC_TRIM", "1").strip() == "0":
        return 0
    function = _trim_function()
    if function is None:
        return 0
    with _lock:
        before = _resident_bytes()
        started = time.monotonic()
        function(0)
        after = _resident_bytes()
    freed = max(0, before - after) if before is not None and after is not None else 0
    if freed >= LOG_THRESHOLD_BYTES:
        print(f"[Memory] Returned {freed / 2**30:.1f} GiB to the system after {reason or 'a release'} "
              f"in {time.monotonic() - started:.2f} s", flush=True)
    return freed

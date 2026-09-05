#!/usr/bin/env python3
"""After overnight_surprise.py: iconic movie scenes with clay/cartoon and kinder endings."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MAESTRO_API", "http://127.0.0.1:42003")

from overnight_surprise import log, run_iconic_scenes, wait_idle


def surprise_running() -> bool:
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except OSError:
            continue
        if "overnight_surprise.py" in cmdline and "overnight_iconic.py" not in cmdline:
            return True
    return False


def main() -> None:
    log("iconic waiter: hold until overnight_surprise.py finishes")
    while surprise_running():
        log("iconic waiter: overnight_surprise.py still running")
        time.sleep(30)
    wait_idle("after-overnight-before-iconic")
    run_iconic_scenes()
    log("iconic waiter done")


if __name__ == "__main__":
    main()

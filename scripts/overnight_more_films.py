#!/usr/bin/env python3
"""After the current resume: Saving Private Ryan and Enemy Mine claymation."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("MAESTRO_API", "http://127.0.0.1:42004")
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from overnight_surprise import log, run_war_and_alien_scenes, wait_idle


def process_has(needle: str) -> bool:
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except OSError:
            continue
        if needle in cmdline and "overnight_more_films.py" not in cmdline:
            return True
    return False


def main() -> None:
    log("more-films waiter: hold for overnight_resume.py")
    while process_has("overnight_resume.py"):
        log("more-films waiter: resume still running")
        time.sleep(30)
    wait_idle("before-ryan-enemy")
    run_war_and_alien_scenes()
    log("more-films done")


if __name__ == "__main__":
    main()

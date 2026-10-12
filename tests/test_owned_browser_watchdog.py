"""The headless renderer is watched by its frames, not by the clock: no new frame for too long means it is stuck."""
import subprocess
import sys
import time

import pytest

from services import world3d_export
from services.world3d_export import World3DExportCancelled, _wait_owned_browser, render_stall_seconds


def child(code: str, staging):
    return subprocess.Popen([sys.executable, "-c", code, str(staging)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)


WRITES_THEN_HANGS = """
import json, sys, time
staging = sys.argv[1]
for frame in (1, 2):
    open(f"{staging}/progress.json", "w").write(json.dumps({"current": frame, "total": 10}))
    time.sleep(0.4)
time.sleep(60)
"""


def test_a_renderer_that_stops_writing_frames_is_killed_and_the_export_fails(tmp_path):
    proc = child(WRITES_THEN_HANGS, tmp_path)
    seen = []
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="stalled: no new frame for 1 s .frame 2/10"):
        _wait_owned_browser(proc, lambda: False, tmp_path, lambda current, total: seen.append((current, total)), stall_seconds=1.0)
    assert proc.poll() is not None, "the process group was killed"
    assert time.monotonic() - started < 10
    assert seen == [(1, 10), (2, 10)], "each frame was published as it was written"


def test_a_slow_renderer_that_keeps_writing_frames_is_left_alone(tmp_path):
    code = """
import json, sys, time
staging = sys.argv[1]
for frame in range(1, 6):
    time.sleep(0.3)
    open(f"{staging}/progress.json", "w").write(json.dumps({"current": frame, "total": 5}))
"""
    proc = child(code, tmp_path)
    seen = []
    _wait_owned_browser(proc, lambda: False, tmp_path, lambda current, total: seen.append(current), stall_seconds=1.0)
    assert proc.returncode == 0 and seen == [1, 2, 3, 4, 5]


def test_cancelling_kills_the_whole_process_group(tmp_path):
    code = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"
    proc = child(code, tmp_path)
    time.sleep(0.5)
    children = subprocess.run(["pgrep", "-g", str(proc.pid)], capture_output=True, text=True).stdout.split()
    assert len(children) >= 2, children
    with pytest.raises(World3DExportCancelled):
        _wait_owned_browser(proc, lambda: True, tmp_path, None, stall_seconds=30)
    time.sleep(0.3)
    assert subprocess.run(["pgrep", "-g", str(proc.pid)], capture_output=True, text=True).stdout.split() == []


def test_the_stall_limit_defaults_to_ten_minutes_and_reads_the_environment(monkeypatch):
    monkeypatch.delenv(world3d_export.STALL_SECONDS_ENV, raising=False)
    assert render_stall_seconds() == 600.0
    monkeypatch.setenv(world3d_export.STALL_SECONDS_ENV, "90")
    assert render_stall_seconds() == 90.0
    monkeypatch.setenv(world3d_export.STALL_SECONDS_ENV, "nonsense")
    assert render_stall_seconds() == 600.0


def test_the_renderer_script_still_writes_progress_per_frame():
    assert "progress.json" in world3d_export._OWNED_BROWSER_JS

"""A stop request must end the server process, promptly and with its exit hooks.

Each test runs a real server in a subprocess with the two things that used to
keep HocusPocus alive after a stop: an open streaming connection (browsers on
the LAN) and a non-daemon thread that never finishes (model workers).
"""

from __future__ import annotations

import http.client
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytest.importorskip("uvicorn")
pytest.importorskip("fastapi")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX signals")

APP_DIR = Path(__file__).resolve().parents[1] / "app"

SERVER = textwrap.dedent(
    """
    import asyncio, atexit, os, sys, threading, time
    sys.path.insert(0, os.environ["APP_DIR"])
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()

    @app.get("/block")
    async def block():
        # A synchronous call that never gives the event loop back.
        time.sleep(10**6)

    @app.get("/stream")
    async def stream():
        async def ticks():
            while True:
                yield b"data: tick\\n\\n"
                await asyncio.sleep(0.2)
        return StreamingResponse(ticks(), media_type="text/event-stream")

    def hook():
        if os.environ.get("STUCK_HOOK"):
            time.sleep(10**6)
        with open(os.environ["MARKER"], "w") as handle:
            handle.write("hooks ran")

    atexit.register(hook)
    threading.Thread(target=lambda: time.sleep(10**6), daemon=False).start()
    from services.server_lifecycle import run_until_stopped
    run_until_stopped(app, host="127.0.0.1", port=int(os.environ["PORT"]))
    """
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _start(tmp_path: Path, shell: bool = False, **env: str):
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    port = _free_port()
    environment = {
        **os.environ,
        "APP_DIR": str(APP_DIR),
        "PORT": str(port),
        "MARKER": str(tmp_path / "marker"),
        "HOCUSPOCUS_GRACEFUL_SECONDS": "1",
        **env,
    }
    command = [sys.executable, str(script)]
    if shell:
        # Like Pinokio: the server runs as the child of a shell.
        command = ["bash", "-c", f"'{sys.executable}' '{script}'; exit 0"]
    process = subprocess.Popen(command, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        process.kill()
        pytest.fail("server did not start")
    # Hold a streaming response open, as a browser on the LAN does.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", "/stream")
    response = connection.getresponse()
    assert response.read1(64).startswith(b"data:")
    return process, connection, port


def _server_pids(shell_pid: int) -> list[int]:
    out = subprocess.run(["pgrep", "-P", str(shell_pid)], capture_output=True, text=True).stdout
    return [int(pid) for pid in out.split()]


def _wait_gone(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        # A reaped-by-init zombie is gone for our purposes.
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as stat:
                if stat.read().split()[2] == "Z":
                    return True
        except OSError:
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("sig", ["SIGINT", "SIGTERM", "SIGHUP"])
def test_stop_signal_ends_the_process_with_its_exit_hooks(tmp_path, sig):
    process, connection, _port = _start(tmp_path)
    started = time.monotonic()
    process.send_signal(getattr(signal, sig))
    try:
        code = process.wait(timeout=15)
    finally:
        connection.close()
        if process.poll() is None:
            process.kill()
    assert code == 0
    assert time.monotonic() - started < 10
    assert (tmp_path / "marker").read_text(encoding="utf-8") == "hooks ran"


def test_a_repeated_sigterm_forces_the_stop(tmp_path):
    process, connection, _port = _start(tmp_path, HOCUSPOCUS_GRACEFUL_SECONDS="60")
    process.send_signal(signal.SIGTERM)
    time.sleep(0.5)
    process.send_signal(signal.SIGTERM)
    try:
        assert process.wait(timeout=15) == 0
    finally:
        connection.close()
        if process.poll() is None:
            process.kill()


def test_a_stuck_exit_hook_cannot_keep_the_process_alive(tmp_path):
    process, connection, _port = _start(tmp_path, STUCK_HOOK="1", HOCUSPOCUS_EXIT_HOOKS_SECONDS="1")
    process.send_signal(signal.SIGTERM)
    try:
        assert process.wait(timeout=15) == 0
    finally:
        connection.close()
        if process.poll() is None:
            process.kill()


def test_the_watchdog_ends_a_shutdown_that_hangs(tmp_path):
    process, connection, port = _start(tmp_path, HOCUSPOCUS_WATCHDOG_SECONDS="3")
    blocker = socket.create_connection(("127.0.0.1", port))
    blocker.sendall(b"GET /block HTTP/1.1\r\nHost: x\r\n\r\n")
    time.sleep(0.5)
    started = time.monotonic()
    process.send_signal(signal.SIGTERM)
    try:
        assert process.wait(timeout=20) == 1
    finally:
        blocker.close()
        connection.close()
        if process.poll() is None:
            process.kill()
    assert time.monotonic() - started < 12


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="parent-death signal is Linux-only")
def test_killing_the_launching_shell_stops_the_server(tmp_path):
    shell, connection, _port = _start(tmp_path, shell=True)
    try:
        servers = _server_pids(shell.pid)
        assert len(servers) == 1
        shell.kill()
        shell.wait(timeout=5)
        assert _wait_gone(servers[0], 15), "server outlived its shell"
        assert (tmp_path / "marker").read_text(encoding="utf-8") == "hooks ran"
    finally:
        connection.close()
        for pid in _server_pids(shell.pid):
            os.kill(pid, signal.SIGKILL)

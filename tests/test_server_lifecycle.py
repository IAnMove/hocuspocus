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
    from services.server_lifecycle import bind_listener, run_until_stopped
    if os.environ.get("PREBIND"):
        # As launch.py does: own the port before announcing it, then hand the socket to Uvicorn.
        listener, port = bind_listener("127.0.0.1", int(os.environ["PORT"]))
        print(f"serving on {port}", flush=True)
        run_until_stopped(app, host="127.0.0.1", port=port, sockets=[listener])
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


def test_bind_listener_owns_the_preferred_port_or_falls_forward_to_the_next_free_one():
    from services.server_lifecycle import bind_listener
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    busy = blocker.getsockname()[1]
    try:
        listener, port = bind_listener("127.0.0.1", busy, span=3)
        try:
            assert port != busy and busy < port <= busy + 3
            assert listener.getsockname()[1] == port, "the socket is already bound and listening"
            with socket.create_connection(("127.0.0.1", port), 1):
                pass
        finally:
            listener.close()
        with pytest.raises(OSError):
            bind_listener("127.0.0.1", busy, span=0)
    finally:
        blocker.close()


def test_the_server_serves_on_a_socket_bound_before_the_announcement(tmp_path):
    process, connection, port = _start(tmp_path, PREBIND="1")
    try:
        probe = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        probe.request("GET", "/stream")
        assert probe.getresponse().read1(16).startswith(b"data:")
        probe.close()
    finally:
        connection.close()
        process.send_signal(signal.SIGTERM)
        assert _wait_gone(process.pid, 10)


@pytest.mark.skipif(os.name != "posix", reason="TIME_WAIT reuse is the POSIX behaviour")
def test_a_port_left_in_time_wait_by_the_previous_server_is_bound_again():
    """A restart used to land on the next port (42004): the old server's closed connections held 42003 in TIME_WAIT."""
    from services.server_lifecycle import bind_listener
    # The previous server bound its port the same way (the kernel reuses TIME_WAIT only when both sides allow it,
    # which Uvicorn's own bind did before the socket was pre-bound here).
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    free = probe.getsockname()[1]
    probe.close()
    old, port = bind_listener("127.0.0.1", free, span=0)
    client = socket.create_connection(("127.0.0.1", port), 1)
    served, _ = old.accept()
    served.close()  # the server closes first: its end of the connection waits in TIME_WAIT on this port
    old.close()
    client.close()
    listener, bound = bind_listener("127.0.0.1", port, span=3)
    try:
        assert bound == port, "the same port again, not the next one"
    finally:
        listener.close()

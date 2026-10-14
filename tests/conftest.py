"""Test-wide environment.

The host guard answers only to this machine's names; Starlette's TestClient
sends ``Host: testserver``, so tests trust that name like a tunnel host.
The machine GPU lock stays off, so no test waits behind a running instance;
its own tests turn it on with a temporary lock path.
"""
import os

os.environ.setdefault("HOCUS_TRUSTED_HOSTS", "testserver")
os.environ.setdefault("HOCUS_GPU_MACHINE_LOCK", "0")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _router_registrations_do_not_outlive_their_test():
    """Router factories push probes (services.workspace_busy) and Activity controls (services.task_controls)
    into process-wide tables, some as closures over the service or engine they were given. Put both tables
    back after every test, so a test that builds a router cannot change what a later one in the same process
    calls. Registrations made at import time (the core server, or the full server's session fixture) are
    already in the table when the test starts, so they stay."""
    from services import task_controls, workspace_busy

    with workspace_busy.restored(), task_controls.restored():
        yield

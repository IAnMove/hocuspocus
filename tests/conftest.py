"""Test-wide environment.

The host guard answers only to this machine's names; Starlette's TestClient
sends ``Host: testserver``, so tests trust that name like a tunnel host.
The machine GPU lock stays off, so no test waits behind a running instance;
its own tests turn it on with a temporary lock path.
"""
import os

os.environ.setdefault("HOCUS_TRUSTED_HOSTS", "testserver")
os.environ.setdefault("HOCUS_GPU_MACHINE_LOCK", "0")

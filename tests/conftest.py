"""Test-wide environment.

The host guard answers only to this machine's names; Starlette's TestClient
sends ``Host: testserver``, so tests trust that name like a tunnel host.
"""
import os

os.environ.setdefault("HOCUS_TRUSTED_HOSTS", "testserver")

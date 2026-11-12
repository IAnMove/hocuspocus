"""The full server, imported once with a fake WanGP, and a fresh state per test.

Importing the server changes process-wide state (see tests/support/full_server.py),
so these tests run in their own pytest process:

    python -m pytest tests/characterization -p no:cacheprovider

In a run that also collects other tests (``pytest`` at the repo root), they are
skipped with that command as the reason. CI runs them in their own step.
"""
from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.support.full_server import ROOT, FullServer, load_full_server
from tests.support.golden import GoldenBook, normalise

PACKAGE = Path(__file__).resolve().parent
RUN_ALONE = "python -m pytest tests/characterization -p no:cacheprovider"
# Thread names (Python names a thread "Thread-N (target)") of the generation workers the routes start.
# Outpaint's shot preparation and blend's assembly thread are not the
# generation worker. They are non-daemon too, and a stuck one would hold the
# process open after the session has reported.
GENERATION_WORKERS = (
    "(_run_generation_with_preparation)",
    "(_run_generation)",
    "(run_generation)",
    "(_prepare_and_run_outpaint)",
    "(_run_blend_generation)",
)


def _inside_package(item: pytest.Item) -> bool:
    return PACKAGE in Path(str(item.path)).resolve().parents


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    own = [item for item in items if _inside_package(item)]
    if own and len(own) != len(items):
        skip = pytest.mark.skip(
            reason=f"imports the full server, which changes process-wide state; run alone: {RUN_ALONE}"
        )
        for item in own:
            item.add_marker(skip)


def pytest_unconfigure(config: pytest.Config) -> None:
    """The routes start generation workers as non-daemon threads. If one never finished, Python would wait for it
    forever at exit and CI would stop only at the job's timeout. The session has reported (and written its JUnit
    file) by now, so a worker still alive after a few seconds ends the process with a failure instead."""
    workers = [thread for thread in threading.enumerate()
               if thread.name.endswith(GENERATION_WORKERS) and not thread.daemon and thread.is_alive()]
    for thread in workers:
        thread.join(5)
    stuck = [thread.name for thread in workers if thread.is_alive()]
    if stuck:
        sys.stderr.write(f"\ntests/characterization: generation workers never finished: {stuck}. "
                         "Exiting with a failure instead of waiting for them.\n")
        sys.stdout.flush()  # the report is still in the pipe's buffer, and os._exit does not flush it
        sys.stderr.flush()
        os._exit(1)


@pytest.fixture(scope="session")
def full_server(tmp_path_factory: pytest.TempPathFactory) -> FullServer:
    return load_full_server(tmp_path_factory.mktemp("full-server"))


@dataclass
class Server:
    """One test's view of the shared server: its own outputs and uploads folders."""

    client: Any
    wgp: Any
    root: Path
    outputs: Path

    def normalise(self, body: Any, *, mask: tuple[str, ...] = (),
                  replace: tuple[tuple[str, str], ...] = ()) -> Any:
        return normalise(
            body,
            paths={str(self.outputs): "<OUTPUTS>", str(self.root): "<STATE>", str(ROOT): "<REPO>"},
            mask=mask,
            replace=replace,
        )

    def check(self, golden: GoldenBook, case: str, method: str, path: str, *,
              mask: tuple[str, ...] = (), replace: tuple[tuple[str, str], ...] = (), **request: Any) -> Any:
        """Call one route, compare its status and normalised JSON body with the golden, return the response."""
        response = self.client.request(method, path, **request)
        try:
            body = response.json()
        except ValueError:
            body = {"<text>": response.text}
        golden.check(case, response.status_code, self.normalise(body, mask=mask, replace=replace))
        return response


@pytest.fixture
def server(full_server: FullServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Server:
    """Point the server at empty folders for this test.

    The server reads ``wgp.server_config["save_path"]`` on every request, and
    ``uploads/`` relative to the working directory, so each test starts with
    no workspaces, outputs or uploads, whatever ran before it.
    """
    from fastapi.testclient import TestClient

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    fake = full_server.wgp
    config = fake.server_config
    for key in ("save_path", "image_save_path", "audio_save_path"):
        monkeypatch.setitem(config, key, str(outputs))
        monkeypatch.setattr(fake, key, str(outputs))
    monkeypatch.setitem(config, "services", {**config.get("services", {}), "active_workspace": "default"})
    monkeypatch.setattr(fake, "server_config_filename", str(tmp_path / "wgp_config.json"))
    monkeypatch.chdir(tmp_path)
    return Server(client=TestClient(full_server.api), wgp=fake, root=tmp_path, outputs=outputs)


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> GoldenBook:
    """The goldens of the calling test module, in ``goldens/<module>.json``."""
    module = Path(str(request.node.path)).stem
    return GoldenBook(PACKAGE / "goldens" / f"{module}.json")

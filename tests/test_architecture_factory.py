"""Characterization tests for the lazy backend application factory."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).parents[1]


def test_importing_factory_does_not_bootstrap_torch_or_process_state() -> None:
    """The import boundary must remain safe for tooling and test discovery."""

    probe = """
import os
import sys

before_cwd = os.getcwd()
before_argv = sys.argv[:]
before_path = sys.path[:]
import launch

assert hasattr(launch, "create_app")
assert "torch" not in sys.modules
assert os.getcwd() == before_cwd
assert sys.argv == before_argv
assert sys.path == before_path
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "app")
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_factory_preserves_legacy_api_surface_and_process_state(monkeypatch) -> None:
    """Factory loading keeps the API object and runtime helper exports intact."""

    import launch

    fake_runtime = ModuleType("_launch_runtime")
    fake_runtime.api = SimpleNamespace(routes=["legacy-route"])
    fake_runtime.legacy_helper = object()
    monkeypatch.setitem(sys.modules, "_launch_runtime", fake_runtime)
    monkeypatch.setattr(launch, "_runtime", None)
    monkeypatch.setattr(launch, "legacy_helper", None, raising=False)

    before_cwd = os.getcwd()
    before_argv = sys.argv[:]
    before_path = sys.path[:]
    app = launch.create_app()

    assert app is fake_runtime.api
    assert app.routes == ["legacy-route"]
    assert launch.legacy_helper is fake_runtime.legacy_helper
    assert os.getcwd() == before_cwd
    assert sys.argv == before_argv
    assert sys.path == before_path


def test_run_server_executes_the_unchanged_runtime_entry_once(monkeypatch) -> None:
    import launch
    from services.platform_capabilities import CORE_RUNTIME_ENV

    calls = []
    monkeypatch.setattr(
        launch.runpy,
        "run_module",
        lambda name, *, run_name: calls.append((name, run_name)),
    )
    monkeypatch.setattr("services.platform_capabilities.host_platform", lambda: "linux")
    monkeypatch.delenv(CORE_RUNTIME_ENV, raising=False)
    before_path = sys.path[:]

    monkeypatch.setattr(launch, "_core_installed", lambda app_dir: False)
    launch.run_server()
    assert calls == [("_launch_runtime", "__main__")]
    assert CORE_RUNTIME_ENV not in os.environ

    # An install that selected core (AMD, Intel, CPU) must never import Torch.
    monkeypatch.setattr(launch, "_core_installed", lambda app_dir: True)
    launch.run_server()
    assert calls[-1] == ("core_runtime", "__main__")
    assert os.environ[CORE_RUNTIME_ENV] == "core"
    assert sys.path == before_path

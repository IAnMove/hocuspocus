"""Contracts of the Recast shot code (planning, manifest, assembly) that no other test pins.

Recorded against the shot functions while they still lived in ``app/_launch_runtime.py`` (the reviewed C7 head
e393f5746). The loader follows a function into the service module that defines it now, so the same assertions run
before and after the move. Nothing here downloads a model or opens a network connection.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from tests.test_recast_helpers import ROOT

RECAST_MODULES = (
    "recast_masks",
    "recast_matte",
    "recast_reference_compose",
    "recast_reference_prepare",
    "recast_shot_planning",
    "recast_shot_manifest",
    "recast_shot_run",
)


@pytest.mark.parametrize("module", RECAST_MODULES)
def test_each_recast_module_imports_on_its_own(module):
    """recast_masks and recast_shot_planning import each other. Each takes the other's names at the bottom of its
    file, so whichever a fresh interpreter imports first, the names the other asks for are already defined."""
    if not (ROOT / "app" / "services" / f"{module}.py").is_file():
        pytest.skip(f"{module} is not a module on this tree")
    result = subprocess.run(
        [sys.executable, "-c", f"import services.{module}"],
        cwd=ROOT / "app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr

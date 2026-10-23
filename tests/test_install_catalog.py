"""The optional-component catalog: one JSON file read by Pinokio, the server and the web UI."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from services import install_catalog, runtime_profiles as profiles
from services.user_diagnostics import describe_engine

ROOT = Path(__file__).resolve().parents[1]


def _load_probe():
    spec = importlib.util.spec_from_file_location("runtime_probe_under_test", ROOT / "scripts" / "runtime_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_component_points_at_a_real_engine_and_installer():
    engines = profiles.catalog()["engines"]
    ids = [component.id for component in install_catalog.components()]
    assert len(ids) == len(set(ids))
    for component in install_catalog.components():
        assert component.engine in engines, component.id
        assert (ROOT / component.script).is_file(), component.script
        assert component.env == engines[component.engine]["env"]
        assert component.estimated_bytes > 0


def test_uninstall_paths_are_generated_folders_never_tracked_code():
    tracked = subprocess.run(["git", "ls-files", "--", "app/services"], cwd=ROOT, capture_output=True, text=True)
    if tracked.returncode != 0:
        pytest.skip("not a git checkout")
    tracked_files = set(tracked.stdout.split("\n"))
    for component in install_catalog.components():
        assert component.env in component.remove, f"{component.id} must remove its environment"
        for relative in component.remove:
            prefix = relative.rstrip("/") + "/"
            assert relative not in tracked_files and not any(f.startswith(prefix) for f in tracked_files), \
                f"{component.id}: {relative} contains tracked files"


@pytest.mark.parametrize("path", ["/etc", "../outside", "app/env", "app/services", "app/services/../env", "ui/dist"])
def test_a_component_cannot_declare_a_path_outside_app_services(path):
    with pytest.raises(ValueError):
        install_catalog.Component(id="x", engine="sam", script="sam_install.js", title="x", summary="x",
                                  estimated_bytes=1, restart_required=False, remove=(path,))


def test_the_base_install_is_never_a_component():
    assert not {"core", "wangp"} & install_catalog.optional_engines()
    assert install_catalog.base()["estimatedBytes"] > 0


def test_h3_legacy_is_optional_without_changing_its_install_fingerprint():
    # defaultInstall stays in profiles.json: it feeds the fingerprint, so flipping it would
    # mark every existing H3 Legacy install stale. The catalog carries the policy instead.
    assert "minimax_h3" in install_catalog.optional_engines()
    selected = profiles.select_profiles("linux", "x64", "nvidia", "580.82.09")["engines"]["minimax_h3"]
    described = describe_engine("minimax_h3", selected, {"installed": False})
    assert described["optional"] is True
    assert described["repair_path"]["id"] == "install_optional"
    base = describe_engine("wangp", profiles.select_profiles("linux", "x64", "nvidia", "580.82.09")["engines"]["wangp"],
                           {"installed": False})
    assert base["optional"] is False and base["repair_path"]["id"] == "install_update"


def test_probe_summary_offers_h3_legacy_as_an_extra_not_a_default():
    result = profiles.select_profiles("linux", "x64", "nvidia", "580.82.09")
    for item in result["engines"].values():
        item["installed"] = False
    text = " ".join(_load_probe().summary(result))
    assert "MiniMax H3 Legacy" in text and "Optional, from the Advanced menu" in text

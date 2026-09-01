"""WanGP generation wall: bind once, never reimport."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from services.generation import (
    ModelCatalog,
    RuntimeConfig,
    bind_wgp,
    get_model_def,
    get_wgp,
)
from services.generation import runtime as generation_runtime
from services.generation.bootstrap import get_or_bootstrap_wgp


@pytest.fixture
def isolated_wgp():
    previous = generation_runtime._wgp
    generation_runtime._wgp = None
    try:
        yield
    finally:
        generation_runtime._wgp = previous


def test_get_wgp_raises_before_bind(isolated_wgp) -> None:
    with pytest.raises(RuntimeError, match="generation.bind_wgp\\(\\) was not called"):
        get_wgp()


def test_get_wgp_is_the_bound_sys_modules_singleton(isolated_wgp, monkeypatch) -> None:
    fake = SimpleNamespace(server_config={"vram_safety_coefficient": 0.5})
    monkeypatch.setitem(sys.modules, "wgp", fake)
    bind_wgp(fake)
    assert get_wgp() is sys.modules["wgp"]
    assert get_wgp() is fake


def test_model_catalog_and_runtime_config_read_the_bound_instance(isolated_wgp) -> None:
    fake = SimpleNamespace(
        get_model_def=lambda model_type: {"family": "ltx2", "name": model_type},
        server_config={
            "services": {"nsfw_mode": True},
            "maestro_production_profile": {"image": {"provider": "local"}},
            "vram_safety_coefficient": 0.72,
        },
    )
    bind_wgp(fake)
    assert get_model_def("ltx2_22B") == {"family": "ltx2", "name": "ltx2_22B"}
    assert ModelCatalog.get_model_def("ltx2_22B")["family"] == "ltx2"
    assert RuntimeConfig.get("vram_safety_coefficient", 0.80) == 0.72
    assert RuntimeConfig.services() == {"nsfw_mode": True}
    assert RuntimeConfig.get("maestro_production_profile")["image"]["provider"] == "local"


def _fake_wgp(root):
    return SimpleNamespace(__file__=str(root / "wgp.py"), server_config={})


def test_standalone_bootstrap_imports_once_and_reuses_the_singleton(
    isolated_wgp,
    monkeypatch,
    tmp_path,
) -> None:
    fake = _fake_wgp(tmp_path)
    calls = []

    def importer(name: str):
        calls.append(name)
        monkeypatch.setitem(sys.modules, name, fake)
        return fake

    monkeypatch.delitem(sys.modules, "wgp", raising=False)
    assert get_or_bootstrap_wgp(expected_root=tmp_path, importer=importer) is fake
    assert get_or_bootstrap_wgp(expected_root=tmp_path, importer=importer) is fake
    assert get_wgp() is sys.modules["wgp"]
    assert calls == ["wgp"]


def test_standalone_bootstrap_binds_an_existing_sys_modules_instance(
    isolated_wgp,
    monkeypatch,
    tmp_path,
) -> None:
    fake = _fake_wgp(tmp_path)
    monkeypatch.setitem(sys.modules, "wgp", fake)

    def unexpected_import(_name: str):
        raise AssertionError("the registered singleton must be reused")

    assert get_or_bootstrap_wgp(expected_root=tmp_path, importer=unexpected_import) is fake
    assert get_wgp() is fake


def test_standalone_bootstrap_rejects_a_different_root_without_binding(
    isolated_wgp,
    monkeypatch,
    tmp_path,
) -> None:
    other_root = tmp_path / "other"
    fake = _fake_wgp(other_root)
    monkeypatch.setitem(sys.modules, "wgp", fake)

    with pytest.raises(RuntimeError, match="already loaded from"):
        get_or_bootstrap_wgp(expected_root=tmp_path)
    with pytest.raises(RuntimeError, match="generation.bind_wgp"):
        get_wgp()


def test_standalone_bootstrap_does_not_bind_a_failed_or_unregistered_import(
    isolated_wgp,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delitem(sys.modules, "wgp", raising=False)

    def failed_import(_name: str):
        raise ImportError("broken WanGP import")

    with pytest.raises(ImportError, match="broken WanGP import"):
        get_or_bootstrap_wgp(expected_root=tmp_path, importer=failed_import)
    with pytest.raises(RuntimeError, match="generation.bind_wgp"):
        get_wgp()

    fake = _fake_wgp(tmp_path)
    with pytest.raises(RuntimeError, match="did not register"):
        get_or_bootstrap_wgp(expected_root=tmp_path, importer=lambda _name: fake)
    with pytest.raises(RuntimeError, match="generation.bind_wgp"):
        get_wgp()


def test_bind_wgp_is_idempotent_but_rejects_a_second_runtime(isolated_wgp) -> None:
    first = SimpleNamespace()
    bind_wgp(first)
    bind_wgp(first)
    with pytest.raises(RuntimeError, match="different WanGP runtime"):
        bind_wgp(SimpleNamespace())

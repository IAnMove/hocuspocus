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


@pytest.fixture
def isolated_wgp():
    previous = generation_runtime._wgp
    bind_wgp(None)
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

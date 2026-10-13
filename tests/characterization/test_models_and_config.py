"""Model catalog over a fake WanGP catalog, and the configuration reads the Settings screen makes."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.support.fake_wgp import catalog_attributes
from tests.support.full_server import APP_DIR


@pytest.fixture
def catalog(server, monkeypatch):
    """Two fake WanGP models; the 3D, rig and MiniMax weights are never on disk."""
    from services import minimax_h3_service, model3d_service, rig_service

    for name, value in catalog_attributes().items():
        monkeypatch.setattr(server.wgp, name, value, raising=False)
    monkeypatch.setattr(model3d_service, "is_model_downloaded", lambda _model_id: False)
    monkeypatch.setattr(minimax_h3_service, "is_model_downloaded", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(rig_service, "is_unirig_downloaded", lambda: False)
    return server


def test_model_catalog(catalog, golden) -> None:
    catalog.check(golden, "models", "GET", "/api/v1/models")
    catalog.check(golden, "models summary", "GET", "/api/v1/models", params={"detail": "false"})


def test_model_settings_defaults(server, golden) -> None:
    server.check(golden, "model visibility", "GET", "/api/v1/model-visibility")
    server.check(golden, "model selections", "GET", "/api/v1/model-selections")
    server.check(golden, "production profile", "GET", "/api/v1/production-profile")


def test_the_server_keeps_temp_files_and_libraries_in_its_state_folder(full_server) -> None:
    """The import sweeps the temp folder; Numba and the libraries default to the live install's folders."""
    import tempfile

    from services.style_library import resolve_style_library_root
    from services.template_library import resolve_template_library_root

    state = full_server.state_root.resolve()
    assert Path(tempfile.gettempdir()).resolve().is_relative_to(state)
    assert Path(os.environ["TMPDIR"]).resolve().is_relative_to(state)
    assert Path(os.environ["NUMBA_CACHE_DIR"]).resolve().is_relative_to(state)
    assert resolve_style_library_root(APP_DIR).is_relative_to(state)
    assert resolve_template_library_root(APP_DIR).is_relative_to(state)


def test_settings_reads(server, golden) -> None:
    server.check(golden, "services config", "GET", "/api/v1/services-config")
    server.check(golden, "presets", "GET", "/api/v1/presets")
    server.check(golden, "mcp settings", "GET", "/api/v1/settings/mcp")
    server.check(golden, "llm status", "GET", "/api/v1/llm/status")
    server.check(golden, "lan auth status", "GET", "/api/v1/auth/lan/status")

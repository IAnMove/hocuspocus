"""Model catalog over a fake WanGP catalog, and the configuration reads the Settings screen makes."""
from __future__ import annotations

import pytest

from tests.support.fake_wgp import catalog_attributes


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


def test_settings_reads(server, golden) -> None:
    server.check(golden, "services config", "GET", "/api/v1/services-config")
    server.check(golden, "presets", "GET", "/api/v1/presets")
    server.check(golden, "mcp settings", "GET", "/api/v1/settings/mcp")
    server.check(golden, "llm status", "GET", "/api/v1/llm/status")
    server.check(golden, "lan auth status", "GET", "/api/v1/auth/lan/status")

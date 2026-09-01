"""The documented Python API remains a real standalone WanGP bootstrap."""
from __future__ import annotations

import sys
from types import SimpleNamespace

from services.generation import bootstrap, get_wgp
from services.generation import runtime as generation_runtime
from shared import api as shared_api


def test_init_bootstraps_and_binds_wgp_without_launch(monkeypatch, tmp_path) -> None:
    previous_bound = generation_runtime._wgp
    previous_runtime = shared_api._RUNTIME
    previous_banner = shared_api._BANNER_PRINTED
    generation_runtime._wgp = None
    shared_api._RUNTIME = None
    shared_api._BANNER_PRINTED = False
    monkeypatch.delitem(sys.modules, "wgp", raising=False)

    application = object()
    downloads = []
    fake = SimpleNamespace(
        __file__=str(tmp_path / "wgp.py"),
        WanGP_version="test",
        WAN2GPApplication=lambda: application,
        download_ffmpeg=lambda: downloads.append(True),
    )

    def import_once():
        monkeypatch.setitem(sys.modules, "wgp", fake)
        return fake

    monkeypatch.setattr(bootstrap, "_import_wgp", import_once)
    try:
        session = shared_api.init(root=tmp_path, console_output=False)
        assert session._ensure_runtime().module is fake
        assert get_wgp() is sys.modules["wgp"] is fake
        assert fake.app is application
        assert downloads == [True]
    finally:
        shared_api._RUNTIME = previous_runtime
        shared_api._BANNER_PRINTED = previous_banner
        generation_runtime._wgp = previous_bound

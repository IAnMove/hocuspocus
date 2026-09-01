"""Bound WanGP runtime. Launch imports wgp once and calls bind_wgp(wgp).

This module never imports WanGP. Consumers go through get_wgp() or the thin
ports below; they must not `import wgp` themselves.
"""
from __future__ import annotations

import threading
from typing import Any

_UNBOUND_MESSAGE = (
    "generation.bind_wgp() was not called; bootstrap through launch or "
    "shared.api.init() first"
)

_wgp = None
_wgp_lock = threading.RLock()


def bind_wgp(module) -> None:
    global _wgp
    if module is None:
        raise ValueError("Cannot bind an empty WanGP runtime")
    with _wgp_lock:
        if _wgp is not None and _wgp is not module:
            raise RuntimeError("A different WanGP runtime is already bound")
        _wgp = module


def get_wgp():
    with _wgp_lock:
        if _wgp is None:
            raise RuntimeError(_UNBOUND_MESSAGE)
        return _wgp


class ModelCatalog:
    """Typed reads of the live WanGP model registry."""

    @staticmethod
    def get_model_def(model_type: str) -> Any:
        return get_wgp().get_model_def(model_type)


class RuntimeConfig:
    """Typed reads of the live WanGP server_config mapping."""

    @staticmethod
    def mapping() -> dict:
        config = getattr(get_wgp(), "server_config", None)
        return config if isinstance(config, dict) else {}

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        return cls.mapping().get(key, default)

    @classmethod
    def services(cls) -> dict:
        services = cls.get("services") or {}
        return services if isinstance(services, dict) else {}


def get_model_def(model_type: str) -> Any:
    return ModelCatalog.get_model_def(model_type)

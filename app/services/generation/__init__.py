"""HocusPocus generation wall around the live WanGP instance."""

from .runtime import (
    ModelCatalog,
    RuntimeConfig,
    bind_wgp,
    get_model_def,
    get_wgp,
)

__all__ = [
    "ModelCatalog",
    "RuntimeConfig",
    "bind_wgp",
    "get_model_def",
    "get_wgp",
]

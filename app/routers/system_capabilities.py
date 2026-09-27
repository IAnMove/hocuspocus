"""HTTP surface for the platform capability authority."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.platform_capabilities import (
    CapabilityDenied,
    platform_capabilities,
    require_capability,
)


def create_system_capabilities_router() -> APIRouter:
    router = APIRouter(tags=["system-capabilities"])

    @router.get("/api/v1/system/capabilities")
    def get_capabilities():
        return platform_capabilities()

    return router


def require_capability_http(capability: str) -> None:
    """Raise 409 feature_unavailable when a local NVIDIA engine is not available."""
    try:
        require_capability(capability)
    except CapabilityDenied as error:
        raise HTTPException(status_code=409, detail=error.as_detail()) from error

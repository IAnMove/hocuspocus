"""Visibility, selections and the production profile.

Mounted where the full server registered model-visibility, so the route
order stays between the model list and the model debug route.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from services import model_visibility


def create_model_preferences_router():
    """GET/PUT model-visibility, production-profile and model-selections, in that order."""
    router = APIRouter()

    @router.get("/api/v1/model-visibility")
    def get_model_visibility():
        """Return the server-persisted model selector whitelist."""
        return model_visibility.get_model_visibility()

    @router.put("/api/v1/model-visibility")
    async def update_model_visibility(request: Request):
        """Persist model visibility independently of the browser's origin."""
        return await model_visibility.update_model_visibility(request)

    @router.get("/api/v1/production-profile")
    def get_production_profile():
        """Return credential-free defaults shared by Studio and every Lab."""
        return model_visibility.get_production_profile()

    @router.put("/api/v1/production-profile")
    async def update_production_profile(request: Request):
        return await model_visibility.update_production_profile(request)

    @router.get("/api/v1/model-selections")
    def get_model_selections():
        """Return model choices independently of Pinokio's changing UI port."""
        return model_visibility.get_model_selections()

    @router.put("/api/v1/model-selections")
    async def update_model_selections(request: Request):
        """Persist the user's last model for each generation mode."""
        return await model_visibility.update_model_selections(request)

    return router

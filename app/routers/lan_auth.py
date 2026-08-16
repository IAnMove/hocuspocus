"""LAN authentication handshake routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from services.lan_auth import (
    LAN_AUTH_COOKIE_NAME,
    LanLoginAttemptLimiter,
    create_session_credential,
    get_lan_token,
    lan_share_enabled,
    remote_lan_auth_required,
    request_has_valid_lan_auth,
    request_peer_key,
    verify_lan_token,
)


class LanAuthLoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


def create_lan_auth_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth/lan", tags=["LAN authentication"])
    attempts = LanLoginAttemptLimiter()

    @router.get("/status")
    def status(request: Request):
        required = remote_lan_auth_required(request)
        return {
            "enabled": lan_share_enabled(),
            "required": required,
            "authenticated": not required or request_has_valid_lan_auth(request),
        }

    @router.post("/login")
    def login(payload: LanAuthLoginRequest, request: Request, response: Response):
        required = remote_lan_auth_required(request)
        peer_key = request_peer_key(request)
        retry_after = attempts.retry_after(peer_key) if required else 0
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="Too many failed LAN login attempts",
                headers={"Retry-After": str(retry_after)},
            )
        if required and not verify_lan_token(payload.token):
            attempts.record_failure(peer_key)
            raise HTTPException(
                status_code=401,
                detail="Invalid LAN access token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if required:
            attempts.clear(peer_key)
            response.set_cookie(
                key=LAN_AUTH_COOKIE_NAME,
                value=create_session_credential(get_lan_token()),
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="strict",
                path="/",
            )
        return {"authenticated": True}

    @router.post("/logout")
    def logout(response: Response):
        response.delete_cookie(
            key=LAN_AUTH_COOKIE_NAME,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return {"authenticated": False}

    return router

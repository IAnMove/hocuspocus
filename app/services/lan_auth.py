"""Session authentication for explicitly LAN-shared Loreframe Lab servers.

Loopback remains frictionless.  When the server is bound for LAN access,
remote API and classic-UI requests require either the configured bearer token
or the derived HttpOnly session cookie issued by the login endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from collections import deque
from collections.abc import Mapping
from urllib.parse import urlsplit

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse


LAN_AUTH_COOKIE_NAME = "loreframe_lan_session"
LAN_AUTH_TOKEN_ENV = "LOREFRAME_LAN_TOKEN"
LAN_AUTH_TOKEN_MIN_LENGTH = 24
LAN_LOGIN_ATTEMPT_LIMIT = 8
LAN_LOGIN_WINDOW_SECONDS = 60
_SESSION_CONTEXT = b"loreframe-lab-lan-session-v1"
_AUTH_PUBLIC_PATHS = {
    "/api/v1/auth/lan/login",
    "/api/v1/auth/lan/status",
}
_PROTECTED_PREFIXES = ("/api/", "/classic")
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_token_lock = threading.Lock()
_generated_token: str | None = None


def _environment(environ: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _hostname(value: str) -> str:
    """Extract a hostname from a Host header or bind value without guessing."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return str(urlsplit(f"//{raw}").hostname or "").casefold()
    except ValueError:
        return ""


def _is_loopback_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def _is_local_hostname(value: str) -> bool:
    host = _hostname(value)
    if host == "localhost" or host.endswith(".localhost"):
        return True
    return _is_loopback_ip(host)


def lan_share_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether the process is intentionally reachable beyond loopback."""
    values = _environment(environ)
    share_value = str(values.get("PINOKIO_SHARE_LOCAL") or "").strip().casefold()
    if share_value in _TRUE_VALUES:
        return True
    if share_value in _FALSE_VALUES:
        return False

    server_name = str(values.get("SERVER_NAME") or "127.0.0.1").strip()
    return bool(server_name and not _is_local_hostname(server_name))


def configured_lan_token(environ: Mapping[str, str] | None = None) -> str:
    value = str(_environment(environ).get(LAN_AUTH_TOKEN_ENV) or "").strip()
    if value and len(value) < LAN_AUTH_TOKEN_MIN_LENGTH:
        raise ValueError(
            f"{LAN_AUTH_TOKEN_ENV} must contain at least "
            f"{LAN_AUTH_TOKEN_MIN_LENGTH} characters"
        )
    return value


def get_lan_token(environ: Mapping[str, str] | None = None) -> str:
    """Return a configured token or one stable random token for this process."""
    explicit = configured_lan_token(environ)
    if explicit:
        return explicit

    global _generated_token
    with _token_lock:
        if _generated_token is None:
            _generated_token = secrets.token_urlsafe(32)
        return _generated_token


def create_session_credential(token: str) -> str:
    """Derive the cookie value so the raw bearer token is never persisted."""
    return hmac.new(
        str(token).encode("utf-8"),
        _SESSION_CONTEXT,
        hashlib.sha256,
    ).hexdigest()


def verify_lan_token(candidate: str, environ: Mapping[str, str] | None = None) -> bool:
    value = str(candidate or "")
    expected = get_lan_token(environ)
    return bool(value) and hmac.compare_digest(value, expected)


def request_is_local(request: HTTPConnection) -> bool:
    """Only exempt a real loopback peer addressing a loopback host.

    Requiring both properties prevents a remote peer from bypassing auth by
    spoofing ``Host: localhost``. Numeric ``<port>.localhost`` proxy hosts are
    deliberately not exempt while sharing because a loopback reverse proxy
    can otherwise hide the original LAN peer; the direct 127.0.0.1 URL stays
    frictionless.
    """
    client = getattr(request, "client", None)
    client_host = str(getattr(client, "host", "") or "")
    headers = getattr(request, "headers", {})
    request_host = str(headers.get("host") or "")
    forwarded_for = str(headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    real_ip = str(headers.get("x-real-ip") or "").strip()
    forwarded_peer = forwarded_for or real_ip
    if forwarded_peer and not _is_loopback_ip(forwarded_peer):
        return False
    request_name = _hostname(request_host)
    direct_loopback_host = request_name == "localhost" or _is_loopback_ip(request_name)
    return _is_loopback_ip(client_host) and direct_loopback_host


def remote_lan_auth_required(
    request: HTTPConnection,
    environ: Mapping[str, str] | None = None,
) -> bool:
    return lan_share_enabled(environ) and not request_is_local(request)


def request_requires_lan_auth(
    request: HTTPConnection,
    environ: Mapping[str, str] | None = None,
) -> bool:
    path = str(getattr(getattr(request, "url", None), "path", "") or "")
    if path in _AUTH_PUBLIC_PATHS:
        return False
    if not any(path == prefix or path.startswith(prefix) for prefix in _PROTECTED_PREFIXES):
        return False
    return remote_lan_auth_required(request, environ)


def request_has_valid_lan_auth(
    request: HTTPConnection,
    environ: Mapping[str, str] | None = None,
) -> bool:
    headers = getattr(request, "headers", {})
    authorization = str(headers.get("authorization") or "")
    scheme, separator, bearer = authorization.partition(" ")
    if separator and scheme.casefold() == "bearer" and verify_lan_token(bearer.strip(), environ):
        return True

    cookies = getattr(request, "cookies", {})
    cookie = str(cookies.get(LAN_AUTH_COOKIE_NAME) or "")
    expected_cookie = create_session_credential(get_lan_token(environ))
    return bool(cookie) and hmac.compare_digest(cookie, expected_cookie)


class LanAuthMiddleware:
    """Fail closed for remote LAN access to API and classic UI routes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope_type = scope.get("type")
        if scope_type not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        if request_requires_lan_auth(connection) and not request_has_valid_lan_auth(connection):
            if scope_type == "websocket":
                await send({"type": "websocket.close", "code": 4401})
                return
            response = JSONResponse(
                status_code=401,
                content={"detail": "LAN authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def describe_lan_auth_startup(environ: Mapping[str, str] | None = None) -> list[str]:
    """Build one-time startup messages; only generated tokens are printed."""
    if not lan_share_enabled(environ):
        return []
    explicit = configured_lan_token(environ)
    if explicit:
        return [
            "[LAN Auth] Remote access is protected by the configured "
            f"{LAN_AUTH_TOKEN_ENV} token.",
        ]
    return [
        "[LAN Auth] Remote access is protected. Enter this session token in the LAN browser:",
        f"[LAN Auth] {get_lan_token(environ)}",
        f"[LAN Auth] Set {LAN_AUTH_TOKEN_ENV} to keep a stable token across restarts.",
    ]


def request_peer_key(request: HTTPConnection) -> str:
    """Return a bounded login-throttle key without trusting remote spoofed headers."""
    client = getattr(request, "client", None)
    client_host = str(getattr(client, "host", "") or "unknown")
    if _is_loopback_ip(client_host):
        headers = getattr(request, "headers", {})
        forwarded_for = str(headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
        real_ip = str(headers.get("x-real-ip") or "").strip()
        return (forwarded_for or real_ip or client_host)[:128]
    return client_host[:128]


class LanLoginAttemptLimiter:
    """Small in-memory limiter for failed token guesses, keyed by remote peer."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = {}

    def _prune(self, now: float) -> None:
        threshold = now - LAN_LOGIN_WINDOW_SECONDS
        for key, attempts in list(self._failures.items()):
            while attempts and attempts[0] <= threshold:
                attempts.popleft()
            if not attempts:
                self._failures.pop(key, None)

    def retry_after(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            self._prune(now)
            attempts = self._failures.get(key)
            if not attempts or len(attempts) < LAN_LOGIN_ATTEMPT_LIMIT:
                return 0
            return max(1, int(LAN_LOGIN_WINDOW_SECONDS - (now - attempts[0]) + 0.999))

    def record_failure(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            self._prune(now)
            self._failures.setdefault(key, deque()).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

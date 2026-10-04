"""Single-user OAuth 2.1 for MCP clients that cannot send the installation key.

ChatGPT connectors only speak OAuth (authorization code with PKCE S256, dynamic
client registration); they cannot be given a static ``Bearer`` key. This is
the smallest authorization server that satisfies them for one person:

* the client registers itself (``register``);
* the person approving types the installation MCP key once on the
  authorization page (``approve``);
* the client exchanges the single-use code for its own short-lived access
  token and a rotating refresh token (``exchange``, ``refresh``);
* each token is bound to an MCP profile (``series``) or to the full
  endpoint (``all``), from the resource URL the client asked for.

Only hashes of tokens are stored. Turning external access off (no key) makes
every token useless, because ``verify`` checks the key is still configured.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

ACCESS_SECONDS = 3600
REFRESH_SECONDS = 30 * 24 * 3600
CODE_SECONDS = 120
MAX_CLIENTS = 32
MAX_FAILURES_PER_MINUTE = 5


class OAuthError(ValueError):
    def __init__(self, error: str, description: str, status: int = 400) -> None:
        self.error, self.status = error, status
        super().__init__(description)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _redirect_allowed(uri: str) -> bool:
    parts = urlsplit(uri)
    if parts.fragment or not parts.netloc:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"}


def profile_of(resource: str | None) -> str:
    """``.../api/v1/mcp/<profile>`` -> profile; the plain endpoint (or none given) -> ``all``."""
    path = urlsplit(resource or "").path.rstrip("/")
    prefix = "/api/v1/mcp/"
    return path[len(prefix):] if path.startswith(prefix) and "/" not in path[len(prefix):] else "all"


class McpOAuth:
    def __init__(self, path: str | os.PathLike, key: Callable[[], str], profiles: set[str], now: Callable[[], float] = time.time) -> None:
        self.path, self.key, self.profiles, self.now = Path(path), key, set(profiles) | {"all"}, now
        self.lock = threading.RLock()
        self.codes: dict[str, dict[str, Any]] = {}
        self.failures: list[float] = []

    # Storage -------------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"clients": {}, "tokens": {}}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        return {"clients": value.get("clients") or {}, "tokens": value.get("tokens") or {}}

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(6)}.tmp")
        try:
            with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
                json.dump(value, handle)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    # Client registration (RFC 7591) ---------------------------------------
    def register(self, body: dict[str, Any]) -> dict[str, Any]:
        uris = body.get("redirect_uris")
        if not isinstance(uris, list) or not uris or len(uris) > 8 or not all(isinstance(u, str) and _redirect_allowed(u) for u in uris):
            raise OAuthError("invalid_redirect_uri", "redirect_uris must be https URLs (or http on localhost)")
        name = str(body.get("client_name") or "MCP client")[:120]
        client_id = "hp-" + secrets.token_urlsafe(18)
        with self.lock:
            state = self._read()
            clients = state["clients"]
            clients[client_id] = {"name": name, "redirect_uris": uris, "created": self.now()}
            for old in sorted(clients, key=lambda key: clients[key]["created"])[:-MAX_CLIENTS]:
                clients.pop(old, None)
            self._write(state)
        return {"client_id": client_id, "client_name": name, "redirect_uris": uris, "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"], "token_endpoint_auth_method": "none", "client_id_issued_at": int(self.now())}

    def client(self, client_id: str) -> dict[str, Any]:
        with self.lock:
            found = self._read()["clients"].get(client_id)
        if found is None:
            raise OAuthError("invalid_client", "Unknown client; register it again", 401)
        return found

    # Authorization ---------------------------------------------------------
    def check_request(self, params: dict[str, str]) -> dict[str, Any]:
        """Validate an authorization request before showing the page; returns the client and profile."""
        if params.get("response_type") != "code":
            raise OAuthError("unsupported_response_type", "Only response_type=code is supported")
        client = self.client(params.get("client_id", ""))
        if params.get("redirect_uri") not in client["redirect_uris"]:
            raise OAuthError("invalid_request", "redirect_uri is not registered for this client")
        if params.get("code_challenge_method") != "S256" or len(params.get("code_challenge", "")) < 43:
            raise OAuthError("invalid_request", "PKCE with code_challenge_method=S256 is required")
        profile = profile_of(params.get("resource"))
        if profile not in self.profiles:
            raise OAuthError("invalid_target", f"Unknown MCP profile {profile}")
        return {"client": client, "profile": profile}

    def approve(self, params: dict[str, str], key: str) -> str:
        """The person typed the installation key: issue a single-use code and return the redirect URL."""
        checked = self.check_request(params)
        installed = self.key()
        if not installed:
            raise OAuthError("access_denied", "External agent access is disabled in HocusPocus settings", 403)
        with self.lock:
            now = self.now()
            self.failures = [t for t in self.failures if now - t < 60]
            if len(self.failures) >= MAX_FAILURES_PER_MINUTE:
                raise OAuthError("slow_down", "Too many wrong keys; wait a minute", 429)
            if not secrets.compare_digest(key.strip(), installed):
                self.failures.append(now)
                raise OAuthError("access_denied", "That is not the HocusPocus MCP key", 403)
            code = secrets.token_urlsafe(32)
            self.codes = {k: v for k, v in self.codes.items() if v["expires"] > now}
            self.codes[_hash(code)] = {"client_id": params["client_id"], "redirect_uri": params["redirect_uri"],
                                       "challenge": params["code_challenge"], "profile": checked["profile"], "expires": now + CODE_SECONDS}
        query = {"code": code, **({"state": params["state"]} if params.get("state") else {})}
        separator = "&" if "?" in params["redirect_uri"] else "?"
        return params["redirect_uri"] + separator + urlencode(query)

    # Tokens ----------------------------------------------------------------
    def _issue(self, state: dict[str, Any], client_id: str, profile: str) -> dict[str, Any]:
        now = self.now()
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(40)
        tokens = {k: v for k, v in state["tokens"].items() if v["expires"] > now}
        tokens[_hash(access)] = {"kind": "access", "client_id": client_id, "profile": profile, "expires": now + ACCESS_SECONDS}
        tokens[_hash(refresh)] = {"kind": "refresh", "client_id": client_id, "profile": profile, "expires": now + REFRESH_SECONDS}
        state["tokens"] = tokens
        return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_SECONDS, "refresh_token": refresh,
                "scope": "mcp"}

    def exchange(self, form: dict[str, str]) -> dict[str, Any]:
        grant = form.get("grant_type")
        if grant == "refresh_token":
            return self.refresh(form)
        if grant != "authorization_code":
            raise OAuthError("unsupported_grant_type", "Use authorization_code or refresh_token")
        with self.lock:
            entry = self.codes.pop(_hash(form.get("code", "")), None)
            if entry is None or entry["expires"] <= self.now():
                raise OAuthError("invalid_grant", "The code is unknown, used or expired")
            if form.get("client_id") != entry["client_id"] or form.get("redirect_uri") != entry["redirect_uri"]:
                raise OAuthError("invalid_grant", "client_id or redirect_uri does not match the authorization")
            if _challenge(form.get("code_verifier", "")) != entry["challenge"]:
                raise OAuthError("invalid_grant", "PKCE verification failed")
            state = self._read()
            issued = self._issue(state, entry["client_id"], entry["profile"])
            self._write(state)
        return issued

    def refresh(self, form: dict[str, str]) -> dict[str, Any]:
        with self.lock:
            state = self._read()
            entry = state["tokens"].pop(_hash(form.get("refresh_token", "")), None)
            if entry is None or entry["kind"] != "refresh" or entry["expires"] <= self.now():
                raise OAuthError("invalid_grant", "The refresh token is unknown or expired")
            if form.get("client_id") and form["client_id"] != entry["client_id"]:
                raise OAuthError("invalid_grant", "client_id does not match the refresh token")
            issued = self._issue(state, entry["client_id"], entry["profile"])  # the used refresh token is gone: rotation
            self._write(state)
        return issued

    def verify(self, token: str, profile: str) -> bool:
        """An access token is valid for its own profile (an ``all`` token for every endpoint) while access is on."""
        if not token or not self.key():
            return False
        with self.lock:
            entry = self._read()["tokens"].get(_hash(token))
        if not entry or entry["kind"] != "access" or entry["expires"] <= self.now():
            return False
        return entry["profile"] == "all" or entry["profile"] == profile

    def revoke_all(self) -> None:
        with self.lock:
            state = self._read()
            state["tokens"] = {}
            self._write(state)

    # Discovery -------------------------------------------------------------
    @staticmethod
    def base_url(request: Any) -> str:
        """The public origin: HOCUS_PUBLIC_URL, else the tunnel's forwarded host and scheme, else the request's."""
        configured = os.environ.get("HOCUS_PUBLIC_URL", "").strip().rstrip("/")
        if configured:
            return configured
        headers = request.headers
        scheme = (headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
        host = (headers.get("x-forwarded-host") or headers.get("host") or request.url.netloc).split(",")[0].strip()
        return f"{scheme}://{host}"

    def resource_metadata_url(self, request: Any, profile: str | None) -> str:
        path = f"/api/v1/mcp/{profile}" if profile else "/api/v1/mcp"
        return f"{self.base_url(request)}/.well-known/oauth-protected-resource{path}"

    def protected_resource(self, request: Any, path: str) -> dict[str, Any]:
        base = self.base_url(request)
        resource = f"{base}/{path.strip('/')}" if path.strip("/") else f"{base}/api/v1/mcp"
        return {"resource": resource, "authorization_servers": [base], "scopes_supported": ["mcp"],
                "bearer_methods_supported": ["header"], "resource_name": "HocusPocus"}

    def authorization_server(self, request: Any) -> dict[str, Any]:
        base = self.base_url(request)
        return {"issuer": base, "authorization_endpoint": f"{base}/oauth/authorize", "token_endpoint": f"{base}/oauth/token",
                "registration_endpoint": f"{base}/oauth/register", "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": ["mcp"],
                "client_id_metadata_document_supported": False}

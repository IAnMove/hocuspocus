from __future__ import annotations

import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response

from routers.lan_auth import create_lan_auth_router
from services.lan_auth import (
    LAN_AUTH_COOKIE_NAME,
    LanAuthMiddleware,
    create_session_credential,
    describe_lan_auth_startup,
    request_requires_lan_auth,
)


TEST_TOKEN = "test-lan-token-with-at-least-32-bytes"
ROOT = Path(__file__).parents[1]


def _configure_share(monkeypatch, *, enabled: bool = True) -> None:
    monkeypatch.setenv("PINOKIO_SHARE_LOCAL", "true" if enabled else "false")
    monkeypatch.setenv("LOREFRAME_LAN_TOKEN", TEST_TOKEN)
    monkeypatch.delenv("SERVER_NAME", raising=False)


def _request(
    path: str,
    *,
    method: str = "GET",
    scheme: str = "http",
    client: str = "192.168.1.30",
    headers: dict[str, str] | None = None,
) -> Request:
    normalized = {"host": "192.168.1.20:7860", **(headers or {})}
    return Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": scheme,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(key.lower().encode(), value.encode()) for key, value in normalized.items()],
        "client": (client, 43210),
        "server": ("192.168.1.20", 7860),
    })


def _middleware_status(request: Request) -> tuple[int, dict[str, str]]:
    sent: list[dict] = []

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"ok":true}'})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(LanAuthMiddleware(downstream)(request.scope, receive, send))
    start = next(item for item in sent if item["type"] == "http.response.start")
    headers = {
        key.decode().casefold(): value.decode()
        for key, value in start.get("headers", [])
    }
    return int(start["status"]), headers


def _route_endpoint(suffix: str):
    router = create_lan_auth_router()
    return next(route.endpoint for route in router.routes if route.path.endswith(suffix))


def test_share_mode_rejects_api_without_credentials(monkeypatch) -> None:
    _configure_share(monkeypatch)
    status, headers = _middleware_status(_request("/api/v1/probe", method="POST"))

    assert status == 401
    assert headers["www-authenticate"] == "Bearer"
    assert TEST_TOKEN not in repr(headers)


def test_share_mode_accepts_valid_bearer_for_reads_and_mutations(monkeypatch) -> None:
    _configure_share(monkeypatch)
    headers = {"authorization": f"Bearer {TEST_TOKEN}"}
    assert _middleware_status(_request("/api/v1/probe", headers=headers))[0] == 200
    assert _middleware_status(
        _request("/api/v1/probe", method="POST", headers=headers)
    )[0] == 200


def test_login_sets_hardened_session_cookie_and_unlocks_ui(monkeypatch) -> None:
    _configure_share(monkeypatch)
    status_endpoint = _route_endpoint("/status")
    assert status_endpoint(_request("/api/v1/auth/lan/status")) == {
        "enabled": True,
        "required": True,
        "authenticated": False,
    }

    login_endpoint = _route_endpoint("/login")
    response = Response()
    result = login_endpoint(
        SimpleNamespace(token=TEST_TOKEN),
        _request("/api/v1/auth/lan/login", method="POST", scheme="https"),
        response,
    )
    assert result == {"authenticated": True}
    cookie = response.headers["set-cookie"].lower()
    assert LAN_AUTH_COOKIE_NAME in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "secure" in cookie
    assert TEST_TOKEN not in cookie

    cookie_pair = response.headers["set-cookie"].split(";", 1)[0]
    status, _headers = _middleware_status(_request(
        "/api/v1/probe",
        method="POST",
        headers={"cookie": cookie_pair},
    ))
    assert status == 200


def test_wrong_login_token_is_rejected_without_secret_disclosure(monkeypatch) -> None:
    _configure_share(monkeypatch)
    response = Response()
    with pytest.raises(HTTPException) as error:
        _route_endpoint("/login")(
            SimpleNamespace(token="wrong"),
            _request("/api/v1/auth/lan/login", method="POST"),
            response,
        )

    assert error.value.status_code == 401
    assert TEST_TOKEN not in str(error.value.detail)
    assert "set-cookie" not in response.headers


def test_session_cookie_is_not_the_raw_lan_token(monkeypatch) -> None:
    _configure_share(monkeypatch)
    credential = create_session_credential(TEST_TOKEN)
    assert credential != TEST_TOKEN
    assert len(credential) == 64

    status, _headers = _middleware_status(_request(
        "/api/v1/probe",
        headers={"cookie": f"{LAN_AUTH_COOKIE_NAME}={credential}"},
    ))
    assert status == 200


def test_loopback_only_mode_remains_credential_free(monkeypatch) -> None:
    _configure_share(monkeypatch, enabled=False)
    assert _middleware_status(_request("/api/v1/probe"))[0] == 200
    assert _middleware_status(_request("/api/v1/probe", method="POST"))[0] == 200


def test_local_loopback_client_is_exempt_even_while_sharing(monkeypatch) -> None:
    _configure_share(monkeypatch)
    request = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/probe"),
        headers={"host": "127.0.0.1:7860"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert request_requires_lan_auth(request) is False


def test_remote_peer_forwarded_by_loopback_proxy_still_requires_auth(monkeypatch) -> None:
    _configure_share(monkeypatch)
    request = _request(
        "/api/v1/probe",
        client="127.0.0.1",
        headers={
            "host": "7860.localhost",
            "x-forwarded-for": "192.168.1.30, 127.0.0.1",
        },
    )
    assert request_requires_lan_auth(request) is True


def test_loopback_proxy_host_is_fail_secure_while_sharing(monkeypatch) -> None:
    _configure_share(monkeypatch)
    request = _request(
        "/api/v1/probe",
        client="127.0.0.1",
        headers={"host": "7860.localhost"},
    )
    assert request_requires_lan_auth(request) is True


def test_public_shell_and_auth_handshake_stay_reachable(monkeypatch) -> None:
    _configure_share(monkeypatch)
    assert _middleware_status(_request("/"))[0] == 200
    assert _middleware_status(_request("/api/v1/auth/lan/status"))[0] == 200


def test_configured_token_is_never_echoed_in_startup_messages(monkeypatch) -> None:
    _configure_share(monkeypatch)
    messages = describe_lan_auth_startup()
    assert messages
    assert TEST_TOKEN not in "\n".join(messages)
    assert "LOREFRAME_LAN_TOKEN" in "\n".join(messages)


def test_weak_configured_token_is_rejected_without_echo(monkeypatch) -> None:
    _configure_share(monkeypatch)
    weak = "too-short"
    monkeypatch.setenv("LOREFRAME_LAN_TOKEN", weak)
    with pytest.raises(ValueError) as error:
        describe_lan_auth_startup()
    assert "at least 24" in str(error.value)
    assert weak not in str(error.value)


def test_failed_logins_are_rate_limited(monkeypatch) -> None:
    _configure_share(monkeypatch)
    login_endpoint = _route_endpoint("/login")
    request = _request("/api/v1/auth/lan/login", method="POST")
    for _attempt in range(8):
        with pytest.raises(HTTPException) as error:
            login_endpoint(SimpleNamespace(token="wrong"), request, Response())
        assert error.value.status_code == 401

    with pytest.raises(HTTPException) as limited:
        login_endpoint(SimpleNamespace(token=TEST_TOKEN), request, Response())
    assert limited.value.status_code == 429
    assert int(limited.value.headers["Retry-After"]) >= 1


def test_unauthenticated_classic_websocket_is_closed(monkeypatch) -> None:
    _configure_share(monkeypatch)
    sent: list[dict] = []

    async def downstream(scope, receive, send):
        raise AssertionError("unauthenticated websocket reached downstream app")

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    scope = {
        **_request("/classic/queue", headers={"upgrade": "websocket"}).scope,
        "type": "websocket",
        "subprotocols": [],
    }
    asyncio.run(LanAuthMiddleware(downstream)(scope, receive, send))
    assert sent == [{"type": "websocket.close", "code": 4401}]


def test_launch_installs_auth_middleware_router_and_startup_notice() -> None:
    tree = ast.parse((ROOT / "app" / "launch.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]

    assert any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "add_middleware"
        and call.args
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "LanAuthMiddleware"
        for call in calls
    )
    middleware_call = next(
        call for call in calls
        if isinstance(call.func, ast.Attribute)
        and call.func.attr == "add_middleware"
        and call.args
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "LanAuthMiddleware"
    )
    trace_middleware = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "trace_user_mutations"
    )
    assert middleware_call.lineno > trace_middleware.end_lineno
    assert any(
        isinstance(call.func, ast.Name)
        and call.func.id == "create_lan_auth_router"
        for call in calls
    )
    assert any(
        isinstance(call.func, ast.Name)
        and call.func.id == "describe_lan_auth_startup"
        for call in calls
    )

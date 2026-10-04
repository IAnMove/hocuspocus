"""ChatGPT-style MCP clients: OAuth 2.1 with PKCE onto a tool profile, next to the installation key."""
from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.mcp_oauth import create_mcp_oauth_router
from routers.wangp_mcp import create_wangp_mcp_router
from services.mcp_oauth import McpOAuth, profile_of

KEY = "installation-key"
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"


def operation(name, mutation=False):
    return {"name": name, "version": 1, "domain": name.split(".")[0], "mutation": mutation, "description": name,
            "inputSchema": {"type": "object", "required": ["version"], "properties": {"version": {"type": "integer", "const": 1}}}}


def app(tmp_path, key=lambda: KEY):
    oauth = McpOAuth(tmp_path / "oauth.json", key, {"series"})
    handlers = {name: (lambda name: lambda arguments: {"version": 1, "tool": name})(name)
                for name in ("series.guide", "generation.image", "scenes.video2d.export")}
    api = FastAPI()
    api.include_router(create_mcp_oauth_router(oauth))
    api.include_router(create_wangp_mcp_router(
        handlers=handlers, journal_path=tmp_path / "journal.sqlite", token_getter=key,
        command_operations=[operation("series.guide"), operation("generation.image", True), operation("scenes.video2d.export", True)],
        profiles={"series": {"tools": {"series.guide", "generation.image"}, "instructions": "Call series.guide first."}}, oauth=oauth))
    return TestClient(api, base_url="https://hocus.example.com"), oauth


def rpc(client, path, method, params=None, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(path, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def sign_in(client, resource="https://hocus.example.com/api/v1/mcp/series"):
    client_id = client.post("/oauth/register", json={"client_name": "ChatGPT", "redirect_uris": [REDIRECT]}).json()["client_id"]
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "code_challenge": CHALLENGE,
              "code_challenge_method": "S256", "state": "xyz", "resource": resource}
    page = client.get("/oauth/authorize", params=params)
    assert page.status_code == 200 and "ChatGPT" in page.text and "Series Lab" in page.text
    wrong = client.post("/oauth/authorize", data={**params, "key": "nope"}, follow_redirects=False)
    assert wrong.status_code == 403 and "clave MCP" in wrong.text
    approved = client.post("/oauth/authorize", data={**params, "key": KEY}, follow_redirects=False)
    assert approved.status_code == 302
    query = parse_qs(urlsplit(approved.headers["location"]).query)
    assert approved.headers["location"].startswith(REDIRECT) and query["state"] == ["xyz"]
    token = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": query["code"][0], "redirect_uri": REDIRECT,
                                              "client_id": client_id, "code_verifier": VERIFIER})
    assert token.status_code == 200, token.text
    return client_id, query["code"][0], token.json()


def test_discovery_points_a_client_from_the_401_to_the_authorization_server(tmp_path):
    client, _ = app(tmp_path)
    denied = rpc(client, "/api/v1/mcp/series", "tools/list")
    assert denied.status_code == 401
    challenge = denied.headers["www-authenticate"]
    assert 'resource_metadata="https://hocus.example.com/.well-known/oauth-protected-resource/api/v1/mcp/series"' in challenge
    resource = client.get("/.well-known/oauth-protected-resource/api/v1/mcp/series").json()
    assert resource["resource"] == "https://hocus.example.com/api/v1/mcp/series"
    assert resource["authorization_servers"] == ["https://hocus.example.com"]
    server = client.get("/.well-known/oauth-authorization-server").json()
    assert server["code_challenge_methods_supported"] == ["S256"] and server["registration_endpoint"].endswith("/oauth/register")
    assert server["token_endpoint_auth_methods_supported"] == ["none"]
    tunnel = client.get("/.well-known/oauth-authorization-server", headers={"x-forwarded-proto": "https", "x-forwarded-host": "abc.trycloudflare.com"})
    assert tunnel.json()["issuer"] == "https://abc.trycloudflare.com"


def test_a_signed_in_client_sees_only_its_profile(tmp_path):
    client, _ = app(tmp_path)
    _, code, tokens = sign_in(client)
    access = tokens["access_token"]
    init = rpc(client, "/api/v1/mcp/series", "initialize", token=access).json()["result"]
    assert init["instructions"] == "Call series.guide first."
    names = {tool["name"] for tool in rpc(client, "/api/v1/mcp/series", "tools/list", token=access).json()["result"]["tools"]}
    assert names == {"series.guide", "generation.image"}
    called = rpc(client, "/api/v1/mcp/series", "tools/call", {"name": "series.guide", "arguments": {"version": 1}}, token=access).json()
    assert called["result"]["structuredContent"] == {"version": 1, "tool": "series.guide"}
    outside = rpc(client, "/api/v1/mcp/series", "tools/call", {"name": "scenes.video2d.export", "arguments": {"version": 1}}, token=access)
    assert outside.json()["result"]["isError"] is True
    assert rpc(client, "/api/v1/mcp", "tools/list", token=access).status_code == 401, "a series token is not a key to everything"
    full = {tool["name"] for tool in rpc(client, "/api/v1/mcp/series", "tools/list", token=KEY).json()["result"]["tools"]}
    assert full == names, "the installation key works on a profile too"
    reused = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                               "client_id": "x", "code_verifier": VERIFIER})
    assert reused.status_code == 400 and reused.json()["error"] == "invalid_grant", "codes are single use"
    assert rpc(client, "/api/v1/mcp/unknown", "tools/list", token=KEY).status_code == 404


def test_refresh_rotates_and_a_new_key_ends_every_token(tmp_path):
    client, oauth = app(tmp_path)
    client_id, _, tokens = sign_in(client)
    renewed = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}).json()
    assert renewed["access_token"] != tokens["access_token"]
    again = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id})
    assert again.status_code == 400, "a used refresh token is gone"
    assert rpc(client, "/api/v1/mcp/series", "tools/list", token=renewed["access_token"]).status_code == 200
    oauth.revoke_all()
    assert rpc(client, "/api/v1/mcp/series", "tools/list", token=renewed["access_token"]).status_code == 401


def test_pkce_redirects_and_wrong_keys_are_checked(tmp_path):
    client, oauth = app(tmp_path)
    bad = client.post("/oauth/register", json={"redirect_uris": ["http://evil.example.com/cb"]})
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_redirect_uri"
    client_id = client.post("/oauth/register", json={"redirect_uris": [REDIRECT]}).json()["client_id"]
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "code_challenge": CHALLENGE,
              "code_challenge_method": "plain"}
    assert client.get("/oauth/authorize", params=params).status_code == 400, "S256 only"
    params["code_challenge_method"] = "S256"
    assert client.get("/oauth/authorize", params={**params, "redirect_uri": "https://other.example.com/cb"}).status_code == 400
    for _ in range(5):
        assert client.post("/oauth/authorize", data={**params, "key": "guess"}, follow_redirects=False).status_code == 403
    assert client.post("/oauth/authorize", data={**params, "key": KEY}, follow_redirects=False).status_code == 429
    oauth.failures.clear()
    location = client.post("/oauth/authorize", data={**params, "key": KEY}, follow_redirects=False).headers["location"]
    code = parse_qs(urlsplit(location).query)["code"][0]
    wrong = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                              "client_id": client_id, "code_verifier": "w" * 64})
    assert wrong.status_code == 400 and wrong.json()["error"] == "invalid_grant"


def test_turning_access_off_disables_oauth_tokens(tmp_path):
    key = {"value": KEY}
    client, _ = app(tmp_path, key=lambda: key["value"])
    _, _, tokens = sign_in(client)
    key["value"] = ""
    assert rpc(client, "/api/v1/mcp/series", "tools/list", token=tokens["access_token"]).status_code == 503


@pytest.mark.parametrize("resource, expected", [
    ("https://x.example.com/api/v1/mcp/series", "series"), ("https://x.example.com/api/v1/mcp", "all"), (None, "all"),
    ("https://x.example.com/api/v1/mcp/series/extra", "all")])
def test_the_resource_picks_the_profile(resource, expected):
    assert profile_of(resource) == expected

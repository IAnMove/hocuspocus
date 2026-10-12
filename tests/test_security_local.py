"""A local app without a login still has to keep its keys and its files to itself."""
from pathlib import Path

from services.lan_auth import lan_auth_enabled, request_requires_lan_auth, verify_lan_token
from services.provider_profile import client_remote_url
from services.win_safe_files import ShareDeleteFileResponse


def test_public_providers_keep_their_saved_url_whatever_the_client_sends():
    saved = "https://api.openai.com"
    assert client_remote_url("openai", "http://attacker.example/", saved) == saved
    assert client_remote_url("grok", "http://127.0.0.1:1/internal", "") == ""
    assert client_remote_url("anthropic", "http://attacker.example/", "") == ""
    assert client_remote_url("remote", " http://192.168.1.5:1234 ", saved) == "http://192.168.1.5:1234"
    assert client_remote_url("ollama", "", "http://127.0.0.1:11434") == "http://127.0.0.1:11434"


def test_served_files_are_never_sniffed_and_active_types_download(tmp_path):
    page = tmp_path / "upload.html"
    page.write_text("<script>alert(1)</script>")
    response = ShareDeleteFileResponse(str(page))
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == "attachment"
    picture = tmp_path / "frame.png"
    picture.write_bytes(b"\x89PNG")
    plain = ShareDeleteFileResponse(str(picture))
    assert plain.headers["x-content-type-options"] == "nosniff" and "content-disposition" not in plain.headers
    drawing = ShareDeleteFileResponse(str(tmp_path / "x.svg"), media_type="image/svg+xml")
    assert drawing.headers["content-disposition"] == "attachment"


def test_sharing_on_the_lan_turns_the_token_gate_on_unless_opted_out(monkeypatch):
    monkeypatch.setenv("PINOKIO_SHARE_LOCAL", "true")
    monkeypatch.delenv("LOREFRAME_LAN_AUTH", raising=False)
    assert lan_auth_enabled() is True
    monkeypatch.setenv("LOREFRAME_LAN_AUTH", "0")
    assert lan_auth_enabled() is False
    monkeypatch.setenv("LOREFRAME_LAN_AUTH", "1")
    assert lan_auth_enabled() is True
    monkeypatch.delenv("LOREFRAME_LAN_AUTH", raising=False)
    monkeypatch.setenv("PINOKIO_SHARE_LOCAL", "false")
    assert lan_auth_enabled() is False, "loopback only: nothing to protect"


def test_mcp_profiles_are_exempt_from_the_lan_gate_like_the_root_endpoint(monkeypatch):
    monkeypatch.setenv("PINOKIO_SHARE_LOCAL", "true")
    monkeypatch.setenv("LOREFRAME_LAN_AUTH", "true")
    monkeypatch.setenv("LOREFRAME_LAN_TOKEN", "test-lan-token-with-at-least-32-bytes")

    class Request:
        def __init__(self, path):
            self.url = type("U", (), {"path": path})()
            self.headers = {"host": "tunnel.trycloudflare.com"}
            self.client = type("C", (), {"host": "198.51.100.7"})()

    assert request_requires_lan_auth(Request("/api/v1/mcp")) is False
    assert request_requires_lan_auth(Request("/api/v1/mcp/series")) is False
    assert request_requires_lan_auth(Request("/api/v1/mcpx")) is True
    assert request_requires_lan_auth(Request("/api/v1/outputs")) is True


def test_a_credential_with_non_ascii_bytes_is_simply_wrong(monkeypatch):
    monkeypatch.setenv("LOREFRAME_LAN_TOKEN", "test-lan-token-with-at-least-32-bytes")
    assert verify_lan_token("clavé-que-no-esé") is False
    assert verify_lan_token("test-lan-token-with-at-least-32-bytes") is True

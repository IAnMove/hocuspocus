"""The server answers only to host names that are its own; a rebound domain gets 421."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import host_guard


def test_our_own_names_are_allowed_and_strangers_are_not(monkeypatch):
    monkeypatch.setenv("HOCUS_PUBLIC_URL", "https://quiet-river-1234.example.net")
    monkeypatch.setenv("HOCUS_TRUSTED_HOSTS", "studio.lan, Media-PC:7860")
    trusted = host_guard.configured_hosts()
    assert trusted == {"quiet-river-1234.example.net", "studio.lan", "media-pc"}
    for host in ("", "127.0.0.1:42003", "192.168.1.87:42003", "[::1]:42003", "localhost", "42003.localhost",
                 "LOCALHOST:7860", "abc-def.trycloudflare.com", "quiet-river-1234.example.net", "media-pc:7860"):
        assert host_guard.host_allowed(host, trusted), host
    for host in ("evil.example", "evil.example:42003", "localhost.evil.example", "127.0.0.1.evil.example", "x.trycloudflare.com.evil.net"):
        assert not host_guard.host_allowed(host, trusted), host
    assert host_guard.host_allowed("this-machine", {"this-machine"})
    names = host_guard.machine_names()
    assert names and all(name == name.lower() for name in names)


def test_the_middleware_rejects_a_rebound_domain_before_any_handler(monkeypatch):
    monkeypatch.delenv("HOCUS_PUBLIC_URL", raising=False)
    monkeypatch.setenv("HOCUS_TRUSTED_HOSTS", "testserver")
    api = FastAPI()
    host_guard.install_host_guard(api)
    calls = []

    @api.get("/api/v1/secret")
    def secret():
        calls.append(1)
        return {"ok": True}

    client = TestClient(api)
    assert client.get("/api/v1/secret").status_code == 200
    assert client.get("/api/v1/secret", headers={"Host": "127.0.0.1:42003"}).status_code == 200
    rebound = client.get("/api/v1/secret", headers={"Host": "evil.example:42003"})
    assert rebound.status_code == 421 and "host name" in rebound.json()["detail"]
    assert client.post("/api/v1/secret", headers={"Host": "evil.example"}).status_code == 421
    assert calls == [1, 1], "the handler never ran for the stranger"

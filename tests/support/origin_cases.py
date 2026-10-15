"""The browser-origin matrix both servers must answer alike (services/request_guards.py).

``tests/characterization/test_launch_misc_bind.py`` drives it through the full server and
``tests/test_core_runtime.py`` through the core server, so a change to one server's guards shows up as a difference.
"""
from __future__ import annotations

REFUSED = (403, {"detail": "Cross-origin API mutations are not allowed"})
# (method, Origin header, Host header, refused by the cross-origin check)
ORIGIN_CASES = (
    *[(method, "http://evil.example", "testserver", True) for method in ("POST", "PUT", "PATCH", "DELETE")],
    *[(method, "http://evil.example", "testserver", False) for method in ("GET", "HEAD", "OPTIONS")],
    ("POST", None, "testserver", False),
    ("POST", "http://testserver", "testserver", False),
    ("DELETE", "http://TestServer", "testserver", False),
    ("POST", "http://testserver:8080", "testserver", True),
    ("POST", "http://localhost:5173", "127.0.0.1:42003", False),
    ("PATCH", "http://[::1]:5173", "localhost:42003", False),
    ("POST", "http://127.0.0.1:5173", "192.168.1.5:42003", True),
    ("POST", "http://192.168.1.5:5173", "127.0.0.1:42003", True),
    ("POST", "http://0.0.0.0:5173", "127.0.0.1:42003", True),
    ("PUT", "https://42003.localhost", "192.168.1.5:42003", False),
    ("POST", "http://42003.localhost:8080", "testserver", False),
    ("POST", "http://x42003.localhost", "testserver", True),
    ("POST", "http://42003.localhost.evil.example", "testserver", True),
    ("POST", "http://192.168.1.5:42003", "192.168.1.5:42003", False),
    ("DELETE", "http://192.168.1.5:5173", "192.168.1.5:42003", True),
    ("POST", "http://[bad", "testserver", True),
    ("POST", "null", "testserver", True),
)


def answer(response) -> tuple:
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text


def refused_by_origin(client, path: str = "/api/v1/__guard_probe__") -> list[tuple]:
    """(method, Origin, Host, refused) for every case, as ``client`` answers them."""
    seen = []
    for method, origin, host, _refused in ORIGIN_CASES:
        headers = {"host": host} if origin is None else {"host": host, "origin": origin}
        seen.append((method, origin, host, answer(client.request(method, path, headers=headers)) == REFUSED))
    return seen

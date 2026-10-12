"""Only answer requests addressed to this machine (``Host`` header).

A page in the user's browser can call ``127.0.0.1:<port>`` with its own
name as ``Host`` when its domain is pointed at 127.0.0.1 (DNS rebinding); the
browser then treats it as the same origin as the app and the CORS and
Origin checks never trigger. Rejecting unknown host names closes that door
without a login: IP literals, ``localhost``, the machine's own name, a
Cloudflare quick tunnel and whatever ``HOCUS_PUBLIC_URL`` or
``HOCUS_TRUSTED_HOSTS`` name are the hosts a real user types.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

PUBLIC_URL_ENV = "HOCUS_PUBLIC_URL"
TRUSTED_HOSTS_ENV = "HOCUS_TRUSTED_HOSTS"
TUNNEL_SUFFIXES = (".trycloudflare.com",)


def _name(host_header: str) -> str:
    """The host name of a ``Host`` header, lower case, without port or brackets."""
    value = str(host_header or "").strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else value[1:]
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def _is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def machine_names() -> set[str]:
    """Names this machine answers to: its hostname, with and without ``.local``."""
    names = set()
    try:
        host = socket.gethostname().strip().lower()
    except OSError:
        host = ""
    if host:
        names.add(host)
        names.add(host.split(".", 1)[0])
        names.add(f"{host.split('.', 1)[0]}.local")
    return names


def configured_hosts(environ=None) -> set[str]:
    env = os.environ if environ is None else environ
    names = set()
    public = str(env.get(PUBLIC_URL_ENV) or "").strip()
    if public:
        parsed = urlsplit(public if "//" in public else f"//{public}")
        if parsed.hostname:
            names.add(parsed.hostname.lower())
    for item in str(env.get(TRUSTED_HOSTS_ENV) or "").split(","):
        item = _name(item)
        if item:
            names.add(item)
    return names


def host_allowed(host_header: str, trusted: Iterable[str] = ()) -> bool:
    """True for an empty Host (non-browser clients), an IP, localhost, this machine, a tunnel or a trusted name."""
    name = _name(host_header)
    if not name or _is_ip(name) or name == "localhost" or name.endswith(".localhost"):
        return True
    if name.endswith(TUNNEL_SUFFIXES):
        return True
    return name in set(trusted)


def install_host_guard(api, *, trusted: Callable[[], Iterable[str]] | None = None) -> None:
    """Reject requests whose Host is not one of ours with 421, before any handler runs."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    names = trusted or (lambda: machine_names() | configured_hosts())

    @api.middleware("http")
    async def guard_host(request: Request, call_next):
        if not host_allowed(request.headers.get("host", ""), names()):
            return JSONResponse(status_code=421, content={"detail": "This server does not answer to that host name"})
        return await call_next(request)


__all__ = ["PUBLIC_URL_ENV", "TRUSTED_HOSTS_ENV", "configured_hosts", "host_allowed", "install_host_guard", "machine_names"]

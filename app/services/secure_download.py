"""One https downloader for remote catalogs: allowed hosts, bounded reads, mandatory checksums.

Every remote file the app installs on request (example collections, the asset
library, community templates) goes through here:

- only ``https://`` URLs without credentials, and only to hosts the caller allows;
- redirects are followed only to another allowed host over https;
- a read never takes more than ``limit + 1`` bytes, so an oversized answer fails
  instead of filling the disk;
- a download with a declared size and SHA-256 is published only when both match.
"""
from __future__ import annotations

import hashlib
import urllib.request
from collections.abc import Callable, Iterable
from typing import IO, Any
from urllib.parse import urljoin, urlparse

USER_AGENT = "HocusPocus/1"
TIMEOUT_SECONDS = 30
CHUNK_BYTES = 1024 * 1024

Opener = Callable[..., Any]


class DownloadRefused(ValueError):
    """The URL, a redirect, the size or the checksum broke the download policy."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class DownloadCancelled(Exception):
    """The caller's cancel hook asked to stop."""


def _hosts(hosts: Iterable[str]) -> frozenset[str]:
    return frozenset(str(host).casefold() for host in hosts)


def check_url(url: Any, hosts: Iterable[str]) -> str:
    """Return ``url`` when it is a plain https URL to an allowed host; raise otherwise."""
    text = str(url or "")
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DownloadRefused("Only https:// downloads are allowed", "not_https")
    if parsed.username or parsed.password:
        raise DownloadRefused("Download links must not carry credentials", "credentials")
    if parsed.hostname.casefold() not in _hosts(hosts):
        raise DownloadRefused(f"Downloads from {parsed.hostname} are not allowed", "host_not_allowed")
    return text


class _AllowedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only when its target passes the same policy as the first URL."""

    def __init__(self, hosts: frozenset[str]) -> None:
        super().__init__()
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802 - urllib API
        target = urljoin(req.full_url, newurl)
        try:
            check_url(target, self.hosts)
        except DownloadRefused as refused:
            raise DownloadRefused(f"Refused redirect to {urlparse(target).hostname or target}", "redirect_refused") from refused
        return super().redirect_request(req, fp, code, msg, headers, target)


def open_url(url: str, timeout: float = TIMEOUT_SECONDS, *, hosts: Iterable[str], user_agent: str = USER_AGENT):
    """Open ``url`` under the policy; the response is a context manager with ``read``."""
    allowed = _hosts(hosts)
    request = urllib.request.Request(check_url(url, allowed), headers={"User-Agent": user_agent})
    opener = urllib.request.build_opener(_AllowedRedirects(allowed))
    return opener.open(request, timeout=timeout)


def opener_for(hosts: Iterable[str], user_agent: str = USER_AGENT) -> Opener:
    """An ``urlopen``-shaped callable bound to one caller's allowed hosts."""
    allowed = _hosts(hosts)

    def opener(url: str, timeout: float = TIMEOUT_SECONDS):
        return open_url(url, timeout, hosts=allowed, user_agent=user_agent)

    return opener


def read_limited(response: IO[bytes], limit: int) -> bytes:
    """Read the whole body, refusing anything larger than ``limit`` bytes."""
    data = response.read(limit + 1)
    if len(data) > limit:
        raise DownloadRefused("Remote file is larger than allowed", "too_large")
    return data


def fetch_limited(url: str, limit: int, *, hosts: Iterable[str], opener: Opener | None = None,
                  timeout: float = TIMEOUT_SECONDS, user_agent: str = USER_AGENT) -> bytes:
    """A small file whose hash is not known in advance (a catalog index); callers verify what it lists."""
    allowed = _hosts(hosts)
    check_url(url, allowed)
    with (opener or opener_for(allowed, user_agent))(url, timeout) as response:
        return read_limited(response, limit)


def verify_bytes(data: bytes, sha256: str) -> bytes:
    if hashlib.sha256(data).hexdigest() != str(sha256 or "").casefold():
        raise DownloadRefused("Downloaded file does not match its checksum", "checksum_mismatch")
    return data


def copy_verified(response: IO[bytes], output: IO[bytes], *, size: int, sha256: str,
                  cancelled: Callable[[], bool] = lambda: False,
                  progress: Callable[[int], None] = lambda count: None) -> None:
    """Stream ``response`` into ``output``; the copy is valid only if size and SHA-256 match exactly."""
    if len(str(sha256 or "")) != 64:
        raise DownloadRefused("A download needs its SHA-256", "checksum_missing")
    digest, received = hashlib.sha256(), 0
    while chunk := response.read(CHUNK_BYTES):
        if cancelled():
            raise DownloadCancelled()
        received += len(chunk)
        if received > size:
            raise DownloadRefused("Download exceeds its declared size", "too_large")
        output.write(chunk)
        digest.update(chunk)
        progress(len(chunk))
    if received != size or digest.hexdigest() != str(sha256).casefold():
        raise DownloadRefused("Download failed integrity verification", "integrity")


__all__ = [
    "DownloadCancelled", "DownloadRefused", "check_url", "copy_verified", "fetch_limited",
    "open_url", "opener_for", "read_limited", "verify_bytes",
]

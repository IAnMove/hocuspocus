"""Community template index: browse and install shared ``.hptemplate`` files.

The index is a small JSON file published by the community site (a GitHub repo
with GitHub Pages). The server fetches it only when someone opens the Community
tab, downloads packages only from the index host (or the repo's raw files),
checks size and SHA-256 and imports them into the library as ``community``.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable
from urllib.parse import urlparse

from services.secure_download import DownloadRefused, fetch_limited
from services.template_format import ID_RE, TemplateError
from services.template_library import MAX_ZIP_BYTES, TemplateLibrary

INDEX_ENV = "HOCUS_TEMPLATE_COMMUNITY_INDEX"
DEFAULT_INDEX = "https://ianmove.github.io/hocuspocus-community/index.json"
INDEX_KIND = "hocuspocus.community-index"
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 2000
CACHE_SECONDS = 600
RAW_HOSTS = ("raw.githubusercontent.com",)

Fetcher = Callable[[str, int], bytes]


def http_fetch(url: str, limit: int) -> bytes:
    """The caller already checked the host; redirects may only stay on that host or the raw-files host."""
    hosts = {urlparse(url).hostname or "", *RAW_HOSTS}
    try:
        return fetch_limited(url, limit, hosts=hosts, timeout=20, user_agent="HocusPocus-templates/1")
    except DownloadRefused as refused:
        if refused.code == "too_large":
            raise TemplateError("Remote file is larger than allowed", code="too_large") from refused
        raise TemplateError(str(refused), status=502, code=refused.code) from refused


def _https(url: Any) -> str:
    text = str(url or "")
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise TemplateError("Community links must be plain https:// URLs", code="invalid_index")
    return text


def _entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not ID_RE.fullmatch(str(raw.get("id") or "")):
        return None
    sha = str(raw.get("sha256") or "")
    if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
        return None
    try:
        package = _https(raw.get("package"))
        preview = _https(raw["preview"]) if raw.get("preview") else None
    except TemplateError:
        return None
    text = lambda key, limit: str(raw.get(key) or "")[:limit]  # noqa: E731
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    return {
        "id": raw["id"], "editor": raw.get("editor") if raw.get("editor") in ("video3d", "video2d") else "video3d",
        "title": text("title", 80) or raw["id"], "description": text("description", 600),
        "tags": [str(tag)[:30] for tag in raw.get("tags") or []][:12],
        "author": {key: str(author[key])[:80] for key in ("name", "x", "url") if author.get(key)},
        "license": text("license", 40), "templateVersion": text("templateVersion", 20),
        "slots": int(raw.get("slots") or 0), "controls": int(raw.get("controls") or 0), "media": int(raw.get("media") or 0),
        "bytes": int(raw.get("bytes") or 0), "sha256": sha, "package": package, "preview": preview,
    }


class CommunityIndex:
    def __init__(self, library: TemplateLibrary, *, index_url: str | None = None, fetch: Fetcher = http_fetch) -> None:
        self.library = library
        self.index_url = index_url or os.environ.get(INDEX_ENV) or DEFAULT_INDEX
        self.fetch = fetch
        self._cache: tuple[float, dict[str, Any]] | None = None

    def _allowed(self, url: str) -> bool:
        host = urlparse(url).netloc.casefold()
        return host == urlparse(self.index_url).netloc.casefold() or host in RAW_HOSTS

    def _load(self, refresh: bool) -> dict[str, Any]:
        if self._cache and not refresh and time.time() - self._cache[0] < CACHE_SECONDS:
            return self._cache[1]
        try:
            raw = json.loads(self.fetch(_https(self.index_url), MAX_INDEX_BYTES).decode("utf-8"))
        except TemplateError:
            raise
        except (OSError, ValueError) as exc:
            raise TemplateError(f"The community index is not reachable right now ({type(exc).__name__})",
                                status=503, code="index_unavailable") from exc
        if not isinstance(raw, dict) or raw.get("kind") != INDEX_KIND or raw.get("version") != 1:
            raise TemplateError("Not a HocusPocus community index", status=502, code="invalid_index")
        entries = [entry for entry in map(_entry, (raw.get("templates") or [])[:MAX_ENTRIES]) if entry and self._allowed(entry["package"])]
        index = {"url": self.index_url, "updatedAt": str(raw.get("updatedAt") or ""), "templates": entries}
        self._cache = (time.time(), index)
        return index

    def _installed(self) -> dict[str, dict[str, Any]]:
        installed = {}
        for summary in self.library.summaries():
            folder = self.library.root / summary["id"]
            installed[summary["id"]] = {"source": summary["source"], "sha256": self.library._origin(folder).get("sha256")}
        return installed

    def listing(self, *, refresh: bool = False, editor: str | None = None, query: str | None = None) -> dict[str, Any]:
        index = self._load(refresh)
        installed = self._installed()
        items = []
        for entry in index["templates"]:
            text = " ".join([entry["title"], entry["description"], " ".join(entry["tags"])]).casefold()
            if (editor and entry["editor"] != editor) or (query and query.casefold() not in text):
                continue
            local = installed.get(entry["id"])
            state = "available" if not local else ("installed" if local.get("sha256") == entry["sha256"] else
                                                   "update" if local.get("source") == "community" else "conflict")
            items.append({**entry, "state": state})
        return {"url": index["url"], "updatedAt": index["updatedAt"], "templates": items}

    def install(self, template_id: str, *, replace: bool = False) -> dict[str, Any]:
        entry = next((item for item in self._load(False)["templates"] if item["id"] == template_id), None)
        if entry is None:
            raise TemplateError("That template is not in the community index", status=404, code="not_found")
        if not self._allowed(entry["package"]):
            raise TemplateError("Package host is not allowed", status=403, code="host_not_allowed")
        local = self._installed().get(template_id)
        if local and local.get("source") != "community" and not replace:
            raise TemplateError("You already have your own template with this id; pass replace to overwrite it",
                                status=409, code="exists")
        try:
            data = self.fetch(entry["package"], MAX_ZIP_BYTES)
        except TemplateError:
            raise
        except OSError as exc:
            raise TemplateError("Could not download the template", status=503, code="download_failed") from exc
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise TemplateError("Downloaded file does not match the index checksum", status=502, code="checksum_mismatch")
        if self.library.read_package(data)["manifest"]["id"] != template_id:
            raise TemplateError("The package id does not match the index entry", status=502, code="id_mismatch")
        return self.library.import_package(data, replace=True, source="community")


__all__ = ["CommunityIndex", "DEFAULT_INDEX", "INDEX_ENV", "INDEX_KIND", "http_fetch"]

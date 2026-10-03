"""Optional asset library: CC0 HDRIs, materials, LUTs, animations, sound effects and models.

Nothing is downloaded at startup or when the catalog is listed; a collection is
installed only when the user asks (``POST /api/v1/library/install``). The pinned
manifest ``app/resources/asset_library.json`` lists every file with its size,
SHA-256 and license; files live content-addressed in ``app/cache/library`` and
are verified again when read, exactly like the optional examples.

A file without a license, an https source URL, an author or the date it was
taken is rejected when the manifest loads, so every installed file can be
credited.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from services.example_assets import ExampleAssets
from services.media_kinds import LIBRARY_KINDS, library_kind_accepts
from services.secure_download import DownloadRefused, check_url

APP_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = APP_ROOT / "resources" / "asset_library.json"
CACHE_DIR = APP_ROOT / "cache" / "library"
SCHEMA_NAME = "hocuspocus.asset-library"
# Collection archives are GitHub release files; GitHub redirects them to its storage hosts.
ARCHIVE_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
# Only public-domain files for now. Accepting CC-BY (credit required) is the user's decision.
LICENSES = frozenset({"CC0-1.0"})
LICENSE_KEYS = ("license", "source", "source_url", "author", "retrieved_at")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COLLECTION_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_FILE_KEY = re.compile(r"([0-9a-f]{64})(\.[a-z0-9]{1,8})")


class LibraryManifestError(ValueError):
    """The library manifest breaks the contract; the message names the file or collection."""


def _fail(where: str, problem: str) -> None:
    raise LibraryManifestError(f"{where}: {problem}")


def _text(entry: dict, key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _check_name(name: Any) -> None:
    path = PurePosixPath(str(name))
    if not isinstance(name, str) or not name or "\\" in name or path.is_absolute() or len(name) > 240 \
            or any(part in ("", ".", "..") for part in name.split("/")):
        _fail(str(name), "file names must be relative paths inside the collection")


def _check_source_url(where: str, url: Any) -> None:
    try:
        check_url(url, [urlparse(str(url or "")).hostname or ""])
    except DownloadRefused:
        _fail(where, "source_url must be a plain https:// link")


def _check_date(where: str, value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail(where, "retrieved_at must be a YYYY-MM-DD date")


def _check_file(name: str, entry: Any, collections: dict) -> None:
    _check_name(name)
    if not isinstance(entry, dict):
        _fail(name, "entry must be an object")
    kind = entry.get("kind")
    if kind not in LIBRARY_KINDS or not library_kind_accepts(kind, name):
        _fail(name, f"kind must be one of {sorted(LIBRARY_KINDS)} and match the extension")
    if not _positive_int(entry.get("size")) or not _SHA256.fullmatch(str(entry.get("sha256") or "")):
        _fail(name, "size and sha256 are required")
    if entry.get("license") not in LICENSES:
        _fail(name, f"license must be one of {sorted(LICENSES)}")
    for key in ("source", "author", "retrieved_at"):
        if not _text(entry, key):
            _fail(name, f"{key} is required")
    _check_source_url(name, entry.get("source_url"))
    _check_date(name, _text(entry, "retrieved_at"))
    if entry.get("collection") not in collections:
        _fail(name, "collection must name a collection of this manifest")


def _check_archive(where: str, archive: Any) -> None:
    if not isinstance(archive, dict) or not _positive_int(archive.get("size")) \
            or not _SHA256.fullmatch(str(archive.get("sha256") or "")):
        _fail(where, "archive needs url, size and sha256")
    try:
        check_url(archive.get("url"), ARCHIVE_HOSTS)
    except DownloadRefused:
        _fail(where, f"archive url must be https on {', '.join(ARCHIVE_HOSTS)}")


def _check_members(collection_id: str, names: Any, files: dict) -> None:
    if not isinstance(names, list) or not names or len(names) != len(set(names)):
        _fail(collection_id, "files must be a non-empty list without repeats")
    for name in names:
        if name not in files or files[name].get("collection") != collection_id:
            _fail(collection_id, f"{name} is not a file of this collection")


def _check_collection(collection_id: str, pack: Any, files: dict, collections: dict) -> None:
    if not _COLLECTION_ID.fullmatch(str(collection_id)) or not isinstance(pack, dict):
        _fail(str(collection_id), "collection ids are lowercase words joined by hyphens")
    names = pack.get("files")
    _check_members(collection_id, names, files)
    dependencies = pack.get("dependencies", [])
    if not isinstance(dependencies, list) or any(item not in collections or item == collection_id for item in dependencies):
        _fail(collection_id, "dependencies must name other collections")
    if pack.get("size") != sum(files[name]["size"] for name in names):
        _fail(collection_id, "size must be the sum of its file sizes")
    _check_archive(collection_id, pack.get("archive"))


def validate_library_manifest(manifest: Any) -> dict:
    """Return ``manifest`` when every file and collection follows the contract; raise otherwise."""
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA_NAME:
        raise LibraryManifestError(f"schema must be {SCHEMA_NAME}")
    if not _positive_int(manifest.get("revision")):
        raise LibraryManifestError("revision must be a positive integer")
    files, collections = manifest.get("files"), manifest.get("collections")
    if not isinstance(files, dict) or not isinstance(collections, dict):
        raise LibraryManifestError("files and collections must be objects")
    for name, entry in files.items():
        _check_file(name, entry, collections)
    for collection_id, pack in collections.items():
        _check_collection(collection_id, pack, files, collections)
    listed = [name for pack in collections.values() for name in pack["files"]]
    if sorted(listed) != sorted(files):
        raise LibraryManifestError("every file must belong to exactly one collection")
    return manifest


class AssetLibrary(ExampleAssets):
    """The examples' verified, content-addressed cache, with a license on every file."""

    def __init__(self, cache: Path, manifest: dict):
        super().__init__(cache, validate_library_manifest(manifest))
        self._by_key = {self.key(name): name for name in self.files}

    def key(self, name: str) -> str:
        """The public, content-addressed name of a file: ``<sha256><extension>``."""
        return self.files[name]["sha256"] + PurePosixPath(name).suffix.casefold()

    def file_for(self, key: str) -> str | None:
        return self._by_key.get(key) if _FILE_KEY.fullmatch(key or "") else None

    def license_for(self, name: str) -> dict[str, str]:
        """The block for ``build_asset_manifest(license=...)`` when the file is used in a workspace."""
        entry = self.entry(name)
        return {"spdx": entry["license"], "source": entry["source"], "source_url": entry["source_url"],
                "author": entry["author"], "retrieved_at": entry["retrieved_at"]}

    def items(self, collection: str) -> list[dict[str, Any]]:
        return [{"name": name, "kind": self.files[name]["kind"], "size": self.files[name]["size"],
                 "sha256": self.files[name]["sha256"], "collection": collection,
                 **{key: self.files[name][key] for key in LICENSE_KEYS},
                 "url": f"/api/v1/library/files/{self.key(name)}"}
                for name in self.collections[collection]["files"]]

    def summary(self, collection: str) -> dict[str, Any]:
        pack = self.collections[collection]
        entries = [self.files[name] for name in pack["files"]]
        return {"title": str(pack.get("title") or collection), "kinds": sorted({entry["kind"] for entry in entries}),
                "licenses": sorted({entry["license"] for entry in entries}),
                "sources": sorted({entry["source"] for entry in entries}), "files": len(entries)}


def load_asset_library(manifest_path: Path = MANIFEST_PATH, cache: Path = CACHE_DIR) -> AssetLibrary:
    return AssetLibrary(cache, json.loads(manifest_path.read_text(encoding="utf-8")))


# Construction reads only the small pinned manifest, never the network.
asset_library = load_asset_library()


__all__ = [
    "ARCHIVE_HOSTS", "AssetLibrary", "LICENSES", "LibraryManifestError", "SCHEMA_NAME", "asset_library",
    "load_asset_library", "validate_library_manifest",
]

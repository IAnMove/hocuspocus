"""Optional example media installed only by an explicit collection download.

GET requests and server startup never download examples. Only manifest-listed
resources can be served; verified installed files remain usable offline.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = APP_ROOT / "resources" / "example_assets.json"


class ExampleUnavailable(Exception):
    pass


class ExampleAssets:
    def __init__(self, cache: Path, manifest: dict):
        self.cache = cache
        self.revision = manifest["revision"]
        self.files = manifest["files"]
        self.collections = manifest.get("collections", {})
        self._verified: dict[str, tuple] = {}

    def entry(self, name: str) -> dict:
        if name not in self.files:
            raise KeyError(name)
        return self.files[name]

    def _target(self, name: str) -> Path:
        entry = self.entry(name)
        # Content-addressed flat storage: request paths never become disk paths.
        return self.cache / (entry["sha256"] + Path(name).suffix)

    def cached(self, name: str) -> Path | None:
        target = self._target(name)
        entry = self.entry(name)
        try:
            stat = target.stat()
            identity = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            if stat.st_size != entry["size"]:
                return None
            if self._verified.get(target.name) != identity:
                with target.open("rb") as source:
                    hasher = hashlib.sha256()
                    while chunk := source.read(1024 * 1024):
                        hasher.update(chunk)
                    digest = hasher.hexdigest()
                if digest != entry["sha256"]:
                    return None
                self._verified[target.name] = identity
            return target
        except OSError:
            return None

    def resolve(self, name: str) -> Path:
        existing = self.cached(name)
        if existing:
            return existing
        raise ExampleUnavailable("Download this example collection from the shot library first.")

    def installed(self, collection: str) -> bool:
        pack = self.collections[collection]
        receipt = self.cache / (collection + ".installed.json")
        try:
            if json.loads(receipt.read_text())["sha256"] != pack["archive"]["sha256"]:
                return False
            return all(self.cached(name) is not None for name in pack["files"])
        except (OSError, ValueError, KeyError):
            return False

    def closure(self, collections: list[str]) -> list[str]:
        found = set()
        def visit(name):
            if name in found:
                return
            pack = self.collections[name]
            found.add(name)
            for dependency in pack["dependencies"]:
                visit(dependency)
        for name in collections:
            visit(name)
        return sorted(found)


def load_example_assets() -> ExampleAssets:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return ExampleAssets(APP_ROOT / "cache" / "examples", manifest)


# Construction reads only a small local manifest, never the network.
example_assets = load_example_assets()

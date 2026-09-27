"""Optional example media, fetched individually from a pinned public revision.

Importing this module or starting the server never downloads examples. Only
manifest-listed resources can be requested; verified files remain usable offline.
"""
from __future__ import annotations

import hashlib
from http.client import HTTPException as HTTPClientError
import json
import os
from pathlib import Path
import tempfile
from threading import Lock, Semaphore
from urllib.parse import quote
from urllib.request import urlopen

APP_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = APP_ROOT / "resources" / "example_assets.json"


class ExampleUnavailable(Exception):
    pass


class ExampleAssets:
    def __init__(self, cache: Path, manifest: dict):
        self.cache = cache
        self.revision = manifest["revision"]
        self.files = manifest["files"]
        self._locks = [Lock() for _ in range(64)]
        self._downloads = Semaphore(4)
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
        entry = self.entry(name)
        lock = self._locks[int(entry["sha256"][:8], 16) % len(self._locks)]
        with lock:
            existing = self.cached(name)
            if existing:
                return existing
            temporary = None
            try:
                with self._downloads:
                    self.cache.mkdir(parents=True, exist_ok=True)
                    url = f"https://raw.githubusercontent.com/IAnMove/hocuspocus/{self.revision}/ui/public/examples/{quote(name, safe='/')}"
                    digest, size = hashlib.sha256(), 0
                    with urlopen(url, timeout=30) as response, tempfile.NamedTemporaryFile(dir=self.cache, suffix=".partial", delete=False) as output:
                        temporary = Path(output.name)
                        while chunk := response.read(1024 * 1024):
                            size += len(chunk)
                            if size > entry["size"]:
                                raise ExampleUnavailable("Example download exceeds its declared size")
                            digest.update(chunk)
                            output.write(chunk)
                    if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                        raise ExampleUnavailable("Example download failed verification")
                    target = self._target(name)
                    os.replace(temporary, target)
                    return target
            except (OSError, ValueError, HTTPClientError) as error:
                raise ExampleUnavailable("Example unavailable. Connect to the internet and retry; downloaded examples work offline.") from error
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)


def load_example_assets() -> ExampleAssets:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return ExampleAssets(APP_ROOT / "cache" / "examples", manifest)


# Construction reads only a small local manifest, never the network.
example_assets = load_example_assets()

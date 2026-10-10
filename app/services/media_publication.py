"""Restore a publication's files if its metadata or receipt cannot be committed.

Callers hold their workspace writer lock throughout this scope. Existing files
are kept as hard links (copies on filesystems without links); writers replace
files rather than changing those inodes. This does not claim crash atomicity.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from services.workspace_store_lock import workspace_store_lock


def publication_lock(folder):
    """One cross-process lock for workspace media and sidecar publishers."""
    return workspace_store_lock(Path(folder).resolve() / ".media-publication")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _backup(path: Path, target: Path) -> Path | None:
    if not path.exists():
        return None
    try:
        os.link(path, target)
    except OSError:
        shutil.copy2(path, target)
    return target


@contextmanager
def publication_transaction(paths):
    """Roll back file replacements, creations and removals on a failed publish."""
    paths = tuple(dict.fromkeys(Path(path) for path in paths))
    with TemporaryDirectory(prefix=".publication-", dir=paths[0].parent) as folder:
        before = [(path, _backup(path, Path(folder) / str(index))) for index, path in enumerate(paths)]
        try:
            yield
        except BaseException:
            for path, backup in reversed(before):
                if backup is None:
                    path.unlink(missing_ok=True)
                else:
                    os.replace(backup, path)
            raise

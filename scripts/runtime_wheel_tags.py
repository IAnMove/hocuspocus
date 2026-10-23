"""Correct wheel tags that upstream published wrongly, after proving the package works.

``uv pip check`` reads the ``Tag:`` lines of each installed package's ``WHEEL`` file.
decord 0.6.0's Linux wheel is *named* ``py3-none-manylinux2010_x86_64`` (so uv installs
it) but its ``WHEEL`` file says ``cp36-cp36m-manylinux2010_x86_64``, so a fresh
install ends with "The package `decord` was built for a different platform".
Installs made before uv checked this carry the filename tag and are unaffected.

Each entry below is one exact, known mismatch. Anything else (another version, another
tag, another platform, a package that does not import) is left alone for uv to report.
This file is deliberately NOT part of the install fingerprint: the repair only matters
to a new install, so existing installs must not look out of date.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import importlib.metadata
import io
import platform
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple


class KnownTag(NamedTuple):
    package: str
    version: str
    wrong: str
    right: str
    system: str
    machine: str


KNOWN_TAGS = (
    KnownTag("decord", "0.6.0", "cp36-cp36m-manylinux2010_x86_64", "py3-none-manylinux2010_x86_64",
             "linux", "x86_64"),
)


def _replace(path: Path, data: bytes) -> None:
    # Package files may be hardlinked to uv's shared cache: never modify in place.
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    temporary.replace(path)


def _rewritten_record(record: Path, entry_name: str, data: bytes) -> bytes:
    rows = list(csv.reader(io.StringIO(record.read_text())))
    row = next((row for row in rows if row[0] == entry_name), None)
    if row is None or len(row) != 3:
        raise RuntimeError("The WHEEL entry is missing from RECORD")
    row[1:] = ["sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("="), str(len(data))]
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    return output.getvalue().encode()


def repair(known: KnownTag) -> bool:
    """Correct one known tag. True when the file was changed."""
    if sys.platform != known.system or platform.machine() != known.machine:
        return False
    try:
        distribution = importlib.metadata.distribution(known.package)
    except importlib.metadata.PackageNotFoundError:
        return False
    if distribution.version != known.version:
        return False
    entry = next((entry for entry in distribution.files or [] if str(entry).endswith(".dist-info/WHEEL")), None)
    if entry is None:
        return False
    wheel = Path(distribution.locate_file(entry))
    if not wheel.resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError(f"Refusing {known.package} metadata changes outside the selected environment")
    original = wheel.read_text()
    if [line for line in original.splitlines() if line.startswith("Tag:")] != [f"Tag: {known.wrong}"]:
        return False
    importlib.import_module(known.package)  # The binary loads here: only then is the tag a label error.
    corrected = original.replace(f"Tag: {known.wrong}", f"Tag: {known.right}").encode()
    record = wheel.with_name("RECORD")
    updated_record = _rewritten_record(record, str(entry), corrected)
    _replace(wheel, corrected)
    _replace(record, updated_record)
    print(f"[Runtime] Verified {known.package} {known.version}; corrected its upstream WHEEL tag "
          f"{known.wrong} to {known.right}")
    return True


def repair_known_tags() -> list[str]:
    return [known.package for known in KNOWN_TAGS if repair(known)]


if __name__ == "__main__":
    repair_known_tags()

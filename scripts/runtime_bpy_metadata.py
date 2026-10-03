"""Repair Blender 4.2's known Linux wheel tag after verifying its real ABI.

Upstream renames cp39 to cp311 in the filename without updating WHEEL.
Keep uv's compatibility check: normalize only this exact pinned mismatch,
after the Blender binary actually imports in Python 3.11.
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


def _replace(path: Path, data: bytes) -> None:
    # Package files may be hardlinked to uv's shared cache: never modify in place.
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    temporary.replace(path)


def repair_bpy_metadata() -> bool:
    if sys.platform != "linux" or sys.version_info[:2] != (3, 11) or platform.machine() != "x86_64":
        return False
    distribution = importlib.metadata.distribution("bpy")
    if distribution.version != "4.2.22" or distribution.metadata.get("Requires-Python") != "==3.11.*":
        return False
    wheel_entry = next((entry for entry in distribution.files or [] if str(entry).endswith(".dist-info/WHEEL")), None)
    if wheel_entry is None:
        return False
    wheel = Path(distribution.locate_file(wheel_entry))
    if not wheel.resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("Refusing Blender metadata changes outside the selected environment")
    original = wheel.read_text()
    wrong = "Tag: cp39-cp39-manylinux_2_28_x86_64"
    if [line for line in original.splitlines() if line.startswith("Tag:")] != [wrong]:
        return False
    bpy = importlib.import_module("bpy")
    if tuple(bpy.app.version) != (4, 2, 22):
        raise RuntimeError("Blender's loaded binary differs from its pinned package")
    corrected = original.replace(wrong, "Tag: cp311-cp311-manylinux_2_28_x86_64")
    record = wheel.with_name("RECORD")
    rows = list(csv.reader(io.StringIO(record.read_text())))
    entry = next((row for row in rows if row[0] == str(wheel_entry)), None)
    if entry is None or len(entry) != 3:
        raise RuntimeError("Blender WHEEL entry is missing from RECORD")
    data = corrected.encode()
    entry[1:] = ["sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("="), str(len(data))]
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    _replace(wheel, data)
    _replace(record, output.getvalue().encode())
    print("[Runtime] Verified Blender 4.2.22 binary; corrected its upstream cp39 WHEEL tag to cp311")
    return True

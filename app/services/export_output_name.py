"""Stable, caller-chosen names for published scene exports (``output_name``).

``scenes.world3d.export`` and ``scenes.video2d.export`` name their MP4
``<time>_world3d-<template>_<id>.mp4`` unless the input has an ``output_name``.
With one the export is published as ``<name>.mp4`` (a ProRes master as
``<name>.mov``), so a Series layer or prop can name that file once and see
every later render of it.

Exporting again with the same name replaces the file, but only once the new
render has been encoded: the new MP4 moves onto the name with ``os.replace``,
so the name always holds a whole file. The version it replaces is kept as
``<name>.previous.mp4`` with its sidecar (one level: an older previous is
replaced), and the published output says ``replaced`` and ``previous``.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from services.asset_manifest import sidecar_path
from services.generation_output_name import INVALID_OUTPUT_NAME, OutputNameError, validate_output_name

PREVIOUS_TAG = ".previous"
VIDEO_SUFFIXES = (".mp4", ".m4v", ".mov", ".webm", ".mkv")
_MAX_LENGTH = 180
_MESSAGE = ("output_name must be one file name without folders, at most 180 characters, not starting with a dot "
            "and not ending in .previous")


def export_file_name(value: object) -> str:
    """``set-crane`` or ``set-crane.mp4`` -> ``set-crane.mp4``; raises ``OutputNameError``."""
    name = validate_output_name(value)
    stem = name
    for suffix in VIDEO_SUFFIXES:
        if name.lower().endswith(suffix):
            stem = name[: -len(suffix)]
            break
    if not stem.strip(" .") or stem.startswith(".") or stem.lower().endswith(PREVIOUS_TAG) or len(stem) + 4 > _MAX_LENGTH:
        raise OutputNameError(_MESSAGE)
    return f"{stem}.mp4"


def name_snapshot(snapshot: dict, payload: dict, error) -> dict:
    """Freeze ``output_name`` into the export snapshot (part of the intent digest); ``error`` builds the HTTP error."""
    if payload.get("output_name") is None:
        return snapshot
    try:
        snapshot["outputName"] = export_file_name(payload["output_name"])
    except OutputNameError as failure:
        raise error(422, INVALID_OUTPUT_NAME, str(failure)) from failure
    return snapshot


def previous_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}{PREVIOUS_TAG}{path.suffix}")


def _keep_copy(source: Path, target: Path) -> None:
    """``target`` becomes a copy of ``source`` (a hard link when the filesystem allows it), atomically."""
    temporary = target.with_name(f".{target.name}.{os.getpid()}.keep")
    temporary.unlink(missing_ok=True)
    try:
        os.link(source, temporary)
    except OSError:
        shutil.copy2(source, temporary)
    os.replace(temporary, target)


def _renamed_sidecar(data: dict, old: str, new: str) -> dict:
    asset = data.get("asset")
    if isinstance(asset, dict):
        asset["filename"] = new
        if isinstance(asset.get("uri"), str):
            asset["uri"] = asset["uri"].replace(old, new)
    if "output_filename" in data:
        data["output_filename"] = new
    return data


def _keep_sidecar(output: Path, previous: Path) -> None:
    """The replaced file's sidecar follows it to ``<name>.previous.meta.json`` with its own file name."""
    current, target = sidecar_path(output), sidecar_path(previous)
    if not current.is_file():
        target.unlink(missing_ok=True)
        return
    try:
        data = json.loads(current.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _keep_copy(current, target)
        return
    if not isinstance(data, dict):
        _keep_copy(current, target)
        return
    temporary = target.with_name(f".{target.name}.{os.getpid()}.keep")
    temporary.write_text(json.dumps(_renamed_sidecar(data, output.name, previous.name), ensure_ascii=False, indent=2),
                         encoding="utf-8")
    os.replace(temporary, target)


def _keep_previous(output: Path, sibling: Path) -> Path:
    previous = previous_path(output)
    _keep_copy(output, previous)
    _keep_sidecar(output, previous)
    if sibling.exists():
        _keep_copy(sibling, previous_path(sibling))
    else:
        previous_path(sibling).unlink(missing_ok=True)
    return previous


def publish_export_file(encoded: Path, output: Path, master: Path | None = None) -> dict:
    """Move an encoded export (and its ProRes master) onto ``output``.

    A file already at ``output`` is kept as ``<name>.previous.mp4`` first, and its sidecar is dropped so the
    new file gets its own asset id. Returns ``{"replaced": True, "previous": name}`` or ``{}``."""
    sibling = output.with_suffix(".mov")
    previous = _keep_previous(output, sibling) if output.exists() else None
    os.replace(encoded, output)
    if master is not None:
        os.replace(master, sibling)
    elif previous is not None:
        sibling.unlink(missing_ok=True)
    if previous is None:
        return {}
    sidecar_path(output).unlink(missing_ok=True)
    return {"replaced": True, "previous": previous.name}


OUTPUT_NAME_SCHEMA = {
    "type": "string", "minLength": 1, "maxLength": _MAX_LENGTH,
    "description": (
        "Optional stable file name for the published MP4: \"set-crane-loop\" or \"set-crane-loop.mp4\" publishes "
        "set-crane-loop.mp4 in the workspace (a ProRes master beside it as set-crane-loop.mov) instead of "
        "<time>_<kind>-<name>_<id>.mp4. Exporting again with the same name replaces that file once the new render "
        "has been encoded, so a Series layer or prop that names it shows the new render; the file it replaced is "
        "kept as set-crane-loop.previous.mp4 with its .meta.json (one level only), and the published output and the "
        "receipt artifact say replaced true and previous. One file name: no folders, at most 180 characters, not "
        "starting with a dot or ending in .previous; a bad name fails with invalid_output_name."),
}


__all__ = ["OUTPUT_NAME_SCHEMA", "PREVIOUS_TAG", "export_file_name", "name_snapshot", "previous_path",
           "publish_export_file"]

"""``assets.import_from_workspace``: copy a file from another workspace of the same install.

Hunyuan3D runs only on the main install, so its GLBs (and images, voices,
clips) are made in one workspace and used in another. This copies one file
with its ``.meta.json`` provenance sidecar (rewritten for the new file and
recording where it came from) and its ``.preview.png``, instead of ``cp``.

The ``default`` workspace's folder is the base that holds every other
workspace, so a path under ``default`` that lies inside another workspace's
folder is refused: name that workspace as ``source_workspace``.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.production_media_common import (
    WORKSPACE, MediaToolError, media_url, operation_schema, read_input, sha256_file, uploads_root,
    workspace_folder,
)

OPERATION = "assets.import_from_workspace"
MAX_BYTES = 4 * 1024 * 1024 * 1024
_KEYS = frozenset({"workspace", "source_workspace", "file", "destination_filename", "overwrite"})


def catalog() -> dict[str, Any]:
    return operation_schema(OPERATION, (
        "Copy one file (a GLB model, image, audio or video) from another workspace of this HocusPocus install into "
        "this workspace, instead of copying it with cp outside HocusPocus (e.g. a Hunyuan3D model made on the main "
        "workspace). file is its path inside source_workspace (subfolders allowed, no ..). Its provenance sidecar "
        "(.meta.json) is copied and rewritten for the new file with copied_from {workspace, file, sha256, copiedAt} "
        "and a lineage parent; a file without one gets a new sidecar that records the copy. Its .preview.png comes "
        "too. destination_filename renames it (same extension). An existing different file of that name is refused "
        "(destination_exists) unless overwrite true; the same bytes return already_present true. Returns file, url, "
        "sha256, bytes, source {workspace, file}, sidecar."
    ), {
        "workspace": {**WORKSPACE, "description": "Destination workspace."},
        "source_workspace": WORKSPACE,
        "file": {"type": "string", "minLength": 1, "maxLength": 500, "description": "Path inside source_workspace."},
        "destination_filename": {"type": "string", "minLength": 1, "maxLength": 180},
        "overwrite": {"type": "boolean"},
    }, ["workspace", "source_workspace", "file"])


def _relative(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or "\x00" in value:
        raise MediaToolError("invalid_command", "file must be a path inside source_workspace.")
    relative = value.replace("\\", "/")
    parts = relative.split("/")
    if relative.startswith("/") or os.path.splitdrive(value)[0] or any(part in ("", ".", "..") for part in parts):
        raise MediaToolError("path_not_allowed", "file must be a relative path inside source_workspace, without ..")
    if any(part.startswith(".") for part in parts):
        raise MediaToolError("path_not_allowed", "Hidden files are not imported.")
    return relative


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root and path != root
    except ValueError:
        return False


def _nested_workspace(workspace_dir, folder: str, relative: str, source_workspace: str) -> str | None:
    """The workspace whose folder holds ``relative`` when that folder is nested in ``folder`` (the default base)."""
    first = relative.split("/", 1)[0]
    if "/" not in relative or first == source_workspace:
        return None
    try:
        other = os.path.realpath(workspace_dir(first))
    except Exception:  # not a valid workspace name: an ordinary subfolder
        return None
    if other != folder and _inside(other, folder):
        return first
    return None


def _source_file(workspace_dir, payload: dict) -> tuple[str, str, str]:
    """(source path, source folder, relative path), confined to the source workspace."""
    source_workspace = payload["source_workspace"]
    folder = workspace_folder(workspace_dir, source_workspace, field="source_workspace", create=False)
    relative = _relative(payload["file"])
    nested = _nested_workspace(workspace_dir, folder, relative, source_workspace)
    if nested:
        raise MediaToolError("path_not_allowed", f"{relative} belongs to workspace {nested}; use source_workspace "
                             f"{nested} and its path there.")
    path = os.path.realpath(os.path.join(folder, *relative.split("/")))
    if not _inside(path, folder):
        raise MediaToolError("path_not_allowed", "file must stay inside source_workspace.")
    if not os.path.isfile(path):
        raise MediaToolError("media_not_found", f"{relative} was not found in {source_workspace}.", 404)
    if os.path.getsize(path) > MAX_BYTES:
        raise MediaToolError("payload_too_large", "File is larger than 4 GB.", 413)
    return path, folder, relative


def _destination_name(payload: dict, source: str) -> str:
    name = payload.get("destination_filename") or os.path.basename(source)
    from services.generation_output_name import OutputNameError, validate_output_name
    try:
        name = validate_output_name(name)
    except OutputNameError as exc:
        raise MediaToolError("invalid_output_name", str(exc)) from exc
    if name.startswith(".") or os.path.splitext(name)[1].lower() != os.path.splitext(source)[1].lower():
        raise MediaToolError("invalid_output_name", "destination_filename must keep the source extension.")
    return name


def _sidecar(source: str, target: Path, workspace: str, provenance: dict[str, Any]) -> str | None:
    """The source's sidecar rewritten for ``target``, or a new one recording the copy; None when another file owns it."""
    from services.asset_catalog import _stable_unmanaged_id
    from services.assets_upload import AssetsUploadError, _sidecar_content

    try:
        copied = _sidecar_content(source, target, workspace)
    except AssetsUploadError:
        copied = None
    if copied is None:
        return _fresh_sidecar(source, target, workspace, provenance)
    metadata = json.loads(copied)
    parent = {"id": (json.loads(Path(source).with_suffix(".meta.json").read_text(encoding="utf-8")).get("asset") or {}).get("id")
              or _stable_unmanaged_id(provenance["workspace"], provenance["file"]),
              "kind": (metadata.get("asset") or {}).get("kind") or "other", "uri": provenance["file"], "role": "copied_from"}
    metadata["copied_from"] = provenance
    if isinstance(metadata.get("origin"), dict):
        metadata["origin"].update(workspace_id=workspace, output_folder=workspace)
    lineage = metadata.get("lineage")
    if isinstance(lineage, dict):
        lineage["parents"] = [*(lineage.get("parents") or []), parent]
        lineage["transformations"] = [*(lineage.get("transformations") or []), {"tool": OPERATION, **provenance}]
    return json.dumps(metadata, ensure_ascii=False, indent=2)


def _fresh_sidecar(source: str, target: Path, workspace: str, provenance: dict[str, Any]) -> str:
    from services.asset_catalog import _stable_unmanaged_id
    from services.asset_manifest import build_asset_manifest, infer_asset_kind

    parent = {"id": _stable_unmanaged_id(provenance["workspace"], provenance["file"]), "kind": infer_asset_kind(source),
              "uri": provenance["file"], "role": "copied_from"}
    manifest = build_asset_manifest(
        target, asset_id=_stable_unmanaged_id(workspace, target.name), workspace_id=workspace, tool=OPERATION,
        capability=OPERATION, actor="system", execution_mode="import", parents=[parent], inputs=[parent],
        transformations=[{"tool": OPERATION, **provenance}], media={"size_bytes": os.path.getsize(source)},
    )
    return json.dumps({**manifest, "copied_from": provenance}, ensure_ascii=False, indent=2)


def _same_or_refused(target: Path, digest: str, overwrite: bool) -> bool:
    """True when ``target`` already holds these bytes; raises when it holds others and overwrite is false."""
    if target.is_symlink() or target.is_dir():
        raise MediaToolError("path_not_allowed", "The destination must be a regular workspace file.")
    if not target.exists():
        return False
    if sha256_file(str(target)) == digest:
        return True
    if not overwrite:
        raise MediaToolError("destination_exists", f"{target.name} already exists in the workspace with other content; "
                             "give destination_filename or overwrite true.", 409)
    return False


def _copy(source: str, target: Path) -> None:
    temporary = target.with_name(f".{target.name}-{os.urandom(6).hex()}.tmp")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_preview(source: str, target: Path, overwrite: bool) -> bool:
    preview = Path(source).with_suffix(".preview.png")
    destination = target.with_suffix(".preview.png")
    if not preview.is_file() or preview.is_symlink() or (destination.exists() and not overwrite):
        return False
    _copy(str(preview), destination)
    return True


def _publish(source: str, target: Path, workspace: str, provenance: dict[str, Any], overwrite: bool) -> bool:
    """Write the sidecar (refusing one another file of the same stem owns), then the file and its preview."""
    from services.assets_upload import AssetsUploadError, _publish_sidecar, _refuse_shared_sidecar

    content = _sidecar(source, target, workspace, provenance)
    try:
        _refuse_shared_sidecar(target, content)
    except AssetsUploadError:
        content = None  # song.wav owns song.meta.json: copy song.png without a sidecar rather than clobber it
    _copy(source, target)
    if content is not None:
        _publish_sidecar(target, content)  # replaces an overwritten file's own sidecar too
    _copy_preview(source, target, overwrite)
    return content is not None


def run(arguments: Any, *, workspace_dir, uploads_dir) -> dict[str, Any]:
    payload = read_input(arguments, _KEYS, ("workspace", "source_workspace", "file"))
    if not isinstance(payload.get("overwrite", False), bool):
        raise MediaToolError("invalid_command", "overwrite must be true or false.")
    workspace = payload["workspace"]
    folder, uploads = workspace_folder(workspace_dir, workspace), uploads_root(uploads_dir)
    source, source_folder, relative = _source_file(workspace_dir, payload)
    if source_folder == folder:
        raise MediaToolError("invalid_command", "source_workspace is this workspace; nothing to import.")
    target = Path(folder) / _destination_name(payload, source)
    digest = sha256_file(source)
    present = _same_or_refused(target, digest, payload.get("overwrite", False))
    provenance = {"workspace": payload["source_workspace"], "file": relative, "sha256": digest,
                  "copiedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    sidecar = target.with_suffix(".meta.json").is_file() if present else _publish(
        source, target, workspace, provenance, payload.get("overwrite", False))
    result = {"file": target.name, "url": media_url(str(target), workspace, uploads, folder), "sha256": digest,
              "bytes": target.stat().st_size, "source": {"workspace": payload["source_workspace"], "file": relative},
              "sidecar": sidecar}
    return {**result, "already_present": True} if present else result

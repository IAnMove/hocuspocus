"""Versioned MCP upload of one workspace asset.

Base64 bytes are stored with the same ``save_upload`` writer as
``core_runtime.upload_file``, but only inside the selected workspace.
An existing file is accepted only after the shared media-path check.
"""
from __future__ import annotations

import base64
import binascii
import glob
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException

from services.asset_catalog import _stable_unmanaged_id
from services.core_upload import MAX_UPLOAD_BYTES, extract_upload, save_upload, unique_upload_name
from services.media_paths import MediaPathNotAllowed, _KIND_EXTENSIONS, resolve_permitted_media_path
from services.wangp_submission import wangp_media_url
from services.workspace_store_lock import workspace_store_lock


MAX_ASSETS_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_ASSETS_UPLOAD_CHARS = 4 * ((MAX_ASSETS_UPLOAD_BYTES + 2) // 3)
_JOURNAL_NAME = ".assets-upload-intents.json"
_DATA_KEYS = frozenset({"workspace", "filename", "data_base64"})
_SOURCE_KEYS = frozenset({"workspace", "source"})
_COPY_OPTIONS = frozenset({"copy_to_workspace", "destination_filename", "expected_destination_sha256"})
_WORKSPACE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)")
_TOO_LARGE = f"Payload exceeds {MAX_ASSETS_UPLOAD_BYTES} bytes"


class AssetsUploadError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def command_catalog() -> list[dict]:
    data_input = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
            "filename": {"type": "string", "minLength": 1, "maxLength": 240},
            "data_base64": {"type": "string", "minLength": 1, "maxLength": MAX_ASSETS_UPLOAD_CHARS},
        },
        "required": ["workspace", "filename", "data_base64"],
    }
    source_input = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
            "source": {"type": "string", "minLength": 1, "maxLength": 2000},
            "copy_to_workspace": {"type": "boolean", "const": True},
            "destination_filename": {"type": "string", "minLength": 1, "maxLength": 240},
            "expected_destination_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        "required": ["workspace", "source"],
    }
    payload = {"oneOf": [data_input, source_input]}
    return [{
        "name": "assets.upload",
        "version": 1,
        "domain": "assets",
        "mutation": True,
        "description": (
            "Store one image, audio, video or GLB model and return its asset id plus canonical URL. "
            f"Send filename and data_base64 (at most {MAX_ASSETS_UPLOAD_BYTES} decoded bytes) "
            "or source, a file already inside this workspace or the uploads root. "
            "For source, optional copy_to_workspace:true imports a copy (at most 500 MB) into the selected workspace. "
            "destination_filename selects an exact name; replacing an existing file requires its current "
            "expected_destination_sha256. Named copies preserve generation sidecars and the source file. "
            "The URL is accepted directly by image_refs, image_start, image_end, and audio_guide. "
            "Reuse intent_id on transport retries. Does not call POST /api/v1/upload and does not use the GPU."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "intent_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "input": payload,
            },
            "required": ["version", "intent_id", "input"],
        },
    }]


def _inside(path: str, root: str) -> bool:
    try:
        resolved = os.path.realpath(path)
        base = os.path.realpath(root)
        return os.path.commonpath((resolved, base)) == base and resolved != base
    except (TypeError, ValueError, OSError):
        return False


def _extension(value: str) -> str:
    path = urlsplit(value).path if value.startswith("/api/") else value
    return os.path.splitext(unquote(path))[1].lower()


def _kind(extension: str) -> str:
    for kind, extensions in _KIND_EXTENSIONS.items():
        if extension in extensions:
            return kind
    raise AssetsUploadError("unsupported_media", "Use an image, audio, video or GLB file", 422)


def _media_error(error: MediaPathNotAllowed) -> AssetsUploadError:
    if str(error) == "Media type is not allowed":
        return AssetsUploadError("unsupported_media", "Use an image, audio, video or GLB file", 422)
    return AssetsUploadError("path_not_allowed", "Media path is not allowed", 422)


def _upload_error(error: ValueError) -> AssetsUploadError:
    if "too large" in str(error).lower():
        return AssetsUploadError("payload_too_large", _TOO_LARGE, 413)
    return AssetsUploadError("invalid_payload", "A file is required", 422)


def _encoded_size(value: str) -> int:
    if len(value) % 4:
        raise AssetsUploadError("invalid_payload", "data_base64 must be standard base64", 422)
    padding = len(value) - len(value.rstrip("="))
    if padding > 2:
        raise AssetsUploadError("invalid_payload", "data_base64 must be standard base64", 422)
    return (len(value) // 4) * 3 - padding


def _decode_base64(value: str) -> bytes:
    if type(value) is not str or not value or value != value.strip():
        raise AssetsUploadError("invalid_payload", "data_base64 must be standard base64", 422)
    if len(value) > MAX_ASSETS_UPLOAD_CHARS or _encoded_size(value) > MAX_ASSETS_UPLOAD_BYTES:
        raise AssetsUploadError("payload_too_large", _TOO_LARGE, 413)
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise AssetsUploadError("invalid_payload", "data_base64 must be standard base64", 422) from error
    if len(data) > MAX_ASSETS_UPLOAD_BYTES:
        raise AssetsUploadError("payload_too_large", _TOO_LARGE, 413)
    if not data:
        raise AssetsUploadError("invalid_payload", "A file is required", 422)
    return data


def _original_name(filename: str) -> str:
    if type(filename) is not str or not filename or filename != filename.strip():
        raise AssetsUploadError("invalid_filename", "filename must be a non-blank basename", 422)
    normalized = filename.replace("\\", "/")
    if normalized != os.path.basename(normalized) or normalized in {".", ".."}:
        raise AssetsUploadError("invalid_filename", "filename must be a non-blank basename", 422)
    _kind(_extension(normalized))
    return normalized


def _store_upload(folder: str, data: bytes, filename: str) -> str:
    if len(data) > MAX_ASSETS_UPLOAD_BYTES:
        raise AssetsUploadError("payload_too_large", _TOO_LARGE, 413)
    try:
        payload, original = extract_upload(data, "", filename)
        saved = save_upload(folder, payload, original)
    except ValueError as error:
        raise _upload_error(error) from error
    path = str(saved.get("path") or "")
    if not _inside(path, folder):
        if path and os.path.isfile(path):
            os.remove(path)
        raise AssetsUploadError("path_not_allowed", "Media path is not allowed", 422)
    return path


def _existing_file(source, workspace: str, uploads_root: str, workspace_root: str) -> str:
    if type(source) is not str or not source.strip() or source != source.strip() or "\x00" in source:
        raise AssetsUploadError("invalid_source", "Use a file already inside the workspace", 422)
    try:
        resolved = resolve_permitted_media_path(
            source,
            uploads_root=uploads_root,
            workspace_root=workspace_root,
            kinds=(_kind(_extension(source)),),
            workspace_name=workspace,
        )
    except AssetsUploadError:
        raise
    except FileNotFoundError as error:
        raise AssetsUploadError("media_not_found", "Media file was not found", 404) from error
    except MediaPathNotAllowed as error:
        raise _media_error(error) from error
    if not _inside(resolved, workspace_root) and not _inside(resolved, uploads_root):
        raise AssetsUploadError("path_not_allowed", "Media path is not allowed", 422)
    return resolved


def _canonical(path: str, workspace: str, uploads_root: str, workspace_root: str) -> dict:
    try:
        url = wangp_media_url(path, workspace, uploads_dir=uploads_root, workspace_dir=workspace_root)
    except ValueError as error:
        raise AssetsUploadError("path_not_allowed", "Media path is not allowed", 422) from error
    scope = "__uploads__" if _inside(path, uploads_root) else workspace
    return {"asset_id": _stable_unmanaged_id(scope, Path(path).name), "url": url}


def _invocation(arguments):
    if type(arguments) is not dict or set(arguments) != {"version", "intent_id", "input"}:
        raise AssetsUploadError("invalid_command", "Use version 1, intent_id and input", 422)
    if type(arguments.get("version")) is not int or arguments["version"] != 1:
        raise AssetsUploadError("invalid_command", "Use version 1, intent_id and input", 422)
    intent_id = arguments.get("intent_id")
    if type(intent_id) is not str or not 1 <= len(intent_id) <= 160 or intent_id != intent_id.strip():
        raise AssetsUploadError("invalid_intent", "intent_id must be an exact 1..160 character id", 422)
    payload = arguments.get("input")
    if type(payload) is not dict:
        raise AssetsUploadError("invalid_command", "Use version 1, intent_id and input", 422)
    return intent_id, payload


def _payload_mode(payload: dict) -> str:
    keys = set(payload)
    if keys == _DATA_KEYS:
        return "data"
    if _SOURCE_KEYS <= keys <= _SOURCE_KEYS | _COPY_OPTIONS:
        if "copy_to_workspace" in payload and payload["copy_to_workspace"] is not True:
            raise AssetsUploadError("invalid_command", "copy_to_workspace must be true or omitted", 422)
        if keys & {"destination_filename", "expected_destination_sha256"} and payload.get("copy_to_workspace") is not True:
            raise AssetsUploadError("invalid_command", "Named copies require copy_to_workspace:true", 422)
        if "expected_destination_sha256" in keys and "destination_filename" not in keys:
            raise AssetsUploadError("invalid_command", "A destination hash requires destination_filename", 422)
        return "source"
    raise AssetsUploadError(
        "invalid_command",
        "Provide workspace with either filename and data_base64, or source",
        422,
    )


def _workspace_name(value) -> str:
    if type(value) is not str or not _WORKSPACE.fullmatch(value):
        raise AssetsUploadError("invalid_workspace", "Use an explicit valid output workspace", 422)
    return value


def _folder(workspace_dir, name: str) -> str:
    try:
        folder = workspace_dir(name)
    except (OSError, ValueError, HTTPException) as error:
        raise AssetsUploadError("invalid_workspace", "Use an explicit valid output workspace", 422) from error
    if type(folder) is not str or not folder or not os.path.isdir(folder):
        raise AssetsUploadError("invalid_workspace", "Use an explicit valid output workspace", 422)
    return os.path.realpath(folder)


def _digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_journal(folder: str) -> dict:
    path = os.path.join(folder, _JOURNAL_NAME)
    if not os.path.isfile(path):
        return {}
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AssetsUploadError("intent_unreadable", "Upload intent journal is unreadable", 503) from error
    if type(loaded) is not dict:
        raise AssetsUploadError("intent_unreadable", "Upload intent journal is unreadable", 503)
    return loaded


def _recall(folder: str, intent_id: str, digest: str):
    entry = _read_journal(folder).get(intent_id)
    if entry is None:
        return None
    if type(entry) is not dict or entry.get("digest") != digest or type(entry.get("result")) is not dict:
        raise AssetsUploadError("intent_conflict", "intent_id was already used with different parameters", 409)
    return entry["result"]


def _remember(folder: str, intent_id: str, digest: str, result: dict) -> None:
    path = os.path.join(folder, _JOURNAL_NAME)
    if not _inside(path, folder):
        raise AssetsUploadError("path_not_allowed", "Media path is not allowed", 422)
    current = _read_journal(folder)
    current[intent_id] = {"digest": digest, "result": result}
    temporary = path + ".tmp"
    Path(temporary).write_text(json.dumps(current, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _named_copy_target(source: str, folder: str, payload: dict) -> Path:
    name = _original_name(payload["destination_filename"])
    if _extension(name) != _extension(source):
        raise AssetsUploadError("invalid_filename", "A copy must keep the source extension", 422)
    target = Path(folder) / name
    if target.is_symlink() or target.is_dir():
        raise AssetsUploadError("path_not_allowed", "Destination must be a regular workspace file", 422)
    expected = payload.get("expected_destination_sha256")
    if expected is not None and (type(expected) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected)):
        raise AssetsUploadError("invalid_command", "Use the destination's current SHA-256", 422)
    current = _file_sha256(target) if target.exists() else None
    if current != expected:
        raise AssetsUploadError("destination_conflict", "Destination changed; inspect its SHA-256 before replacing it", 409)
    return target


def _same_stem_files(media: Path) -> list[str]:
    """Other files whose sidecar is ``media``'s too: sidecars are keyed by stem, so ``song.wav`` and ``song.png``
    both use ``song.meta.json``."""
    return sorted(entry.name for entry in media.parent.glob(f"{glob.escape(media.stem)}.*")
                  if entry.stem == media.stem and entry.name != media.name and entry.is_file())


def _sidecar_owner(metadata: object, media: Path) -> str | None:
    """The file a stem-keyed sidecar describes: the ``asset.filename`` it records. A sidecar that records none is
    ``media``'s when no other file shares the stem; otherwise whose it is cannot be told (None)."""
    asset = metadata.get("asset") if isinstance(metadata, dict) else None
    recorded = asset.get("filename") if isinstance(asset, dict) else None
    if isinstance(recorded, str) and recorded.strip():
        return os.path.basename(recorded)
    return None if _same_stem_files(media) else media.name


def _sidecar_holders(meta: Path, target: Path, others: list[str]) -> list[str]:
    """The existing files other than ``target`` whose metadata ``meta`` is."""
    try:
        metadata = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metadata = None
    owner = _sidecar_owner(metadata, target)
    if owner is None:
        return others
    return [owner] if owner != target.name and (target.parent / owner).is_file() else []


def _refuse_shared_sidecar(target: Path, content: str | None) -> None:
    """The copy writes ``content`` as ``target``'s sidecar, or removes it when None. Neither may touch the metadata
    of another existing output with the same stem, nor create a sidecar that output would read as its own. A
    sidecar whose output is gone is replaced."""
    meta = target.with_suffix(".meta.json")
    others = _same_stem_files(target)
    if meta.is_file():
        holders = _sidecar_holders(meta, target, others)
    else:
        holders = others if content is not None else []
    if holders:
        raise AssetsUploadError("sidecar_conflict", f"{meta.name} is also the metadata file of {', '.join(holders)}; "
                                "choose a destination_filename with another name before the extension", 409)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sidecar_content(source: str, target: Path, workspace: str) -> str | None:
    source_meta = Path(source).with_suffix(".meta.json")
    if source_meta.is_symlink():
        raise AssetsUploadError("path_not_allowed", "Generation sidecar must be a regular file", 422)
    if not source_meta.exists():
        return None
    try:
        if source_meta.stat().st_size > MAX_ASSETS_UPLOAD_BYTES:
            raise ValueError("Sidecar too large")
        metadata = json.loads(source_meta.read_text(encoding="utf-8"))
        if type(metadata) is not dict or type(metadata.get("asset", {})) is not dict:
            raise ValueError("Invalid generation sidecar")
    except (OSError, ValueError) as error:
        raise AssetsUploadError("invalid_sidecar", "Generation sidecar is unreadable", 422) from error
    if _sidecar_owner(metadata, Path(source)) != Path(source).name:
        return None  # It was written for another output with the same stem (clip.mp4 for clip.wav).
    metadata["asset"] = {**metadata.get("asset", {}), "filename": target.name, "uri": target.name,
                         "id": _stable_unmanaged_id(workspace, target.name)}
    metadata["copied_from"] = Path(source).name
    return json.dumps(metadata, ensure_ascii=False, indent=2)


def _publish_sidecar(target: Path, content: str | None) -> None:
    target_meta = target.with_suffix(".meta.json")
    if content is None:
        target_meta.unlink(missing_ok=True)
        return
    temporary = target_meta.with_name(f".{target_meta.name}-{os.urandom(8).hex()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target_meta)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_into_workspace(source: str, folder: str, payload: dict) -> str:
    if os.path.getsize(source) > MAX_UPLOAD_BYTES:
        raise AssetsUploadError("payload_too_large", "File too large (max 500 MB)", 413)
    named = "destination_filename" in payload
    target = _named_copy_target(source, folder, payload) if named else Path(folder) / unique_upload_name(Path(source).name)
    content = _sidecar_content(source, target, payload["workspace"]) if named else None
    if named:
        _refuse_shared_sidecar(target, content)
    temporary = target.with_name(f".{target.name}-{os.urandom(8).hex()}.tmp")
    try:
        shutil.copyfile(source, temporary)
        if temporary.stat().st_size > MAX_UPLOAD_BYTES:
            raise AssetsUploadError("payload_too_large", "File too large (max 500 MB)", 413)
        temporary.replace(target)
        if named:
            _publish_sidecar(target, content)
    finally:
        temporary.unlink(missing_ok=True)
    return str(target)


def _upload_asset(arguments, *, workspace_dir, uploads_dir) -> dict:
    intent_id, payload = _invocation(arguments)
    mode = _payload_mode(payload)
    workspace = _workspace_name(payload.get("workspace"))
    folder = _folder(workspace_dir, workspace)
    uploads_root = uploads_dir()
    if type(uploads_root) is not str or not uploads_root:
        raise AssetsUploadError("storage_unavailable", "Upload storage is unavailable", 503)
    prior = _recall(folder, intent_id, _digest(payload))
    if prior is not None:
        return prior
    if mode == "data":
        path = _store_upload(folder, _decode_base64(payload["data_base64"]), _original_name(payload["filename"]))
    else:
        path = _existing_file(payload["source"], workspace, uploads_root, folder)
        if payload.get("copy_to_workspace"):
            path = _copy_into_workspace(path, folder, payload)
    result = _canonical(path, workspace, uploads_root, folder)
    _remember(folder, intent_id, _digest(payload), result)
    return result


def upload_asset(arguments, *, workspace_dir, uploads_dir) -> dict:
    _, payload = _invocation(arguments)
    _payload_mode(payload)
    folder = _folder(workspace_dir, _workspace_name(payload.get("workspace")))
    with workspace_store_lock(Path(folder) / _JOURNAL_NAME):
        return _upload_asset(arguments, workspace_dir=workspace_dir, uploads_dir=uploads_dir)


def command_handlers(workspace_dir, uploads_dir):
    async def handle(arguments):
        try:
            result = upload_asset(arguments, workspace_dir=workspace_dir, uploads_dir=uploads_dir)
        except AssetsUploadError as exc:
            raise HTTPException(exc.status, {"code": exc.code, "message": exc.message, "retryable": False}) from exc
        return {"version": 1, "status": "completed", "operation": "assets.upload", "result": result}

    return {"assets.upload": handle}

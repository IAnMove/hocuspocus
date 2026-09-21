"""Portable Video3D packages: hashed media, preflight repair, zip-slip guards."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import stat
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import parse_qs, unquote, urlparse

from services.asset_manifest import (
    build_asset_manifest,
    infer_asset_kind,
    read_asset_manifest,
    sidecar_path,
    write_asset_manifest,
)
from services.scene_commands import DocumentInput
from services.scene_library import save_world3d

PACKAGE_KIND = "hocuspocus.scene-package"
PACKAGE_SCHEMA = "hocuspocus.scene-package"
PACKAGE_VERSION = 1
TEMPLATE_KIND = "hocuspocus.world3d.template"
MANIFEST_NAME = "package.json"
MEDIA_DIR = "media"
DOCUMENTS_DIR = "documents"
PACKAGE_FILENAME = "package.workspace"
HASH_PREFIX = "sha256:"

MAX_ZIP_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_DOCUMENTS = 32
MAX_ASSETS = 256
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_EXPORT_BODY = 8 * 1024 * 1024

_WORKSPACE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]{0,119})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")

ALLOWED_MEDIA_EXT = frozenset({
    ".glb", ".gltf", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac",
    ".mp4", ".webm", ".mov",
})
CINEMA_MEMBER_HINTS = frozenset({
    "cinema.js", "cinema.ts", "cinema.mjs", "tools/cinema.js",
    "tools/cinema.ts", "tools/cinema.mjs", "cinema/runtime.js",
    "cinema/runtime.ts",
})
SUPPORTED_CINEMA_EXTENSIONS = frozenset()
KNOWN_DOCUMENT_KEYS = frozenset({
    "version", "units", "up", "width", "height", "fps", "duration",
    "templateId", "camera", "light", "slots", "soundtrack", "production",
    "clipNumber", "sfx", "worldSfx", "texts", "playbackSpeed",
    "environment", "dressing", "workshopScreen",
})
KNOWN_WRAPPER_KEYS = frozenset({
    "kind", "version", "id", "title", "description", "includeAssets",
    "createdAt", "document",
})
KNOWN_SLOT_KEYS = frozenset({
    "id", "slot", "position", "rotationY", "scale", "sourceUrl", "sourceRef",
    "speech", "media", "screen", "surface", "appearance", "textureRepeat",
    "performance", "grounded", "clip", "clipPlayback", "motion", "loop",
    "character",
})
CINEMA_FIELD_NAMES = ("cinema", "cinemaExtension", "cinemaRuntime")

STUB_PNG = b"\x89PNG\r\n\x1a\npreview"
STUB_PREVIEW = "data:image/png;base64," + base64.b64encode(STUB_PNG).decode("ascii")

class ScenePackageError(ValueError):
    status = 422
    code = "invalid_package"


class ScenePackageTooLarge(ScenePackageError):
    status = 413
    code = "too_large"


class ScenePackageSecurity(ScenePackageError):
    status = 422
    code = "rejected"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_workspace(name: str) -> str:
    text = str(name or "").strip()
    if not _WORKSPACE.fullmatch(text):
        raise ScenePackageError("Choose an explicit workspace")
    return text


def _issue(code: str, message: str, *, repair: bool = False, path: str = "") -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message, "repair": repair}
    if path:
        item["path"] = path
    return item


def is_template_wrapper(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("kind") == TEMPLATE_KIND


def _cinema_from_field(field: Any) -> str | None:
    if isinstance(field, str) and field.strip():
        return field.strip()
    if isinstance(field, Mapping):
        ext = field.get("extension") or field.get("id") or field.get("kind")
        if ext:
            return str(ext)
    return None


def cinema_extension_of(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    kind = str(value.get("kind") or "")
    if kind.startswith("hocuspocus.cinema"):
        return str(value.get("extension") or value.get("id") or kind)
    for key in CINEMA_FIELD_NAMES:
        found = _cinema_from_field(value.get(key))
        if found:
            return found
    extras = value.get("extensions")
    if isinstance(extras, list):
        for item in extras:
            text = str(item or "").strip()
            if "cinema" in text:
                return text
    return None


def reject_unknown_cinema(value: Any) -> None:
    ext = cinema_extension_of(value)
    if ext and ext not in SUPPORTED_CINEMA_EXTENSIONS:
        raise ScenePackageSecurity(f"Unknown cinema extension: {ext}")
    if is_template_wrapper(value):
        reject_unknown_cinema(value.get("document"))


def unwrap_document(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ScenePackageError("Each packed item must be a scene document")
    if is_template_wrapper(value):
        nested = value.get("document")
        if not isinstance(nested, Mapping):
            raise ScenePackageError("Scenario template is missing its scene document")
        return dict(nested)
    return dict(value)


def _prefixed(prefix: str, key: str) -> str:
    return f"{prefix}{key}" if prefix else key


def _unknown_keys(record: Mapping[str, Any], known: frozenset[str], prefix: str) -> list[str]:
    return [_prefixed(prefix, key) for key in record if key not in known]


def _unknown_slot_fields(slots: Any, prefix: str) -> list[str]:
    found: list[str] = []
    if not isinstance(slots, list):
        return found
    for index, slot in enumerate(slots):
        if isinstance(slot, Mapping):
            found.extend(
                f"{prefix}slots[{index}].{key}"
                for key in slot if key not in KNOWN_SLOT_KEYS
            )
    return found


def collect_unknown_fields(raw: Mapping[str, Any], prefix: str = "") -> list[str]:
    if not is_template_wrapper(raw):
        return _unknown_keys(raw, KNOWN_DOCUMENT_KEYS, prefix) + _unknown_slot_fields(raw.get("slots"), prefix)
    found = _unknown_keys(raw, KNOWN_WRAPPER_KEYS, prefix)
    nested = raw.get("document")
    if isinstance(nested, Mapping):
        nested_prefix = f"{prefix}document." if prefix else "document."
        found.extend(collect_unknown_fields(nested, nested_prefix))
    return found


def _basename(value: str) -> str:
    return Path(str(value or "").replace("\\", "/")).name


def safe_export_filename(name: str) -> str:
    base = _basename(name)
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-")[:120]
    return cleaned or "asset"


def _url_has_controls(text: str) -> bool:
    return any(ord(char) <= 32 or char == "\\" for char in text)


def _classify_api_path(path: str) -> str | None:
    if path.startswith("/api/v1/file/"):
        return "gallery"
    if path.startswith("/api/v1/uploads/"):
        return "uploads"
    return None


def _classify_local_path(path: str, text: str) -> str:
    api = _classify_api_path(path)
    if api:
        return api
    dotted = ".." in Path(path).parts
    if path.startswith(f"{MEDIA_DIR}/"):
        return "unsafe" if dotted else "relative"
    if path.startswith("/") or "://" in text:
        return "external"
    return "unsafe" if dotted else "relative"


def classify_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return "empty"
    if _url_has_controls(text):
        return "unsafe"
    lowered = text.casefold()
    if lowered.startswith(("blob:", "file:", "filesystem:", "javascript:", "data:")):
        return "transient"
    if lowered.startswith(("http://", "https://", "//")):
        return "external"
    parsed = urlparse(text)
    return _classify_local_path(unquote(parsed.path or text.split("?", 1)[0]), text)


def parse_media_locator(url: str, fallback_workspace: str | None = None) -> tuple[str | None, str]:
    text = str(url or "").strip()
    parsed = urlparse(text)
    path = unquote((parsed.path or text.split("?", 1)[0]).lstrip("/"))
    workspace = fallback_workspace
    query = parse_qs(parsed.query, keep_blank_values=False)
    names = query.get("workspace") or []
    if names and str(names[0]).strip():
        workspace = str(names[0]).strip()
    if path.startswith("api/v1/file/"):
        return workspace, _basename(path[len("api/v1/file/"):])
    if path.startswith("api/v1/uploads/"):
        return "__uploads__", _basename(path[len("api/v1/uploads/"):])
    return workspace, _basename(path) if "/" in path or path.startswith(MEDIA_DIR) else path


def _first_text(value: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        text = str(value.get(key) or "").strip()
        if text:
            return text
    return ""


def _resolve_ref_location(
    value: Mapping[str, Any], url: str, fallback_workspace: str | None,
) -> tuple[str, str]:
    filename = _basename(_first_text(value, "filename"))
    workspace = _first_text(value, "workspaceId", "workspace_id") or fallback_workspace or ""
    if filename:
        return workspace, filename
    parsed_ws, parsed_name = parse_media_locator(url, workspace)
    return parsed_ws or workspace, parsed_name


def _ref_from_mapping(value: Mapping[str, Any], fallback_workspace: str | None) -> dict[str, Any] | None:
    url = _first_text(value, "url", "sourceUrl")
    workspace, filename = _resolve_ref_location(value, url, fallback_workspace)
    if not filename and not url:
        return None
    return {
        "workspaceId": workspace,
        "filename": filename or safe_export_filename(url),
        "url": url,
        "assetId": _first_text(value, "assetId", "asset_id"),
    }


def _ref_from_any(raw: Any, url: str = "") -> dict[str, Any] | None:
    ref = _ref_from_mapping(raw, None) if isinstance(raw, Mapping) else None
    if ref is None and isinstance(raw, str) and raw:
        workspace, filename = parse_media_locator(raw, None)
        ref = {"workspaceId": workspace or "", "filename": filename, "url": raw, "assetId": ""}
    if ref is None and url:
        workspace, filename = parse_media_locator(url, None)
        ref = {"workspaceId": workspace or "", "filename": filename, "url": url, "assetId": ""}
    if ref is not None and url and not ref.get("url"):
        ref["url"] = url
    return ref


def _add_use(uses: list[dict[str, Any]], raw: Any, *, doc_id: str, role: str, kind: str, url: str = "") -> None:
    ref = _ref_from_any(raw, url)
    if ref is None:
        return
    uses.append({"doc_id": doc_id, "role": role, "kind": kind, **ref})


def _uses_from_speech(speech: Mapping[str, Any], index: int, doc_id: str, uses: list[dict[str, Any]]) -> None:
    _add_use(uses, speech.get("audio"), doc_id=doc_id, role=f"slots[{index}].speech.audio", kind="audio")
    _add_use(uses, speech.get("atlas"), doc_id=doc_id, role=f"slots[{index}].speech.atlas", kind="image")
    clips = speech.get("clips")
    if not isinstance(clips, list):
        return
    for clip_index, clip in enumerate(clips):
        if isinstance(clip, Mapping):
            _add_use(uses, clip.get("audio"), doc_id=doc_id, role=f"slots[{index}].speech.clips[{clip_index}].audio", kind="audio")


def _uses_from_slot(slot: Any, index: int, doc_id: str, uses: list[dict[str, Any]]) -> None:
    if not isinstance(slot, Mapping):
        return
    media = str(slot.get("media") or "model3d")
    kind = "image" if media in {"image", "screen"} else "model3d"
    _add_use(uses, slot.get("sourceRef"), doc_id=doc_id, role=f"slots[{index}]", kind=kind, url=str(slot.get("sourceUrl") or ""))
    screen = slot.get("screen")
    if isinstance(screen, Mapping):
        screen_kind = "video" if screen.get("media") == "video" else "image"
        _add_use(uses, screen.get("sourceRef"), doc_id=doc_id, role=f"slots[{index}].screen", kind=screen_kind,
                 url=str(screen.get("sourceUrl") or ""))
    speech = slot.get("speech")
    if isinstance(speech, Mapping):
        _uses_from_speech(speech, index, doc_id, uses)


def _world_media_kind(url: str) -> str:
    kind = _kind_from_name(_basename(url.split("?", 1)[0]))
    return kind if kind in {"image", "video"} else "image"


def _packable_world_media(url: str, ref: Any) -> bool:
    classified = classify_url(url) if url else "empty"
    if classified in {"gallery", "uploads"}:
        return True
    return classified in {"empty", "relative"} and isinstance(ref, Mapping)


def _uses_from_world_sfx(cues: Any, doc_id: str, uses: list[dict[str, Any]]) -> None:
    if not isinstance(cues, list):
        return
    for index, cue in enumerate(cues):
        if not isinstance(cue, Mapping):
            continue
        url = str(cue.get("sourceUrl") or "")
        ref = cue.get("sourceRef")
        if not _packable_world_media(url, ref):
            continue
        _add_use(uses, ref, doc_id=doc_id, role=f"worldSfx[{index}]", kind=_world_media_kind(url), url=url)


def iter_asset_uses(document: Mapping[str, Any], *, doc_id: str = "") -> list[dict[str, Any]]:
    uses: list[dict[str, Any]] = []
    body = unwrap_document(document)
    slots = body.get("slots") if isinstance(body.get("slots"), list) else []
    for index, slot in enumerate(slots):
        _uses_from_slot(slot, index, doc_id, uses)
    tracks = body.get("soundtrack") if isinstance(body.get("soundtrack"), list) else []
    for index, track in enumerate(tracks):
        if isinstance(track, Mapping):
            _add_use(uses, track.get("audio"), doc_id=doc_id, role=f"soundtrack[{index}]", kind="audio")
    _uses_from_world_sfx(body.get("worldSfx"), doc_id, uses)
    return uses


def _rewrite_ref(container: dict[str, Any], key: str, locator: Callable[[dict[str, Any]], dict[str, Any] | None]) -> None:
    current = container.get(key)
    if not isinstance(current, Mapping):
        return
    updated = locator(dict(current))
    if updated is None:
        return
    container[key] = updated


def _source_payload(container: Mapping[str, Any], url_key: str = "sourceUrl", ref_key: str = "sourceRef") -> dict[str, Any]:
    original = {"workspaceId": "", "filename": "", "url": str(container.get(url_key) or ""), "assetId": ""}
    ref = container.get(ref_key)
    if isinstance(ref, Mapping):
        original.update(ref)
    return original


def _apply_located(
    target: dict[str, Any],
    locator: Callable[[dict[str, Any]], dict[str, Any] | None],
    url_key: str = "sourceUrl",
    ref_key: str = "sourceRef",
) -> None:
    updated = locator(_source_payload(target, url_key, ref_key))
    if updated is None:
        return
    target[ref_key] = updated
    target[url_key] = updated["url"]


def _rewrite_speech(speech: dict[str, Any], locator: Callable[[dict[str, Any]], dict[str, Any] | None]) -> None:
    _rewrite_ref(speech, "audio", locator)
    _rewrite_ref(speech, "atlas", locator)
    clips = speech.get("clips")
    if not isinstance(clips, list):
        return
    for clip in clips:
        if isinstance(clip, dict):
            _rewrite_ref(clip, "audio", locator)


def _rewrite_slot(slot: Any, locator: Callable[[dict[str, Any]], dict[str, Any] | None]) -> None:
    if not isinstance(slot, dict):
        return
    _apply_located(slot, locator)
    screen = slot.get("screen")
    if isinstance(screen, dict):
        _apply_located(screen, locator)
    speech = slot.get("speech")
    if isinstance(speech, dict):
        _rewrite_speech(speech, locator)


def _rewrite_track(track: Any, locator: Callable[[dict[str, Any]], dict[str, Any] | None]) -> None:
    if isinstance(track, dict):
        _rewrite_ref(track, "audio", locator)


def _rewrite_world_cue(cue: Any, locator: Callable[[dict[str, Any]], dict[str, Any] | None]) -> None:
    if not isinstance(cue, dict):
        return
    updated = locator(_source_payload(cue))
    if updated is None:
        return
    # Keep sourceUrl only. WorldFxCue forbids extra keys such as sourceRef, and
    # additive apply revalidates every existing world cue against that model.
    cue["sourceUrl"] = updated["url"]


def _rewrite_list(entries: Any, locator: Callable[[dict[str, Any]], dict[str, Any] | None], rewrite_item: Callable) -> None:
    if not isinstance(entries, list):
        return
    for item in entries:
        rewrite_item(item, locator)


def _document_body(packed: dict[str, Any]) -> dict[str, Any]:
    nested = packed.get("document")
    if is_template_wrapper(packed) and isinstance(nested, dict):
        return nested
    return packed


def rewrite_document_refs(
    document: Mapping[str, Any],
    locator: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> dict[str, Any]:
    packed = deepcopy(dict(document))
    body = _document_body(packed)
    _rewrite_list(body.get("slots"), locator, _rewrite_slot)
    _rewrite_list(body.get("soundtrack"), locator, _rewrite_track)
    _rewrite_list(body.get("worldSfx"), locator, _rewrite_world_cue)
    return packed


def _is_empty_member(raw: str) -> bool:
    return not raw or raw.endswith("/")


def _escapes_package(raw: str) -> bool:
    return "\x00" in raw or raw.startswith("/") or raw.startswith("../") or raw == ".."


def _is_windows_abs(raw: str) -> bool:
    drive = raw.split("/", 1)[0]
    return ":" in drive and raw[:1].isalpha()


def _unsafe_member_parts(parts: list[str]) -> bool:
    return not parts or ".." in parts or any(not _SAFE_SEGMENT.fullmatch(part) for part in parts)


def safe_zip_member(name: str) -> str:
    raw = str(name or "").replace("\\", "/")
    if _is_empty_member(raw) or _escapes_package(raw) or _is_windows_abs(raw):
        raise ScenePackageSecurity("Rejected path traversal in the package")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if _unsafe_member_parts(parts):
        raise ScenePackageSecurity("Package member names must be relative and simple")
    return "/".join(parts)


def zipinfo_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return bool(mode) and stat.S_ISLNK(mode)


def _read_zip_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise ScenePackageTooLarge("A packaged file exceeds the size limit")
    buffer = bytearray()
    with archive.open(info, "r") as handle:
        while len(buffer) < info.file_size:
            chunk = handle.read(min(1024 * 1024, info.file_size - len(buffer)))
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > limit:
                raise ScenePackageTooLarge("Uncompressed package member exceeds the size limit")
        extra = handle.read(1)
    if extra:
        raise ScenePackageSecurity("Zip member is larger than its declared size")
    if len(buffer) != info.file_size:
        raise ScenePackageError("Zip member is truncated")
    return bytes(buffer)


def inspect_zip_members(path: Path) -> list[zipfile.ZipInfo]:
    size = path.stat().st_size
    if size > MAX_ZIP_BYTES:
        raise ScenePackageTooLarge("Package zip exceeds the size limit")
    if not zipfile.is_zipfile(path):
        raise ScenePackageError("Expected a scene package zip")
    with zipfile.ZipFile(path, "r") as archive:
        infos = list(archive.infolist())
    total = 0
    names: set[str] = set()
    for info in infos:
        if info.is_dir():
            continue
        member = safe_zip_member(info.filename)
        if member in names:
            raise ScenePackageError("Package contains duplicate members")
        names.add(member)
        if zipinfo_is_symlink(info):
            raise ScenePackageSecurity("Rejected a symlink inside the package")
        if info.file_size > MAX_MEMBER_BYTES:
            raise ScenePackageTooLarge("A packaged file exceeds the size limit")
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ScenePackageTooLarge("Uncompressed package exceeds the size limit")
        lowered = member.casefold()
        if lowered in CINEMA_MEMBER_HINTS or lowered.endswith("/cinema.js") or lowered.endswith("/cinema.ts"):
            raise ScenePackageSecurity("Unknown cinema extension is not supported in the editor")
    return infos


AssetReader = Callable[[str, str], bytes | None]


def gallery_url(workspace: str, filename: str) -> str:
    from urllib.parse import quote
    if workspace == "__uploads__":
        return "/api/v1/uploads/" + quote(filename, safe="")
    return "/api/v1/file/" + quote(filename, safe="") + "?workspace=" + quote(workspace, safe="")


def _kind_from_name(filename: str, hinted: str = "") -> str:
    if hinted in {"image", "audio", "video", "model3d", "document", "other"}:
        return hinted
    return infer_asset_kind(filename)


def _read_local_asset(reader: AssetReader, use: Mapping[str, Any], default_workspace: str) -> tuple[bytes | None, str]:
    url = str(use.get("url") or "")
    kind = classify_url(url) if url else "empty"
    if kind in {"transient", "unsafe", "external"}:
        raise ScenePackageSecurity("Unauthorized external or transient media link")
    workspace = str(use.get("workspaceId") or default_workspace or "")
    filename = str(use.get("filename") or "")
    if kind == "uploads":
        workspace, filename = parse_media_locator(url, workspace)
    elif kind == "gallery":
        parsed_ws, parsed_name = parse_media_locator(url, workspace)
        workspace, filename = parsed_ws or workspace, parsed_name or filename
    if not filename:
        return None, ""
    data = reader(workspace or default_workspace, filename)
    return data, filename


def _media_suffix(filename: str, fallback: str) -> str:
    suffix = Path(filename).suffix.casefold()
    if suffix in ALLOWED_MEDIA_EXT:
        return suffix
    other = Path(fallback or "bin").suffix.casefold()
    return other if other in ALLOWED_MEDIA_EXT else ".bin"


def _ref_lookup_keys(ref: Mapping[str, Any], workspace: str) -> list[tuple[str, str, str]]:
    url = str(ref.get("url") or "")
    filename = str(ref.get("filename") or "")
    scoped = str(ref.get("workspaceId") or workspace or "")
    keys = [(scoped, filename, url)]
    if url:
        parsed_ws, parsed_name = parse_media_locator(url, scoped or None)
        parsed_ws = str(parsed_ws or scoped)
        parsed_name = parsed_name or filename
        keys.extend((
            (parsed_ws, parsed_name, url),
            (scoped, "", url),
            (parsed_ws, parsed_name, ""),
            ("", "", url),
        ))
    if filename:
        keys.append((scoped, filename, ""))
    seen: set[tuple[str, str, str]] = set()
    unique: list[tuple[str, str, str]] = []
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        unique.append(key)
    return unique


def _register_packed_asset(
    use: Mapping[str, Any],
    data: bytes,
    filename: str,
    workspace: str,
    files: dict[str, bytes],
    assets_by_hash: dict[str, dict[str, Any]],
    hash_by_key: dict[tuple[str, str, str], str],
) -> None:
    digest = sha256_bytes(data)
    member = f"{MEDIA_DIR}/{digest}{_media_suffix(filename, str(use.get('filename') or ''))}"
    current = assets_by_hash.get(digest)
    if current is None:
        if len(assets_by_hash) >= MAX_ASSETS:
            raise ScenePackageError("Too many unique assets in one package")
        files[member] = data
        assets_by_hash[digest] = {
            "sha256": digest,
            "kind": _kind_from_name(filename, str(use.get("kind") or "")),
            "path": member,
            "filename": safe_export_filename(filename),
            "size": len(data),
            "uses": [f"{use['doc_id']}:{use['role']}"],
        }
    else:
        current["uses"].append(f"{use['doc_id']}:{use['role']}")
    for key in _ref_lookup_keys(use, workspace):
        hash_by_key[key] = digest


def _packed_locator(workspace: str, assets_by_hash: dict[str, dict[str, Any]], hash_by_key: dict[tuple[str, str, str], str]):
    def locate(ref: dict[str, Any]) -> dict[str, Any] | None:
        url = str(ref.get("url") or "")
        filename = str(ref.get("filename") or "")
        if not url and not filename:
            return None
        digest = next((hash_by_key[key] for key in _ref_lookup_keys(ref, workspace) if key in hash_by_key), None)
        if not digest:
            return None
        asset = assets_by_hash[digest]
        return {
            "workspaceId": PACKAGE_FILENAME,
            "filename": asset["filename"],
            "url": asset["path"],
            "assetId": HASH_PREFIX + digest,
        }
    return locate


def _skip_empty_use(use: Mapping[str, Any]) -> bool:
    url = str(use.get("url") or "")
    return classify_url(url) == "empty" and not use.get("filename")


def _encode_packed_document(rewritten: Mapping[str, Any]) -> bytes:
    encoded = json.dumps(rewritten, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise ScenePackageTooLarge("Scene document exceeds 2 MB")
    return encoded


def _document_pack_name(rewritten: Mapping[str, Any], index: int) -> tuple[str, str, str | None]:
    role = "template" if is_template_wrapper(rewritten) else "shot"
    title = rewritten.get("title") if is_template_wrapper(rewritten) else None
    production = rewritten.get("production") if isinstance(rewritten.get("production"), Mapping) else {}
    name = str(title or production.get("title") or rewritten.get("templateId") or f"shot-{index}")[:120]
    warning = None
    if role == "template":
        warning = "Packed a scenario wrapper; media still travels with the package, unlike a template file."
    return role, name, warning


def _pack_document(
    raw: Mapping[str, Any],
    index: int,
    reader: AssetReader,
    workspace: str,
    files: dict[str, bytes],
    assets_by_hash: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str], str | None]:
    reject_unknown_cinema(raw)
    unknown = [f"documents[{index}].{field}" for field in collect_unknown_fields(raw)]
    hash_by_key: dict[tuple[str, str, str], str] = {}
    for use in iter_asset_uses(raw, doc_id=f"shot-{index}"):
        if _skip_empty_use(use):
            continue
        data, filename = _read_local_asset(reader, use, workspace)
        if data is None:
            raise ScenePackageError(f"Missing scene asset: {filename or use.get('url')}")
        _register_packed_asset(use, data, filename, workspace, files, assets_by_hash, hash_by_key)
    rewritten = rewrite_document_refs(raw, _packed_locator(workspace, assets_by_hash, hash_by_key))
    encoded = _encode_packed_document(rewritten)
    path = f"{DOCUMENTS_DIR}/shot-{index}.json"
    files[path] = encoded
    role, name, warning = _document_pack_name(rewritten, index)
    packed = {"id": f"shot-{index}", "role": role, "path": path, "sha256": sha256_bytes(encoded), "name": name}
    return packed, unknown, warning


def build_package(
    documents: Iterable[Mapping[str, Any]],
    reader: AssetReader,
    *,
    title: str = "",
    workspace: str = "",
) -> tuple[dict[str, Any], dict[str, bytes]]:
    shots = list(documents)
    if not shots:
        raise ScenePackageError("Export at least one scene document")
    if len(shots) > MAX_DOCUMENTS:
        raise ScenePackageError("Too many documents in one package")
    files: dict[str, bytes] = {}
    assets_by_hash: dict[str, dict[str, Any]] = {}
    packed_documents: list[dict[str, Any]] = []
    unknown: list[str] = []
    warnings: list[str] = []
    for index, raw in enumerate(shots, start=1):
        packed, fields, warning = _pack_document(raw, index, reader, workspace, files, assets_by_hash)
        packed_documents.append(packed)
        unknown.extend(fields)
        if warning:
            warnings.append(warning)
    if unknown:
        warnings.append("Unknown fields are preserved and listed; the editor did not drop them.")
    manifest = {
        "kind": PACKAGE_KIND,
        "schema": PACKAGE_SCHEMA,
        "schema_version": PACKAGE_VERSION,
        "title": (title or "Scene package")[:120],
        "created_at": utc_now(),
        "documents": packed_documents,
        "assets": list(assets_by_hash.values()),
        "unknown_fields": unknown,
        "warnings": warnings,
    }
    files[MANIFEST_NAME] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    return manifest, files


def write_package_zip(
    documents: Iterable[Mapping[str, Any]],
    reader: AssetReader,
    *,
    title: str = "",
    workspace: str = "",
) -> bytes:
    manifest, files = build_package(documents, reader, title=title, workspace=workspace)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    payload = buffer.getvalue()
    if len(payload) > MAX_ZIP_BYTES:
        raise ScenePackageTooLarge("Package zip exceeds the size limit")
    _ = manifest
    return payload


def _load_json_member(data: bytes, name: str) -> Any:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ScenePackageTooLarge(f"{name} exceeds 2 MB")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScenePackageError(f"{name} is not valid JSON") from exc


def _validate_manifest(manifest_raw: Any) -> tuple[dict[str, Any], list[Any], list[Any]]:
    if not isinstance(manifest_raw, Mapping):
        raise ScenePackageError("package.json must be an object")
    kind = manifest_raw.get("kind") or manifest_raw.get("schema")
    if kind == TEMPLATE_KIND:
        raise ScenePackageError("This is a scenario template, not a portable project package")
    if kind != PACKAGE_KIND and manifest_raw.get("schema") != PACKAGE_SCHEMA:
        raise ScenePackageError("Unsupported scene package kind")
    version = manifest_raw.get("schema_version", manifest_raw.get("version"))
    if version != PACKAGE_VERSION:
        raise ScenePackageError("Unsupported scene package version")
    reject_unknown_cinema(manifest_raw)
    documents_meta = manifest_raw.get("documents")
    assets_meta = manifest_raw.get("assets")
    if not isinstance(documents_meta, list) or not documents_meta:
        raise ScenePackageError("Package lists no documents")
    if len(documents_meta) > MAX_DOCUMENTS:
        raise ScenePackageError("Too many documents in one package")
    if not isinstance(assets_meta, list) or len(assets_meta) > MAX_ASSETS:
        raise ScenePackageError("Invalid package asset list")
    return dict(manifest_raw), documents_meta, assets_meta


def _extract_document(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    entry: Mapping[str, Any],
    files: dict[str, bytes],
) -> dict[str, Any]:
    member_name = safe_zip_member(str(entry.get("path") or ""))
    if not member_name.startswith(f"{DOCUMENTS_DIR}/"):
        raise ScenePackageSecurity("Document paths must stay under documents/")
    if member_name not in members:
        raise ScenePackageError(f"Missing packed document {member_name}")
    payload = _read_zip_member(archive, members[member_name], MAX_DOCUMENT_BYTES)
    expected = str(entry.get("sha256") or "")
    if expected and sha256_bytes(payload) != expected:
        raise ScenePackageError(f"Document {member_name} does not match its manifest hash")
    parsed = _load_json_member(payload, member_name)
    if not isinstance(parsed, Mapping):
        raise ScenePackageError("Packed document must be an object")
    files[member_name] = payload
    return dict(parsed)


def _extract_asset(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    entry: Mapping[str, Any],
    files: dict[str, bytes],
) -> dict[str, Any]:
    member_name = safe_zip_member(str(entry.get("path") or ""))
    if not member_name.startswith(f"{MEDIA_DIR}/"):
        raise ScenePackageSecurity("Media paths must stay under media/")
    digest = str(entry.get("sha256") or "")
    if not _SHA256.fullmatch(digest):
        raise ScenePackageError("Asset hash is missing or invalid")
    if not Path(member_name).name.startswith(digest):
        raise ScenePackageSecurity("Media filename must start with its content hash")
    status = "ok"
    if member_name not in members:
        status = "missing"
    else:
        payload = _read_zip_member(archive, members[member_name], MAX_MEMBER_BYTES)
        if sha256_bytes(payload) != digest:
            status = "tampered"
        else:
            files[member_name] = payload
    return {**dict(entry), "path": member_name, "sha256": digest, "status": status, "present": status == "ok"}


def read_package(path: Path) -> dict[str, Any]:
    infos = inspect_zip_members(path)
    members = {safe_zip_member(info.filename): info for info in infos if not info.is_dir()}
    if MANIFEST_NAME not in members:
        raise ScenePackageError("Package is missing package.json")
    with zipfile.ZipFile(path, "r") as archive:
        manifest, documents_meta, assets_meta = _validate_manifest(
            _load_json_member(_read_zip_member(archive, members[MANIFEST_NAME], MAX_DOCUMENT_BYTES), MANIFEST_NAME)
        )
        files: dict[str, bytes] = {}
        documents = [_extract_document(archive, members, entry, files) for entry in documents_meta if isinstance(entry, Mapping)]
        if len(documents) != len(documents_meta):
            raise ScenePackageError("Invalid document entry")
        assets = [_extract_asset(archive, members, entry, files) for entry in assets_meta if isinstance(entry, Mapping)]
        if len(assets) != len(assets_meta):
            raise ScenePackageError("Invalid asset entry")
        extras = sorted(name for name in members if name not in files and name != MANIFEST_NAME)
    return {"manifest": manifest, "documents": documents, "assets": assets, "files": files, "extra_members": extras}


def _reject_bare_json(path: Path, first: bytes) -> None:
    if not (first.lstrip().startswith(b"{") or first.lstrip().startswith(b"[")):
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScenePackageError("Expected a scene package zip") from exc
    if is_template_wrapper(raw):
        raise ScenePackageError("This is a scenario template, not a portable project package")
    raise ScenePackageError("Expected a scene package zip")


def _document_issues(document: Mapping[str, Any], index: int) -> tuple[list[dict[str, Any]], list[str]]:
    prefix = f"documents[{index}]."
    issues: list[dict[str, Any]] = []
    cinema = cinema_extension_of(document)
    if cinema and cinema not in SUPPORTED_CINEMA_EXTENSIONS:
        issues.append(_issue("cinema_extension", f"Unknown cinema extension: {cinema}", path=prefix.rstrip(".")))
    try:
        DocumentInput(document=unwrap_document(document))
    except Exception as exc:
        issues.append(_issue("invalid_document", str(exc), path=prefix.rstrip(".")))
    for use in iter_asset_uses(document, doc_id=f"shot-{index}"):
        if classify_url(str(use.get("url") or "")) in {"external", "unsafe", "transient"}:
            issues.append(_issue("external_link", "Unauthorized external or transient media link", path=use["role"]))
    unknown = [prefix + field for field in collect_unknown_fields(document)]
    return issues, unknown


def _asset_issues(assets: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for asset in assets:
        label = asset.get("filename") or asset["sha256"]
        if asset["status"] == "missing":
            issues.append(_issue("missing_asset", f"Missing packed asset {label}", repair=True, path=str(asset["path"])))
        elif asset["status"] == "tampered":
            issues.append(_issue("tampered_asset", f"Asset {label} does not match its hash", repair=True, path=str(asset["path"])))
    return issues


def preflight_package(path: Path) -> dict[str, Any]:
    _reject_bare_json(path, path.read_bytes()[:32])
    packed = read_package(path)
    issues: list[dict[str, Any]] = []
    unknown: list[str] = []
    for index, document in enumerate(packed["documents"], start=1):
        doc_issues, fields = _document_issues(document, index)
        issues.extend(doc_issues)
        unknown.extend(fields)
    issues.extend(_asset_issues(packed["assets"]))
    issues.extend(_issue("extra_member", f"Unexpected package member {extra}", path=extra) for extra in packed["extra_members"])
    if unknown:
        issues.append(_issue("unknown_fields", "Unknown fields were kept and listed rather than dropped"))
    blocking = [item for item in issues if item["code"] in {"cinema_extension", "external_link", "invalid_document"}]
    ok = not blocking and not any(item.get("repair") for item in issues)
    summaries = packed["manifest"].get("documents") or []
    return {
        "ok": ok,
        "kind": PACKAGE_KIND,
        "schema_version": PACKAGE_VERSION,
        "title": packed["manifest"].get("title") or "",
        "documents": [{"id": entry.get("id"), "role": entry.get("role"), "name": entry.get("name")} for entry in summaries],
        "assets": packed["assets"],
        "unknown_fields": unknown or packed["manifest"].get("unknown_fields") or [],
        "warnings": packed["manifest"].get("warnings") or [],
        "issues": issues,
        "extra_members": packed["extra_members"],
        "size_bytes": path.stat().st_size,
        "can_import": ok,
    }



from services.scene_packages_import import (
    apply_reassign,
    find_existing_by_hash,
    import_package,
)


def make_workspace_reader(
    workspace_dir: Callable[[str], str],
    uploads_dir: Callable[[], str] | None = None,
) -> AssetReader:
    def reader(workspace_id: str, filename: str) -> bytes | None:
        name = _basename(filename)
        if not name or name in {".", ".."}:
            return None
        roots: list[Path] = []
        if workspace_id == "__uploads__" and uploads_dir is not None:
            roots.append(Path(uploads_dir()))
        else:
            try:
                roots.append(Path(workspace_dir(workspace_id or "default")))
            except Exception:
                return None
            if uploads_dir is not None:
                roots.append(Path(uploads_dir()))
        for root in roots:
            candidate = (root / name).resolve()
            try:
                if os.path.commonpath((str(candidate), str(root.resolve()))) != str(root.resolve()):
                    continue
            except (OSError, ValueError):
                continue
            if candidate.is_file() and not candidate.is_symlink():
                return candidate.read_bytes()
        return None
    return reader


def format_contract() -> dict[str, Any]:
    return {
        "kind": PACKAGE_KIND,
        "schema": PACKAGE_SCHEMA,
        "schema_version": PACKAGE_VERSION,
        "template_kind": TEMPLATE_KIND,
        "layout": [MANIFEST_NAME, f"{DOCUMENTS_DIR}/shot-N.json", f"{MEDIA_DIR}/<sha256>.<ext>"],
        "limits": {
            "zip_bytes": MAX_ZIP_BYTES,
            "uncompressed_bytes": MAX_UNCOMPRESSED_BYTES,
            "member_bytes": MAX_MEMBER_BYTES,
            "documents": MAX_DOCUMENTS,
            "assets": MAX_ASSETS,
        },
        "notes": [
            "Export packs only referenced media and dedupes by SHA-256.",
            "A .world3d.template.json is a scenario layout, not a portable project.",
            "Unknown cinema extensions are rejected; unknown document fields are listed and kept.",
        ],
    }

"""Import, reassignment and unique-name helpers for scene packages."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from services.asset_manifest import (
    build_asset_manifest,
    read_asset_manifest,
    sidecar_path,
    write_asset_manifest,
)
from services.scene_library import save_world3d

from services.scene_packages import (
    HASH_PREFIX,
    PACKAGE_KIND,
    STUB_PREVIEW,
    AssetReader,
    ScenePackageError,
    _SHA256,
    _basename,
    _kind_from_name,
    classify_url,
    gallery_url,
    is_template_wrapper,
    parse_media_locator,
    preflight_package,
    read_package,
    require_workspace,
    rewrite_document_refs,
    safe_export_filename,
    sha256_bytes,
    sha256_file,
    unwrap_document,
)

def _sidecar_hash(path: Path) -> str | None:
    manifest = read_asset_manifest(path)
    if not isinstance(manifest, Mapping):
        return None
    asset = manifest.get("asset")
    if isinstance(asset, Mapping) and str(asset.get("filename") or "") not in {"", path.name}:
        return None
    technical = manifest.get("technical")
    if isinstance(technical, Mapping):
        digest = str(technical.get("sha256") or "")
        if _SHA256.fullmatch(digest):
            return digest
    return None


def find_existing_by_hash(root: Path, digest: str, size: int | None = None) -> Path | None:
    if not root.is_dir():
        return None
    try:
        entries = list(root.iterdir())
    except OSError:
        return None
    sized: list[Path] = []
    for entry in entries:
        if not entry.is_file() or entry.name.endswith(".meta.json") or entry.name.endswith(".preview.png"):
            continue
        marked = _sidecar_hash(entry)
        if marked == digest:
            try:
                if sha256_file(entry) == digest:
                    return entry
            except OSError:
                continue
            continue
        try:
            if size is not None and entry.stat().st_size == size:
                sized.append(entry)
        except OSError:
            continue
    for entry in sized:
        try:
            if sha256_file(entry) == digest:
                return entry
        except OSError:
            continue
    return None


def _name_is_free(root: Path, name: str, digest: str) -> bool:
    dest = root / name
    if dest.exists():
        try:
            return sha256_file(dest) == digest
        except OSError:
            return False
    return not sidecar_path(dest).exists()


def _unique_name(root: Path, filename: str, digest: str) -> str:
    safe = safe_export_filename(filename)
    stem, suffix = Path(safe).stem, Path(safe).suffix
    candidates = [safe, f"{stem}-{digest[:8]}{suffix}"]
    candidates.extend(f"{stem}-{digest[:8]}-{index}{suffix}" for index in range(2, 16))
    for name in candidates:
        if _name_is_free(root, name, digest):
            return name
    raise ScenePackageError(f"Could not allocate a unique name for {safe}")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pkg.tmp")
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _reassign_locator(item: Mapping[str, Any], workspace: str) -> tuple[str, str]:
    filename = str(item.get("filename") or "")
    source_workspace = str(item.get("workspace") or item.get("workspaceId") or workspace)
    url = str(item.get("url") or "")
    if not url:
        return filename, source_workspace
    parsed_ws, parsed_name = parse_media_locator(url, source_workspace)
    return parsed_name or filename, parsed_ws or source_workspace


def _reassign_one(item: Mapping[str, Any], reader: AssetReader, workspace: str) -> tuple[str, dict[str, Any]]:
    digest = str(item.get("sha256") or "").casefold()
    if not _SHA256.fullmatch(digest):
        raise ScenePackageError("Reassignment is missing a content hash")
    filename, source_workspace = _reassign_locator(item, workspace)
    data = reader(source_workspace, filename)
    if data is None:
        raise ScenePackageError(f"Replacement asset not found: {filename}")
    return digest, {
        "data": data,
        "filename": filename,
        "workspaceId": source_workspace,
        "url": gallery_url(source_workspace, filename),
        "sha256": sha256_bytes(data),
        "assetId": str(item.get("assetId") or ""),
    }


def apply_reassign(
    packed: Mapping[str, Any],
    reassign: Iterable[Mapping[str, Any]],
    reader: AssetReader,
    workspace: str,
) -> dict[str, dict[str, Any]]:
    replacements: dict[str, dict[str, Any]] = {}
    for item in reassign:
        if isinstance(item, Mapping):
            digest, payload = _reassign_one(item, reader, workspace)
            replacements[digest] = payload
    return replacements


def _assert_importable(report: Mapping[str, Any], packed: Mapping[str, Any], replacements: Mapping[str, Any]) -> None:
    blocking = {"cinema_extension", "external_link", "invalid_document"}
    for issue in report["issues"]:
        if issue["code"] in blocking:
            raise ScenePackageError(issue["message"])
    for asset in packed["assets"]:
        if asset["status"] != "ok" and asset["sha256"] not in replacements:
            raise ScenePackageError(f"Repair required for {asset.get('filename') or asset['sha256']}")


def _published_ref(workspace: str, filename: str, url: str, asset_id: str = "") -> dict[str, Any]:
    return {"workspaceId": workspace, "filename": filename, "url": url, "assetId": asset_id}


def _publish_one_asset(
    asset: Mapping[str, Any],
    packed: Mapping[str, Any],
    replacements: Mapping[str, dict[str, Any]],
    workspace: str,
    root: Path,
    written: list[Path],
) -> tuple[str, dict[str, Any], bool]:
    digest = str(asset["sha256"])
    replacement = replacements.get(digest)
    if replacement:
        return digest, _published_ref(
            replacement["workspaceId"] or workspace, replacement["filename"],
            replacement["url"], str(replacement.get("assetId") or ""),
        ), True
    data = packed["files"].get(asset["path"])
    filename = str(asset.get("filename") or f"{digest}.bin")
    if not data:
        raise ScenePackageError(f"Missing packed asset {filename}")
    existing = find_existing_by_hash(root, digest, len(data))
    if existing is not None:
        manifest = read_asset_manifest(existing) or {}
        asset_block = manifest.get("asset") if isinstance(manifest, Mapping) else None
        asset_id = str(asset_block.get("id") or "") if isinstance(asset_block, Mapping) else ""
        return digest, _published_ref(workspace, existing.name, gallery_url(workspace, existing.name), asset_id), True
    dest_name = _unique_name(root, filename, digest)
    dest = root / dest_name
    if dest.exists():
        manifest = read_asset_manifest(dest) or {}
        asset_block = manifest.get("asset") if isinstance(manifest, Mapping) else None
        asset_id = str(asset_block.get("id") or "") if isinstance(asset_block, Mapping) else ""
        return digest, _published_ref(workspace, dest.name, gallery_url(workspace, dest.name), asset_id), True
    _write_bytes(dest, data)
    written.append(dest)
    manifest = build_asset_manifest(
        dest, kind=_kind_from_name(dest_name, str(asset.get("kind") or "")),
        workspace_id=workspace, tool="scene-package-import", actor="user",
        execution_mode="import", technical={"sha256": digest, "package_kind": PACKAGE_KIND},
    )
    written.append(write_asset_manifest(dest, manifest))
    return digest, _published_ref(workspace, dest_name, gallery_url(workspace, dest_name), manifest["asset"]["id"]), False


def _imported_name(rewritten: Mapping[str, Any], body: Mapping[str, Any]) -> str:
    title = rewritten.get("title") if is_template_wrapper(rewritten) else None
    production = body.get("production") if isinstance(body.get("production"), Mapping) else {}
    return str(title or production.get("title") or body.get("templateId") or "Imported scene")


def _locate_published(
    published_by_hash: Mapping[str, Mapping[str, Any]],
    published_by_filename: Mapping[str, Mapping[str, Any]] | None = None,
):
    by_filename = published_by_filename or {}

    def locate(ref: dict[str, Any]) -> dict[str, Any] | None:
        url = str(ref.get("url") or "")
        asset_id = str(ref.get("assetId") or "")
        digest = asset_id[len(HASH_PREFIX):] if asset_id.startswith(HASH_PREFIX) else ""
        if not digest and classify_url(url) == "relative":
            digest = Path(url).stem[:64]
        published = published_by_hash.get(digest)
        if not published:
            filename = str(ref.get("filename") or "")
            if not filename and url:
                _, filename = parse_media_locator(url)
            published = by_filename.get(filename)
        if not published:
            return None
        return {
            "workspaceId": published["workspaceId"],
            "filename": published["filename"],
            "url": published["url"],
            "assetId": published["assetId"] or asset_id,
        }
    return locate


def _rollback(written: list[Path]) -> None:
    for item in reversed(written):
        try:
            item.unlink(missing_ok=True)
        except OSError:
            pass


def import_package(
    path: Path,
    *,
    workspace: str,
    workspace_dir: Callable[[str], str],
    reader: AssetReader,
    reassign: Iterable[Mapping[str, Any]] = (),
    preview: str | None = None,
) -> dict[str, Any]:
    workspace = require_workspace(workspace)
    report = preflight_package(path)
    packed = read_package(path)
    replacements = apply_reassign(packed, reassign, reader, workspace)
    _assert_importable(report, packed, replacements)
    root = Path(workspace_dir(workspace))
    root.mkdir(parents=True, exist_ok=True)
    published_by_hash: dict[str, dict[str, Any]] = {}
    published_by_filename: dict[str, dict[str, Any]] = {}
    written: list[Path] = []
    reused = created = 0
    try:
        for asset in packed["assets"]:
            digest, published, was_reused = _publish_one_asset(asset, packed, replacements, workspace, root, written)
            published_by_hash[digest] = published
            original_name = str(asset.get("filename") or published["filename"] or "")
            if original_name:
                published_by_filename[original_name] = published
            reused += int(was_reused)
            created += int(not was_reused)
        published_scenes = []
        locate = _locate_published(published_by_hash, published_by_filename)
        for document in packed["documents"]:
            rewritten = rewrite_document_refs(document, locate)
            body = unwrap_document(rewritten)
            saved = save_world3d(
                {"workspace": workspace, "document": body, "name": _imported_name(rewritten, body),
                 "preview": preview or STUB_PREVIEW},
                workspace_dir,
            )
            written.append(root / saved["name"])
            thumb = root / saved["name"].replace(".json", ".preview.png")
            if thumb.exists():
                written.append(thumb)
            published_scenes.append(saved)
        return {
            "ok": True, "workspace": workspace, "scenes": published_scenes,
            "assets_created": created, "assets_reused": reused,
            "unknown_fields": report.get("unknown_fields") or [],
            "warnings": report.get("warnings") or [],
        }
    except Exception:
        _rollback(written)
        raise


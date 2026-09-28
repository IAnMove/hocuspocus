"""Server-side library of user and community templates (``.hptemplate``).

Templates live outside workspaces, one folder per id (``<author>/<slug>/``) with
the same members as the portable zip plus ``origin.json``. People and agents use
the same library through HTTP and the MCP ``templates.*`` commands.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

from services.scene_packages import (
    ScenePackageError,
    _read_zip_member,
    classify_url,
    gallery_url,
    parse_media_locator,
    safe_zip_member,
    zipinfo_is_symlink,
)
from services.template_format import (
    KIND,
    MEDIA_REF_RE,
    PREVIEW_EXT,
    TemplateError,
    check_document,
    clear_slot,
    fill_slot,
    is_bundled_example,
    media_kind,
    media_refs,
    normalize_manifest,
    rewrite_media,
    set_control,
    slugify,
    targets_of,
)

LEGACY_WORLD3D_KIND = "hocuspocus.world3d.template"
LIBRARY_DIR_ENV = "HOCUS_TEMPLATE_LIBRARY_DIR"
MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 48 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_MEDIA = 64
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
MANIFEST, DOCUMENT, ORIGIN = "template.json", "document.json", "origin.json"
SOURCES = ("user", "imported", "community")

AssetReader = Callable[[str, str], bytes | None]


def resolve_template_library_root(app_dir: str | os.PathLike[str]) -> Path:
    """Durable storage outside the source tree (same policy as the style library)."""
    configured = str(os.environ.get(LIBRARY_DIR_ENV) or "").strip()
    app_path = Path(app_dir).expanduser().resolve()
    if configured:
        path = Path(configured).expanduser()
        return (path if path.is_absolute() else app_path.parent / path).resolve()
    pinokio_home = str(os.environ.get("PINOKIO_HOME") or "").strip()
    if pinokio_home:
        return Path(pinokio_home).expanduser().resolve() / "cache" / "maestro" / "template-library"
    if app_path.parent.parent.name in {"api", "plugin"}:
        return (app_path.parent.parent.parent / "cache" / "maestro" / "template-library").resolve()
    return (app_path.parent / ".maestro-data" / "template-library").resolve()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


class TemplateLibrary:
    def __init__(self, root: str | os.PathLike[str], *, workspace_dir: Callable[[str], str], reader: AssetReader) -> None:
        self.root = Path(root)
        self.workspace_dir = workspace_dir
        self.reader = reader

    # ---- storage ---------------------------------------------------------
    def _folder(self, template_id: str) -> Path:
        from services.template_format import ID_RE
        if not isinstance(template_id, str) or not ID_RE.fullmatch(template_id):
            raise TemplateError("Unknown template id", status=404, code="not_found")
        return self.root / template_id

    def _read(self, template_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        folder = self._folder(template_id)
        try:
            manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
            document = json.loads((folder / DOCUMENT).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise TemplateError("Template not found", status=404, code="not_found") from exc
        except (OSError, ValueError) as exc:
            raise TemplateError("Template files are unreadable", status=409, code="unreadable") from exc
        return folder, manifest, document

    def _origin(self, folder: Path) -> dict[str, Any]:
        try:
            return json.loads((folder / ORIGIN).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"source": "user"}

    def _write(self, manifest: dict, document: dict, files: dict[str, bytes], origin: dict, *,
               replace: bool, expected_updated_at: str | None) -> dict[str, Any]:
        folder = self._folder(manifest["id"])
        if (folder / MANIFEST).exists():
            current = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
            if expected_updated_at is not None and expected_updated_at != current.get("updatedAt"):
                raise TemplateError("Template changed since you opened it; reload first", status=409, code="revision_conflict")
            if expected_updated_at is None and not replace:
                raise TemplateError("A template with this id exists; pass expected_updated_at or replace",
                                    status=409, code="exists")
            manifest["createdAt"] = current.get("createdAt") or manifest["createdAt"]
        folder.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".tpl-", dir=folder.parent))
        try:
            (staging / MANIFEST).write_bytes(_dump(manifest))
            (staging / DOCUMENT).write_bytes(_dump(document))
            (staging / ORIGIN).write_bytes(_dump(origin))
            for name, data in files.items():
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            backup = folder.with_name(folder.name + ".old")
            if folder.exists():
                folder.rename(backup)
            staging.rename(folder)
            shutil.rmtree(backup, ignore_errors=True)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return self.summary(manifest["id"])

    # ---- reading -----------------------------------------------------------
    def summary(self, template_id: str) -> dict[str, Any]:
        folder, manifest, _ = self._read(template_id)
        preview = manifest.get("preview")
        return {
            **{key: manifest.get(key) for key in ("id", "editor", "title", "description", "tags", "author", "license",
                                                   "templateVersion", "createdAt", "updatedAt", "requires")},
            "slots": manifest.get("slots") or [], "controls": manifest.get("controls") or [],
            "media": len(manifest.get("media") or []), "source": self._origin(folder).get("source", "user"),
            "previewUrl": f"/api/v1/templates/{template_id}/preview" if preview else None,
        }

    def summaries(self, *, editor: str | None = None, tag: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
        items = []
        if not self.root.is_dir():
            return items
        for manifest_path in sorted(self.root.glob(f"*/*/{MANIFEST}")):
            template_id = f"{manifest_path.parent.parent.name}/{manifest_path.parent.name}"
            try:
                item = self.summary(template_id)
            except TemplateError:
                continue
            text = " ".join([item["title"] or "", item["description"] or "", " ".join(item["tags"] or [])]).casefold()
            if (editor and item["editor"] != editor) or (tag and tag not in (item["tags"] or [])) or (query and query.casefold() not in text):
                continue
            items.append(item)
        return sorted(items, key=lambda item: item.get("updatedAt") or "", reverse=True)

    def get(self, template_id: str) -> dict[str, Any]:
        _, manifest, document = self._read(template_id)
        return {"template": self.summary(template_id), "manifest": manifest, "document": document}

    def file(self, template_id: str, member: str) -> Path:
        folder = self._folder(template_id)
        name = safe_zip_member(member)
        path = folder / name
        if name not in (MANIFEST, DOCUMENT) and not name.startswith("media/") and not name.startswith("preview"):
            raise TemplateError("Not a template file", status=404, code="not_found")
        if not path.is_file():
            raise TemplateError("File not found", status=404, code="not_found")
        return path

    def preview_path(self, template_id: str) -> Path:
        _, manifest, _ = self._read(template_id)
        if not manifest.get("preview"):
            raise TemplateError("This template has no preview", status=404, code="not_found")
        return self.file(template_id, manifest["preview"])

    # ---- saving from a workspace ------------------------------------------
    def _pack_workspace_media(self, editor: str, document: dict, workspace: str, include_media: bool,
                              manifest: dict) -> tuple[dict, dict[str, bytes]]:
        files: dict[str, bytes] = {}
        if not include_media:
            for slot in manifest["slots"]:
                clear_slot(editor, document, slot)
            document = self._drop_unbound(editor, document)
        leftovers: list[str] = []

        def pack(value: str) -> str | None:
            if is_bundled_example(value) or MEDIA_REF_RE.fullmatch(value):
                return None
            if classify_url(value) not in {"gallery", "uploads", "relative"}:
                return None
            if not include_media:
                leftovers.append(value)
                return None
            owner, filename = parse_media_locator(value, workspace)
            data = self.reader(owner or workspace, filename)
            kind = media_kind(filename)
            if data is None or kind is None:
                raise TemplateError(f"Cannot read media {filename!r} from the workspace", status=409, code="missing_media")
            name = f"media/{_sha(data)}{Path(filename).suffix.casefold()}"
            files[name] = data
            return name

        packed = rewrite_media(editor, document, pack)
        if leftovers:
            raise TemplateError("These media are not in any slot; declare a slot for them or include media: "
                                + ", ".join(sorted({Path(item.split('?')[0]).name for item in leftovers}))[:600],
                                code="unbound_media")
        if len(files) > MAX_MEDIA:
            raise TemplateError(f"A template can carry at most {MAX_MEDIA} media files")
        return packed, files

    @staticmethod
    def _drop_unbound(editor: str, document: dict) -> dict:
        """Without media, a Video 3D soundtrack is removed (it is not a slot)."""
        if editor == "video3d" and document.get("soundtrack"):
            document = {**document}
            document.pop("soundtrack", None)
        return document

    def _preview(self, workspace: str, preview: str | None) -> dict[str, bytes]:
        if not preview:
            return {}
        if preview.startswith("data:image/"):
            return self._inline_preview(preview)
        owner, filename = parse_media_locator(preview, workspace)
        suffix = Path(filename).suffix.casefold()
        data = self.reader(owner or workspace, filename) if suffix in PREVIEW_EXT else None
        if data is None or len(data) > MAX_PREVIEW_BYTES:
            raise TemplateError("preview must be a PNG, JPEG or WebP image up to 2 MB in the workspace", code="invalid_preview")
        return {f"preview{'.jpg' if suffix == '.jpeg' else suffix}": data}

    @staticmethod
    def _inline_preview(preview: str) -> dict[str, bytes]:
        head, _, body = preview.partition(",")
        suffix = {"data:image/png;base64": ".png", "data:image/jpeg;base64": ".jpg", "data:image/webp;base64": ".webp"}.get(head)
        try:
            data = base64.b64decode(body, validate=True) if suffix else b""
        except ValueError:
            data = b""
        if not data or len(data) > MAX_PREVIEW_BYTES:
            raise TemplateError("preview must be a PNG, JPEG or WebP image up to 2 MB", code="invalid_preview")
        return {f"preview{suffix}": data}

    def save(self, *, workspace: str, editor: str, document: Any, metadata: dict[str, Any], include_media: bool = False,
             preview: str | None = None, expected_updated_at: str | None = None) -> dict[str, Any]:
        document = check_document(editor, json.loads(json.dumps(document)))
        now = _now()
        manifest = normalize_manifest({**metadata, "kind": KIND, "version": 1, "editor": editor,
                                       "createdAt": now, "updatedAt": now}, document)
        packed, files = self._pack_workspace_media(editor, document, workspace, include_media, manifest)
        files.update(self._preview(workspace, preview))
        manifest.update(self._media_manifest(files))
        return self._write(manifest, packed, files, {"source": "user", "savedAt": now, "workspace": workspace},
                           replace=False, expected_updated_at=expected_updated_at)

    @staticmethod
    def _media_manifest(files: dict[str, bytes]) -> dict[str, Any]:
        media = [{"path": name, "sha256": _sha(data), "bytes": len(data), "type": media_kind(name)}
                 for name, data in sorted(files.items()) if name.startswith("media/")]
        preview = next((name for name in files if name.startswith("preview")), None)
        return {"media": media, **({"preview": preview} if preview else {})}

    # ---- applying into a workspace -------------------------------------------
    def apply(self, template_id: str, *, workspace: str, slots: dict[str, str] | None = None,
              controls: dict[str, Any] | None = None) -> dict[str, Any]:
        folder, manifest, document = self._read(template_id)
        editor = manifest["editor"]
        self._set_inputs(manifest, document, slots or {}, controls or {})
        copied: list[str] = []

        def materialize(value: str) -> str | None:
            match = MEDIA_REF_RE.fullmatch(value)
            if not match:
                return None
            name = f"tpl-{match.group(1)[:16]}{match.group(2)}"
            target = Path(self.workspace_dir(workspace)) / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(folder / value, target)
                copied.append(name)
            return gallery_url(workspace, name)

        applied = rewrite_media(editor, document, materialize)
        missing = [slot["id"] for slot in manifest.get("slots") or [] if slot.get("required") and not self._slot_filled(editor, applied, slot)]
        return {"template": template_id, "editor": editor, "document": applied, "copiedMedia": copied, "missingSlots": missing}

    @staticmethod
    def _set_inputs(manifest: dict, document: dict, slots: dict[str, str], controls: dict[str, Any]) -> None:
        known_slots = {slot["id"]: slot for slot in manifest.get("slots") or []}
        known_controls = {control["id"]: control for control in manifest.get("controls") or []}
        unknown = sorted((set(slots) - set(known_slots)) | (set(controls) - set(known_controls)))
        if unknown:
            raise TemplateError(f"Unknown slots or controls: {', '.join(unknown)}", code="unknown_input")
        for control_id, value in controls.items():
            set_control(document, known_controls[control_id], value)
        for slot_id, source in slots.items():
            if classify_url(str(source)) not in {"gallery", "uploads"} and not is_bundled_example(str(source)):
                raise TemplateError(f"Slot {slot_id} needs a workspace or example file", code="invalid_source")
            fill_slot(manifest["editor"], document, known_slots[slot_id], str(source))

    @staticmethod
    def _slot_filled(editor: str, document: dict, slot: dict[str, Any]) -> bool:
        if editor == "video3d":
            return any(isinstance(item, dict) and item.get("slot") == slot["target"] and item.get("sourceUrl")
                       for item in document.get("slots") or [])
        return any(isinstance(item, dict) and item.get("id") == slot["target"] and item.get("source")
                   for item in document.get("layers") or [])

    # ---- portable packages ----------------------------------------------------
    def export(self, template_id: str) -> tuple[str, bytes]:
        folder, manifest, _ = self._read(template_id)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob("*")):
                name = path.relative_to(folder).as_posix()
                if path.is_file() and name != ORIGIN:
                    archive.writestr(name, path.read_bytes())
        return f"{template_id.replace('/', '--')}.hptemplate", buffer.getvalue()

    def export_to_workspace(self, template_id: str, workspace: str) -> dict[str, Any]:
        name, data = self.export(template_id)
        target = Path(self.workspace_dir(workspace)) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"file": name, "bytes": len(data), "sha256": _sha(data), "url": gallery_url(workspace, name)}

    def read_package(self, data: bytes) -> dict[str, Any]:
        """Parse and validate a package (zip) or a legacy ``*.world3d.template.json``."""
        if data[:1] in (b"{", b" ", b"\n") and len(data) <= 2 * 1024 * 1024:
            return self._legacy(data)
        if len(data) > MAX_ZIP_BYTES or not zipfile.is_zipfile(io.BytesIO(data)):
            raise TemplateError("Expected a .hptemplate file (zip) up to 64 MB", code="invalid_package")
        members = self._members(data)
        manifest_raw = self._json(members.pop(MANIFEST, None), MANIFEST)
        document = self._json(members.pop(DOCUMENT, None), DOCUMENT)
        manifest = normalize_manifest(manifest_raw, document)
        files, issues = self._package_files(manifest_raw, document, members)
        manifest.update(self._media_manifest(files))
        return {"manifest": manifest, "document": document, "files": files, "issues": issues, "sha256": _sha(data)}

    def _members(self, data: bytes) -> dict[str, bytes]:
        members: dict[str, bytes] = {}
        total = 0
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > MAX_MEDIA + 3:
                raise TemplateError("Too many files in the package", code="invalid_package")
            for info in infos:
                try:
                    name = safe_zip_member(info.filename)
                    if zipinfo_is_symlink(info):
                        raise TemplateError("Symlinks are not allowed", code="unsafe_package")
                    total += info.file_size
                    if total > MAX_TOTAL_BYTES:
                        raise TemplateError("Package is too large once unpacked", code="invalid_package")
                    members[name] = _read_zip_member(archive, info, MAX_MEMBER_BYTES)
                except ScenePackageError as exc:
                    raise TemplateError(str(exc), code="unsafe_package") from exc
        return members

    @staticmethod
    def _json(data: bytes | None, name: str) -> Any:
        if data is None:
            raise TemplateError(f"{name} is missing", code="invalid_package")
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TemplateError(f"{name} is not valid JSON", code="invalid_package") from exc

    @staticmethod
    def _package_files(manifest_raw: dict, document: dict, members: dict[str, bytes]) -> tuple[dict[str, bytes], list[dict]]:
        files: dict[str, bytes] = {}
        issues: list[dict[str, str]] = []
        for name, data in members.items():
            match = MEDIA_REF_RE.fullmatch(name)
            if match and media_kind(name) and _sha(data) == match.group(1):
                files[name] = data
            elif name.startswith("preview") and Path(name).suffix in PREVIEW_EXT and len(data) <= MAX_PREVIEW_BYTES:
                files[name] = data
            else:
                issues.append({"code": "ignored_member", "message": f"Ignored {name}"})
        editor = manifest_raw.get("editor")
        referenced = {container.get(key) for container, key in media_refs(editor, document)
                      if isinstance(container.get(key), str) and MEDIA_REF_RE.fullmatch(container.get(key))}
        missing = sorted(ref for ref in referenced if ref not in files)
        if missing:
            raise TemplateError(f"The package references media it does not contain: {', '.join(missing)[:400]}",
                                code="missing_media")
        return files, issues

    def _legacy(self, data: bytes) -> dict[str, Any]:
        raw = self._json(data, "template")
        if not isinstance(raw, dict) or raw.get("kind") != LEGACY_WORLD3D_KIND or not isinstance(raw.get("document"), dict):
            raise TemplateError("Not a .hptemplate or a Video 3D *.world3d.template.json", code="invalid_package")
        document = raw["document"]
        for slot in document.get("slots") or []:
            if isinstance(slot, dict) and classify_url(str(slot.get("sourceUrl") or "")) in {"gallery", "uploads", "relative"}:
                slot.update({"sourceUrl": "", "clip": None})
                slot.pop("sourceRef", None)
        document.pop("soundtrack", None)
        title = str(raw.get("title") or "Imported scenario")
        manifest = normalize_manifest({"kind": KIND, "version": 1, "editor": "video3d", "title": title,
                                       "description": raw.get("description") or "", "id": f"local/{slugify(title)}",
                                       "createdAt": raw.get("createdAt") or _now(), "updatedAt": _now()}, document)
        return {"manifest": {**manifest, "media": []}, "document": document, "files": {}, "sha256": _sha(data),
                "issues": [{"code": "legacy", "message": "Converted from a Video 3D scenario template; media were not included"}]}

    def preflight(self, data: bytes) -> dict[str, Any]:
        try:
            package = self.read_package(data)
        except TemplateError as error:
            return {"canImport": False, "error": {"code": error.code, "message": str(error)}}
        manifest = package["manifest"]
        exists = (self._folder(manifest["id"]) / MANIFEST).exists()
        return {"canImport": True, "exists": exists, "sha256": package["sha256"], "issues": package["issues"],
                "template": {key: manifest.get(key) for key in ("id", "editor", "title", "description", "tags", "author",
                                                                  "license", "templateVersion", "requires", "slots", "controls")},
                "media": [{"path": item["path"], "type": item["type"], "bytes": item["bytes"]} for item in manifest.get("media", [])],
                "slotTargets": sorted(targets_of(manifest["editor"], package["document"]))}

    def import_package(self, data: bytes, *, replace: bool = False, source: str = "imported") -> dict[str, Any]:
        package = self.read_package(data)
        manifest = package["manifest"]
        manifest["updatedAt"] = _now()
        origin = {"source": source if source in SOURCES else "imported", "importedAt": manifest["updatedAt"], "sha256": package["sha256"]}
        return self._write(manifest, package["document"], package["files"], origin, replace=replace, expected_updated_at=None)

    def import_from_workspace(self, workspace: str, file: str, *, replace: bool = False) -> dict[str, Any]:
        data = self.reader(workspace, Path(file).name)
        if data is None:
            raise TemplateError("File not found in the workspace", status=404, code="not_found")
        return self.import_package(data, replace=replace)

    def delete(self, template_id: str) -> dict[str, Any]:
        folder, _, _ = self._read(template_id)
        shutil.rmtree(folder)
        try:
            folder.parent.rmdir()
        except OSError:
            pass
        return {"deleted": template_id}


__all__ = ["TemplateLibrary", "resolve_template_library_root", "LIBRARY_DIR_ENV"]

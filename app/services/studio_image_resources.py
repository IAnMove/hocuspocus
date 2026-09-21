"""Resolve Studio command inputs using the existing media and LoRA locations.

This is read-only preparation. It neither installs models nor publishes assets.
Canonical URLs retain the source workspace even when output uses another one.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import re
import shutil
import uuid
from urllib.parse import parse_qs, quote, unquote, urlsplit

from services.wangp_submission import resolve_wangp_media, wangp_media_url


IMAGE_FIELDS = ("image_refs", "image_start", "image_end", "image_guide", "image_mask")


def file_identity(path):
    source = Path(path)
    before = source.stat()
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("A selected resource changed while being inspected; select it again")
    return {"sha256": digest.hexdigest(), "size_bytes": after.st_size}


class StudioImageResources:
    media_kind = "image"

    def __init__(self, *, workspace_dir, uploads_dir, list_workspaces,
                 lora_search_dirs, lora_compatible):
        self.workspace_dir = workspace_dir
        self.uploads_dir = uploads_dir
        self.list_workspaces = list_workspaces
        self.lora_search_dirs = lora_search_dirs
        self.lora_compatible = lora_compatible

    def _workspace_names(self):
        return {item["name"] for item in self.list_workspaces() if isinstance(item, dict)
                and isinstance(item.get("name"), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", item["name"])}

    def _source_workspace(self, path):
        roots = [(name, Path(self.workspace_dir(name)).resolve()) for name in self._workspace_names()]
        # The default output directory contains the named workspace folders.
        # Prefer the most specific root instead of relabelling a nested source.
        roots.sort(key=lambda item: len(item[1].parts), reverse=True)
        return next(((name, root) for name, root in roots if path.is_relative_to(root)), None)

    def _media(self, value):
        if value.startswith(("asset_", "asset:", "asset-")):
            return self._media(self._asset_url(value))
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise ValueError("Choose an exact local media URL from the asset catalog")
        if parsed.path.startswith("/api/v1/assets/"):
            if parsed.query:
                raise ValueError("Asset references cannot override their source location")
            return self._media(self._asset_url(unquote(parsed.path[len("/api/v1/assets/"):])))
        workspace, source_workspace = self._url_workspace(parsed)
        path = resolve_wangp_media(value, workspace, uploads_dir=self.uploads_dir(),
                                  workspace_dir=self.workspace_dir(workspace))
        if source_workspace != "__uploads__":
            actual = self._source_workspace(Path(path).resolve())
            if actual is None or actual[0] != source_workspace:
                raise ValueError("The reference must name its actual source workspace")
        return path, source_workspace

    def _url_workspace(self, parsed):
        """Resolve the explicit source root before any file lookup."""
        if parsed.path.startswith("/api/v1/uploads/"):
            if parsed.query:
                raise ValueError("Upload references cannot override their source location")
            return "default", "__uploads__"
        if parsed.path.startswith("/api/v1/file/"):
            query = parse_qs(parsed.query, keep_blank_values=True)
            if set(query) != {"workspace"} or len(query["workspace"]) != 1:
                raise ValueError("File references require one explicit source workspace")
            workspace = query["workspace"][0]
            if workspace not in self._workspace_names():
                raise ValueError("The reference source workspace is not available")
            return workspace, workspace
        raise ValueError("Choose a canonical upload or workspace file URL")

    def _asset_url(self, identity):
        from services.asset_catalog import find_asset
        roots = [{"workspace_id": name, "path": self.workspace_dir(name)} for name in self._workspace_names()]
        roots.append({"workspace_id": "__uploads__", "path": self.uploads_dir()})
        asset = find_asset(roots, identity)
        if not asset or asset.get("kind") != self.media_kind:
            raise ValueError(f"Choose an existing {self.media_kind} asset ID")
        locations = asset.get("locations") or []
        if len(locations) != 1:
            raise ValueError("This asset has multiple locations; choose an exact source URL")
        location = locations[0]
        filename = quote(location["filename"], safe="")
        if location["workspace_id"] == "__uploads__":
            return f"/api/v1/uploads/{filename}"
        return f"/api/v1/file/{filename}?workspace={quote(location['workspace_id'], safe='')}"

    def canonicalize_legacy(self, value):
        """Convert an exact legacy path, without matching basenames elsewhere."""
        text = str(value).strip()
        if text.startswith(("blob:", "data:", "local-edit:")):
            raise ValueError("Upload the image in this tab before generating")
        if text.startswith(("http://", "https://")):
            parsed = urlsplit(text)
            text = parsed.path + (("?" + parsed.query) if parsed.query else "")
        text = self._coerce_gallery_url(text)
        if text.startswith(("/api/v1/", "asset_", "asset:", "asset-")):
            self._media(text)
            return text
        source = Path(text)
        relative = not source.is_absolute()
        if relative:
            source = self._resolve_relative_media(text)
        if not source.is_file():
            raise ValueError("A legacy reference must be an exact existing local path")
        resolved = source.resolve()
        uploads = Path(self.uploads_dir()).resolve()
        if resolved.is_relative_to(uploads):
            return wangp_media_url(resolved, "default", uploads_dir=uploads,
                                   workspace_dir=self.workspace_dir("default"))
        located = self._source_workspace(resolved)
        if located:
            workspace, root = located
            return wangp_media_url(resolved, workspace, uploads_dir=uploads, workspace_dir=root)
        if relative:
            return self._adopt_into_uploads(resolved, uploads)
        raise ValueError("The legacy reference is outside known media locations")

    def _local_media_roots(self, uploads: Path | None = None) -> list[Path]:
        """Roots that may supply a leftover relative file such as .pinokio-temp/*.

        cwd.parent is included only when it is not the filesystem root. A process
        started from /workspace or /app would otherwise treat / as a media root
        and copy any readable file into uploads.
        """
        cwd = Path.cwd().resolve()
        roots = []
        if uploads is not None:
            roots.append(Path(uploads).resolve())
        roots.append(cwd)
        parent = cwd.parent.resolve()
        if parent != cwd and len(parent.parts) > 1:
            roots.append(parent)
        return roots

    def _coerce_gallery_url(self, text: str) -> str:
        """Map gallery/output URLs onto the canonical file/upload forms `_media` accepts."""
        parsed = urlsplit(text)
        path = unquote(parsed.path)
        if path.startswith("/api/v1/outputs/thumbnail/"):
            name = path[len("/api/v1/outputs/thumbnail/"):].lstrip("/")
            path = "/api/v1/file/" + name
        elif path.startswith("/api/v1/outputs/"):
            rest = path[len("/api/v1/outputs/"):].lstrip("/")
            if rest and "/" not in rest.split("?")[0]:
                path = "/api/v1/file/" + rest
        if path.startswith("/api/v1/file/"):
            name = path[len("/api/v1/file/"):]
            query = parse_qs(parsed.query, keep_blank_values=True)
            workspace = (query.get("workspace") or ["default"])[0] or "default"
            if workspace not in self._workspace_names():
                workspace = "default"
            return f"/api/v1/file/{quote(name, safe='')}?workspace={quote(workspace, safe='')}"
        if path.startswith("/api/v1/uploads/"):
            name = path[len("/api/v1/uploads/"):]
            return f"/api/v1/uploads/{quote(name, safe='/')}"
        return text

    def _resolve_relative_media(self, value: str) -> Path:
        normalized = value.replace("\\", "/")
        if normalized.startswith("../") or "/../" in f"/{normalized}/" or normalized in {".", ".."}:
            raise ValueError("A legacy reference must be an exact existing local path")
        if "/" not in normalized:
            matches = []
            uploads = Path(self.uploads_dir()).resolve()
            candidate = uploads / normalized
            if candidate.is_file():
                matches.append(candidate)
            for name in self._workspace_names():
                candidate = Path(self.workspace_dir(name)).resolve() / normalized
                if candidate.is_file():
                    matches.append(candidate)
            if len(matches) == 1:
                return matches[0]
            raise ValueError("A legacy reference must be an exact existing local path")
        for root in self._local_media_roots():
            candidate = (root / value).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.is_file():
                return candidate
        raise ValueError("A legacy reference must be an exact existing local path")

    def _adopt_into_uploads(self, resolved: Path, uploads: Path) -> str:
        allowed = self._local_media_roots(uploads)
        if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
            raise ValueError("The legacy reference is outside known media locations")
        dest = uploads / f"{uuid.uuid4().hex}{resolved.suffix.lower() or '.png'}"
        shutil.copy2(resolved, dest)
        return wangp_media_url(
            dest, "default", uploads_dir=uploads, workspace_dir=self.workspace_dir("default"),
        )

    def prepare_media(self, params):
        working = deepcopy(params)
        resources = []
        for field in IMAGE_FIELDS:
            raw = working.get(field)
            if not raw:
                continue
            values = raw if isinstance(raw, list) else [raw]
            paths = []
            for index, value in enumerate(values):
                if value == "":
                    # Native per-prompt optional frame lists retain empty
                    # positions. An empty slot is not a selected resource.
                    paths.append("")
                    continue
                path, workspace = self._media(value)
                identity = file_identity(path)
                from PIL import Image
                with Image.open(path) as picture:
                    picture.verify()
                resources.append({"role": field, "index": index, "url": value,
                                  "workspace": workspace, **identity})
                paths.append(path)
            working[field] = paths if isinstance(raw, list) else paths[0]
        # Resolution has already happened against each explicit source root;
        # native fallback must not reinterpret those URLs in the output folder.
        working.pop("canonical_image_refs", None)
        return working, resources

    def prepare_loras(self, params, model_definition):
        resources = []
        if not params.get("activated_loras"):
            return resources
        roots = self.lora_search_dirs(params["model_type"])
        for name in params.get("activated_loras") or []:
            if Path(name).name != name or "/" in name or "\\" in name:
                raise ValueError("Choose an exact LoRA name from this model's catalog")
            matches = _lora_candidates(roots, name)
            if len(matches) != 1:
                raise ValueError("A selected LoRA is missing or ambiguous in the model's search locations")
            path = matches.pop()
            if not self.lora_compatible(model_definition, path):
                raise ValueError("A selected LoRA is incompatible with the selected model")
            resources.append({"role": "lora", "name": name, **file_identity(path)})
        return resources


def _lora_candidates(roots, name):
    matches = set()
    for directory in roots:
        root = Path(directory).resolve()
        candidate = root / name
        if candidate.is_file():
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError("A selected LoRA points outside its model's search location")
            matches.add(str(resolved))
    return matches


def validate_lora_multipliers(params, maximum_phases):
    from shared.utils.loras_mutipliers import parse_loras_multipliers, preparse_loras_multipliers
    names = params.get("activated_loras") or []
    text = params.get("loras_multipliers") or ""
    multipliers = preparse_loras_multipliers(text) if text else []
    if len(multipliers) > len(names):
        raise ValueError("LoRA multiplier count exceeds the selected LoRA count")
    for multiplier in multipliers:
        for phase in multiplier.split(";"):
            for part in phase.split(","):
                if not math.isfinite(float(part)):
                    raise ValueError("LoRA multipliers must be finite numbers")
    _, _, error = parse_loras_multipliers(text, len(names), params["num_inference_steps"],
                                          nb_phases=maximum_phases,
                                          model_switch_phase=params.get("model_switch_phase", 1))
    if error:
        raise ValueError(error)

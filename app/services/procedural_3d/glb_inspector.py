"""CPU-only GLB animation inspector.

Reads a local GLB path or byte string, reports clips/meshes/skins/materials,
and refuses external buffer or image URIs. This is an internal helper: a path
argument is not permission to expose arbitrary filesystem access over HTTP.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from services.procedural_3d.glb_container import ContainerError, parse_glb_container

SCHEMA_VERSION = "glb-inspection-v1"
InspectionStatus = Literal["valid", "unsupported", "corrupt"]
DurationStatus = Literal["verified", "unknown", "invalid"]
IssueSeverity = Literal["error", "warning"]

_STATUS_RANK = {"valid": 0, "unsupported": 1, "corrupt": 2}
_FLOAT_COMPONENT = 5126
_COMPONENT_BYTES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_TYPE_COUNTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}
_KNOWN_TARGET_PATHS = {"translation", "rotation", "scale", "weights"}
_KNOWN_INTERPOLATIONS = {"LINEAR", "STEP", "CUBICSPLINE"}
_BLOCKED_URI_KINDS = frozenset({"http", "file", "relative", "other_scheme"})


class _TimeReadError(Exception):
    def __init__(
        self,
        duration: DurationStatus,
        code: str | None,
        inspection: InspectionStatus | None = None,
    ) -> None:
        self.duration = duration
        self.code = code
        self.inspection = inspection


@dataclass(frozen=True)
class GlbInspectorLimits:
    max_file_bytes: int = 64 * 1024 * 1024
    max_json_bytes: int = 4 * 1024 * 1024
    max_chunks: int = 8
    max_json_items: int = 200_000
    max_accessors: int = 20_000
    max_animations: int = 4_096
    max_channels_per_animation: int = 16_384
    max_reported_channels: int = 512
    max_time_samples: int = 1_000_000
    max_accessor_bytes: int = 32 * 1024 * 1024
    max_data_uri_bytes: int = 8 * 1024 * 1024
    max_named_resources: int = 50_000


@dataclass(frozen=True)
class InspectorIssue:
    code: str
    severity: IssueSeverity
    message: str
    path: str | None = None


@dataclass(frozen=True)
class NamedResource:
    index: int
    name: str


@dataclass(frozen=True)
class MeshReport:
    index: int
    name: str
    primitive_count: int
    attributes: tuple[str, ...]
    morph_target_count: int
    has_joints: bool
    has_weights: bool
    triangle_count: int | None = None


@dataclass(frozen=True)
class SkinReport:
    index: int
    name: str
    joint_count: int
    skeleton: int | None


@dataclass(frozen=True)
class BufferReport:
    index: int
    byte_length: int | None
    uri_kind: str
    blocked: bool


@dataclass(frozen=True)
class AnimationChannelReport:
    index: int
    sampler: int | None
    target_node: int | None
    target_path: str
    interpolation: str


@dataclass(frozen=True)
class AnimationClipReport:
    index: int
    name: str
    channel_count: int
    sampler_count: int
    interpolations: tuple[str, ...]
    target_paths: tuple[str, ...]
    target_node_indices: tuple[int, ...]
    channels: tuple[AnimationChannelReport, ...]
    duration_seconds: float | None
    duration_status: DurationStatus
    name_collision: bool


@dataclass
class GlbInspectionReport:
    schema_version: str = SCHEMA_VERSION
    status: InspectionStatus = "corrupt"
    file_size_bytes: int = 0
    sha256: str | None = None
    gltf_version: str | None = None
    min_version: str | None = None
    generator: str | None = None
    chunk_count: int = 0
    has_bin_chunk: bool = False
    meshes: list[MeshReport] = field(default_factory=list)
    nodes: list[NamedResource] = field(default_factory=list)
    skins: list[SkinReport] = field(default_factory=list)
    materials: list[NamedResource] = field(default_factory=list)
    animations: list[AnimationClipReport] = field(default_factory=list)
    buffers: list[BufferReport] = field(default_factory=list)
    extensions_used: list[str] = field(default_factory=list)
    extensions_required: list[str] = field(default_factory=list)
    issues: list[InspectorIssue] = field(default_factory=list)
    total_triangles: int | None = None


def report_to_dict(report: GlbInspectionReport) -> dict[str, Any]:
    return asdict(report)


def inspect_glb(
    path: str | Path,
    *,
    limits: GlbInspectorLimits | None = None,
) -> GlbInspectionReport:
    """Inspect a local GLB. The path is an internal argument, not an HTTP API."""
    chosen = Path(path)
    limits = limits or GlbInspectorLimits()
    if not chosen.exists():
        raise FileNotFoundError(str(chosen))
    if chosen.is_dir():
        raise IsADirectoryError(str(chosen))
    size = chosen.stat().st_size
    if size > limits.max_file_bytes:
        return _empty_report(
            status="unsupported",
            file_size_bytes=size,
            sha256=None,
            issues=[
                InspectorIssue(
                    code="file_too_large",
                    severity="error",
                    message=(
                        f"file is {size} bytes; limit is {limits.max_file_bytes}"
                    ),
                )
            ],
        )
    data = chosen.read_bytes()
    return inspect_glb_bytes(data, limits=limits)


def inspect_glb_bytes(
    data: bytes,
    *,
    limits: GlbInspectorLimits | None = None,
) -> GlbInspectionReport:
    limits = limits or GlbInspectorLimits()
    digest = hashlib.sha256(data).hexdigest()
    size = len(data)
    if size > limits.max_file_bytes:
        return _empty_report(
            status="unsupported",
            file_size_bytes=size,
            sha256=digest,
            issues=[
                InspectorIssue(
                    code="file_too_large",
                    severity="error",
                    message=(
                        f"payload is {size} bytes; limit is {limits.max_file_bytes}"
                    ),
                )
            ],
        )
    if size >= 1 and data[:1] == b"{":
        return _empty_report(
            status="unsupported",
            file_size_bytes=size,
            sha256=digest,
            issues=[
                InspectorIssue(
                    code="gltf_json_not_glb",
                    severity="error",
                    message="JSON glTF (.gltf) is not inspected; supply a GLB",
                )
            ],
        )
    try:
        container = parse_glb_container(
            data,
            max_chunks=limits.max_chunks,
            max_json_bytes=limits.max_json_bytes,
        )
    except ContainerError as exc:
        return _empty_report(
            status="corrupt",
            file_size_bytes=size,
            sha256=digest,
            issues=[
                InspectorIssue(
                    code=str(exc),
                    severity="error",
                    message=_container_message(str(exc)),
                )
            ],
        )
    inspector = _Inspector(limits=limits, file_size=size, digest=digest)
    inspector.chunk_count = len(container.chunks)
    inspector.has_bin_chunk = container.bin_bytes is not None
    for code, message in container.issues:
        severity: IssueSeverity = "warning"
        status: InspectionStatus = "valid"
        if code == "unsupported_glb_version":
            severity = "error"
            status = "unsupported"
        inspector.add_issue(code, severity, message)
        inspector.degrade(status)
    inspector.inspect_document(container.json_bytes or b"", container.bin_bytes)
    return inspector.build()


def _empty_report(
    *,
    status: InspectionStatus,
    file_size_bytes: int,
    sha256: str | None,
    issues: list[InspectorIssue],
) -> GlbInspectionReport:
    return GlbInspectionReport(
        status=status,
        file_size_bytes=file_size_bytes,
        sha256=sha256,
        issues=issues,
    )


def _container_message(code: str) -> str:
    messages = {
        "truncated_header": "GLB header is shorter than 12 bytes",
        "invalid_magic": "file is not a GLB (magic mismatch)",
        "truncated_file": "file is shorter than the declared GLB length",
        "invalid_declared_length": "GLB header length is smaller than the header",
        "too_many_chunks": "GLB has more chunks than the inspector limit",
        "truncated_chunk_header": "GLB chunk header is truncated",
        "invalid_chunk_length": "GLB chunk length is invalid",
        "truncated_chunk": "GLB chunk payload is truncated",
        "unaligned_chunk_length": "GLB chunk length is not a multiple of 4",
        "json_too_large": "JSON chunk exceeds the inspector limit",
        "json_chunk_not_first": "the first GLB chunk is not JSON",
        "duplicate_json_chunk": "GLB contains more than one JSON chunk",
        "duplicate_bin_chunk": "GLB contains more than one BIN chunk",
        "missing_json_chunk": "GLB has no JSON chunk",
        "chunk_offset_overflow": "GLB chunk offset overflowed",
    }
    return messages.get(code, code)


def classify_uri(uri: object | None) -> str:
    """Classify a glTF URI without decoding, resolving, or fetching it."""
    if uri is None:
        return "embedded_bin"
    if not isinstance(uri, str):
        return "invalid"
    stripped = uri.strip()
    if stripped == "":
        return "relative"
    lower = stripped.lower()
    if lower.startswith("data:"):
        return "data_uri"
    if lower.startswith("http://") or lower.startswith("https://"):
        return "http"
    if lower.startswith("file:"):
        return "file"
    if "://" in stripped:
        return "other_scheme"
    return "relative"


def _reject_json_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON number {token!r}")


def _count_json_items(value: object, remaining: int) -> int:
    stack = [value]
    while stack:
        if remaining <= 0:
            raise ValueError("json_too_many_items")
        remaining -= 1
        current = stack.pop()
        if isinstance(current, dict):
            stack.extend(current.keys())
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return remaining


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_nonneg_int(value: object, *, maximum: int) -> int | None:
    number = _as_int(value)
    if number is None or number < 0 or number > maximum:
        return None
    return number


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _exact_name(item: object) -> str:
    if not isinstance(item, dict):
        return ""
    name = item.get("name")
    if name is None:
        return ""
    if isinstance(name, str):
        return name
    return ""


class _Inspector:
    def __init__(self, *, limits: GlbInspectorLimits, file_size: int, digest: str) -> None:
        self.limits = limits
        self.file_size = file_size
        self.digest = digest
        self.status: InspectionStatus = "valid"
        self.issues: list[InspectorIssue] = []
        self.chunk_count = 0
        self.has_bin_chunk = False
        self.gltf_version: str | None = None
        self.min_version: str | None = None
        self.generator: str | None = None
        self.meshes: list[MeshReport] = []
        self.nodes: list[NamedResource] = []
        self.skins: list[SkinReport] = []
        self.materials: list[NamedResource] = []
        self.animations: list[AnimationClipReport] = []
        self.buffers: list[BufferReport] = []
        self.extensions_used: list[str] = []
        self.extensions_required: list[str] = []
        self.accessor_bytes_used = 0
        self._duration_reads = True
        self._payloads: list[bytes | None] = []
        self._accessors: list[Any] = []
        self._buffer_views: list[Any] = []

    def degrade(self, status: InspectionStatus) -> None:
        if _STATUS_RANK[status] > _STATUS_RANK[self.status]:
            self.status = status

    def add_issue(
        self,
        code: str,
        severity: IssueSeverity,
        message: str,
        path: str | None = None,
    ) -> None:
        self.issues.append(
            InspectorIssue(code=code, severity=severity, message=message, path=path)
        )

    def inspect_document(self, json_bytes: bytes, bin_bytes: bytes | None) -> None:
        try:
            raw_text = json_bytes.decode("utf-8")
        except UnicodeDecodeError:
            self.add_issue("invalid_json_utf8", "error", "JSON chunk is not valid UTF-8")
            self.degrade("corrupt")
            return
        try:
            document = json.loads(raw_text, parse_constant=_reject_json_constant)
            _count_json_items(document, self.limits.max_json_items)
        except RecursionError:
            self.add_issue("json_too_deep", "error", "JSON chunk exceeded the decoder nesting limit")
            self.degrade("corrupt")
            return
        except MemoryError:
            self.add_issue("json_too_large", "error", "JSON chunk exceeded available memory")
            self.degrade("unsupported")
            return
        except ValueError as exc:
            code = "json_too_many_items" if str(exc) == "json_too_many_items" else "invalid_json"
            if code == "json_too_many_items":
                self.add_issue(code, "error", "glTF JSON exceeds the inspector item limit")
                self.degrade("unsupported")
            else:
                self.add_issue(code, "error", f"JSON chunk is not valid: {exc}")
                self.degrade("corrupt")
            return
        if not isinstance(document, dict):
            self.add_issue("gltf_root_not_object", "error", "glTF JSON root is not an object")
            self.degrade("corrupt")
            return
        self._inspect_asset(document)
        self._inspect_extensions(document)
        self._resolve_buffers(document, bin_bytes)
        self._buffer_views = document.get("bufferViews") if isinstance(document.get("bufferViews"), list) else []
        self._accessors = document.get("accessors") if isinstance(document.get("accessors"), list) else []
        if len(self._accessors) > self.limits.max_accessors:
            self.add_issue(
                "too_many_accessors",
                "error",
                f"accessor count {len(self._accessors)} exceeds the inspector limit",
            )
            self.degrade("unsupported")
            self._duration_reads = False
        self._inspect_resources(document)
        self._inspect_images(document)
        self._inspect_animations(document)

    def _inspect_asset(self, document: dict[str, Any]) -> None:
        asset = document.get("asset")
        if not isinstance(asset, dict):
            self.add_issue("missing_asset", "error", "glTF asset object is missing")
            self.degrade("corrupt")
            return
        version = _as_str(asset.get("version"))
        self.gltf_version = version
        self.min_version = _as_str(asset.get("minVersion"))
        self.generator = _as_str(asset.get("generator"))
        if version is None:
            self.add_issue("missing_gltf_version", "error", "asset.version is missing")
            self.degrade("corrupt")
            return
        if not version.startswith("2."):
            self.add_issue(
                "unsupported_gltf_version",
                "error",
                f"glTF asset version {version!r} is not 2.x",
                path="asset/version",
            )
            self.degrade("unsupported")

    def _inspect_extensions(self, document: dict[str, Any]) -> None:
        used = document.get("extensionsUsed")
        required = document.get("extensionsRequired")
        self.extensions_used = _string_list(used)
        self.extensions_required = _string_list(required)
        if used is not None and not isinstance(used, list):
            self.add_issue("extensions_used_not_array", "warning", "extensionsUsed is not an array")
        if required is not None and not isinstance(required, list):
            self.add_issue(
                "extensions_required_not_array",
                "error",
                "extensionsRequired is not an array",
            )
            self.degrade("corrupt")
        if self.extensions_required:
            self.add_issue(
                "required_extensions",
                "error",
                "required glTF extensions are present; playback may be incompatible",
                path="extensionsRequired",
            )
            self.degrade("unsupported")

    def _resolve_buffers(self, document: dict[str, Any], bin_bytes: bytes | None) -> None:
        raw = document.get("buffers")
        if raw is None:
            self._payloads = []
            return
        if not isinstance(raw, list):
            self.add_issue("buffers_not_array", "error", "buffers is not an array")
            self.degrade("corrupt")
            self._payloads = []
            return
        if len(raw) > self.limits.max_named_resources:
            self.add_issue("too_many_buffers", "error", "buffer count exceeds the inspector limit")
            self.degrade("unsupported")
            self._duration_reads = False
            self._payloads = []
            return
        payloads: list[bytes | None] = []
        for index, item in enumerate(raw):
            payload, report = self._resolve_one_buffer(index, item, bin_bytes)
            payloads.append(payload)
            self.buffers.append(report)
        self._payloads = payloads

    def _resolve_one_buffer(
        self,
        index: int,
        item: object,
        bin_bytes: bytes | None,
    ) -> tuple[bytes | None, BufferReport]:
        path = f"buffers/{index}"
        if not isinstance(item, dict):
            self.add_issue("buffer_not_object", "error", "buffer entry is not an object", path)
            self.degrade("corrupt")
            return None, BufferReport(index=index, byte_length=None, uri_kind="invalid", blocked=True)
        byte_length = _as_nonneg_int(item.get("byteLength"), maximum=self.limits.max_file_bytes)
        if byte_length is None:
            self.add_issue("invalid_buffer_byte_length", "error", "buffer.byteLength is invalid", path)
            self.degrade("corrupt")
            return None, BufferReport(index=index, byte_length=None, uri_kind="invalid", blocked=True)
        uri = item.get("uri")
        kind = classify_uri(uri)
        if kind == "invalid":
            self.add_issue("invalid_buffer_uri_type", "error", "buffer.uri is not a string", path)
            self.degrade("corrupt")
            return None, BufferReport(index=index, byte_length=byte_length, uri_kind=kind, blocked=True)
        if kind in _BLOCKED_URI_KINDS:
            self.add_issue(
                "external_buffer_blocked",
                "error",
                f"refused to open external buffer URI of kind {kind}",
                path,
            )
            self.degrade("unsupported")
            return None, BufferReport(index=index, byte_length=byte_length, uri_kind=kind, blocked=True)
        if kind == "data_uri":
            payload = self._clip_buffer_payload(
                self._decode_data_uri(str(uri), path),
                byte_length,
                path,
            )
            return payload, BufferReport(
                index=index,
                byte_length=byte_length,
                uri_kind=kind,
                blocked=payload is None,
            )
        if index != 0:
            self.add_issue(
                "buffer_missing_uri",
                "error",
                "only buffer 0 may omit uri and use the GLB BIN chunk",
                path,
            )
            self.degrade("corrupt")
            return None, BufferReport(index=index, byte_length=byte_length, uri_kind=kind, blocked=True)
        if bin_bytes is None:
            self.add_issue("missing_bin_chunk", "error", "buffer has no URI and no BIN chunk", path)
            self.degrade("corrupt")
            return None, BufferReport(index=index, byte_length=byte_length, uri_kind=kind, blocked=True)
        payload = self._clip_buffer_payload(bin_bytes, byte_length, path)
        return payload, BufferReport(
            index=index,
            byte_length=byte_length,
            uri_kind=kind,
            blocked=payload is None,
        )

    def _clip_buffer_payload(
        self,
        payload: bytes | None,
        byte_length: int | None,
        path: str,
    ) -> bytes | None:
        if payload is None:
            return None
        if byte_length is None:
            return payload
        if byte_length > len(payload):
            self.add_issue(
                "buffer_shorter_than_byte_length",
                "error",
                "buffer payload is shorter than byteLength",
                path,
            )
            self.degrade("corrupt")
            return None
        return payload[:byte_length]

    def _decode_data_uri(self, uri: str, path: str) -> bytes | None:
        comma = uri.find(",")
        if comma < 0:
            self.add_issue("invalid_data_uri", "error", "data URI has no payload comma", path)
            self.degrade("corrupt")
            return None
        metadata = uri[:comma]
        payload = uri[comma + 1 :]
        if ";base64" not in metadata.lower():
            self.add_issue(
                "unsupported_data_uri",
                "error",
                "only base64 data URIs are decoded",
                path,
            )
            self.degrade("unsupported")
            return None
        if len(payload) > self.limits.max_data_uri_bytes * 2:
            self.add_issue("data_uri_too_large", "error", "data URI exceeds the inspector limit", path)
            self.degrade("unsupported")
            return None
        try:
            decoded = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error) as exc:
            self.add_issue("invalid_data_uri", "error", f"data URI is not valid base64: {exc}", path)
            self.degrade("corrupt")
            return None
        if len(decoded) > self.limits.max_data_uri_bytes:
            self.add_issue("data_uri_too_large", "error", "decoded data URI exceeds the inspector limit", path)
            self.degrade("unsupported")
            return None
        return decoded

    def _inspect_resources(self, document: dict[str, Any]) -> None:
        self.nodes = self._named_resources(document.get("nodes"), "nodes")
        self.materials = self._named_resources(document.get("materials"), "materials")
        self.meshes = self._mesh_reports(document.get("meshes"))
        self.skins = self._skin_reports(document.get("skins"))

    def _named_resources(self, raw: object, field_name: str) -> list[NamedResource]:
        items = self._bounded_object_list(raw, field_name)
        result: list[NamedResource] = []
        for index, item in enumerate(items):
            name = _exact_name(item)
            if isinstance(item, dict) and "name" in item and not isinstance(item.get("name"), str):
                self.add_issue(
                    "name_not_string",
                    "warning",
                    f"{field_name}[{index}].name is not a string; stored as empty",
                    path=f"{field_name}/{index}/name",
                )
            result.append(NamedResource(index=index, name=name))
        return result

    def _mesh_reports(self, raw: object) -> list[MeshReport]:
        items = self._bounded_object_list(raw, "meshes")
        reports: list[MeshReport] = []
        for index, item in enumerate(items):
            primitives = item.get("primitives") if isinstance(item, dict) else None
            primitive_list = primitives if isinstance(primitives, list) else []
            attributes: set[str] = set()
            morphs = 0
            for primitive in primitive_list:
                if not isinstance(primitive, dict):
                    continue
                attrs = primitive.get("attributes")
                if isinstance(attrs, dict):
                    attributes.update(str(key) for key in attrs.keys())
                targets = primitive.get("targets")
                if isinstance(targets, list):
                    morphs = max(morphs, len(targets))
            reports.append(
                MeshReport(
                    index=index,
                    name=_exact_name(item),
                    primitive_count=len(primitive_list),
                    attributes=tuple(sorted(attributes)),
                    morph_target_count=morphs,
                    has_joints="JOINTS_0" in attributes,
                    has_weights="WEIGHTS_0" in attributes,
                    triangle_count=_mesh_triangles(self._accessors, primitive_list),
                )
            )
        return reports

    def _skin_reports(self, raw: object) -> list[SkinReport]:
        items = self._bounded_object_list(raw, "skins")
        reports: list[SkinReport] = []
        for index, item in enumerate(items):
            joints = item.get("joints") if isinstance(item, dict) else None
            joint_count = len(joints) if isinstance(joints, list) else 0
            skeleton = _as_int(item.get("skeleton")) if isinstance(item, dict) else None
            reports.append(
                SkinReport(
                    index=index,
                    name=_exact_name(item),
                    joint_count=joint_count,
                    skeleton=skeleton if skeleton is not None and skeleton >= 0 else None,
                )
            )
        return reports

    def _inspect_images(self, document: dict[str, Any]) -> None:
        raw = document.get("images")
        if raw is None:
            return
        items = self._bounded_object_list(raw, "images")
        for index, item in enumerate(items):
            if "uri" not in item:
                continue
            kind = classify_uri(item.get("uri"))
            if kind in _BLOCKED_URI_KINDS or kind == "invalid":
                self.add_issue(
                    "external_image_blocked",
                    "error",
                    f"refused to open external image URI of kind {kind}",
                    path=f"images/{index}/uri",
                )
                self.degrade("unsupported")

    def _inspect_animations(self, document: dict[str, Any]) -> None:
        raw = document.get("animations")
        if raw is None:
            return
        items = self._bounded_object_list(raw, "animations")
        if len(items) > self.limits.max_animations:
            self.add_issue(
                "too_many_animations",
                "error",
                f"animation count {len(items)} exceeds the inspector limit",
            )
            self.degrade("unsupported")
            return
        names = [_exact_name(item) for item in items]
        collisions = {name for name in names if name and names.count(name) > 1}
        empty_collision = names.count("") > 1
        reports: list[AnimationClipReport] = []
        for index, item in enumerate(items):
            reports.append(self._inspect_one_animation(index, item, collisions, empty_collision))
        self.animations = reports

    def _inspect_one_animation(
        self,
        index: int,
        item: dict[str, Any],
        collisions: set[str],
        empty_collision: bool,
    ) -> AnimationClipReport:
        path = f"animations/{index}"
        name = _exact_name(item)
        if "name" in item and not isinstance(item.get("name"), str):
            self.add_issue("name_not_string", "warning", "animation name is not a string", f"{path}/name")
        channels_raw = item.get("channels")
        samplers_raw = item.get("samplers")
        channels_list = channels_raw if isinstance(channels_raw, list) else []
        samplers_list = samplers_raw if isinstance(samplers_raw, list) else []
        if channels_raw is not None and not isinstance(channels_raw, list):
            self.add_issue("channels_not_array", "error", "animation.channels is not an array", path)
            self.degrade("corrupt")
        if samplers_raw is not None and not isinstance(samplers_raw, list):
            self.add_issue("samplers_not_array", "error", "animation.samplers is not an array", path)
            self.degrade("corrupt")
        channel_count = len(channels_list)
        if channel_count > self.limits.max_channels_per_animation:
            self.add_issue(
                "too_many_channels",
                "error",
                "animation channel count exceeds the inspector limit",
                path,
            )
            self.degrade("unsupported")
            channels_list = []
        channel_reports, interpolations, target_paths, target_nodes, durations = (
            self._collect_channels(path, channels_list, samplers_list)
        )
        duration_seconds, duration_status = _combine_durations(durations)
        if channel_count == 0:
            self.add_issue("empty_animation", "warning", "animation has no usable channels", path)
            duration_seconds, duration_status = None, "unknown"
        collision = (name in collisions) or (name == "" and empty_collision)
        return AnimationClipReport(
            index=index,
            name=name,
            channel_count=channel_count,
            sampler_count=len(samplers_list),
            interpolations=tuple(sorted(interpolations)),
            target_paths=tuple(sorted(target_paths)),
            target_node_indices=tuple(sorted(target_nodes)),
            channels=tuple(channel_reports[: self.limits.max_reported_channels]),
            duration_seconds=duration_seconds,
            duration_status=duration_status,
            name_collision=collision,
        )

    def _collect_channels(
        self,
        path: str,
        channels_list: list[Any],
        samplers_list: list[Any],
    ) -> tuple[
        list[AnimationChannelReport],
        set[str],
        set[str],
        set[int],
        list[tuple[float | None, DurationStatus]],
    ]:
        channel_reports: list[AnimationChannelReport] = []
        interpolations: set[str] = set()
        target_paths: set[str] = set()
        target_nodes: set[int] = set()
        durations: list[tuple[float | None, DurationStatus]] = []
        for channel_index, channel in enumerate(channels_list):
            report, interpolation, target_path, target_node, duration = self._inspect_channel(
                path, channel_index, channel, samplers_list
            )
            channel_reports.append(report)
            if interpolation:
                interpolations.add(interpolation)
            if target_path:
                target_paths.add(target_path)
            if target_node is not None:
                target_nodes.add(target_node)
            durations.append(duration)
        return channel_reports, interpolations, target_paths, target_nodes, durations

    def _inspect_channel(
        self,
        animation_path: str,
        channel_index: int,
        channel: object,
        samplers_list: list[Any],
    ) -> tuple[
        AnimationChannelReport,
        str,
        str,
        int | None,
        tuple[float | None, DurationStatus],
    ]:
        path = f"{animation_path}/channels/{channel_index}"
        if not isinstance(channel, dict):
            self.add_issue("channel_not_object", "error", "animation channel is not an object", path)
            self.degrade("corrupt")
            empty = AnimationChannelReport(
                index=channel_index,
                sampler=None,
                target_node=None,
                target_path="",
                interpolation="",
            )
            return empty, "", "", None, (None, "invalid")
        sampler_index = _as_int(channel.get("sampler"))
        target = channel.get("target") if isinstance(channel.get("target"), dict) else {}
        target_node = _as_int(target.get("node")) if isinstance(target, dict) else None
        target_path = _as_str(target.get("path")) if isinstance(target, dict) else None
        target_path = target_path or ""
        interpolation = ""
        duration: tuple[float | None, DurationStatus] = (None, "unknown")
        if target_path and target_path not in _KNOWN_TARGET_PATHS:
            self.add_issue(
                "unsupported_target_path",
                "warning",
                f"animation target path {target_path!r} is not a core glTF path",
                f"{path}/target/path",
            )
        if sampler_index is None or sampler_index < 0 or sampler_index >= len(samplers_list):
            self.add_issue("invalid_sampler_index", "error", "channel.sampler is out of range", path)
            self.degrade("corrupt")
        else:
            sampler = samplers_list[sampler_index]
            interpolation, duration = self._sampler_duration(path, sampler)
        report = AnimationChannelReport(
            index=channel_index,
            sampler=sampler_index,
            target_node=target_node,
            target_path=target_path,
            interpolation=interpolation,
        )
        return report, interpolation, target_path, target_node, duration

    def _sampler_duration(
        self,
        channel_path: str,
        sampler: object,
    ) -> tuple[str, tuple[float | None, DurationStatus]]:
        if not isinstance(sampler, dict):
            self.add_issue("sampler_not_object", "error", "animation sampler is not an object", channel_path)
            self.degrade("corrupt")
            return "", (None, "invalid")
        interpolation = _as_str(sampler.get("interpolation")) or "LINEAR"
        if interpolation not in _KNOWN_INTERPOLATIONS:
            self.add_issue(
                "unsupported_interpolation",
                "warning",
                f"interpolation {interpolation!r} is not LINEAR/STEP/CUBICSPLINE",
                f"{channel_path}/sampler",
            )
        input_index = _as_int(sampler.get("input"))
        if input_index is None:
            self.add_issue("missing_sampler_input", "error", "sampler.input is missing", channel_path)
            self.degrade("corrupt")
            return interpolation, (None, "invalid")
        times, status, note = self._read_time_accessor(input_index)
        if status != "verified":
            if note:
                self.add_issue(note, "error", _accessor_message(note), f"{channel_path}/sampler/input")
            return interpolation, (None, status)
        finite = [value for value in times if math.isfinite(value)]
        if times and len(finite) != len(times):
            self.add_issue(
                "non_finite_time",
                "error",
                "animation input contains NaN or Infinity; those samples are not times",
                f"{channel_path}/sampler/input",
            )
            self.degrade("corrupt")
            return interpolation, (None, "invalid")
        if not finite:
            return interpolation, (None, "invalid")
        if any(later < earlier for earlier, later in zip(finite, finite[1:])):
            self.add_issue(
                "non_monotonic_times",
                "warning",
                "animation input times are not non-decreasing",
                f"{channel_path}/sampler/input",
            )
        duration = float(max(finite))
        declared = self._declared_time_max(input_index)
        if declared is not None and not _same_time(declared, duration):
            self.add_issue(
                "accessor_minmax_mismatch",
                "warning",
                "accessor min/max do not match sampled times; duration uses sampled data",
                f"{channel_path}/sampler/input",
            )
        return interpolation, (duration, "verified")

    def _declared_time_max(self, accessor_index: int) -> float | None:
        if accessor_index < 0 or accessor_index >= len(self._accessors):
            return None
        accessor = self._accessors[accessor_index]
        if not isinstance(accessor, dict):
            return None
        maximum = accessor.get("max")
        if not isinstance(maximum, list) or not maximum:
            return None
        value = maximum[0]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        as_float = float(value)
        if not math.isfinite(as_float):
            return None
        return as_float

    def _read_time_accessor(
        self,
        accessor_index: int,
    ) -> tuple[list[float], DurationStatus, str | None]:
        if not self._duration_reads:
            return [], "unknown", None
        try:
            accessor, count = self._time_accessor_fields(accessor_index)
            payload, start, byte_stride = self._time_accessor_layout(accessor, count)
        except _TimeReadError as exc:
            if exc.inspection is not None:
                self.degrade(exc.inspection)
            return [], exc.duration, exc.code
        work = count * 4
        if self.accessor_bytes_used + work > self.limits.max_accessor_bytes:
            self.degrade("unsupported")
            return [], "unknown", "accessor_work_limit"
        self.accessor_bytes_used += work
        values = [
            struct.unpack_from("<f", payload, start + (index * byte_stride))[0]
            for index in range(count)
        ]
        return values, "verified", None

    def _time_accessor_fields(self, accessor_index: int) -> tuple[dict[str, Any], int]:
        if accessor_index < 0 or accessor_index >= len(self._accessors):
            raise _TimeReadError("invalid", "accessor_index_out_of_range", "corrupt")
        accessor = self._accessors[accessor_index]
        if not isinstance(accessor, dict):
            raise _TimeReadError("invalid", "accessor_not_object", "corrupt")
        if accessor.get("sparse") is not None:
            raise _TimeReadError("unknown", "sparse_time_accessor", "unsupported")
        count = _as_int(accessor.get("count"))
        if count is None or count < 0:
            raise _TimeReadError("invalid", "invalid_accessor_count", "corrupt")
        if count > self.limits.max_time_samples:
            raise _TimeReadError("unknown", "too_many_time_samples", "unsupported")
        if _as_int(accessor.get("componentType")) != _FLOAT_COMPONENT:
            raise _TimeReadError("invalid", "time_accessor_not_float", "corrupt")
        if (_as_str(accessor.get("type")) or "SCALAR") != "SCALAR":
            raise _TimeReadError("invalid", "time_accessor_not_scalar", "corrupt")
        if count == 0:
            raise _TimeReadError("invalid", "empty_time_accessor")
        return accessor, count

    def _time_accessor_layout(
        self,
        accessor: dict[str, Any],
        count: int,
    ) -> tuple[bytes, int, int]:
        view_index = accessor.get("bufferView")
        if view_index is None:
            raise _TimeReadError("unknown", "time_accessor_without_buffer_view", "unsupported")
        view_index = _as_int(view_index)
        if view_index is None or view_index < 0 or view_index >= len(self._buffer_views):
            raise _TimeReadError("invalid", "buffer_view_index_out_of_range", "corrupt")
        view = self._buffer_views[view_index]
        if not isinstance(view, dict):
            raise _TimeReadError("invalid", "buffer_view_not_object", "corrupt")
        buffer_index = _as_int(view.get("buffer"))
        if buffer_index is None or buffer_index < 0 or buffer_index >= len(self._payloads):
            raise _TimeReadError("invalid", "buffer_index_out_of_range", "corrupt")
        payload = self._payloads[buffer_index]
        if payload is None:
            raise _TimeReadError("unknown", None)
        view_offset = _as_nonneg_int(view.get("byteOffset") or 0, maximum=len(payload))
        accessor_offset = _as_nonneg_int(accessor.get("byteOffset") or 0, maximum=len(payload))
        view_length = _as_nonneg_int(view.get("byteLength"), maximum=len(payload))
        stride = view.get("byteStride")
        byte_stride = 4 if stride is None else (_as_nonneg_int(stride, maximum=255) or 0)
        if view_offset is None or accessor_offset is None or view_length is None or byte_stride < 4:
            raise _TimeReadError("invalid", "invalid_accessor_layout", "corrupt")
        start = view_offset + accessor_offset
        last = start + byte_stride * (count - 1) + 4
        if start < view_offset or last > view_offset + view_length or last > len(payload):
            raise _TimeReadError("invalid", "accessor_out_of_range", "corrupt")
        return payload, start, byte_stride

    def _bounded_object_list(self, raw: object, field_name: str) -> list[dict[str, Any]]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            self.add_issue(
                f"{field_name}_not_array",
                "error",
                f"{field_name} is not an array",
                path=field_name,
            )
            self.degrade("corrupt")
            return []
        if len(raw) > self.limits.max_named_resources:
            self.add_issue(
                f"too_many_{field_name}",
                "error",
                f"{field_name} count exceeds the inspector limit",
                path=field_name,
            )
            self.degrade("unsupported")
            return []
        items: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            if isinstance(item, dict):
                items.append(item)
            else:
                self.add_issue(
                    f"{field_name}_entry_not_object",
                    "error",
                    f"{field_name}[{index}] is not an object",
                    path=f"{field_name}/{index}",
                )
                self.degrade("corrupt")
                items.append({})
        return items

    def build(self) -> GlbInspectionReport:
        return GlbInspectionReport(
            schema_version=SCHEMA_VERSION,
            status=self.status,
            file_size_bytes=self.file_size,
            sha256=self.digest,
            gltf_version=self.gltf_version,
            min_version=self.min_version,
            generator=self.generator,
            chunk_count=self.chunk_count,
            has_bin_chunk=self.has_bin_chunk,
            meshes=self.meshes,
            nodes=self.nodes,
            skins=self.skins,
            materials=self.materials,
            animations=self.animations,
            buffers=self.buffers,
            extensions_used=self.extensions_used,
            extensions_required=self.extensions_required,
            issues=self.issues,
            total_triangles=_total_triangles(self.meshes),
        )


def _accessor_count(accessors: list[Any], index: object) -> int | None:
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    if index < 0 or index >= len(accessors):
        return None
    accessor = accessors[index]
    if not isinstance(accessor, dict):
        return None
    count = accessor.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return None
    return count


def _primitive_triangles(accessors: list[Any], primitive: dict[str, Any]) -> int | None:
    """Indexed triangles use ``count(indices) / 3``. Otherwise ``count(POSITION) / 3``.

    Mode 4 is TRIANGLES. An omitted mode is the glTF default, which is also 4.
    Any other mode is ``None``.
    """
    mode = primitive.get("mode", 4)
    if isinstance(mode, bool) or not isinstance(mode, int) or mode != 4:
        return None
    if "indices" in primitive:
        count = _accessor_count(accessors, primitive.get("indices"))
    else:
        attributes = primitive.get("attributes")
        position = attributes.get("POSITION") if isinstance(attributes, dict) else None
        count = _accessor_count(accessors, position)
    if count is None or count % 3:
        return None
    return count // 3


def _mesh_triangles(accessors: list[Any], primitives: list[Any]) -> int | None:
    counts: list[int] = []
    for primitive in primitives:
        if not isinstance(primitive, dict):
            return None
        count = _primitive_triangles(accessors, primitive)
        if count is None:
            return None
        counts.append(count)
    return sum(counts)


def _total_triangles(meshes: list[MeshReport]) -> int | None:
    if any(mesh.triangle_count is None for mesh in meshes):
        return None
    return sum(int(mesh.triangle_count or 0) for mesh in meshes)


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)]


def _combine_durations(
    durations: list[tuple[float | None, DurationStatus]],
) -> tuple[float | None, DurationStatus]:
    if not durations:
        return None, "unknown"
    if any(status == "unknown" for _, status in durations):
        return None, "unknown"
    if any(status == "invalid" for _, status in durations):
        return None, "invalid"
    verified = [value for value, status in durations if status == "verified" and value is not None]
    if len(verified) == len(durations):
        return max(verified), "verified"
    return None, "unknown"


def _same_time(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-5, abs_tol=1e-6)


def _accessor_message(code: str) -> str:
    messages = {
        "accessor_index_out_of_range": "animation sampler input accessor is out of range",
        "accessor_not_object": "animation sampler input accessor is not an object",
        "sparse_time_accessor": "sparse time accessors are not decoded",
        "invalid_accessor_count": "animation input accessor count is invalid",
        "time_accessor_not_float": "animation input must be FLOAT (5126); other types are not converted",
        "time_accessor_not_scalar": "animation input must be SCALAR",
        "empty_time_accessor": "animation input accessor has count 0",
        "time_accessor_without_buffer_view": "animation input accessor has no bufferView",
        "buffer_view_index_out_of_range": "animation input bufferView is out of range",
        "buffer_view_not_object": "animation input bufferView is not an object",
        "buffer_index_out_of_range": "animation input buffer index is out of range",
        "invalid_accessor_layout": "animation input accessor layout is invalid",
        "accessor_out_of_range": "animation input samples fall outside the bufferView",
        "accessor_work_limit": "decoding animation inputs would exceed the inspector work limit",
        "too_many_time_samples": "animation input sample count exceeds the inspector limit",
    }
    return messages.get(code, code)



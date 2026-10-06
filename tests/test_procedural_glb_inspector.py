from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import urllib.request
from pathlib import Path

import pytest

from services.procedural_3d import (
    SCHEMA_VERSION,
    GlbInspectorLimits,
    inspect_glb,
    inspect_glb_bytes,
    report_to_dict,
)
from services.procedural_3d.glb_inspector import classify_uri


GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def _f32(*values: float) -> bytes:
    return b"".join(struct.pack("<f", value) for value in values)


def _u16(*values: int) -> bytes:
    return b"".join(struct.pack("<H", value) for value in values)


def pack_glb(document: dict, blob: bytes = b"") -> bytes:
    json_bytes = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    json_bytes += b" " * ((4 - (len(json_bytes) % 4)) % 4)
    chunks = struct.pack("<II", len(json_bytes), JSON_CHUNK) + json_bytes
    if blob:
        padded = blob + (b"\x00" * ((4 - (len(blob) % 4)) % 4))
        chunks += struct.pack("<II", len(padded), BIN_CHUNK) + padded
    return struct.pack("<III", GLB_MAGIC, 2, 12 + len(chunks)) + chunks


def _identity() -> list[float]:
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def two_clip_scene() -> tuple[dict, bytes]:
    """Known-duration clips: Walk=1.0s, Run=2.5s. Names are exact, not aliases."""
    positions = _f32(0, 0, 0, 1, 0, 0, 0, 1, 0)
    joints = _u16(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    weights = _f32(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)
    ibm = _f32(*_identity())
    walk_times = _f32(0.0, 1.0)
    walk_trans = _f32(0, 0, 0, 1, 0, 0)
    run_times = _f32(0.0, 1.25, 2.5)
    run_trans = _f32(0, 0, 0, 0, 1, 0, 0, 2, 0)
    blob = positions + joints + weights + ibm + walk_times + walk_trans + run_times + run_trans
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": 36},
        {"buffer": 0, "byteOffset": 36, "byteLength": 24},
        {"buffer": 0, "byteOffset": 60, "byteLength": 48},
        {"buffer": 0, "byteOffset": 108, "byteLength": 64},
        {"buffer": 0, "byteOffset": 172, "byteLength": 8},
        {"buffer": 0, "byteOffset": 180, "byteLength": 24},
        {"buffer": 0, "byteOffset": 204, "byteLength": 12},
        {"buffer": 0, "byteOffset": 216, "byteLength": 36},
    ]
    accessors = [
        {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": 1, "componentType": 5123, "count": 3, "type": "VEC4"},
        {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC4"},
        {"bufferView": 3, "componentType": 5126, "count": 1, "type": "MAT4"},
        {
            "bufferView": 4,
            "componentType": 5126,
            "count": 2,
            "type": "SCALAR",
            "min": [0.0],
            "max": [1.0],
        },
        {"bufferView": 5, "componentType": 5126, "count": 2, "type": "VEC3"},
        {
            "bufferView": 6,
            "componentType": 5126,
            "count": 3,
            "type": "SCALAR",
            "min": [0.0],
            "max": [2.5],
        },
        {"bufferView": 7, "componentType": 5126, "count": 3, "type": "VEC3"},
    ]
    document = {
        "asset": {"version": "2.0", "generator": "hocuspocus-test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Root", "mesh": 0, "skin": 0}],
        "meshes": [
            {
                "name": "Body",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "JOINTS_0": 1,
                            "WEIGHTS_0": 2,
                        }
                    }
                ],
            }
        ],
        "skins": [{"name": "Armature", "joints": [0], "inverseBindMatrices": 3, "skeleton": 0}],
        "materials": [{"name": "Skin"}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": accessors,
        "animations": [
            {
                "name": "Walk",
                "samplers": [{"input": 4, "output": 5, "interpolation": "LINEAR"}],
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
            },
            {
                "name": "Run",
                "samplers": [{"input": 6, "output": 7, "interpolation": "STEP"}],
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
            },
        ],
    }
    return document, blob


def inspect_two_clip_scene():
    document, blob = two_clip_scene()
    return inspect_glb_bytes(pack_glb(document, blob))


def _issue_codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def test_two_synthetic_clips_have_verified_distinct_durations():
    report = inspect_two_clip_scene()
    assert report.schema_version == SCHEMA_VERSION
    assert report.status == "valid"
    assert report.gltf_version == "2.0"
    assert [mesh.name for mesh in report.meshes] == ["Body"]
    assert report.meshes[0].has_joints is True
    assert [node.name for node in report.nodes] == ["Root"]
    assert report.skins[0].name == "Armature"
    assert report.skins[0].joint_count == 1
    assert [material.name for material in report.materials] == ["Skin"]
    assert [(clip.index, clip.name, clip.duration_seconds, clip.duration_status) for clip in report.animations] == [
        (0, "Walk", 1.0, "verified"),
        (1, "Run", 2.5, "verified"),
    ]
    assert report.animations[0].interpolations == ("LINEAR",)
    assert report.animations[1].interpolations == ("STEP",)


def test_clip_names_are_exact_and_not_given_inferred_semantics():
    document, blob = two_clip_scene()
    document["animations"].append(
        {
            "name": "Armature|clip0|baselayer",
            "samplers": [{"input": 4, "output": 5, "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
        }
    )
    document["animations"].append(
        {
            "name": "Hip_Hop_Dance_1",
            "samplers": [{"input": 6, "output": 7, "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
        }
    )
    report = inspect_glb_bytes(pack_glb(document, blob))
    names = [clip.name for clip in report.animations]
    assert names == ["Walk", "Run", "Armature|clip0|baselayer", "Hip_Hop_Dance_1"]
    payload = json.dumps(report_to_dict(report))
    assert "suggested_semantic" not in payload
    assert "idle" not in payload.lower()
    for clip in report.animations:
        assert not hasattr(clip, "semantic")
        assert not hasattr(clip, "action")
        assert not hasattr(clip, "alias")


def test_duplicate_and_empty_names_stay_distinct_by_index():
    document, blob = two_clip_scene()
    document["animations"] = [
        {
            "name": "Walk",
            "samplers": [{"input": 4, "output": 5}],
            "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
        },
        {
            "name": "Walk",
            "samplers": [{"input": 6, "output": 7}],
            "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
        },
        {
            "samplers": [{"input": 4, "output": 5}],
            "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
        },
        {
            "name": "",
            "samplers": [{"input": 6, "output": 7}],
            "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
        },
    ]
    report = inspect_glb_bytes(pack_glb(document, blob))
    assert [clip.name for clip in report.animations] == ["Walk", "Walk", "", ""]
    assert [clip.index for clip in report.animations] == [0, 1, 2, 3]
    assert all(clip.name_collision for clip in report.animations)


def test_duration_uses_sampled_times_not_lying_minmax():
    document, blob = two_clip_scene()
    document["accessors"][4]["max"] = [99.0]
    report = inspect_glb_bytes(pack_glb(document, blob))
    walk = report.animations[0]
    assert walk.duration_seconds == 1.0
    assert walk.duration_status == "verified"
    assert "accessor_minmax_mismatch" in _issue_codes(report)


def test_nan_and_infinity_are_not_treated_as_times():
    times = _f32(float("nan"), float("inf"))
    trans = _f32(0, 0, 0, 1, 0, 0)
    blob = times + trans
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 8},
            {"buffer": 0, "byteOffset": 8, "byteLength": 24},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 2, "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC3"},
        ],
        "nodes": [{}],
        "animations": [
            {
                "name": "BadTimes",
                "samplers": [{"input": 0, "output": 1}],
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
            }
        ],
    }
    report = inspect_glb_bytes(pack_glb(document, blob))
    clip = report.animations[0]
    assert clip.duration_seconds is None
    assert clip.duration_status == "invalid"
    assert "non_finite_time" in _issue_codes(report)


def test_integer_time_accessor_is_not_silently_converted():
    blob = struct.pack("<HH", 0, 2500) + _f32(0, 0, 0, 1, 0, 0)
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 4},
            {"buffer": 0, "byteOffset": 4, "byteLength": 24},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5123, "count": 2, "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC3"},
        ],
        "nodes": [{}],
        "animations": [
            {
                "name": "IntTimes",
                "samplers": [{"input": 0, "output": 1}],
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
            }
        ],
    }
    report = inspect_glb_bytes(pack_glb(document, blob))
    clip = report.animations[0]
    assert clip.duration_seconds is None
    assert clip.duration_status == "invalid"
    assert "time_accessor_not_float" in _issue_codes(report)


def test_empty_animation_duration_is_unknown_not_zero():
    document, blob = two_clip_scene()
    document["animations"] = [{"name": "Empty", "samplers": [], "channels": []}]
    report = inspect_glb_bytes(pack_glb(document, blob))
    clip = report.animations[0]
    assert clip.duration_seconds is None
    assert clip.duration_status == "unknown"
    assert "empty_animation" in _issue_codes(report)


def test_truncated_glb_is_corrupt():
    document, blob = two_clip_scene()
    data = pack_glb(document, blob)
    report = inspect_glb_bytes(data[:-24])
    assert report.status == "corrupt"
    assert _issue_codes(report) & {
        "truncated_file",
        "truncated_chunk",
        "truncated_chunk_header",
    }


def test_declared_length_larger_than_file_is_corrupt():
    document, blob = two_clip_scene()
    data = bytearray(pack_glb(document, blob))
    struct.pack_into("<I", data, 8, len(data) + 4096)
    report = inspect_glb_bytes(bytes(data))
    assert report.status == "corrupt"
    assert "truncated_file" in _issue_codes(report)


def test_invalid_magic_and_json_gltf_are_rejected():
    assert inspect_glb_bytes(b"not a glb file!!!!").status == "corrupt"
    json_gltf = json.dumps({"asset": {"version": "2.0"}}).encode("utf-8")
    report = inspect_glb_bytes(json_gltf)
    assert report.status == "unsupported"
    assert "gltf_json_not_glb" in _issue_codes(report)


def test_accessor_view_out_of_range_is_corrupt():
    document, blob = two_clip_scene()
    document["animations"][0]["samplers"][0]["input"] = 4
    document["accessors"][4]["bufferView"] = 99
    report = inspect_glb_bytes(pack_glb(document, blob))
    assert report.status == "corrupt"
    assert report.animations[0].duration_status == "invalid"
    assert "buffer_view_index_out_of_range" in _issue_codes(report)


def test_bool_count_is_not_accepted_as_integer():
    document, blob = two_clip_scene()
    document["accessors"][4]["count"] = True
    report = inspect_glb_bytes(pack_glb(document, blob))
    assert report.animations[0].duration_status == "invalid"
    assert "invalid_accessor_count" in _issue_codes(report)


def test_http_buffer_is_blocked_and_does_not_fetch(monkeypatch):
    calls: list[object] = []

    def boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("network must not be used")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 16, "uri": "https://example.invalid/mesh.bin"}],
        "nodes": [{"name": "Only"}],
    }
    report = inspect_glb_bytes(pack_glb(document))
    assert report.status == "unsupported"
    assert "external_buffer_blocked" in _issue_codes(report)
    assert report.buffers[0].blocked is True
    assert report.buffers[0].uri_kind == "http"
    assert calls == []


def test_relative_and_file_uris_do_not_open_sidecars(tmp_path, monkeypatch):
    opened: list[str] = []
    real_open = open

    def tracking_open(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", tracking_open)
    secret = tmp_path / "mesh.bin"
    secret.write_bytes(b"SECRET")
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 6, "uri": "mesh.bin"}],
        "images": [{"uri": secret.as_uri()}],
    }
    glb_path = tmp_path / "model.glb"
    glb_path.write_bytes(pack_glb(document))
    report = inspect_glb(glb_path)
    assert report.status == "unsupported"
    assert "external_buffer_blocked" in _issue_codes(report)
    assert "external_image_blocked" in _issue_codes(report)
    assert str(secret) not in opened
    assert all(Path(item).name != "mesh.bin" for item in opened)
    assert secret.read_bytes() == b"SECRET"


def test_inspect_glb_bytes_does_not_open_any_path(monkeypatch, tmp_path):
    opened: list[str] = []
    real_open = open

    def tracking_open(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", tracking_open)
    (tmp_path / "trap.bin").write_bytes(b"nope")
    document, blob = two_clip_scene()
    inspect_glb_bytes(pack_glb(document, blob))
    assert opened == []


def test_file_uri_classifier_does_not_decode_traversal():
    assert classify_uri("https://example.invalid/a.glb") == "http"
    assert classify_uri("file:///etc/passwd") == "file"
    assert classify_uri("../secret.bin") == "relative"
    assert classify_uri("%2e%2e/secret.bin") == "relative"
    assert classify_uri("") == "relative"
    assert classify_uri("data:application/octet-stream;base64,AAAA") == "data_uri"
    assert classify_uri(None) == "embedded_bin"
    assert classify_uri(123) == "invalid"


def test_oversized_file_is_not_read(tmp_path):
    path = tmp_path / "huge.glb"
    path.write_bytes(pack_glb({"asset": {"version": "2.0"}}))
    report = inspect_glb(path, limits=GlbInspectorLimits(max_file_bytes=8))
    assert report.status == "unsupported"
    assert report.sha256 is None
    assert "file_too_large" in _issue_codes(report)


def test_required_extension_is_unsupported():
    document, blob = two_clip_scene()
    document["extensionsUsed"] = ["KHR_draco_mesh_compression"]
    document["extensionsRequired"] = ["KHR_draco_mesh_compression"]
    report = inspect_glb_bytes(pack_glb(document, blob))
    assert report.status == "unsupported"
    assert "required_extensions" in _issue_codes(report)
    assert report.extensions_required == ["KHR_draco_mesh_compression"]


def test_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        inspect_glb(tmp_path / "missing-file.glb")


def test_inspect_glb_hashes_the_file(tmp_path):
    document, blob = two_clip_scene()
    data = pack_glb(document, blob)
    path = tmp_path / "scene.glb"
    path.write_bytes(data)
    report = inspect_glb(path)
    assert report.sha256 == hashlib.sha256(data).hexdigest()
    assert report.file_size_bytes == len(data)


def test_sparse_time_accessor_is_unknown_not_zero():
    document, blob = two_clip_scene()
    document["accessors"][4]["sparse"] = {"count": 1, "indices": {}, "values": {}}
    report = inspect_glb_bytes(pack_glb(document, blob))
    assert report.animations[0].duration_seconds is None
    assert report.animations[0].duration_status == "unknown"
    assert "sparse_time_accessor" in _issue_codes(report)


def test_deeply_nested_json_returns_a_report_instead_of_raising():
    raw_json = ("[" * 4000 + "]" * 4000).encode("utf-8")
    raw_json += b" " * ((4 - (len(raw_json) % 4)) % 4)
    payload = struct.pack("<III", GLB_MAGIC, 2, 12 + 8 + len(raw_json))
    payload += struct.pack("<II", len(raw_json), JSON_CHUNK) + raw_json
    report = inspect_glb_bytes(payload)
    assert report.status in {"corrupt", "unsupported"}


def test_accessor_cap_stays_unsupported_not_corrupt():
    document, blob = two_clip_scene()
    report = inspect_glb_bytes(
        pack_glb(document, blob),
        limits=GlbInspectorLimits(max_accessors=1),
    )
    assert report.status == "unsupported"
    assert "too_many_accessors" in _issue_codes(report)
    assert report.animations[0].name == "Walk"
    assert report.animations[0].duration_status == "unknown"
    assert report.animations[0].duration_seconds is None


def test_over_limit_time_samples_are_unknown_not_corrupt():
    document, blob = two_clip_scene()
    report = inspect_glb_bytes(
        pack_glb(document, blob),
        limits=GlbInspectorLimits(max_time_samples=1),
    )
    assert report.status == "unsupported"
    assert "too_many_time_samples" in _issue_codes(report)
    assert report.animations[0].duration_status == "unknown"
    assert report.animations[0].duration_seconds is None


def test_data_uri_payload_is_clipped_to_byte_length():
    times = _f32(0.0, 1.0, 99.0)
    trans = _f32(0, 0, 0, 1, 0, 0)
    blob = times[:8] + trans
    uri = "data:application/octet-stream;base64," + base64.b64encode(times).decode("ascii")
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 8, "uri": uri}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 8},
            {"buffer": 0, "byteOffset": 8, "byteLength": 24},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 2, "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC3"},
        ],
        "nodes": [{}],
        "animations": [
            {
                "name": "Clipped",
                "samplers": [{"input": 0, "output": 1}],
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
            }
        ],
    }
    report = inspect_glb_bytes(pack_glb(document, blob))
    # Output accessor is outside the clipped 8-byte buffer, but input times must
    # not include the extra 99.0 float from the data URI.
    assert report.animations[0].duration_seconds == 1.0
    assert 99.0 not in (
        [report.animations[0].duration_seconds] if report.animations[0].duration_seconds else []
    )


def test_partial_channel_failure_does_not_verify_clip_duration():
    document, blob = two_clip_scene()
    document["accessors"].append(
        {
            "bufferView": 4,
            "componentType": 5126,
            "count": 2,
            "type": "SCALAR",
            "sparse": {"count": 1, "indices": {}, "values": {}},
        }
    )
    document["animations"][0]["samplers"].append({"input": 8, "output": 5})
    document["animations"][0]["channels"].append(
        {"sampler": 1, "target": {"node": 0, "path": "scale"}}
    )
    report = inspect_glb_bytes(pack_glb(document, blob))
    walk = report.animations[0]
    assert walk.duration_seconds is None
    assert walk.duration_status == "unknown"
    assert "sparse_time_accessor" in _issue_codes(report)


def test_uri_less_non_zero_buffer_does_not_alias_bin_chunk():
    document, blob = two_clip_scene()
    document["buffers"].append({"byteLength": 4})
    report = inspect_glb_bytes(pack_glb(document, blob))
    assert report.status == "corrupt"
    assert "buffer_missing_uri" in _issue_codes(report)
    assert report.buffers[1].blocked is True


def test_indexed_cube_counts_twelve_triangles():
    positions = _f32(
        -1, -1, -1, 1, -1, -1, 1, 1, -1, -1, 1, -1,
        -1, -1, 1, 1, -1, 1, 1, 1, 1, -1, 1, 1,
    )
    indices = _u16(
        0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6,
        0, 4, 5, 0, 5, 1, 2, 6, 7, 2, 7, 3,
        0, 3, 7, 0, 7, 4, 1, 5, 6, 1, 6, 2,
    )
    blob = positions + indices
    document = {
        "asset": {"version": "2.0"},
        "meshes": [{"name": "Cube", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }
    report = inspect_glb_bytes(pack_glb(document, blob))
    assert report.meshes[0].triangle_count == 12
    assert report.total_triangles == 12


def test_non_triangle_mode_has_no_count():
    positions = _f32(0, 0, 0, 1, 0, 0, 0, 1, 0)
    document = {
        "asset": {"version": "2.0"},
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "mode": 5}]}],
        "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
    }
    report = inspect_glb_bytes(pack_glb(document, positions))
    assert report.meshes[0].triangle_count is None
    assert report.total_triangles is None


def test_json_nan_is_corrupt():
    raw_json = b'{"asset":{"version":NaN}}'
    raw_json += b" " * ((4 - (len(raw_json) % 4)) % 4)
    payload = struct.pack("<III", GLB_MAGIC, 2, 12 + 8 + len(raw_json))
    payload += struct.pack("<II", len(raw_json), JSON_CHUNK) + raw_json
    report = inspect_glb_bytes(payload)
    assert report.status == "corrupt"
    assert "invalid_json" in _issue_codes(report)

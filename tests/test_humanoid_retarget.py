"""BVH and glTF clips retarget onto the standard humanoid by height."""

from __future__ import annotations

import base64
import json
import math
import struct
from pathlib import Path

import numpy as np
import pytest

from services.humanoid_rig.retarget import retarget_bvh, retarget_glb, retarget_gltf

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "humanoid_rig" / "wave.bvh"
_GLB_MAGIC = 0x46546C67
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
# wave.bvh rest offsets: hips Y 0.9, highest end site 1.4, lowest end site 0.1.
_WAVE_SOURCE_HEIGHT = 1.3
_WAVE_HIPS = np.array(
    [[0.0, 0.9, 0.0], [0.0, 1.0, 0.0], [0.0, 1.1, 0.0]],
    dtype=np.float64,
)


def _axis_quat(axis: int, degrees: float) -> np.ndarray:
    half = math.radians(degrees) * 0.5
    vector = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))[axis]
    scale = math.sin(half)
    return np.array(
        [vector[0] * scale, vector[1] * scale, vector[2] * scale, math.cos(half)],
        dtype=np.float64,
    )


def _read_wave() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_wave_scales_translation_and_keeps_rotations():
    text = _read_wave()
    tall = retarget_bvh(text, 1.7)
    short = retarget_bvh(text, 1.2)
    assert tall["bones"] == (
        "Hips",
        "Spine",
        "LeftArm",
        "RightArm",
        "LeftUpLeg",
        "RightUpLeg",
    )
    assert "Head" not in tall["rotations"]
    assert "Head" not in tall["bones"]
    np.testing.assert_allclose(tall["times"], [0.0, 0.5, 1.0])
    assert tall["duration"] == 1.0
    assert np.array_equal(tall["times"], short["times"])
    for name in tall["bones"]:
        assert np.array_equal(tall["rotations"][name], short["rotations"][name])
    np.testing.assert_allclose(
        short["hips_translation"],
        tall["hips_translation"] * (1.2 / 1.7),
        atol=1e-6,
        rtol=0,
    )
    np.testing.assert_allclose(tall["hips_translation"][:, 0], 0.0, atol=1e-8)
    np.testing.assert_allclose(tall["hips_translation"][:, 2], 0.0, atol=1e-8)
    assert tall["hips_translation"][2, 1] > tall["hips_translation"][0, 1]
    np.testing.assert_allclose(
        tall["hips_translation"],
        _WAVE_HIPS * (1.7 / _WAVE_SOURCE_HEIGHT),
        atol=1e-8,
    )
    posed = _axis_quat(2, 30.0)
    np.testing.assert_allclose(tall["rotations"]["LeftArm"][0], _axis_quat(2, 0.0))
    np.testing.assert_allclose(tall["rotations"]["LeftArm"][1], posed, atol=1e-8)
    np.testing.assert_allclose(tall["rotations"]["LeftArm"][2], posed, atol=1e-8)
    assert tall["warnings"] == ["unrecognized joint ExtraProp"]
    assert tall["hips_translation"].dtype == np.float64


def test_wave_parse_is_deterministic():
    text = _read_wave()
    first = retarget_bvh(text, 1.7)
    second = retarget_bvh(text, 1.7)
    assert first["bones"] == second["bones"]
    assert first["warnings"] == second["warnings"]
    assert first["duration"] == second["duration"]
    assert np.array_equal(first["times"], second["times"])
    assert np.array_equal(first["hips_translation"], second["hips_translation"])
    for name in first["bones"]:
        assert np.array_equal(first["rotations"][name], second["rotations"][name])


def test_bvh_rotation_channels_apply_in_listed_order():
    text = """HIERARCHY
ROOT Hips
{
    OFFSET 0 1 0
    CHANNELS 3 Xposition Yposition Zposition
    JOINT LeftArm
    {
        OFFSET 0 1 0
        CHANNELS 2 Zrotation Yrotation
        End Site
        {
            OFFSET 0 0.5 0
        }
    }
}
MOTION
Frames: 1
Frame Time: 0.5
0 0 0 90 90
"""
    clip = retarget_bvh(text, 2.0, source_height=1.0)
    assert clip["bones"] == ("LeftArm",)
    assert "Head" not in clip["rotations"]
    np.testing.assert_allclose(
        clip["rotations"]["LeftArm"][0],
        [-0.5, 0.5, 0.5, 0.5],
        atol=1e-8,
    )
    np.testing.assert_allclose(clip["hips_translation"], [[0.0, 2.0, 0.0]])


def test_bvh_without_recognized_bones_raises():
    text = """HIERARCHY
ROOT ExtraProp
{
    OFFSET 0 1 0
    CHANNELS 1 Xrotation
    End Site
    {
        OFFSET 0 0.2 0
    }
}
MOTION
Frames: 1
Frame Time: 0.5
0
"""
    with pytest.raises(ValueError):
        retarget_bvh(text, 1.7)


def test_target_height_must_be_positive():
    text = _read_wave()
    with pytest.raises(ValueError):
        retarget_bvh(text, 0)
    with pytest.raises(ValueError):
        retarget_bvh(text, float("nan"))


def _pad4(payload: bytes, fill: bytes) -> bytes:
    extra = (-len(payload)) % 4
    return payload + fill * extra


def _pack_glb(document: dict, blob: bytes) -> bytes:
    json_chunk = _pad4(json.dumps(document, separators=(",", ":")).encode("utf-8"), b" ")
    bin_chunk = _pad4(blob, b"\x00")
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    return b"".join((
        struct.pack("<III", _GLB_MAGIC, 2, total),
        struct.pack("<II", len(json_chunk), _JSON_CHUNK),
        json_chunk,
        struct.pack("<II", len(bin_chunk), _BIN_CHUNK),
        bin_chunk,
    ))


def _gltf_clip(arm_name: str, blob: bytes, *, translation: bool):
    uri = "data:application/octet-stream;base64," + base64.b64encode(blob).decode("ascii")
    accessors = [
        {
            "bufferView": 0,
            "byteOffset": 4,
            "componentType": 5126,
            "count": 2,
            "type": "SCALAR",
        },
        {
            "bufferView": 1,
            "byteOffset": 0,
            "componentType": 5126,
            "count": 2,
            "type": "VEC4",
        },
    ]
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": 12},
        {"buffer": 0, "byteOffset": 12, "byteLength": 32},
    ]
    samplers = [{"input": 0, "output": 1, "interpolation": "LINEAR"}]
    channels = [{"sampler": 0, "target": {"node": 1, "path": "rotation"}}]
    if translation:
        accessors.append({
            "bufferView": 2,
            "byteOffset": 0,
            "componentType": 5126,
            "count": 2,
            "type": "VEC3",
        })
        views.append({"buffer": 0, "byteOffset": 44, "byteLength": 24})
        samplers.append({"input": 0, "output": 2, "interpolation": "LINEAR"})
        channels.append({"sampler": 1, "target": {"node": 0, "path": "translation"}})
    return {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": uri, "byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": accessors,
        "nodes": [
            {"name": "Hips", "translation": [0, 1, 0], "children": [1, 2]},
            {"name": arm_name, "translation": [0.2, 0.4, 0]},
            {"name": "Tail", "translation": [0, 0.2, 0.5]},
        ],
        "animations": [{"samplers": samplers, "channels": channels}],
    }


def _clip_blob(*, with_translation: bool) -> tuple[bytes, np.ndarray]:
    quats = np.array(
        [[0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0, 1.0]],
        dtype="<f4",
    )
    quats[1] = np.array([0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4)], dtype="<f4")
    parts = [
        b"\xab\xab\xab\xab",
        np.array([0.0, 1.0], dtype="<f4").tobytes(),
        quats.tobytes(),
    ]
    if with_translation:
        parts.append(np.array([[0.0, 1.0, 0.0], [0.0, 2.0, 0.0]], dtype="<f4").tobytes())
    return b"".join(parts), quats.astype(np.float64)


def test_gltf_strips_prefix_scales_hips_and_rejects_http():
    blob, quats = _clip_blob(with_translation=True)
    document = _gltf_clip("mixamorig:LeftArm", blob, translation=True)
    tall = retarget_gltf(document, 1.7, source_height=1.0)
    short = retarget_gltf(document, 1.2, source_height=1.0)
    assert tall["bones"] == ("LeftArm",)
    assert "Head" not in tall["rotations"]
    np.testing.assert_array_equal(tall["rotations"]["LeftArm"], quats)
    assert np.array_equal(tall["rotations"]["LeftArm"], short["rotations"]["LeftArm"])
    np.testing.assert_allclose(tall["times"], [0.0, 1.0])
    assert tall["duration"] == 1.0
    np.testing.assert_allclose(tall["hips_translation"], [[0.0, 1.7, 0.0], [0.0, 3.4, 0.0]])
    np.testing.assert_allclose(
        short["hips_translation"],
        tall["hips_translation"] * (1.2 / 1.7),
        atol=1e-6,
        rtol=0,
    )
    assert tall["warnings"] == ["unrecognized joint Tail"]
    external = {
        **document,
        "buffers": [{"uri": "http://example.com/buffer.bin", "byteLength": len(blob)}],
    }
    with pytest.raises(ValueError, match="^external uri$"):
        retarget_gltf(external, 1.7, source_height=1.0)


@pytest.mark.parametrize("arm_name", ["mixamorig_LeftArm", "Mixamo_LeftArm"])
def test_gltf_accepts_other_mixamo_prefixes(arm_name):
    blob, quats = _clip_blob(with_translation=False)
    document = _gltf_clip(arm_name, blob, translation=False)
    clip = retarget_gltf(document, 1.0, source_height=1.0)
    np.testing.assert_array_equal(clip["rotations"]["LeftArm"], quats)
    assert clip["warnings"] == ["unrecognized joint Tail"]


def test_gltf_linear_rotation_is_slerped_between_keys():
    times = np.array([0.0, 1.0], dtype="<f4").tobytes()
    quats = np.array([[0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 1.0, 0.0]], dtype="<f4").tobytes()
    hips = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.0]], dtype="<f4").tobytes()
    hip_times = np.array([0.0, 0.5, 1.0], dtype="<f4").tobytes()
    blob = times + quats + hip_times + hips
    uri = "data:application/octet-stream;base64," + base64.b64encode(blob).decode("ascii")
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": uri, "byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 8},
            {"buffer": 0, "byteOffset": 8, "byteLength": 32},
            {"buffer": 0, "byteOffset": 40, "byteLength": 12},
            {"buffer": 0, "byteOffset": 52, "byteLength": 36},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 2, "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC4"},
            {"bufferView": 2, "componentType": 5126, "count": 3, "type": "SCALAR"},
            {"bufferView": 3, "componentType": 5126, "count": 3, "type": "VEC3"},
        ],
        "nodes": [
            {"name": "Hips", "translation": [0, 1, 0]},
            {"name": "mixamorig:LeftArm"},
        ],
        "animations": [{
            "samplers": [
                {"input": 0, "output": 1, "interpolation": "LINEAR"},
                {"input": 2, "output": 3, "interpolation": "LINEAR"},
            ],
            "channels": [
                {"sampler": 0, "target": {"node": 1, "path": "rotation"}},
                {"sampler": 1, "target": {"node": 0, "path": "translation"}},
            ],
        }],
    }
    clip = retarget_gltf(document, 1.0, source_height=1.0)
    np.testing.assert_allclose(clip["times"], [0.0, 0.5, 1.0])
    halfway = [0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4)]
    np.testing.assert_allclose(clip["rotations"]["LeftArm"][1], halfway, atol=1e-6)
    np.testing.assert_allclose(clip["hips_translation"][1], [0.0, 1.0, 0.0], atol=1e-6)


def test_gltf_source_height_uses_bone_world_span():
    blob, _quats = _clip_blob(with_translation=False)
    document = _gltf_clip("mixamorig:LeftArm", blob, translation=False)
    clip = retarget_gltf(document, 1.0)
    np.testing.assert_allclose(clip["hips_translation"], [[0.0, 2.5, 0.0], [0.0, 2.5, 0.0]])


def test_gltf_hip_height_fallback_when_span_is_flat():
    blob, _quats = _clip_blob(with_translation=False)
    document = _gltf_clip("LeftArm", blob, translation=False)
    document["nodes"][0]["translation"] = [0, 0.4, 0]
    document["nodes"][1]["translation"] = [0, 0, 0]
    clip = retarget_gltf(document, 0.8)
    np.testing.assert_allclose(clip["hips_translation"], [[0.0, 0.4, 0.0], [0.0, 0.4, 0.0]])


def test_glb_roundtrip_matches_gltf_json():
    blob, quats = _clip_blob(with_translation=True)
    document = _gltf_clip("mixamorig:LeftArm", blob, translation=True)
    packed = json.loads(json.dumps(document))
    packed["buffers"] = [{"byteLength": len(blob)}]
    from_glb = retarget_glb(_pack_glb(packed, blob), 1.7, source_height=1.0)
    from_json = retarget_gltf(document, 1.7, source_height=1.0)
    assert from_glb["bones"] == from_json["bones"] == ("LeftArm",)
    assert from_glb["warnings"] == ["unrecognized joint Tail"]
    assert from_glb["duration"] == from_json["duration"]
    np.testing.assert_array_equal(from_glb["times"], from_json["times"])
    np.testing.assert_array_equal(from_glb["rotations"]["LeftArm"], quats)
    np.testing.assert_allclose(from_glb["hips_translation"], from_json["hips_translation"])

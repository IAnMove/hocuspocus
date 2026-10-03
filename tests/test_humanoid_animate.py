"""Clips land on a rigged GLB, and a plain mesh is refused."""
import json
from pathlib import Path

import pytest

pytest.importorskip("pygltflib")

from pygltflib import GLTF2

import numpy as np

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.animate import animate_humanoid, stored_rig
from services.humanoid_rig.gltf_export import read_primitives, write_rigged_glb
from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.names import BONE_NAMES, NORMAL_HEIGHT
from services.humanoid_rig.rig import _combined, rig_humanoid
from services.humanoid_rig.skeleton import build_skeleton
from services.humanoid_rig.weights import compute_weights
from services.procedural_3d.compose import compose_glb
from tests.humanoid_bodies import as_glb, body
from tests.humanoid_skinning import batch_worlds

ROOT = Path(__file__).parents[1] / "tests" / "fixtures" / "humanoid_rig"


def _pet() -> bytes:
    document = json.loads((ROOT / "pet.json").read_text())
    return compose_glb(document["pieces"], document["id"])


def _channels(data: bytes, index: int) -> list[str]:
    gltf = GLTF2.load_from_bytes(data)
    animation = gltf.animations[index]
    return [channel.target.path for channel in animation.channels]


def test_library_clips_append_without_renumbering():
    rigged, sidecar = rig_humanoid(_pet())
    assert [clip["name"] for clip in sidecar["clips"]] == ["Idle"]
    first, listed, warnings = animate_humanoid(rigged, ["walk", "wave"], 120)
    assert warnings == []
    assert [item["name"] for item in listed] == ["Walk", "Wave"]
    assert [item["index"] for item in listed] == [1, 2]
    assert set(_channels(first, 1)) == {"rotation", "translation"}
    second, more, _warnings = animate_humanoid(first, ["dance_side"], 90)
    assert more == [{"index": 3, "name": "Dance Side", "duration": pytest.approx(2 * 60 / 90)}]
    assert len(GLTF2.load_from_bytes(second).animations) == 4


def test_imported_bvh_writes_a_hips_translation_channel():
    rigged, _sidecar = rig_humanoid(_pet())
    data, listed, warnings = animate_humanoid(rigged, None, 120, (ROOT / "wave.bvh").read_bytes(), ".bvh", "wave hello")
    assert listed[0]["name"] == "wave hello" and listed[0]["index"] == 1
    assert _channels(data, 1)[-1] == "translation"
    assert "1 joints were not used (fingers, props or extra bones)" in warnings


def _legacy_rig() -> bytes:
    """A rig as the first humanoid release wrote it: identity rests, no Hips marker."""
    source = as_glb(body("human_a"))
    positions, indices, _counts = _combined(read_primitives(source))
    found = detect_landmarks(positions, indices)
    skeleton = build_skeleton(found["points"], found["height"], found["y_min"], 1, found["head_region"])
    scale = found["height"] / NORMAL_HEIGHT
    for bone in skeleton["bones"]:
        parent = bone["parent"]
        bone["rotation"] = rot.IDENTITY.copy()
        if parent is not None:
            bone["translation"] = (skeleton["world"][bone["name"]] - skeleton["world"][parent]) / scale
    joints, weights = compute_weights(positions, indices, skeleton)
    return write_rigged_glb(source, skeleton, [(joints, weights)])


def test_a_legacy_rig_still_gets_arms_down_in_a_walk():
    legacy = _legacy_rig()
    data, listed, _warnings = animate_humanoid(legacy, ["walk"], 120)
    clip = listed[0]
    assert clip["name"] == "Walk"
    rig = stored_rig(data)
    gltf = GLTF2.load_from_bytes(data)
    assert len(gltf.animations) == 1
    from services.humanoid_rig.clips import clip_library

    walk = clip_library(120, ["walk"], stored_rig(legacy))[0]
    local = np.stack([walk["rotations"].get(name, np.tile(rig.bones[index]["rotation"], (len(walk["times"]), 1)))
                      for index, name in enumerate(BONE_NAMES)], axis=1)
    worlds = batch_worlds(rig.bones, local, walk["hips_translation"])
    arm = worlds[:, BONE_NAMES.index("LeftForeArm"), :3, 3] - worlds[:, BONE_NAMES.index("LeftArm"), :3, 3]
    assert float((arm[:, 1] / np.linalg.norm(arm, axis=1)).max()) < -0.8


def test_a_mesh_without_the_standard_skeleton_is_refused():
    plain = compose_glb([{"type": "box", "color": "#888888"}], "box")
    with pytest.raises(ValueError, match="standard humanoid skeleton not found"):
        animate_humanoid(plain, ["idle"], 120)


def _worker_python() -> Path:
    import subprocess

    from services.rig_service import APP_DIR, cpu_worker_python
    from services.runtime_environment import isolated_environment

    candidates = []
    chosen = cpu_worker_python()
    if chosen is not None:
        candidates.append(chosen)
    managed = APP_DIR / "services" / "hunyuan3d" / "env" / "bin" / "python"
    if managed.is_file():
        candidates.append(managed)
    for python in candidates:
        env = isolated_environment(python)
        probe = subprocess.run([str(python), "-c", "import numpy, pygltflib"], env=env, capture_output=True, text=True)
        if probe.returncode == 0:
            return python
    pytest.skip("humanoid worker python is not installed")


def test_worker_animate_mode_matches_the_library(tmp_path):
    from routers.model3d_animate import execute_animate

    rigged, _sidecar = rig_humanoid(_pet())
    source = tmp_path / "pet.glb"
    source.write_bytes(rigged)
    output = tmp_path / "out.glb"
    result = execute_animate(
        {"mode": "animate", "source": str(source), "animations": ["walk"], "animation_bpm": 120},
        output,
        python=_worker_python(),
    )
    assert output.is_file()
    assert result["clips"][0]["name"] == "Walk"
    assert result["clips"][0]["index"] == 1

"""Clips land on a rigged GLB, and a plain mesh is refused."""
import json
from pathlib import Path

import pytest

pytest.importorskip("pygltflib")

from pygltflib import GLTF2

from services.humanoid_rig.animate import animate_humanoid
from services.humanoid_rig.rig import rig_humanoid
from services.procedural_3d.compose import compose_glb

ROOT = Path(__file__).parents[1] / "tests" / "fixtures" / "humanoid_rig"


def _pet() -> bytes:
    document = json.loads((ROOT / "pet.json").read_text())
    return compose_glb(document["pieces"], document["id"])


def _channels(data: bytes, index: int) -> list[str]:
    gltf = GLTF2.load_from_bytes(data)
    animation = gltf.animations[index]
    return [channel.target.path for channel in animation.channels]


def test_library_clips_append_without_renumbering():
    rigged, _sidecar = rig_humanoid(_pet())
    first, listed, warnings = animate_humanoid(rigged, ["walk", "wave"], 120)
    assert warnings == []
    assert [item["name"] for item in listed] == ["Walk", "Wave"]
    assert [item["index"] for item in listed] == [0, 1]
    assert _channels(first, 0) == ["rotation"] * len(GLTF2.load_from_bytes(first).animations[0].channels)
    second, more, _warnings = animate_humanoid(first, ["dance_side"], 90)
    assert more == [{"index": 2, "name": "Dance Side", "duration": pytest.approx(2 * 60 / 90)}]
    assert len(GLTF2.load_from_bytes(second).animations) == 3


def test_imported_bvh_writes_a_hips_translation_channel():
    rigged, _sidecar = rig_humanoid(_pet())
    data, listed, warnings = animate_humanoid(rigged, None, 120, (ROOT / "wave.bvh").read_bytes(), ".bvh")
    assert listed[0]["name"] == "Imported" and listed[0]["index"] == 0
    assert _channels(data, 0)[-1] == "translation"
    assert isinstance(warnings, list)


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
    assert result["clips"][0]["index"] == 0

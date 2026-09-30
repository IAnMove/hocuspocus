"""The humanoid engine accepts its own clips and still refuses procedural-only ids."""
import pytest

from services.rig_service import start_job


def _start(body):
    try:
        start_job(body=body, source_path="missing.glb", output_dir=".", workspace="movie")
    except RuntimeError as exc:
        if "Pinokio" in str(exc) or "not installed" in str(exc).lower():
            pytest.skip(str(exc))
        raise


def test_humanoid_rejects_spin_and_a_bad_pose():
    with pytest.raises(ValueError, match="spin"):
        _start({"engine": "humanoid", "animations": ["spin"]})
    with pytest.raises(ValueError, match="pose must be t or a"):
        _start({"engine": "humanoid", "animations": ["wave"], "pose": "side"})


def test_procedural_still_rejects_humanoid_only_clips():
    with pytest.raises(ValueError, match="wave"):
        _start({"engine": "procedural", "animations": ["wave"]})

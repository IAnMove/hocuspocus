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
    with pytest.raises(ValueError, match="pose must be auto, t or a"):
        _start({"engine": "humanoid", "animations": ["wave"], "pose": "side"})


def test_procedural_still_rejects_humanoid_only_clips():
    with pytest.raises(ValueError, match="wave"):
        _start({"engine": "procedural", "animations": ["wave"]})


def test_capabilities_list_the_humanoid_clips_with_categories():
    from services.humanoid_rig.names import CLIP_IDS
    from services.rig_service import _humanoid_animation_catalog

    catalog = _humanoid_animation_catalog()
    assert [item["id"] for item in catalog] == list(CLIP_IDS)
    assert {"Move", "Gesture", "Dance", "Stand", "Action"} == {item["category"] for item in catalog}


def test_a_refused_mesh_reports_its_code_and_a_readable_reason():
    from services.rig_service import _WorkerRefused

    refused = _WorkerRefused({"ok": False, "error": "not_humanoid", "reason": "hands_stuck"})
    assert refused.fields == {"error_code": "not_humanoid", "error_reason": "hands_stuck"}
    assert str(refused).startswith("not_humanoid: the arms touch the body")
    other = _WorkerRefused({"ok": False, "error": "rig_failed", "reason": "disk full"})
    assert str(other) == "rig_failed: disk full"

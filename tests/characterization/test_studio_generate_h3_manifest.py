"""The Studio generate route opens the media a library pick names in an H3 Omni manifest."""
from __future__ import annotations

from pathlib import Path

from tests.characterization import media
from tests.characterization.test_run_generation import BODY
from tests.characterization.test_run_generation import clip, rig  # noqa: F401  (fixtures, used by name)
from tests.characterization.test_studio_generate import _h3_def, _params


def _omni_rig(rig, monkeypatch) -> None:  # noqa: F811
    definitions = {"fake_h3_omni": _h3_def(omni_reference=True)}
    real_def = rig.server.wgp.get_model_def
    rig.set_wgp("get_model_def", lambda model_type: definitions.get(model_type) or real_def(model_type))


def test_a_library_pick_in_the_manifest_reaches_the_job_as_a_real_file(rig, monkeypatch) -> None:  # noqa: F811
    _omni_rig(rig, monkeypatch)
    workspace = Path(rig.launch._workspace_dir("default"))
    name = "2026-01-02-03h04m05s_seed1_a person with a long prompt, same face.png"
    media.image(workspace / name)

    job = rig.run({**BODY, "model_type": "fake_h3_omni", "minimax_h3_window_storyboard": False,
                   "minimax_h3_references": [{"type": "image", "path": name, "filename": name}]})

    path = _params(rig, job)["minimax_h3_references"][0]["path"]
    assert Path(path) == workspace / name


def test_a_name_that_is_nowhere_is_still_refused_by_name(rig, monkeypatch) -> None:  # noqa: F811
    _omni_rig(rig, monkeypatch)
    response = rig.server.client.post("/api/v1/generate", json={
        **BODY, "model_type": "fake_h3_omni", "minimax_h3_window_storyboard": False,
        "minimax_h3_references": [{"type": "image", "path": "missing.png"}]})

    assert response.status_code == 400
    assert "Reference 1 file was not found: missing.png" in response.text

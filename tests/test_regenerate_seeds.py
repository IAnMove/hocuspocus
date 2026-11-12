"""A Regenerate is a new attempt: without a seed the user chose it must not repeat the first result."""
from __future__ import annotations

from unittest.mock import patch

from services import model3d_external, model3d_service
from services.game_generators.base import attempt_seed


def test_game_assets_keep_seed_one_first_and_vary_on_regenerate():
    fresh = {"spec": {}, "attempts": []}
    redone = {"spec": {}, "attempts": [{"id": "a1"}]}
    chosen = {"spec": {"seed": 9}, "attempts": [{"id": "a1"}]}
    assert attempt_seed(fresh, "a1") == 1
    assert attempt_seed(redone, "a2") != attempt_seed(redone, "a3")
    assert attempt_seed(redone, "a2") == attempt_seed(redone, "a2")       # a resume of the same attempt keeps it
    assert attempt_seed(chosen, "a2") == 9


def test_a_3d_job_without_a_seed_draws_one_and_a_chosen_seed_is_kept():
    with patch.object(model3d_service.secrets, "randbelow", return_value=77):
        assert model3d_service._requested_seed(None) == 77
        assert model3d_service._requested_seed(-1) == 77
    assert model3d_service._requested_seed(5) == 5
    model = {"resolutions": [1024], "supports_low_vram": False, "supports_camera_fov": False}
    with patch.object(model3d_external.secrets, "randbelow", return_value=88):
        assert model3d_external._settings({}, model)["seed"] == 88
        assert model3d_external._settings({"seed": -1}, model)["seed"] == 88
    assert model3d_external._settings({"seed": 4}, model)["seed"] == 4

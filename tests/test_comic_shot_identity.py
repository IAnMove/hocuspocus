"""Comic PRE shot identity stays stable across resume and seed derivation."""
from __future__ import annotations

from app.services import director_pipeline
from services.director import comic_identity


def test_comic_identity_helpers_are_reexported():
    assert director_pipeline._comic_shot is comic_identity._comic_shot
    assert director_pipeline._stable_comic_shot_id is comic_identity._stable_comic_shot_id
    assert director_pipeline._comic_shot_seed is comic_identity._comic_shot_seed
    assert director_pipeline._comic_preflight_fingerprint is comic_identity._comic_preflight_fingerprint


def test_stable_shot_id_prefers_plan_then_joined_panels():
    params = {"comic_shots": [{"page_number": 2, "panel_number": 4}]}
    assert director_pipeline._stable_comic_shot_id(
        params, 0, {"shot_id": "panel-alpha"},
    ) == "panel-alpha"
    assert director_pipeline._stable_comic_shot_id(
        params, 0, {"source_panel_ids": ["a", "b"]},
    ) == "a+b"
    assert director_pipeline._stable_comic_shot_id(params, 0) == "comic-shot-2-4"


def test_shot_seed_is_reproducible_and_honors_explicit_seed():
    params = {"master_seed": 42, "comic_shots": [{"shot_id": "panel-alpha"}]}
    first = director_pipeline._comic_shot_seed(params, 0)
    second = director_pipeline._comic_shot_seed(params, 0, {"shot_id": "panel-alpha"})
    assert first == second
    assert director_pipeline._comic_shot_seed(
        params, 0, {"seed": 7},
    ) == 7


def test_preflight_fingerprint_changes_when_the_source_panel_changes(tmp_path):
    source = tmp_path / "panel.png"
    source.write_bytes(b"panel-a")
    params = {
        "comic_id": "comic-1",
        "master_seed": 1,
        "provided_clip_image_paths": [str(source)],
        "comic_shots": [{"shot_id": "panel-alpha"}],
    }
    first = director_pipeline._comic_preflight_fingerprint(params, [], [])
    source.write_bytes(b"panel-b")
    second = director_pipeline._comic_preflight_fingerprint(params, [], [])
    assert first != second

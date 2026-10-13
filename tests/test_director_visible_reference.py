"""Director's hidden house rules, visible and overridable (glass walls PR A).

Wall 1, the shared reference: with no reference image, Director draws one
picture from shot 1 and draws every shot from it (Maestro). The run option
``reference_anchor`` keeps that as the default (``always``) and adds
``no_cast_refs`` and ``off``. The Dashboard sees the picture and can replace or
clear it.

Wall 2, light and clothes from the reference: Maestro ended every image prompt
with "Use lighting and color temp from reference image" (also in the
no-reference guide) and removed clothing words from every Pass 2 image prompt.
The light rule now follows ``lighting_continuity`` (default ``auto``: only with
the user's own reference image); the clothing rule follows
``keep_reference_wardrobe`` (default on).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.director_review import create_director_review_router
from services import director_pipeline
from services.director import image_prompt_rules
from services.director import orchestrator as director_orchestrator
from services.director.image_prompt_rules import get_image_prompt_rules, prepare_guide
from services.director.orchestrator import DirectorFlags, DirectorOrchestrator
from services.director.planners.base import BasePlanner
from services.director.planners.music_video import MusicVideoPlanner
from services.director.planners.short_film import ShortFilmPlanner
from services.director.prompt_cleanup import sanitize_pass2_image_prompts
from services.director.prompt_polish import polish_prompts_third_pass
from services.director.schema import ProductionPlan
from services.director.visible_defaults import resolve_option, resolve_run_options
from services.video_extra_info import build_saved_clip_info

SHOT = "A woman waits on the harbour at dawn."


def _wgp(tmp_path: Path, **services):
    return patch.object(
        director_pipeline,
        "_wgp",
        SimpleNamespace(server_config={"services": services}, save_path=str(tmp_path)),
    )


def _generate(tmp_path: Path, mode: str | None, *, cast: bool) -> tuple[list[dict], dict]:
    """Run the start-image phase; return every submitted generation and the params."""
    params: dict = {"pipeline_type": "short_film_story", "image_model": "qwen_image_21"}
    if mode is not None:
        params["reference_anchor"] = mode
    if cast:
        portrait = tmp_path / "portrait.png"
        portrait.write_bytes(b"image")
        params["character_ref_paths"] = [str(portrait)]
    record = {
        "id": "anchor", "status": "running", "phase": "generating_images", "progress": {},
        "clip_plans": [], "clip_images": [], "output_files": [], "created_at": time.time(),
        "params": params, "pause_reason": None, "out_dir": str(tmp_path),
    }
    submitted: list[dict] = []

    def submit(gen_params, **_kwargs):
        submitted.append(gen_params)
        name = f"image-{len(submitted)}.png"
        (tmp_path / name).write_bytes(b"image")
        return [name]

    with _wgp(tmp_path), \
            patch.dict(director_pipeline._pipelines, {"anchor": record}), \
            patch.object(director_pipeline, "_submit_and_wait", side_effect=submit):
        director_pipeline._run_image_generation(
            "anchor", params, [{"image_prompt": SHOT}], out_dir=str(tmp_path),
        )
    return submitted, params


def _names(refs: list[str]) -> list[str]:
    return [Path(ref).name for ref in refs]


# ── Each mode, with and without character references ─────────────────────

@pytest.mark.parametrize("mode", [None, "always"])
def test_the_default_draws_one_shared_reference_and_every_shot_from_it(tmp_path, mode):
    submitted, params = _generate(tmp_path, mode, cast=False)
    assert len(submitted) == 2  # the shared reference, then the shot
    anchor, shot = submitted
    assert anchor["image_refs"] == [] and anchor["video_prompt_type"] == ""
    assert _names(shot["image_refs"]) == ["image-1.png"] and shot["video_prompt_type"] == "KI"
    assert params["generated_reference_image_filename"] == "image-1.png"
    assert params["generated_reference_image_prompt"] == anchor["prompt"]


def test_with_character_references_the_shared_reference_comes_first(tmp_path):
    submitted, _params = _generate(tmp_path, "always", cast=True)
    anchor, shot = submitted
    assert _names(anchor["image_refs"]) == ["portrait.png"]
    assert _names(shot["image_refs"]) == ["image-1.png", "portrait.png"]


def test_no_cast_refs_skips_the_shared_reference_when_the_cast_has_portraits(tmp_path):
    submitted, params = _generate(tmp_path, "no_cast_refs", cast=True)
    assert len(submitted) == 1
    assert _names(submitted[0]["image_refs"]) == ["portrait.png"]
    assert "generated_reference_image_filename" not in params


def test_no_cast_refs_still_draws_one_without_portraits(tmp_path):
    submitted, _params = _generate(tmp_path, "no_cast_refs", cast=False)
    assert len(submitted) == 2


@pytest.mark.parametrize("cast", [False, True])
def test_off_draws_each_shot_from_its_own_prompt(tmp_path, cast):
    submitted, params = _generate(tmp_path, "off", cast=cast)
    assert len(submitted) == 1
    shot = submitted[0]
    assert shot["prompt"] == SHOT
    assert _names(shot["image_refs"]) == (["portrait.png"] if cast else [])
    assert shot["video_prompt_type"] == ("KI" if cast else "")  # no refs at all: plain text-to-image
    assert "generated_reference_image_filename" not in params


# ── The shared reference's prompt has no fixed style word ─────────────────

def test_the_shared_reference_prompt_has_no_cinematic_filler(tmp_path):
    submitted, _params = _generate(tmp_path, "always", cast=False)
    assert "cinematic" not in submitted[0]["prompt"].lower()
    assert submitted[0]["prompt"].startswith("Create a character reference for visual continuity.")
    assert SHOT in submitted[0]["prompt"]
    empty = director_pipeline._director_anchor_prompt({}, [], has_cast_refs=False)
    assert "cinematic" not in empty.lower() and "establishing shot" not in empty


# ── Resolution: request → Settings › Services → default ───────────────────

def test_the_option_comes_from_the_request_then_the_settings_then_the_default():
    services = {"director_reference_anchor": "no_cast_refs"}
    assert resolve_option("reference_anchor", "off", services) == "off"
    assert resolve_option("reference_anchor", None, services) == "no_cast_refs"
    assert resolve_option("reference_anchor", "bogus", {}) == "always"
    params = resolve_run_options({}, {"director_lighting_continuity": "per_shot"})
    assert params == {
        "reference_anchor": "always",
        "lighting_continuity": "per_shot",
        "keep_reference_wardrobe": True,
    }


def test_start_pipeline_persists_the_resolved_options(tmp_path):
    started: list[dict] = []
    with _wgp(tmp_path, director_reference_anchor="off"), \
            patch.object(director_pipeline, "_validate_director_models"), \
            patch.object(director_pipeline, "_create_director_video_execution_profile", return_value={}), \
            patch.object(director_pipeline, "_save_pipeline_state", return_value=True), \
            patch.object(director_pipeline, "_notify_pipeline_snapshot"), \
            patch.object(director_pipeline, "_start_pipeline_worker"), \
            patch.dict(director_pipeline._pipelines, {}):
        pid = director_pipeline.start_pipeline({
            "pipeline_type": "short_film_story", "image_model": "qwen_image_21",
            "keep_reference_wardrobe": False, "generated_reference_image_prompt": "stale",
        })
        started.append(director_pipeline._pipelines[pid]["params"])
    params = started[0]
    assert params["reference_anchor"] == "off"  # from Settings › Services
    assert params["keep_reference_wardrobe"] is False  # from the request
    assert params["lighting_continuity"] == "auto"  # the default
    assert "generated_reference_image_prompt" not in params


# ── Visible: generation details ───────────────────────────────────────────

def test_generation_details_show_the_shared_reference():
    details = director_pipeline._public_pipeline_generation_details({
        "pipeline_type": "short_film_story",
        "reference_anchor": "always",
        "generated_reference_image_filename": "anchor.png",
        "generated_reference_image_prompt": "Create a character reference…",
    })
    assert details["reference_anchor"] == {
        "mode": "always", "source": "generated", "filename": "anchor.png",
        "prompt": "Create a character reference…",
    }
    assert details["lighting_continuity"] == "auto" and details["keep_reference_wardrobe"] is True
    user = director_pipeline._public_pipeline_generation_details({
        "pipeline_type": "short_film_story", "reference_image_path": "/uploads/me.png",
    })
    assert user["reference_anchor"] == {"mode": "always", "source": "user", "filename": "me.png"}
    legacy = director_pipeline._public_pipeline_generation_details({"pipeline_type": "short_film_story"})
    assert legacy["reference_anchor"] == {"mode": "always", "source": "none"}  # saved before the option


def test_direct_video_and_comic_runs_have_no_shared_reference_details():
    details = director_pipeline._public_pipeline_generation_details({
        "pipeline_type": "music_video",
        "music_video_treatment": {"generation_mode": "direct_video"},
    })
    assert "reference_anchor" not in details
    comic = director_pipeline._public_pipeline_generation_details({"pipeline_type": "comic_movie"})
    assert "reference_anchor" not in comic and "lighting_continuity" not in comic


# ── Replace and clear from the Dashboard, then repair ─────────────────────

PID = "anchor-test"


def _saved_run(tmp_path: Path) -> Path:
    for name in ("anchor.png", "shot-0.png", "shot-1.png"):
        (tmp_path / name).write_bytes(b"image")
    state = {
        "pipeline_id": PID, "status": "completed", "pipeline_type": "short_film_story",
        "image_model": "qwen_image_21", "video_model": "ltx2_22B_distilled_1_1",
        "generated_reference_image_filename": "anchor.png",
        "clips": [
            {"index": 0, "image_prompt": "A fox in a birch forest.", "start_image_filename": "shot-0.png"},
            {"index": 1, "image_prompt": "The fox at a river.", "start_image_filename": "shot-1.png"},
        ],
        "clip_plans": [{"image_prompt": "A fox in a birch forest."}, {"image_prompt": "The fox at a river."}],
        "output_files": ["shot-0.png", "shot-1.png"],
        "workspace": "default",
        "_params_snapshot": {
            "pipeline_type": "short_film_story", "reference_anchor": "always",
            "generated_reference_image_filename": "anchor.png",
            "generated_reference_image_prompt": "Create a character reference…",
        },
    }
    path = tmp_path / f"{director_pipeline._PIPELINE_FILE_PREFIX}{PID}.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _put(tmp_path: Path, filename):
    app = FastAPI()
    app.include_router(create_director_review_router(lambda _name: str(tmp_path)))
    return TestClient(app).put(
        f"/api/v1/director/pipelines/{PID}/anchor",
        json={"workspace": "default", "filename": filename},
    )


def _rerun(tmp_path: Path, clip_index: int) -> dict:
    submitted: list[dict] = []

    def submit(gen_params, **_kwargs):
        submitted.append(gen_params)
        (tmp_path / "rerun.png").write_bytes(b"image")
        return ["rerun.png"]

    with _wgp(tmp_path), patch.object(director_pipeline, "_submit_and_wait", side_effect=submit):
        director_pipeline.rerun_clip_image(str(tmp_path), PID, clip_index)
    return submitted[0]


def test_a_repair_draws_from_the_shared_reference_by_default(tmp_path):
    _saved_run(tmp_path)
    assert _names(_rerun(tmp_path, 1)["image_refs"]) == ["anchor.png"]


def test_replace_makes_a_run_image_the_shared_reference(tmp_path):
    path = _saved_run(tmp_path)
    response = _put(tmp_path, "shot-1.png")
    assert response.status_code == 200, response.text
    assert response.json()["generation_details"]["reference_anchor"] == {
        "mode": "always", "source": "generated", "filename": "shot-1.png", "prompt": "",
    }
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["generated_reference_image_filename"] == "shot-1.png"
    assert saved["_params_snapshot"]["generated_reference_image_filename"] == "shot-1.png"
    assert _names(_rerun(tmp_path, 0)["image_refs"]) == ["shot-1.png"]


def test_clear_stops_repairs_and_reruns_from_using_it(tmp_path):
    path = _saved_run(tmp_path)
    response = _put(tmp_path, None)
    assert response.status_code == 200, response.text
    assert response.json()["generation_details"]["reference_anchor"] == {"mode": "off", "source": "none"}
    sent = _rerun(tmp_path, 1)
    # Neither the old picture nor shot 1 (the legacy fallback) is used again.
    assert sent["image_refs"] == [] and sent["video_prompt_type"] == ""
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["generated_reference_image_filename"] is None
    assert saved["_params_snapshot"]["reference_anchor"] == "off"


@pytest.mark.parametrize("filename", ["../elsewhere.png", "missing.png", "notes.txt"])
def test_replace_accepts_only_images_of_this_run(tmp_path, filename):
    path = _saved_run(tmp_path)
    before = path.read_bytes()
    assert _put(tmp_path, filename).status_code == 422
    assert path.read_bytes() == before


def test_the_users_own_reference_is_not_replaced_here(tmp_path):
    path = _saved_run(tmp_path)
    state = json.loads(path.read_text(encoding="utf-8"))
    state["reference_image_path"] = str(tmp_path / "mine.png")
    path.write_text(json.dumps(state), encoding="utf-8")
    assert _put(tmp_path, None).status_code == 422


def test_a_busy_run_refuses_the_change(tmp_path):
    _saved_run(tmp_path)
    with patch.dict(director_pipeline._pipelines, {PID: {"status": "running"}}):
        assert _put(tmp_path, None).status_code == 409


# ── 8.7: the deterministic fallback plan is visible and has no style filler ──

def test_a_fallback_plan_is_marked_and_has_no_cinematic_filler():
    responses = iter([
        "INT. HARBOUR - DAWN\n\nMara waits on the pier.\n\nThe ferry arrives and she boards.",
        "Prose instead of shots.",
        "More prose.",
    ])

    def provider(**_kwargs):
        return next(responses)

    plan = ShortFilmPlanner(llm_generate=provider, llm_generate_streaming=provider).plan(
        story_description="Mara leaves the island.", target_duration=40, target_scenes=2,
        fps=24, frames_steps=8, frames_minimum=41,
    )
    assert plan.planning_source == "deterministic_fallback"
    assert plan.to_dict()["planning_source"] == "deterministic_fallback"
    texts = [
        text.lower() for shot in plan.shots
        for text in (shot.image_prompt or "", shot.video_prompt or "", shot.visual_style or "", shot.lighting or "")
    ]
    assert texts and not any("cinematic" in text for text in texts)


def test_the_saved_run_records_where_its_plan_came_from(tmp_path):
    record = {
        "id": "fallback", "status": "running", "phase": "planning", "progress": {},
        "clip_plans": [], "clip_images": [], "output_files": [], "created_at": time.time(),
        "params": {"pipeline_type": "short_film_story"}, "out_dir": str(tmp_path),
        "planning_source": "deterministic_fallback",
    }
    with _wgp(tmp_path), patch.dict(director_pipeline._pipelines, {"fallback": record}):
        assert director_pipeline._save_pipeline_state("fallback")
    saved = json.loads((tmp_path / f"{director_pipeline._PIPELINE_FILE_PREFIX}fallback.json").read_text(encoding="utf-8"))
    assert saved["planning_source"] == "deterministic_fallback"


# ══ Wall 2: light and clothes from the reference ═════════════════════════

LIGHT = "color temp from reference image"
GOWN = "The singer now in a red evening gown stands on the stage. She is running toward the crowd, lost in the moment. Soft light."
CLEANED = "The singer now in a red evening stands on the stage. Soft light."


class _Planner(BasePlanner):
    def plan(self, **_kwargs):  # pragma: no cover - not used
        return ProductionPlan(skill_type="test", shots=[])


def _options(*, user: bool, any_ref: bool, **attributes) -> dict:
    planner = _Planner()
    for name, value in attributes.items():
        setattr(planner, name, value)
    return planner._image_rule_options(has_user_reference=user, has_any_reference=any_ref)


# ── The light rule ────────────────────────────────────────────────────────

def test_the_text_to_image_rules_never_end_with_the_reference_light():
    # No reference exists when the plan is written with this guide.
    assert LIGHT not in get_image_prompt_rules(False)
    assert LIGHT not in get_image_prompt_rules(False, **_options(user=False, any_ref=False))
    guide = (Path(image_prompt_rules.__file__).parents[1] / "llm_guides" / "director" / "flux_image_generation.md")
    assert LIGHT not in guide.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("image_model", ["flux2_klein_9b", "qwen_image_21"])
def test_auto_light_copies_the_reference_only_with_the_users_reference_image(image_model):
    with_user = get_image_prompt_rules(True, image_model=image_model, **_options(user=True, any_ref=True))
    cast_only = get_image_prompt_rules(True, image_model=image_model, **_options(user=False, any_ref=True))
    assert LIGHT in with_user
    assert LIGHT not in cast_only
    # Only the separate rule carries it: the edit guides no longer do.
    assert LIGHT not in prepare_guide(image_prompt_rules.load_guide(image_prompt_rules._route_image_pass2_guide(image_model)))


def test_reference_and_per_shot_light_override_auto():
    assert _options(user=False, any_ref=True, lighting_continuity="reference")["lighting_from_reference"] is True
    assert _options(user=True, any_ref=True, lighting_continuity="per_shot")["lighting_from_reference"] is False
    rules = get_image_prompt_rules(True, image_model="qwen_image_21", **_options(
        user=True, any_ref=True, lighting_continuity="per_shot",
    ))
    assert LIGHT not in rules


def _story_prompts(**plan_kwargs) -> tuple[list[str], ProductionPlan]:
    """Plan a story with a provider that answers in prose; return its system prompts."""
    prompts: list[str] = []
    responses = iter([
        "INT. HARBOUR - DAWN\n\nMara waits on the pier.\n\nThe ferry arrives and she boards.",
        "Prose instead of shots.",
        "More prose.",
    ])

    def provider(**kwargs):
        prompts.append(str(kwargs.get("system_prompt") or ""))
        return next(responses)

    planner = ShortFilmPlanner(llm_generate=provider, llm_generate_streaming=provider)
    plan = planner.plan(
        story_description="Mara leaves the island.", target_duration=40, target_scenes=2,
        fps=24, frames_steps=8, frames_minimum=41, image_model="qwen_image_21", **plan_kwargs,
    )
    return prompts, plan


def test_a_story_with_character_references_only_no_longer_copies_the_anchors_light(tmp_path):
    portrait = tmp_path / "mara.png"
    portrait.write_bytes(b"image")
    prompts, _plan = _story_prompts(character_ref_paths=[str(portrait)], character_ref_labels=["Mara"])
    assert any("NEVER NAME GARMENTS" in prompt for prompt in prompts)  # the edit guide was used
    assert not any(LIGHT in prompt for prompt in prompts)
    prompts, _plan = _story_prompts(reference_image_path=str(portrait))
    assert any(LIGHT in prompt for prompt in prompts)


def test_the_music_video_aesthetic_block_follows_the_same_flag():
    def plan_prompts(lighting: str) -> str:
        prompts: list[str] = []

        def provider(**kwargs):
            prompts.append(str(kwargs.get("system_prompt") or ""))
            return json.dumps([])

        planner = MusicVideoPlanner(llm_generate=provider)
        planner.lighting_continuity = lighting
        with pytest.raises(RuntimeError):
            planner.plan(
                clips=[{"start": 0, "end": 4, "label": "intro", "beat_count": 8}],
                scene_description="A singer at a harbour.", bpm=120,
                reference_image_path="/uploads/singer.png", image_model="qwen_image_21",
            )
        return prompts[0]

    assert "VISUAL AESTHETIC" in plan_prompts("auto") and LIGHT in plan_prompts("auto")
    per_shot = plan_prompts("per_shot")
    assert "VISUAL AESTHETIC" not in per_shot and LIGHT not in per_shot


# ── With no reference of any kind ─────────────────────────────────────────

def test_shared_reference_off_and_no_refs_gives_the_reference_free_guide():
    options = _options(user=False, any_ref=False, reference_anchor="off")
    assert options["reference_free"] is True
    rules = get_image_prompt_rules(False, **options)
    assert "Nth image" not in rules and "attire from reference" not in rules and LIGHT not in rules
    assert "There is no reference image" in rules
    # The default still draws a shared reference, so the guide keeps the reference wording.
    assert "Nth image" in get_image_prompt_rules(False, **_options(user=False, any_ref=False))
    assert "<!--" not in rules


# ── Clothes from references ───────────────────────────────────────────────

@pytest.mark.parametrize("image_model", ["flux2_klein_9b", "qwen_image_21"])
def test_keep_wardrobe_off_drops_the_clothing_block(image_model):
    kept = get_image_prompt_rules(True, image_model=image_model)
    dropped = get_image_prompt_rules(True, image_model=image_model, keep_wardrobe=False)
    assert "NEVER NAME GARMENTS" in kept and "bikini, bra, lingerie" in kept
    assert "NEVER NAME GARMENTS" not in dropped and "bikini, bra, lingerie" not in dropped
    assert "<!--" not in kept and "<!--" not in dropped
    assert "Do NOT invent or describe clothing" not in get_image_prompt_rules(False, keep_wardrobe=False)


def test_the_pass2_cleanup_counts_what_it_removes():
    shots = [{"image_prompt": GOWN, "keyframe_prompts": [GOWN, 3]}, {"image_prompt": "A quiet room."}]
    sanitize_pass2_image_prompts(shots)
    assert shots[0]["image_prompt"] == CLEANED
    assert shots[0]["keyframe_prompts"] == [CLEANED, 3]
    assert shots[0]["_prompt_cleanup"] == {"garments": 2, "motion_sentences": 2, "fillers": 2}
    assert "_prompt_cleanup" not in shots[1]


def test_keep_wardrobe_off_keeps_clothing_words():
    shots = [{"image_prompt": GOWN}]
    sanitize_pass2_image_prompts(shots, keep_wardrobe=False)
    assert "red evening gown" in shots[0]["image_prompt"]
    assert shots[0]["_prompt_cleanup"] == {"garments": 0, "motion_sentences": 1, "fillers": 1}


@pytest.mark.parametrize("keep", [True, False])
def test_the_pass3_image_cleanup_follows_keep_wardrobe(keep):
    # Pass 3 polish (Settings › Services › prompt polish "3rd pass") runs the
    # same cleanup after its LLM; with Keep clothes off it keeps them too.
    plan = [{"video_prompt": "", "image_prompt": "The singer now in a red evening gown stands on the stage. Soft light."}]
    with patch("services.llm_service.enhance_prompt", side_effect=lambda **kwargs: kwargs["prompt"]):
        result = polish_prompts_third_pass(
            plan, "ltx2_22B_distilled_1_1", "qwen_image_21",
            polish_video_prompts=False, keep_wardrobe=keep,
        )
    assert ("evening gown" in result[0]["image_prompt"]) is (not keep)


def test_raw_prompts_leave_the_pass2_prompts_as_written():
    shots = [{"image_prompt": GOWN, "keyframe_prompts": [GOWN]}]
    sanitize_pass2_image_prompts(shots, raw_prompts=True)
    assert shots == [{"image_prompt": GOWN, "keyframe_prompts": [GOWN]}]


# ── The counts land in the shot metadata and Extra info ───────────────────

def _music_shot(image_prompt: str) -> dict:
    return {
        "clip_index": 1, "scene_goal": "The singer waits", "scene_type": "performance",
        "subjects_on_screen": [], "environment": "A stage", "visual_style": "anime",
        "lighting": "soft", "mood": "calm", "action_beats": ["She waits"],
        "camera_plan": {"framing": "medium shot", "movement": "slow push in", "movement_intensity": "subtle"},
        "ending_beat": "She smiles", "image_source": "original", "image_prompt": image_prompt,
        "visual_changes": [], "video_prompt": "The camera slowly pushes in while the singer smiles at the crowd.",
        "keyframe_prompts": [], "window_prompts": [],
    }


def _music_plan(**attributes) -> ProductionPlan:
    planner = MusicVideoPlanner(llm_generate=lambda **_kwargs: json.dumps([_music_shot(GOWN)]))
    for name, value in attributes.items():
        setattr(planner, name, value)
    return planner.plan(
        clips=[{"start": 0, "end": 4, "label": "verse", "beat_count": 8}],
        scene_description="A singer on a stage.", bpm=120,
    )


def test_the_counts_land_in_the_shot_metadata():
    shot = _music_plan().shots[0]
    assert shot.image_prompt == CLEANED
    assert shot.metadata["prompt_cleanup"] == {"garments": 1, "motion_sentences": 1, "fillers": 1}
    raw = _music_plan(raw_prompts=True).shots[0]
    assert raw.image_prompt == GOWN and "prompt_cleanup" not in raw.metadata
    kept = _music_plan(keep_reference_wardrobe=False).shots[0]
    assert "red evening gown" in kept.image_prompt


def test_extra_info_shows_what_was_removed_before_the_model():
    pipeline = {
        "clips": [{"index": 0, "video_filename": "take.mp4"}, {"index": 1, "video_filename": "other.mp4"}],
        "clip_plans": [
            {"metadata": {"prompt_cleanup": {"garments": 2, "motion_sentences": 1, "fillers": 0}}},
            {"metadata": {}},
        ],
    }
    clip = build_saved_clip_info("take.mp4", {"params": {}}, pipeline=pipeline)
    assert clip["prompt_cleanup"] == {"garments": 2, "motion_sentences": 1, "fillers": 0}
    assert build_saved_clip_info("other.mp4", {"params": {}}, pipeline=pipeline)["prompt_cleanup"] == {}
    assert build_saved_clip_info("take.mp4", {"params": {}})["prompt_cleanup"] == {}


# ── Request → Settings › Services → default, for the v2 plan endpoint too ──

def test_the_orchestrator_gives_planners_the_resolved_options():
    seen: list[tuple] = []

    class _Recorder:
        def __init__(self, **_kwargs):
            pass

        def plan(self, **_kwargs):
            seen.append((self.reference_anchor, self.lighting_continuity, self.keep_reference_wardrobe))
            return ProductionPlan(skill_type="music_video", shots=[])

    services = {"director_lighting_continuity": "per_shot", "director_keep_reference_wardrobe": False}
    wgp = SimpleNamespace(server_config={"services": services})
    flags = DirectorFlags.from_dict({"reference_anchor": "off"})  # a v2 plan request's director_flags
    with patch.dict("sys.modules", {"wgp": wgp}), \
            patch.dict(director_orchestrator._PLANNER_MAP, {"music_video": _Recorder}):
        DirectorOrchestrator(flags=flags).plan("music_video")
        DirectorOrchestrator().plan("music_video")
    assert seen == [("off", "per_shot", False), ("always", "per_shot", False)]

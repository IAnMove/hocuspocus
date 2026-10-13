"""Director layers in their narrow scope.

The no-visible-text lock is added only to the prompts the LLM wrote in a sung
project (a music video). A prompt the user types never gets it. The
"Maintain the same ... art style." prefix is added only for Flux.2 Klein.
"""
from __future__ import annotations

import ast
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import director_pipeline
from app.services.director.policies import (
    no_visible_text_lock_applies,
    project_has_lyrics,
)

LOCK = "NO VISIBLE TEXT LOCK:"
LYRIC = "Despierta dentro de mí"
LETTERING = f"The singer raises one hand. Text overlays: '{LYRIC}'. The camera pushes in."
STYLE = "black and white hand-drawn pencil sketch"
PREFIX = f"Maintain the same {STYLE} art style. "
RUNTIME = Path(__file__).resolve().parents[1] / "app" / "_launch_runtime.py"


def _wgp(**extra):
    return patch.object(
        director_pipeline,
        "_wgp",
        SimpleNamespace(server_config={"services": {}}, **extra),
    )


# ── Which projects are sung ─────────────────────────────────────────────

@pytest.mark.parametrize(
    ("params", "sung"),
    [
        ({"pipeline_type": "music_video"}, True),
        ({}, True),  # the Director's workflow when a project saved none
        ({"pipeline_type": "short_film_story"}, False),
        ({"pipeline_type": "short_film_audio", "lyrics": "Hello, are you there?"}, False),
        ({"pipeline_type": "comic_movie"}, False),
    ],
)
def test_only_music_videos_are_sung(params, sung):
    assert project_has_lyrics(params) is sung


def test_the_lock_needs_a_sung_project_that_does_not_allow_text():
    assert no_visible_text_lock_applies({"pipeline_type": "music_video"}) is True
    assert no_visible_text_lock_applies(
        {"pipeline_type": "music_video", "allow_clip_text": True},
    ) is False
    assert no_visible_text_lock_applies({"pipeline_type": "short_film_story"}) is False


# ── Prompts the LLM wrote ────────────────────────────────────────────────

def _plan_legacy(pipeline_type: str, **params):
    plans = [{"image_prompt": LETTERING, "video_prompt": LETTERING}]
    with patch("services.llm_service.plan_clip_prompts_and_images", return_value=plans), \
            patch(
                "services.llm_service.plan_short_film_from_story",
                return_value={"clips": [{}], "clip_plans": plans},
            ):
        clip_plans, _ = director_pipeline._run_planning_legacy(
            "narrow", {"pipeline_type": pipeline_type, **params}, pipeline_type,
        )
    return clip_plans[0]


def test_a_music_video_plan_gets_the_lock():
    plan = _plan_legacy("music_video")
    for field in ("image_prompt", "video_prompt"):
        assert plan[field].startswith(LOCK)
        assert LYRIC not in plan[field]
        assert "The singer raises one hand" in plan[field]


def test_a_music_video_that_allows_text_keeps_its_lettering():
    plan = _plan_legacy("music_video", allow_clip_text=True)
    assert plan["video_prompt"] == LETTERING


def test_a_story_plan_has_no_lock():
    plan = _plan_legacy("short_film_story")
    assert plan["image_prompt"] == LETTERING
    assert plan["video_prompt"] == LETTERING


def test_a_saved_prompt_rerun_gets_the_lock_only_in_a_music_video():
    snapshot = {"preserve_visual_style": True, "visual_style": "European comic art, ink lines"}
    with _wgp():
        sung = director_pipeline._saved_prompt_contract(
            {"pipeline_type": "music_video", "_params_snapshot": snapshot}, LETTERING, "image",
        )
        story = director_pipeline._saved_prompt_contract(
            {"pipeline_type": "short_film_story", "_params_snapshot": snapshot}, LETTERING, "image",
        )
    assert sung.startswith(LOCK) and LYRIC not in sung
    # The story keeps the style lock it asked for; only the text lock is gone.
    assert LOCK not in story and LYRIC in story and "VISUAL STYLE LOCK:" in story


# ── Prompts the user typed (direct-video H3 segment edit) ───────────────

def _h3_state(tmp_path: Path, pipeline_type: str) -> dict:
    segment = "The singer walks through the archive. Text appears: 'SOY LIBRE'."
    (tmp_path / "old_0.mp4").write_bytes(b"video")
    state = {
        "pipeline_id": "segment",
        "created_at": time.time(),
        "status": "completed",
        "pipeline_type": pipeline_type,
        "video_model": "minimax_h3_legacy",
        "video_params": {"resolution": "960x544", "h3_reference_mode": "first_frame"},
        "clips": [{
            "index": 0,
            "video_prompt": segment,
            "planned_clip": {"duration_sec": 5},
            "h3_segments": [{
                "index": 0,
                "filename": "old_0.mp4",
                "prompt": segment,
                "frames": 124,
                "seed": 900,
                "reference_mode": "first_frame",
                "stale": False,
            }],
        }],
        "clip_plans": [{"video_prompt": segment}],
        "output_files": ["old_0.mp4"],
        "workspace": "default",
        "_params_snapshot": {"pipeline_type": pipeline_type, "master_seed": 900},
    }
    path = tmp_path / "_director_pipeline_segment.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return state


def _rerun_direct_segment(tmp_path: Path, pipeline_type: str, typed: str | None = None) -> str:
    _h3_state(tmp_path, pipeline_type)
    submitted: list[dict] = []

    def submit(params, **_kwargs):
        submitted.append(params)
        (tmp_path / "new.mp4").write_bytes(b"new video")
        return ["new.mp4"]

    with patch.object(
        director_pipeline,
        "_direct_video_settings",
        return_value=(True, "IMMUTABLE PAINTED WORLD."),
    ), patch.object(director_pipeline, "_submit_and_wait", side_effect=submit):
        director_pipeline.rerun_h3_segment(
            str(tmp_path), "segment", 0, 0, prompt_override=typed, cascade=False,
        )
    assert len(submitted) == 1
    return submitted[0]["prompt"]


def test_a_typed_direct_video_segment_keeps_its_lettering(tmp_path: Path):
    prompt = _rerun_direct_segment(
        tmp_path, "music_video", typed="A neon wall. Text appears: 'ABIERTO'.",
    )
    assert LOCK not in prompt
    assert "ABIERTO" in prompt


def test_a_saved_direct_video_segment_gets_the_lock_only_in_a_music_video(tmp_path: Path):
    (tmp_path / "sung").mkdir()
    (tmp_path / "story").mkdir()
    sung = _rerun_direct_segment(tmp_path / "sung", "music_video")
    story = _rerun_direct_segment(tmp_path / "story", "short_film_story")
    assert LOCK in sung and "SOY LIBRE" not in sung
    assert LOCK not in story and "SOY LIBRE" in story


def test_the_v2_plan_endpoint_decides_the_lock_with_the_shared_rule():
    tree = ast.parse(RUNTIME.read_text(encoding="utf-8"))
    endpoint = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_director_v2_plan_body"
    )
    calls = [node for node in ast.walk(endpoint) if isinstance(node, ast.Call)]
    called = {getattr(call.func, "id", getattr(call.func, "attr", "")) for call in calls}
    assert "no_visible_text_lock_applies" in called
    for call in calls:
        name = getattr(call.func, "id", getattr(call.func, "attr", ""))
        if not name.startswith("enforce_"):
            continue
        for keyword in call.keywords:
            if keyword.arg == "allow_clip_text":
                # The raw flag alone would lock stories too.
                assert "body" not in ast.unparse(keyword.value)


# ── Style prefix: Flux.2 Klein only ─────────────────────────────────────

@pytest.mark.parametrize(
    "model",
    ["flux2_klein_9b", "flux2_klein_4b", "flux2_klein_base_9b", "flux2_klein_base_4b"],
)
def test_klein_models_get_the_style_prefix(model):
    with _wgp():
        assert director_pipeline._style_prefix_for(STYLE, model) == PREFIX


@pytest.mark.parametrize(
    "model",
    ["qwen_image_edit_plus_20b", "flux2_dev", "flux_dev_kontext", "z_image", "minimax:image-01", ""],
)
def test_other_image_models_get_no_style_prefix(model):
    with _wgp():
        assert director_pipeline._style_prefix_for(STYLE, model) == ""


def test_a_finetune_follows_its_architecture():
    architectures = {"my_ink_finetune": "flux2_klein_9b", "my_qwen_finetune": "qwen_image_edit_plus_20b"}
    with _wgp(get_base_model_type=architectures.get):
        assert director_pipeline._style_prefix_for(STYLE, "my_ink_finetune") == PREFIX
        assert director_pipeline._style_prefix_for(STYLE, "my_qwen_finetune") == ""
    with _wgp():
        assert director_pipeline._style_prefix_for("", "flux2_klein_9b") == ""


def _rerun_image(tmp_path: Path, image_model: str) -> str:
    state = {
        "pipeline_id": "styled",
        "created_at": time.time(),
        "status": "completed",
        "pipeline_type": "short_film_story",
        "image_model": image_model,
        "video_model": "ltx2_22B_distilled_1_1",
        "clips": [{"index": 0, "image_prompt": "A fox waits in a birch forest."}],
        "clip_plans": [{"image_prompt": "A fox waits in a birch forest."}],
        "workspace": "default",
        "_params_snapshot": {"pipeline_type": "short_film_story", "_reference_style": STYLE},
    }
    (tmp_path / "_director_pipeline_styled.json").write_text(json.dumps(state), encoding="utf-8")
    submitted: list[dict] = []

    def submit(params, **_kwargs):
        submitted.append(params)
        (tmp_path / "fox.png").write_bytes(b"image")
        return ["fox.png"]

    with _wgp(save_path=str(tmp_path)), \
            patch.object(director_pipeline, "_submit_and_wait", side_effect=submit):
        director_pipeline.rerun_clip_image(str(tmp_path), "styled", 0)
    assert len(submitted) == 1
    return submitted[0]["prompt"]


def test_a_klein_image_rerun_gets_the_prefix(tmp_path: Path):
    assert _rerun_image(tmp_path, "flux2_klein_9b") == PREFIX + "A fox waits in a birch forest."


def test_a_qwen_image_rerun_is_sent_as_planned(tmp_path: Path):
    assert _rerun_image(tmp_path, "qwen_image_edit_plus_20b") == "A fox waits in a birch forest."


def _generate_images(tmp_path: Path, image_model: str) -> list[str]:
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"image")
    params = {
        "pipeline_type": "short_film_story",
        "reference_image_path": str(reference),
        "image_model": image_model,
        "_reference_style": STYLE,
    }
    record = {
        "id": "images",
        "status": "running",
        "phase": "generating_images",
        "progress": {},
        "clip_plans": [],
        "clip_images": [],
        "output_files": [],
        "created_at": time.time(),
        "params": params,
        "pause_reason": None,
        "out_dir": str(tmp_path),
    }
    submitted: list[str] = []

    def submit(gen_params, **_kwargs):
        submitted.append(gen_params["prompt"])
        name = f"shot-{len(submitted)}.png"
        (tmp_path / name).write_bytes(b"image")
        return [name]

    with _wgp(save_path=str(tmp_path)), \
            patch.dict(director_pipeline._pipelines, {"images": record}), \
            patch.object(director_pipeline, "_submit_and_wait", side_effect=submit):
        director_pipeline._run_image_generation(
            "images", params, [{"image_prompt": "A fox waits in a birch forest."}],
            out_dir=str(tmp_path),
        )
    return submitted


def test_klein_start_images_get_the_prefix(tmp_path: Path):
    assert _generate_images(tmp_path, "flux2_klein_9b") == [PREFIX + "A fox waits in a birch forest."]


def test_other_models_start_images_are_sent_as_planned(tmp_path: Path):
    assert _generate_images(tmp_path, "qwen_image_edit_plus_20b") == ["A fox waits in a birch forest."]


# ── Review follow-ups (2026-10-13) ──────────────────────────────────────

def _services(**services):
    return patch.object(
        director_pipeline, "_wgp", SimpleNamespace(server_config={"services": services}),
    )


@pytest.mark.parametrize(
    ("params", "services", "wanted"),
    [
        ({"image_model": "flux2_klein_9b"}, {}, True),
        ({}, {}, True),  # the Director's default image model is Klein 9B
        ({"image_model": "qwen_image_edit_plus_20b"}, {}, False),
        ({"image_model": "flux2_klein_9b", "_reference_style": ""}, {}, False),  # resume
        ({"image_model": "flux2_klein_9b"}, {"raw_prompts": True}, False),  # no prefix with raw
    ],
)
def test_the_style_vision_call_runs_only_when_the_prefix_is_used(params, services, wanted):
    with _services(**services):
        assert director_pipeline._reference_style_wanted(params) is wanted


def test_prompts_approved_in_the_review_screen_are_typed():
    # The UI's direct-video review sends its approved prompts as
    # provided_clip_plans: the LLM's keep the lock the plan endpoint gave
    # them, and the user's edit keeps its lettering.
    params = {"pipeline_type": "music_video"}
    with _services():
        planned = director_pipeline._apply_direct_video_contract(
            [{"video_prompt": "Rain on a dark street."}], params, "Night city.",
        )
        approved = [planned[0], {"video_prompt": "A neon sign reads 'OPEN' in the rain."}]
        plans = director_pipeline._approved_review_plans(approved)
        sent = director_pipeline._apply_direct_video_contract(plans, params, "Night city.")
    assert sent[0]["video_prompt"].count(LOCK) == 1
    assert LOCK not in sent[1]["video_prompt"] and "'OPEN'" in sent[1]["video_prompt"]
    assert "_director_typed_prompts" not in approved[1]
    assert director_pipeline._approved_review_plans([]) is None
    assert director_pipeline._approved_review_plans(None) is None


def test_a_story_edit_at_the_review_pause_gets_no_lock_and_a_music_video_edit_keeps_its_lettering():
    edited = "A shop window with a hand-painted sign reading 'OPEN'."
    for pipeline_type in ("short_film_story", "music_video"):
        params = {"pipeline_type": pipeline_type}
        with _services():
            shown = director_pipeline._apply_final_prompt_locks(
                [{"image_prompt": LETTERING}, {"image_prompt": LETTERING}], params,
            )
            with patch.dict(director_pipeline._pipelines, {"pause": {"status": "paused", "clip_plans": shown}}):
                director_pipeline.continue_pipeline(
                    "pause", {"clip_plans": [{"image_prompt": edited}, dict(shown[1])]},
                )
                reviewed = director_pipeline._pipelines["pause"]["clip_plans"]
            rechecked = director_pipeline._apply_final_prompt_locks(reviewed, params)
        assert rechecked[0]["image_prompt"] == edited
        assert (LOCK in rechecked[1]["image_prompt"]) is (pipeline_type == "music_video")



@pytest.mark.parametrize("direct_video", [True, False])
def test_a_segment_regenerate_keeps_a_prompt_typed_at_the_review_pause(tmp_path: Path, direct_video: bool):
    # Regenerate one H3 segment without typing a new prompt: a music-video
    # shot the user typed at the review pause never gets the no-text lock back.
    segment = "The singer walks through the archive. Text appears: 'SOY LIBRE'."
    (tmp_path / "old_0.mp4").write_bytes(b"video")
    (tmp_path / "start.png").write_bytes(b"start")
    sent: dict[str, str] = {}
    for typed in (["video_prompt"], []):
        state = {
            "pipeline_id": "typed",
            "created_at": time.time(),
            "status": "completed",
            "pipeline_type": "music_video",
            "video_model": "minimax_h3_legacy" if direct_video else "minimax_h3",
            "video_params": {"resolution": "960x544", "h3_reference_mode": "first_frame"},
            "clips": [{
                "index": 0,
                "start_image_filename": "start.png",
                "video_prompt": segment,
                "planned_clip": {"duration_sec": 5},
                "h3_segments": [{
                    "index": 0, "filename": "old_0.mp4", "prompt": segment, "frames": 124,
                    "seed": 900, "reference_mode": "first_frame", "stale": False,
                }],
            }],
            "clip_plans": [{"video_prompt": segment, "_director_typed_prompts": typed}],
            "output_files": ["old_0.mp4"],
            "workspace": "default",
            "_params_snapshot": {"pipeline_type": "music_video", "master_seed": 900},
        }
        (tmp_path / "_director_pipeline_typed.json").write_text(json.dumps(state), encoding="utf-8")
        submitted: list[dict] = []

        def submit(params, **_kwargs):
            submitted.append(params)
            (tmp_path / "new.mp4").write_bytes(b"new video")
            return ["new.mp4"]

        with _wgp(), patch.object(
            director_pipeline,
            "_direct_video_settings",
            return_value=(True, "IMMUTABLE PAINTED WORLD.") if direct_video else (False, ""),
        ), patch.object(director_pipeline, "_submit_and_wait", side_effect=submit):
            director_pipeline.rerun_h3_segment(str(tmp_path), "typed", 0, 0, cascade=False)
        assert len(submitted) == 1
        sent["typed" if typed else "planned"] = submitted[0]["prompt"]
    assert LOCK not in sent["typed"] and "SOY LIBRE" in sent["typed"]
    assert LOCK in sent["planned"] and "SOY LIBRE" not in sent["planned"]

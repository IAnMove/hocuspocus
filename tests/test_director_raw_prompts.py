"""Raw prompts: the Director sends a prompt exactly as planned; a prompt the user types keeps its lettering."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.services import director_pipeline

# A music video: the no-visible-text lock is for sung projects only
# (tests/test_director_narrow_locks.py covers stories).
STATE = {
    "pipeline_type": "music_video",
    "_params_snapshot": {"preserve_visual_style": True, "visual_style": "European comic art, ink lines"},
}
PROMPT = "A shop window with a sign reading 'OPEN'."


def _services(**services):
    return patch.object(director_pipeline, "_wgp", SimpleNamespace(server_config={"services": services}))


def test_music_video_rerun_prompts_get_the_locks_by_default():
    with _services():
        sent = director_pipeline._saved_prompt_contract(STATE, PROMPT, "image")
    assert sent.startswith("NO VISIBLE TEXT LOCK") and "VISUAL STYLE LOCK:" in sent


def test_raw_prompts_send_the_plan_as_written():
    with _services(raw_prompts=True):
        assert director_pipeline._saved_prompt_contract(STATE, PROMPT, "image") == PROMPT
        assert director_pipeline._raw_prompts() is True


def test_a_prompt_the_user_typed_keeps_the_text_it_asks_for():
    with _services():
        sent = director_pipeline._saved_prompt_contract(STATE, PROMPT, "image", typed=True)
    assert "OPEN" in sent and "NO VISIBLE TEXT LOCK" not in sent and "VISUAL STYLE LOCK:" in sent


# ── Every lock pass of a Director run (2026-10-13 review gaps) ─────────────

import ast
import copy
import inspect
import re
from pathlib import Path

from app.services.director import orchestrator as director_orchestrator
from app.services.director.planners.short_film import ShortFilmPlanner
from app.services.director.schema import ProductionPlan, ShotPlan

STYLE_PARAMS = {
    "visual_style": "European comic art, ink lines",
    "preserve_visual_style": True,
    "character_visual_style": "flat cel-shaded figures",
}
PLANNED = [
    {"image_prompt": PROMPT, "video_prompt": "The shopkeeper flips the sign to 'OPEN'.",
     "window_prompts": ["A neon title card reads 'SALE'."]},
    {"image_prompt": "A street at dusk.", "video_prompt": "Cars pass the shop."},
]
LOCKS = ("VISUAL STYLE LOCK", "CHARACTER STYLE LOCK", "NO VISIBLE TEXT LOCK")


def _prompts(plans):
    return [
        text for plan in plans
        for text in (plan.get("image_prompt"), plan.get("video_prompt"), *(plan.get("window_prompts") or []))
        if text
    ]


def test_the_final_lock_pass_sends_raw_plans_as_written():
    # One helper serves the main pass, the re-check after the review pause,
    # the sequential H3 validation pass and the legacy planner.
    with _services(raw_prompts=True):
        sent = director_pipeline._apply_final_prompt_locks(copy.deepcopy(PLANNED), STYLE_PARAMS)
    assert sent == PLANNED
    with _services():
        locked = director_pipeline._apply_final_prompt_locks(copy.deepcopy(PLANNED), STYLE_PARAMS)
    assert all(all(lock in text for lock in LOCKS) for text in _prompts(locked))


def test_the_pipeline_locks_only_through_the_raw_aware_helpers():
    source = inspect.getsource(director_pipeline)
    for call, helper in (
        ("enforce_visual_style_on_clip_plans(", "_apply_final_prompt_locks"),
        ("enforce_direct_video_on_clip_plans(", "_apply_direct_video_contract"),
    ):
        assert source.count(call) == 1, call
        assert call in inspect.getsource(getattr(director_pipeline, helper))
    # The no-text switch of every H3 segment and rerun goes through _clip_text_allowed.
    assert not re.findall(
        r'^\s*(?:allow_clip_text=)?(?:direct_)?params\.get\("allow_clip_text"\) is True,?$', source, re.M,
    )


def test_raw_direct_video_gets_no_no_text_lock():
    plans = [{"video_prompt": "A neon sign reads 'OPEN' as rain falls."}]
    params = {"allow_clip_text": False}
    with _services(raw_prompts=True):
        sent = director_pipeline._apply_direct_video_contract(copy.deepcopy(plans), params, "Night city.")
        assert director_pipeline._clip_text_allowed(params) is True
    assert "NO VISIBLE TEXT LOCK" not in sent[0]["video_prompt"] and "OPEN" in sent[0]["video_prompt"]
    with _services():
        locked = director_pipeline._apply_direct_video_contract(copy.deepcopy(plans), params, "Night city.")
        assert director_pipeline._clip_text_allowed(params) is False
    assert "NO VISIBLE TEXT LOCK" in locked[0]["video_prompt"]


def test_the_legacy_planner_sends_raw_plans_as_written():
    params = {**STYLE_PARAMS, "scene_description": "A shop opens.", "planned_clips": [{}, {}]}
    with _services(raw_prompts=True), patch(
        "services.llm_service.plan_clip_prompts_and_images",
        return_value={"clip_plans": copy.deepcopy(PLANNED)},
    ):
        plans, _clips = director_pipeline._run_planning_legacy("raw-legacy", params, "music_video")
    assert plans == PLANNED
    with _services(raw_prompts=True), patch(
        "services.llm_service.plan_short_film_from_story",
        return_value={"clips": [], "clip_plans": []},
    ) as story_planner:
        director_pipeline._run_planning_legacy("raw-legacy", params, "short_film_story")
    assert story_planner.call_args.kwargs["raw_prompts"] is True


def _v2_plan_body() -> ast.FunctionDef:
    source = (Path(__file__).resolve().parents[1] / "app" / "_launch_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_director_v2_plan_body"
    )


def test_the_v2_plan_endpoint_adds_no_lock_with_raw_prompts():
    body = _v2_plan_body()
    guarded = {
        id(node.body) for node in ast.walk(body)
        if isinstance(node, ast.IfExp) and isinstance(node.test, ast.Name) and node.test.id == "raw_prompts"
        and isinstance(node.body, ast.Name) and node.body.id == "clip_plans"
    }
    lock_calls = [
        node for node in ast.walk(body)
        if isinstance(node, ast.IfExp) and isinstance(node.orelse, ast.Call)
        and getattr(node.orelse.func, "id", "") == "enforce_visual_style_on_clip_plans"
    ]
    all_lock_calls = [
        node for node in ast.walk(body)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "enforce_visual_style_on_clip_plans"
    ]
    assert len(all_lock_calls) == 2 and len(lock_calls) == 2
    assert all(id(node.body) in guarded for node in lock_calls)
    direct = next(
        node for node in ast.walk(body)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "enforce_direct_video_on_clip_plans"
    )
    text_kw = next(kw for kw in direct.keywords if kw.arg == "allow_clip_text")
    assert "raw_prompts" in ast.unparse(text_kw.value)
    assert "flags.raw_prompts = raw_prompts" in ast.unparse(body)


def _shot(**fields) -> ShotPlan:
    return ShotPlan.from_dict({
        "shot_id": "s1",
        "visual_style": "anime",
        "metadata": {"canonical_visual_style": "anime cel shading", "preserve_visual_style": True},
        **fields,
    })


def test_the_orchestrator_keeps_the_planners_words_with_raw_prompts():
    video = "She turns in the scene and smiles at the camera."
    shots = [
        _shot(video_prompt=video, image_prompt="A girl at a window.", source_mode_preference="i2v",
              image_strategy="reference_edit"),
        _shot(shot_id="s2", window_prompts=["She walks.", "She runs."], keyframe_prompts=["A girl running."]),
    ]
    plan = ProductionPlan(skill_type="short_film", shots=shots)
    flags = director_orchestrator.DirectorFlags()
    flags.raw_prompts = True
    raw = director_orchestrator.DirectorOrchestrator(flags=flags).render_plan(plan, has_reference=True)
    assert raw[0]["video_prompt"] == video and raw[0]["image_prompt"] == "A girl at a window."
    assert raw[1]["video_prompt"] == "She walks.\nShe runs." and raw[1]["keyframe_prompts"] == ["A girl running."]
    locked = director_orchestrator.DirectorOrchestrator().render_plan(plan, has_reference=True)
    assert "VISUAL STYLE LOCK" in locked[0]["video_prompt"] and "exact first frame" in locked[0]["video_prompt"]
    assert "in the scene" not in locked[0]["video_prompt"]  # compression, skipped with raw
    assert all("VISUAL STYLE LOCK" in text for text in locked[1]["keyframe_prompts"])


def test_the_orchestrator_tells_the_planner_about_raw_prompts():
    seen = []

    class _Planner:
        def __init__(self, **_):
            pass

        def plan(self, **_):
            seen.append(self.raw_prompts)
            return ProductionPlan(skill_type="music_video", shots=[])

    flags = director_orchestrator.DirectorFlags()
    flags.raw_prompts = True
    with patch.dict(director_orchestrator._PLANNER_MAP, {"music_video": _Planner}):
        director_orchestrator.DirectorOrchestrator(flags=flags).plan("music_video")
    assert seen == [True]


def test_the_story_planner_adds_no_style_lock_with_raw_prompts():
    # Pass 2 answers in prose, so the deterministic screenplay fallback plans the shots.
    responses = iter([
        "INT. ENGINE ROOM - NIGHT\n\nMara enters the silent engine room while red lights pulse. "
        "She studies the broken core.\n\nHer rivals arrive and the city lights return.",
        "Prose instead of shots.",
        "More prose.",
    ])

    def provider(**_kwargs):
        return next(responses)

    planner = ShortFilmPlanner(llm_generate=provider, llm_generate_streaming=provider)
    planner.raw_prompts = True
    plan = planner.plan(
        story_description="Mara must trust her rivals.", target_duration=40, target_scenes=2,
        fps=24, frames_steps=8, frames_minimum=41,
        visual_style="2D anime, clean cel shading", preserve_visual_style=True,
    )
    assert len(plan.shots) == 2
    assert all(shot.metadata["canonical_visual_style"] == "2D anime, clean cel shading" for shot in plan.shots)
    assert not any(
        "VISUAL STYLE LOCK" in text
        for shot in plan.shots
        for text in (shot.image_prompt or "", shot.video_prompt or "", *(shot.window_prompts or []))
    )


# ── A prompt the user edits at the review pause is typed ──────────────────


def _paused(pid: str, plans: list[dict]):
    return patch.dict(director_pipeline._pipelines, {pid: {"status": "paused", "clip_plans": plans}})


def test_a_prompt_edited_at_the_review_pause_keeps_its_lettering():
    params = {**STYLE_PARAMS, "allow_clip_text": False}
    with _services():
        shown = director_pipeline._apply_final_prompt_locks(copy.deepcopy(PLANNED), params)
        edited = copy.deepcopy(shown)
        edited[0]["image_prompt"] = "A shop window with a hand-painted sign reading 'OPEN'."
        with _paused("review-pid", shown):
            assert director_pipeline.continue_pipeline("review-pid", {"clip_plans": edited})
            reviewed = director_pipeline._pipelines["review-pid"]["clip_plans"]
        rechecked = director_pipeline._apply_final_prompt_locks(reviewed, params)
    first = rechecked[0]["image_prompt"]
    assert "'OPEN'" in first and "NO VISIBLE TEXT LOCK" not in first
    assert "VISUAL STYLE LOCK" in first and "CHARACTER STYLE LOCK" in first
    assert reviewed[0]["_director_typed_prompts"] == ["image_prompt"]
    assert rechecked[0]["video_prompt"] == shown[0]["video_prompt"]
    assert rechecked[1] == {**shown[1]} and "_director_typed_prompts" not in rechecked[1]
    state = {"clip_plans": reviewed}
    assert director_pipeline._typed_at_review(state, 0, "image_prompt")
    assert not director_pipeline._typed_at_review(state, 0, "video_prompt")
    assert not director_pipeline._typed_at_review(state, 5, "image_prompt")


def test_a_direct_video_prompt_edited_at_the_review_pause_keeps_its_lettering():
    params = {"allow_clip_text": False}
    with _services():
        shown = director_pipeline._apply_direct_video_contract(
            [{"video_prompt": "Rain on a dark street."}], params, "Night city.",
        )
        edited = [{**shown[0], "video_prompt": "A neon sign reads 'OPEN' in the rain."}]
        with _paused("review-direct", shown):
            director_pipeline.continue_pipeline("review-direct", {"clip_plans": edited})
            reviewed = director_pipeline._pipelines["review-direct"]["clip_plans"]
        rechecked = director_pipeline._apply_direct_video_contract(reviewed, params, "Night city.")
    assert "'OPEN'" in rechecked[0]["video_prompt"]
    assert "NO VISIBLE TEXT LOCK" not in rechecked[0]["video_prompt"]


def test_only_changed_prompts_are_marked_typed():
    from app.services.director.policies import mark_typed_prompt_edits

    shown = [{"image_prompt": "A cat.", "window_prompts": ["One.", "Two."]}, {"video_prompt": "Walk."}]
    edited = [
        {"image_prompt": "  A   cat. ", "window_prompts": ["One.", "Two!"]},
        {"video_prompt": "Walk.", "_director_typed_prompts": ["video_prompt", "bogus"]},
        {"image_prompt": "New shot."},
    ]
    marked = mark_typed_prompt_edits(shown, edited)
    assert marked[0]["_director_typed_prompts"] == ["window_prompts"]
    assert marked[1]["_director_typed_prompts"] == ["video_prompt"]
    assert marked[2]["_director_typed_prompts"] == ["image_prompt"]
    assert "_director_typed_prompts" not in edited[0]
    assert mark_typed_prompt_edits(shown, None) is None

from __future__ import annotations

import json

from app.services.director.orchestrator import DirectorOrchestrator
from app.services.director.planners.comic_movie import (
    ComicMoviePlanner,
    RISK_PRIORITY,
    select_representative_shot_indices,
)
from app.services.director.renderers.ltx_i2v import LtxI2VRenderer
from app.services.director.policies import enforce_visual_style_on_clip_plans


def _panel(index: int, **updates):
    panel = {
        "id": f"P{index + 1:03d}",
        "page_number": index // 4 + 1,
        "panel_number": index % 4 + 1,
        "duration": 4,
        "scene_description": f"The traveler completes story beat {index + 1}.",
        "narrative_role": "rising action",
        "image_path": f"/tmp/panel-{index + 1:03d}.png",
        "characters": ["NARA"],
        "visual_style": "hand-inked comic line art",
        "capture_width": 730,
        "capture_height": 1061,
    }
    panel.update(updates)
    return panel


def test_large_comic_fallback_becomes_a_reasonable_film_edit():
    def empty_but_valid_response(**_kwargs):
        return "[]"

    planner = ComicMoviePlanner(
        llm_generate=empty_but_valid_response,
        llm_generate_streaming=empty_but_valid_response,
    )
    panels = [_panel(index) for index in range(96)]

    first = planner.plan(comic_context="A complete journey.", comic_shots=panels)
    second = planner.plan(comic_context="A complete journey.", comic_shots=panels)

    assert 25 <= len(first.shots) <= 40
    assert len(first.shots) < len(panels)
    assert [shot.shot_id for shot in first.shots] == [
        shot.shot_id for shot in second.shots
    ]
    assert all(shot.metadata["source_panel_ids"] for shot in first.shots)
    assert all(shot.metadata["provided_image_path"] for shot in first.shots)
    assert all(shot.metadata["fit_mode"] == "contain" for shot in first.shots)
    assert sum(bool(shot.metadata["test_selected"]) for shot in first.shots) <= 6


def test_zero_target_means_auto_instead_of_one_shot_per_chunk():
    planner = ComicMoviePlanner(
        llm_generate=lambda **_kwargs: "[]",
        llm_generate_streaming=lambda **_kwargs: "[]",
    )
    panels = [_panel(index) for index in range(96)]

    automatic = planner.plan(
        comic_context="A complete journey.",
        comic_shots=panels,
    )
    zero_target = planner.plan(
        comic_context="A complete journey.",
        comic_shots=panels,
        target_shots=0,
    )

    assert len(zero_target.shots) == len(automatic.shots)
    assert 25 <= len(zero_target.shots) <= 40


def test_negative_test_sample_overrides_do_not_expand_every_panel_into_a_shot():
    planner = ComicMoviePlanner(
        llm_generate=lambda **_kwargs: "[]",
        llm_generate_streaming=lambda **_kwargs: "[]",
    )
    panels = [
        _panel(
            index,
            test_selected=False,
            test_selected_override=True,
        )
        for index in range(96)
    ]

    plan = planner.plan(
        comic_context="A complete journey.",
        comic_shots=panels,
    )

    assert 25 <= len(plan.shots) <= 40
    assert len(plan.shots) < len(panels)


def test_storyboard_contract_can_disable_fusion_and_omission():
    def must_not_adapt(**_kwargs):
        raise AssertionError("The editorial adapter must not run for storyboards")

    planner = ComicMoviePlanner(
        llm_generate=must_not_adapt,
        llm_generate_streaming=must_not_adapt,
    )
    panels = [
        _panel(
            index,
            video_prompt=(
                f"The subject completes authored storyboard action {index + 1}."
            ),
            motion_mode="action",
        )
        for index in range(12)
    ]

    plan = planner.plan(
        comic_context="An already approved storyboard.",
        comic_shots=panels,
        adapt_to_film=False,
    )

    assert len(plan.shots) == len(panels)
    assert all(
        shot.metadata["source_panel_ids"] == [f"P{index + 1:03d}"]
        for index, shot in enumerate(plan.shots)
    )


def test_long_storyboard_motion_direction_uses_bounded_complete_batches():
    calls: list[dict] = []

    def batched_motion_response(**kwargs):
        prompt = kwargs["prompt"]
        encoded_items = (
            prompt.split("PANELS IN THIS BATCH:\n", 1)[1]
            .split("\n\nReturn exactly", 1)[0]
        )
        items = json.loads(encoded_items)
        calls.append({
            "indices": [item["source_index"] for item in items],
            "scripts": [item["script_for_performance"] for item in items],
            "image_count": len(kwargs.get("image_paths") or []),
            "max_tokens": kwargs["max_new_tokens"],
            "schema": kwargs.get("json_schema"),
        })
        return json.dumps([
            {
                "source_index": item["source_index"],
                "video_prompt": (
                    "The traveler performs authored movement for source "
                    f"{item['source_index']} and settles."
                ),
            }
            for item in items
        ])

    planner = ComicMoviePlanner(
        llm_generate=batched_motion_response,
        llm_generate_streaming=batched_motion_response,
    )
    panels = [_panel(index) for index in range(96)]
    panels[0]["script"] = (
        "[Caption] The city sleeps.\n"
        "[Nara] We move now.\n"
        "[SFX] RUMBLE"
    )

    plan = planner.plan(
        comic_context="An already approved 96-panel storyboard.",
        comic_shots=panels,
        adapt_to_film=False,
    )

    assert len(plan.shots) == 96
    assert len(calls) == 8
    assert [index for call in calls for index in call["indices"]] == list(
        range(96)
    )
    assert all(1 <= len(call["indices"]) <= 12 for call in calls)
    assert all(call["image_count"] == len(call["indices"]) for call in calls)
    assert calls[0]["scripts"][0] == "Nara: We move now."
    assert all(call["max_tokens"] <= 12 * 420 for call in calls)
    assert all(
        call["schema"]["minItems"] == len(call["indices"])
        and call["schema"]["maxItems"] == len(call["indices"])
        for call in calls
    )
    assert all(
        f"authored movement for source {index}" in shot.video_prompt
        for index, shot in enumerate(plan.shots)
    )
    assert "Nara: We move now." in plan.shots[0].video_prompt


def test_contextual_quiet_portrait_defaults_to_exact_hold():
    planner = ComicMoviePlanner(
        llm_generate=lambda **_kwargs: "[]",
        llm_generate_streaming=lambda **_kwargs: "[]",
    )

    plan = planner.plan(
        comic_context="A quiet character study.",
        comic_shots=[
            _panel(
                0,
                motion_mode="contextual",
                scene_description=(
                    "Quiet close-up portrait of Nara's thoughtful face."
                ),
                narrative_role="silent reflection",
                framing="close-up portrait",
            ),
        ],
    )

    assert len(plan.shots) == 1
    assert plan.shots[0].metadata["renderer"] == "hold"
    assert plan.shots[0].metadata["motion_level"] == 0
    assert plan.shots[0].metadata["camera"] == "locked"


def test_tagged_comic_script_sends_only_real_dialogue_to_ltx_and_pre_metadata():
    planner = ComicMoviePlanner(
        llm_generate=lambda **_kwargs: "[]",
        llm_generate_streaming=lambda **_kwargs: "[]",
    )
    spoken = (
        "Nara: I kept the last seed safe, even when the desert "
        "forgot the rain."
    )

    plan = planner.plan(
        comic_context="Nara offers the final seed.",
        comic_shots=[
            _panel(
                0,
                script=(
                    "[Caption] The blue dusk settles over the ruins.\n"
                    f"[Nara] {spoken.removeprefix('Nara: ')}\n"
                    "[SFX] RUMBLE"
                ),
                scene_description="Nara offers the seed without stepping forward.",
                renderer="ltx",
                renderer_override=True,
                motion_mode="contextual",
            ),
        ],
        adapt_to_film=False,
    )

    shot = plan.shots[0]
    assert shot.metadata["dialogue"] == spoken
    assert spoken in shot.video_prompt
    assert "blue dusk settles" not in shot.video_prompt
    assert "RUMBLE" not in shot.video_prompt
    assert len(shot.video_prompt.split()) <= 110


def test_long_dialogue_is_preserved_in_metadata_but_bounded_in_motion_prompt():
    planner = ComicMoviePlanner(
        llm_generate=lambda **_kwargs: "[]",
        llm_generate_streaming=lambda **_kwargs: "[]",
    )
    spoken = "Nara: " + " ".join(f"word{index}" for index in range(55))

    plan = planner.plan(
        comic_context="A deliberately long rehearsal line.",
        comic_shots=[
            _panel(
                0,
                dialogue=spoken,
                renderer="ltx",
                renderer_override=True,
            ),
        ],
        adapt_to_film=False,
    )

    shot = plan.shots[0]
    assert shot.metadata["dialogue"] == spoken
    assert "word54" in shot.metadata["dialogue"]
    assert "word54" not in shot.video_prompt
    assert len(shot.video_prompt.split()) <= 110


def test_llm_adaptation_may_fuse_omit_and_split_panels():
    response = [
        {
            "source_panel_ids": ["P001", "P002", "P003"],
            "primary_source_panel_id": "P002",
            "action": "The traveler grips the seed, studies the guardian, then offers it.",
            "camera": "locked",
            "motion_level": 2,
            "duration_seconds": 3.5,
            "renderer": "hold",
            "fit_mode": "reframe",
            "end_beat": "the seed rests between their open hands",
            "dialogue": "",
            "narrative_role": "trust begins",
            "framing": "medium two-shot",
        },
        {
            "source_panel_ids": ["P004"],
            "primary_source_panel_id": "P004",
            "action": "The guardian slowly reaches toward the seed.",
            "camera": "locked",
            "motion_level": 2,
            "duration_seconds": 2.8,
            "renderer": "ltx",
            "fit_mode": "cover",
            "end_beat": "his fingertips stop above the seed",
            "dialogue": "",
            "narrative_role": "hesitation",
            "framing": "close-up on hands",
        },
        {
            # Repeating a source ID is an intentional split of one key panel.
            "source_panel_ids": ["P004"],
            "primary_source_panel_id": "P004",
            "action": "His fingers close around the seed and his shoulders release.",
            "camera": "locked",
            "motion_level": 2,
            "duration_seconds": 2.5,
            "renderer": "ltx",
            "fit_mode": "cover",
            "end_beat": "he holds the seed securely",
            "dialogue": "",
            "narrative_role": "acceptance",
            "framing": "close-up on hands",
        },
        {
            "source_panel_ids": [
                "P005", "P006", "P007", "P008", "P009", "P010",
            ],
            "primary_source_panel_id": "P006",
            "action": "Dust lifts as both characters kneel and press the seed into the soil.",
            "camera": "locked",
            "motion_level": 3,
            "duration_seconds": 4,
            "renderer": "ltx",
            "fit_mode": "reframe",
            "end_beat": "their hands rest together on the earth",
            "dialogue": "",
            "narrative_role": "shared action",
            "framing": "wide two-shot",
        },
    ]

    def editorial_response(**_kwargs):
        return json.dumps(response)

    planner = ComicMoviePlanner(
        llm_generate=editorial_response,
        llm_generate_streaming=editorial_response,
    )
    panels = [_panel(index) for index in range(12)]
    panels[1].update({
        "test_selected": True,
        "test_selected_override": True,
        "renderer": "ltx",
        "renderer_override": True,
        "motion_level": 1,
        "motion_level_override": True,
        "duration_seconds": 5.5,
        "duration_override": True,
        "camera_move": "push-in",
        "camera_override": True,
        "video_prompt": (
            "Locked composition. Crystal dust crosses the foreground and "
            "settles beside the traveler's hand."
        ),
        "video_prompt_override": True,
        "seed": 424242,
        "seed_override": True,
        "end_frame_mode": "none",
        "end_frame_override": True,
    })
    plan = planner.plan(
        comic_context="A messenger entrusts the final seed to an ancient guardian.",
        comic_shots=panels,
    )

    assert len(plan.shots) == 4
    assert plan.shots[0].metadata["source_panel_ids"] == ["P001", "P002", "P003"]
    assert plan.shots[0].metadata["primary_source_index"] == 1
    assert plan.shots[0].metadata["provided_image_path"] == "/tmp/panel-002.png"
    assert plan.shots[1].metadata["source_panel_ids"] == ["P004"]
    assert plan.shots[2].metadata["source_panel_ids"] == ["P004"]
    assert plan.shots[1].shot_id != plan.shots[2].shot_id
    assert plan.shots[0].metadata["renderer"] == "ltx"
    assert plan.shots[0].metadata["motion_level"] == 1
    assert plan.shots[0].duration_sec == 5.5
    assert plan.shots[0].metadata["camera"] == "push-in"
    assert plan.shots[0].metadata["test_selected"] is True
    assert plan.shots[0].metadata["seed"] == 424242
    assert plan.shots[0].metadata["end_frame_mode"] == "none"
    assert plan.shots[0].video_prompt.startswith("Locked composition.")
    assert "hand-inked" not in plan.shots[0].video_prompt
    assert len(plan.shots[0].video_prompt.split()) < 110


def test_explicit_secondary_override_forces_a_primary_fallback_shot():
    response = [{
        "source_panel_ids": [
            f"P{index + 1:03d}" for index in range(10)
        ],
        "primary_source_panel_id": "P001",
        "action": "The entire sequence resolves as a single compressed beat.",
        "camera": "locked",
        "motion_level": 1,
        "duration_seconds": 3,
        "renderer": "hold",
        "fit_mode": "contain",
        "end_beat": "the traveler becomes still",
        "dialogue": "",
        "narrative_role": "compressed sequence",
        "framing": "wide shot",
    }]
    planner = ComicMoviePlanner(
        llm_generate=lambda **_kwargs: json.dumps(response),
        llm_generate_streaming=lambda **_kwargs: json.dumps(response),
    )
    panels = [_panel(index) for index in range(10)]
    panels[5].update({
        "renderer": "ltx",
        "renderer_override": True,
        "scene_description": "The traveler deliberately opens the sealed gate.",
        "action_override": True,
        "seed": 777,
        "seed_override": True,
    })

    plan = planner.plan(
        comic_context="The edited gate action must remain visible.",
        comic_shots=panels,
    )

    edited = [
        shot for shot in plan.shots
        if shot.metadata["primary_source_panel_id"] == "P006"
    ]
    assert len(edited) == 1
    assert edited[0].metadata["source_panel_ids"] == ["P006"]
    assert edited[0].metadata["renderer"] == "ltx"
    assert edited[0].metadata["seed"] == 777
    assert edited[0].metadata["provided_image_path"] == "/tmp/panel-006.png"
    assert "opens the sealed gate" in edited[0].video_prompt


def test_adaptation_falls_back_when_a_critical_story_panel_is_omitted():
    groups = [
        ["P001", "P002", "P003", "P004"],
        ["P005", "P006", "P007"],
        ["P008", "P009", "P010"],
    ]
    response = [{
        "source_panel_ids": ids,
        "primary_source_panel_id": ids[-1],
        "action": f"The beat ending at {ids[-1]} resolves visibly.",
        "camera": "locked",
        "motion_level": 2,
        "duration_seconds": 3,
        "renderer": "ltx",
        "fit_mode": "contain",
        "end_beat": "the action settles",
        "dialogue": "",
        "narrative_role": "development",
        "framing": "medium shot",
    } for ids in groups]
    planner = ComicMoviePlanner(
        llm_generate=lambda **_kwargs: json.dumps(response),
        llm_generate_streaming=lambda **_kwargs: json.dumps(response),
    )
    panels = [_panel(index) for index in range(12)]
    panels[10]["narrative_role"] = "Climax"

    plan = planner.plan(
        comic_context="The climax must survive the edit.",
        comic_shots=panels,
    )

    covered = {
        source_id
        for shot in plan.shots
        for source_id in shot.metadata["source_panel_ids"]
    }
    assert "P011" in covered
    assert covered == {f"P{index + 1:03d}" for index in range(12)}


def test_reviewed_film_shots_preserve_manual_edit_contract():
    def must_not_call_llm(**_kwargs):
        raise AssertionError("Reviewed film shots bypass automatic adaptation")

    planner = ComicMoviePlanner(
        llm_generate=must_not_call_llm,
        llm_generate_streaming=must_not_call_llm,
    )
    panels = [_panel(index) for index in range(3)]
    plan = planner.plan(
        comic_context="Reviewed story.",
        comic_shots=panels,
        film_shots=[
            {
                "included": True,
                "shot_id": "reviewed-opening",
                "source_panel_ids": ["P001", "P002"],
                "primary_source_panel_id": "P002",
                "renderer": "parallax",
                "action": "Crystal dust shifts between foreground and horizon.",
                "camera": "locked",
                "motion_level": 1,
                "duration_seconds": 3.25,
                "fit_mode": "contain",
                "test_selected": True,
                "seed": 424242,
                "end_beat": "the dust settles",
                "dialogue": "",
            },
            {
                "included": False,
                "source_panel_ids": ["P003"],
                "renderer": "hold",
            },
        ],
    )

    assert len(plan.shots) == 1
    shot = plan.shots[0]
    assert shot.shot_id == "reviewed-opening"
    assert shot.duration_sec == 3.25
    assert shot.metadata["renderer"] == "parallax"
    assert shot.metadata["source_panel_ids"] == ["P001", "P002"]
    assert shot.metadata["provided_image_path"] == "/tmp/panel-002.png"
    assert shot.metadata["fit_mode"] == "contain"
    assert shot.metadata["seed"] == 424242
    assert shot.metadata["test_selected"] is True


def test_representative_test_selection_covers_each_risk_category():
    candidates = [
        {"metadata": {"risk_tags": [risk]}}
        for risk in RISK_PRIORITY
    ]
    assert select_representative_shot_indices(candidates, max_count=6) == list(range(6))


def test_orchestrator_keeps_film_identity_metadata_in_clip_plans():
    rendered = [{
        "shot_id": "comic-P002-deadbeef",
        "video_prompt": "The traveler offers the seed. The camera remains locked.",
        "image_prompt": "prepared keyframe",
        "source_panel_ids": ["P001", "P002"],
        "primary_source_panel_id": "P002",
        "primary_source_index": 1,
        "provided_image_path": "/tmp/panel-002.png",
        "renderer": "ltx",
        "fit_mode": "reframe",
        "seed": 123,
        "risk_tags": ["portrait", "multi-character"],
        "test_selected": True,
        "motion_level": 2,
        "metadata": {
            "source_panel_ids": ["P001", "P002"],
            "primary_source_panel_id": "P002",
            "renderer": "ltx",
        },
    }]

    clips = DirectorOrchestrator.plan_to_clip_plans(rendered)

    assert clips[0]["shot_id"] == "comic-P002-deadbeef"
    assert clips[0]["source_panel_ids"] == ["P001", "P002"]
    assert clips[0]["provided_image_path"] == "/tmp/panel-002.png"
    assert clips[0]["renderer"] == "ltx"
    assert clips[0]["metadata"]["primary_source_panel_id"] == "P002"


def test_motion_only_comic_prompt_is_not_redecorated_by_i2v_renderer():
    planner = ComicMoviePlanner(
        llm_generate=lambda **_kwargs: "[]",
        llm_generate_streaming=lambda **_kwargs: "[]",
    )
    plan = planner.plan(
        comic_context="Reviewed.",
        comic_shots=[_panel(0)],
        film_shots=[{
            "source_panel_ids": ["P001"],
            "renderer": "ltx",
            "action": "The traveler closes her fingers around the seed.",
            "camera": "locked",
            "end_beat": "her hand becomes still",
        }],
    )
    shot = plan.shots[0]
    assert LtxI2VRenderer.ensure_source_style(shot.video_prompt, shot) == shot.video_prompt

    clips = [{
        "video_prompt": shot.video_prompt,
        "image_prompt": "A clean horizontal keyframe.",
        "metadata": shot.metadata,
    }]
    enforce_visual_style_on_clip_plans(
        clips,
        "hand-inked comic line art",
        preserve=True,
        has_reference=True,
    )
    assert clips[0]["video_prompt"] == shot.video_prompt
    assert "VISUAL STYLE LOCK:" in clips[0]["image_prompt"]


def test_contextual_fallback_does_not_route_every_quiet_panel_to_ltx():
    planner = ComicMoviePlanner(
        llm_generate=lambda **_kwargs: "[]",
        llm_generate_streaming=lambda **_kwargs: "[]",
    )
    panels = [
        _panel(
            0,
            motion_mode="contextual",
            characters=[],
            narrative_role="wide establishing landscape",
            scene_description="A silent crystal horizon under drifting clouds.",
        ),
        _panel(
            1,
            motion_mode="contextual",
            narrative_role="quiet portrait",
            scene_description="Nara watches the horizon without moving.",
        ),
        _panel(
            2,
            motion_mode="contextual",
            narrative_role="action",
            scene_description="Nara runs across the collapsing bridge.",
        ),
    ]

    plan = planner.plan(
        comic_context="A brief visual sequence.",
        comic_shots=panels,
        adapt_to_film=False,
    )

    assert [shot.metadata["renderer"] for shot in plan.shots] == [
        "parallax",
        "hold",
        "ltx",
    ]

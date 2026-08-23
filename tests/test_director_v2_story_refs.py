"""Regression tests for Story Lab reference hand-off to Director v2."""

from __future__ import annotations

import ast
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.services.director.planners.comic_movie import ComicMoviePlanner
from app.services.director.planners.music_video import (
    MusicVideoPlanner,
    build_music_video_cast_lock,
    build_music_video_coverage,
    normalize_music_video_treatment,
)
from app.services.director.policies import enforce_direct_video_on_clip_plans
from app.services.director.planners.short_film import ShortFilmPlanner
from app.services.director.schema import CharacterProfile
from app.services import director_pipeline
from app.services.director_pipeline import _has_visual_references
from app.services.director_video_strategy import SHOT_IMAGE_PROMPT_ONLY


def _load_planner_kwargs():
    source = Path(__file__).parents[1].joinpath("app", "_launch_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_DIRECTOR_V2_PLANNER_KEYS"
            for target in node.targets
        ):
            selected.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "_director_v2_planner_kwargs":
            selected.append(node)
    namespace: dict = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "_launch_runtime.py", "exec"), namespace)
    return namespace["_director_v2_planner_kwargs"]


_director_v2_planner_kwargs = _load_planner_kwargs()


def _music_shot(index: int) -> dict:
    return {
        "clip_index": index,
        "scene_goal": f"Complete narrative beat {index}",
        "scene_type": "narrative",
        "subjects_on_screen": [],
        "environment": "A moonlit archive",
        "visual_style": "cinematic data dream",
        "lighting": "soft cyan light",
        "mood": "reflective",
        "action_beats": ["Data motes gather"],
        "camera_plan": {
            "framing": "medium shot",
            "movement": "slow push in",
            "movement_intensity": "subtle",
        },
        "ending_beat": "The archive glows",
        "image_source": "original",
        "image_prompt": f"A complete static first frame in a moonlit archive for clip {index}.",
        "visual_changes": ["The archive begins to glow"],
        "video_prompt": f"The camera slowly advances while pale data motes gather for clip {index}.",
        "keyframe_prompts": [],
        "window_prompts": [],
    }


class _NoLlmShortFilmPlanner(ShortFilmPlanner):
    def _plan_story_driven(self, **kwargs):
        self.received_has_reference = kwargs["has_reference"]
        return [], "Reference-only story"


class TestDirectorV2StoryRefs(unittest.TestCase):
    def test_music_video_treatment_normalizes_editable_fields(self):
        treatment = normalize_music_video_treatment({
            "mode": "performance",
            "performer_presence": 140,
            "recurring_sets": "stage\nrooftop",
            "lip_sync": "occasional",
        })
        self.assertEqual(treatment["mode"], "performance")
        self.assertEqual(treatment["performer_presence"], 100)
        self.assertEqual(treatment["recurring_sets"], ["stage", "rooftop"])
        self.assertEqual(treatment["lip_sync"], "occasional")

    def test_cast_lock_forbids_modern_rappers_in_a_named_world(self):
        lock = build_music_video_cast_lock(
            "Videoclip de los enanos de The Lord of the Rings",
            {"forbidden_elements": "raperos modernos, hoodies, cadenas de oro"},
        )
        self.assertIn("AUDIO GENRE IS NOT CAST", lock)
        self.assertIn("rapper", lock.casefold())
        self.assertIn("raperos modernos", lock)

    def test_direct_video_treatment_keeps_master_prompt_and_ignores_visual_refs(self):
        treatment = normalize_music_video_treatment({
            "generation_mode": "direct_video",
            "direct_video_master_prompt": "Immutable painted science-fiction world.",
        })
        self.assertEqual(treatment["generation_mode"], "direct_video")
        self.assertEqual(
            treatment["direct_video_master_prompt"],
            "Immutable painted science-fiction world.",
        )
        params = {
            "pipeline_type": "music_video",
            "music_video_treatment": treatment,
            "reference_image_path": "/tmp/portrait.png",
            "character_ref_paths": ["/tmp/character.png"],
            "location_ref_paths": ["/tmp/location.png"],
        }
        self.assertFalse(director_pipeline._has_visual_references(params))

    def test_story_trailer_direct_video_is_text_only_too(self):
        params = {
            "pipeline_type": "short_film_story",
            "music_video_treatment": {
                "generation_mode": "direct_video",
                "direct_video_master_prompt": "Immutable cinematic supermarket world.",
            },
            "reference_image_path": "/tmp/ignored-world.png",
            "character_ref_paths": ["/tmp/ignored-character.png"],
        }

        enabled, master_prompt = director_pipeline._direct_video_settings(params)

        self.assertTrue(enabled)
        self.assertEqual(master_prompt, "Immutable cinematic supermarket world.")
        self.assertFalse(director_pipeline._has_visual_references(params))
        self.assertEqual(
            director_pipeline._director_effective_shot_image_policy(params),
            SHOT_IMAGE_PROMPT_ONLY,
        )

    def test_direct_video_overrides_stale_saved_image_policy(self):
        params = {
            "pipeline_type": "music_video",
            "music_video_treatment": {
                "generation_mode": "direct_video",
                "direct_video_master_prompt": "Immutable painted world.",
            },
            "_director_shot_image_policy": "generate",
        }
        state = {
            "pipeline_type": "music_video",
            "generation_mode": "direct_video",
            "shot_image_policy": "generate",
            "_params_snapshot": params,
        }

        self.assertEqual(
            director_pipeline._director_effective_shot_image_policy(params),
            SHOT_IMAGE_PROMPT_ONLY,
        )
        self.assertEqual(
            director_pipeline._saved_pipeline_shot_image_policy(state),
            SHOT_IMAGE_PROMPT_ONLY,
        )

    def test_direct_video_default_prompt_is_style_neutral(self):
        treatment = normalize_music_video_treatment({"generation_mode": "direct_video"})
        master_prompt = treatment["direct_video_master_prompt"]
        self.assertIn("coherent visual language", master_prompt)
        self.assertNotIn("Heavy Metal", master_prompt)

    def test_direct_video_contract_repeats_master_and_removes_image_prompts(self):
        plans = [{
            "scene_goal": "Reveal the alien citadel",
            "environment": "a red desert beneath two moons",
            "video_prompt": "A lone warrior raises a black sword as the camera pushes in.",
            "image_prompt": "This must never reach an image model.",
            "keyframe_prompts": ["Nor this keyframe."],
        }]
        enforce_direct_video_on_clip_plans(
            plans,
            "IMMUTABLE PAINTED WORLD.",
            allow_clip_text=False,
        )
        prompt = plans[0]["video_prompt"]
        self.assertTrue(prompt.startswith("integrated_multimodal_description: [Shot 1]"))
        self.assertIn("Shared visual direction: IMMUTABLE PAINTED WORLD", prompt)
        self.assertIn("Reveal the alien citadel", prompt)
        self.assertNotIn("Scene overview:", prompt)
        self.assertIn("A lone warrior raises", prompt)
        self.assertIn("non_diegetic_music: N/A", prompt)
        self.assertEqual(plans[0]["image_prompt"], "")
        self.assertEqual(plans[0]["image_source"], "none")
        self.assertEqual(plans[0]["keyframe_prompts"], [])
        self.assertEqual(plans[0]["h3_segment_prompts"], [])
        self.assertIn("VISIBLE TEXT LOCK", prompt)

    def test_direct_video_preflight_preserves_authored_audio_and_music(self):
        source = (
            'SPOKEN LANGUAGE CONTRACT: Spanish. '
            '{"integrated_multimodal_description":"A woman crosses a stormy plaza.",'
            '"overall_soundscape":"Rain, thunder and hurried footsteps.",'
            '"non_diegetic_music":"Low strings rise into a sharp brass hit."}'
        )
        plans = [{
            "scene_goal": "Reveal the threat",
            "environment": "a stormy plaza",
            "video_prompt": source,
            "_director_audio_plan": {"mode": "music_driven"},
        }]

        enforce_direct_video_on_clip_plans(
            plans,
            "IMMUTABLE NOIR WORLD.",
        )

        self.assertIn("[Shot 1]", plans[0]["video_prompt"])
        self.assertIn("A woman crosses a stormy plaza", plans[0]["video_prompt"])
        self.assertNotIn('{"integrated_multimodal_description"', plans[0]["video_prompt"])
        self.assertIn("Rain, thunder and hurried footsteps", plans[0]["video_prompt"])
        self.assertIn("Low strings rise into a sharp brass hit", plans[0]["video_prompt"])
        self.assertEqual(
            plans[0]["_director_h3_source_prompt"], plans[0]["video_prompt"],
        )

        director_pipeline._preflight_h3_director_prompts(
            "minimax_h3_legacy", plans,
        )
        compiled = plans[0]["video_prompt"]
        self.assertEqual(compiled.count("overall_soundscape:"), 1)
        self.assertEqual(compiled.count("non_diegetic_music:"), 1)
        self.assertIn("Rain, thunder and hurried footsteps", compiled)
        self.assertIn("Low strings rise into a sharp brass hit", compiled)
        self.assertNotIn("Natural scene-appropriate stereo ambience", compiled)

    def test_direct_video_never_leaks_global_audio_meta_into_soundscape(self):
        plans = [{
            "scene_goal": "A silent cave reveal",
            "environment": "a wet stone cave",
            "video_prompt": "A traveler raises a lantern and stays silent.",
            "audio_plan": {"mode": "ambient_only", "ambience": "distant cave drips"},
        }]
        enforce_direct_video_on_clip_plans(
            plans,
            "Dark adventure cinematography.",
            audio_direction=(
                "Natural synchronized production sound matching the visible "
                "environment and actions; include explicitly described dialogue "
                "or music, otherwise use ambience and sound effects only."
            ),
        )
        soundscape = plans[0]["video_prompt"].split(
            "overall_soundscape:", 1
        )[1].split("non_diegetic_music:", 1)[0].casefold()
        self.assertIn("distant cave drips", soundscape)
        self.assertNotIn("dialogue", soundscape)
        self.assertNotIn("music", soundscape)
    def test_choruses_reuse_signature_set_with_controlled_coverage(self):
        clips = [
            {"label": "verse"},
            {"label": "chorus"},
            {"label": "verse"},
            {"label": "chorus"},
            {"label": "bridge"},
        ]
        treatment = normalize_music_video_treatment({
            "mode": "hybrid",
            "performer_presence": 60,
            "recurring_sets": ["gold stage", "city", "white void"],
        })
        coverage = build_music_video_coverage(clips, treatment)
        self.assertEqual(coverage[1]["recurring_set"], "gold stage")
        self.assertEqual(coverage[3]["recurring_set"], "gold stage")
        self.assertTrue(coverage[1]["reuse_chorus_signature"])
        self.assertTrue(coverage[3]["performer_present"])
        self.assertEqual(coverage[4]["recurring_set"], "white void")

    def test_music_video_rejects_empty_plans_instead_of_fake_reframe_prompts(self):
        with self.assertRaisesRegex(RuntimeError, "returned 0 valid shots; 2 were required"):
            MusicVideoPlanner._validate_llm_shot_plans([], 2)

    def test_music_video_rejects_partial_prompts_before_image_generation(self):
        plans = [{
            "image_prompt": "REFRAME: medium shot | MOOD: steady",
            "video_prompt": "",
        }]
        with self.assertRaisesRegex(RuntimeError, "incomplete image/video prompts for shots 1"):
            MusicVideoPlanner._validate_llm_shot_plans(plans, 1)

    def test_music_video_accepts_surplus_complete_plans(self):
        plan = {
            "image_prompt": "A complete static first frame in a moonlit archive.",
            "video_prompt": "The camera slowly advances while pale data motes drift through the archive.",
        }
        MusicVideoPlanner._validate_llm_shot_plans([plan, plan, plan], 2)

    def test_music_video_partitions_surplus_as_alternatives(self):
        plans = [
            {
                "clip_index": index,
                "image_prompt": f"A complete static first frame for numbered clip {index}.",
                "video_prompt": f"The camera moves through the complete action for numbered clip {index}.",
            }
            for index in (1, 2, 3)
        ]
        slots, missing, alternatives = MusicVideoPlanner._partition_shot_plans(plans, 2)
        self.assertEqual(sorted(slots), [0, 1])
        self.assertEqual(missing, [])
        self.assertEqual(len(alternatives), 1)

    def test_music_video_repairs_only_missing_indexes_once(self):
        calls = []

        def generate(**kwargs):
            calls.append(kwargs)
            return json.dumps([_music_shot(1 if len(calls) == 1 else 2)])

        plan = MusicVideoPlanner(llm_generate=generate).plan(
            clips=[
                {"start": 0, "end": 4, "label": "intro", "beat_count": 8},
                {"start": 4, "end": 8, "label": "verse", "beat_count": 8},
            ],
            scene_description="A concise story about a living archive.",
            bpm=120,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(plan.shots), 2)
        self.assertIn("Missing clip indexes: 2", calls[1]["prompt"])
        self.assertNotIn("Missing clip indexes: 1", calls[1]["prompt"])

    def test_music_video_performer_uses_driving_audio_not_lyric_ledger(self):
        plan = MusicVideoPlanner(
            llm_generate=lambda **kwargs: json.dumps([_music_shot(1)]),
        ).plan(
            clips=[{
                "start": 0.0,
                "end": 4.0,
                "label": "verse",
                "beat_count": 8,
                "dominant_speaker": "lead",
            }],
            lyrics=[{
                "start": 0.0,
                "end": 8.0,
                "text": "Uno dos tres cuatro cinco seis",
                "speaker": "lead",
            }],
            scene_description="A single performer in a cave.",
            bpm=90,
            music_video_treatment={"mode": "performance", "performer_presence": 100, "lip_sync": "frequent"},
        )

        shot = plan.shots[0]
        self.assertEqual(shot.dialogue_beats or [], [])
        self.assertEqual(shot.audio_plan.mode, "audio_driven")
        self.assertTrue(shot.audio_plan.lip_sync_critical)

    def test_music_video_lip_sync_none_stays_mute(self):
        plan = MusicVideoPlanner(
            llm_generate=lambda **kwargs: json.dumps([_music_shot(1)]),
        ).plan(
            clips=[{
                "start": 0.0,
                "end": 4.0,
                "label": "verse",
                "beat_count": 8,
            }],
            lyrics=[{
                "start": 0.0,
                "end": 4.0,
                "text": "Uno dos tres",
                "speaker": "lead",
            }],
            scene_description="A single performer in a cave.",
            bpm=90,
            music_video_treatment={"mode": "performance", "performer_presence": 100, "lip_sync": "none"},
        )

        shot = plan.shots[0]
        self.assertEqual(shot.dialogue_beats or [], [])
        self.assertEqual(shot.audio_plan.mode, "music_driven")
        self.assertFalse(shot.audio_plan.lip_sync_critical)

    def test_music_video_plans_large_timelines_in_bounded_ordered_batches(self):
        calls = []

        def generate(**kwargs):
            calls.append(kwargs)
            match = re.search(r"Requested clip indexes: ([0-9, ]+)", kwargs["prompt"])
            self.assertIsNotNone(match)
            requested = [int(value) for value in match.group(1).split(", ")]
            shots = [_music_shot(index) for index in requested]
            # Regression fake: providers truncate any response above 8 objects.
            return json.dumps(shots[:8] if len(shots) > 8 else shots)

        clips = [
            {"start": index * 4, "end": (index + 1) * 4, "label": "verse", "beat_count": 8}
            for index in range(41)
        ]
        plan = MusicVideoPlanner(llm_generate=generate).plan(
            clips=clips,
            scene_description="A long-form performance crossing one coherent city.",
            bpm=120,
        )

        self.assertEqual(len(calls), 6)
        self.assertTrue(all(call["json_schema"]["maxItems"] <= 8 for call in calls))
        self.assertTrue(all(call["max_new_tokens"] <= 8 * 700 + 768 for call in calls))
        self.assertEqual(len(plan.shots), 41)
        self.assertEqual(
            [shot.scene_goal for shot in plan.shots],
            [f"Complete narrative beat {index}" for index in range(1, 42)],
        )
        self.assertEqual(len({shot.shot_id for shot in plan.shots}), 41)

    def test_music_video_uses_individual_fallback_only_for_still_missing_tail(self):
        calls = []

        def generate(**kwargs):
            calls.append(kwargs)
            return json.dumps([
                _music_shot(1 if len(calls) == 1 else 2 if len(calls) == 2 else 3),
            ])

        plan = MusicVideoPlanner(llm_generate=generate).plan(
            clips=[
                {"start": 0, "end": 4, "label": "intro", "beat_count": 8},
                {"start": 4, "end": 8, "label": "verse", "beat_count": 8},
                {"start": 8, "end": 12, "label": "chorus", "beat_count": 8},
            ],
            scene_description="A concise story about a living archive.",
            bpm=120,
        )

        self.assertEqual(len(calls), 3)
        self.assertEqual(len(plan.shots), 3)
        self.assertIn("Missing clip indexes: 2, 3", calls[1]["prompt"])
        self.assertIn("Missing clip indexes: 3", calls[2]["prompt"])
        self.assertNotIn("Missing clip indexes: 2, 3", calls[2]["prompt"])

    def test_music_video_rejects_duplicate_batch_indexes_without_overwrite(self):
        first = _music_shot(1)
        duplicate = _music_shot(1)
        duplicate["scene_goal"] = "This duplicate must not overwrite the first plan"
        slots, missing, alternatives = MusicVideoPlanner._partition_batch_shot_plans(
            [first, duplicate, _music_shot(2)],
            2,
            [0, 1],
        )

        self.assertEqual(missing, [])
        self.assertEqual(alternatives, [])
        self.assertEqual(slots[0]["scene_goal"], first["scene_goal"])

    def test_music_video_persists_surplus_plans_as_alternatives(self):
        def generate(**_kwargs):
            return json.dumps([_music_shot(1), _music_shot(2), _music_shot(3)])

        plan = MusicVideoPlanner(llm_generate=generate).plan(
            clips=[
                {"start": 0, "end": 4, "label": "intro", "beat_count": 8},
                {"start": 4, "end": 8, "label": "verse", "beat_count": 8},
            ],
            scene_description="A concise story about a living archive.",
            bpm=120,
        )

        serialized = plan.to_dict()
        self.assertEqual(len(plan.shots), 2)
        self.assertEqual(len(serialized["alternative_shots"]), 1)
        self.assertEqual(serialized["alternative_shots"][0]["clip_index"], 3)

    def test_music_video_prompt_contract_separates_lyrics_from_visible_text(self):
        calls = []

        def generate(**kwargs):
            calls.append(kwargs)
            return json.dumps([_music_shot(1)])

        MusicVideoPlanner(llm_generate=generate).plan(
            clips=[{"start": 0, "end": 4, "label": "verse", "beat_count": 8}],
            scene_description="A singer wakes inside a digital archive.",
            lyrics=[{"start": 0, "end": 4, "text": "Despierta dentro de mí"}],
            bpm=90,
            preserve_visual_style=True,
            character_visual_style="handmade plasticine claymation figures",
            allow_clip_text=False,
        )

        self.assertIn("CHARACTER RENDERING CONTRACT — STRICT", calls[0]["system_prompt"])
        self.assertIn("No readable text may appear", calls[0]["system_prompt"])
        self.assertIn("never render as visible text", calls[0]["prompt"])
        self.assertNotIn('lyrics: "Despierta dentro de mí"', calls[0]["prompt"])

    def test_character_and_location_references_are_preserved(self):
        body = {
            "story_description": "A compact episode.",
            "character_ref_paths": ["/tmp/mara.png"],
            "character_ref_labels": ["Mara"],
            "location_ref_paths": ["/tmp/city.png"],
            "location_ref_labels": ["Sunken city"],
            "image_model": "flux2_klein_9b",
            "video_model": "ltx2_22B_distilled_1_1",
            "visual_style": "2D anime, clean cel shading",
            "preserve_visual_style": True,
            "character_visual_style": "2D anime characters",
            "allow_clip_text": False,
            "music_video_treatment": {"mode": "hybrid"},
        }
        self.assertEqual(_director_v2_planner_kwargs(body), body)

    def test_unknown_transport_fields_do_not_reach_planners(self):
        result = _director_v2_planner_kwargs({
            "story_description": "A compact episode.",
            "workspace": "default",
            "api_key": "must-not-pass",
        })
        self.assertEqual(result, {"story_description": "A compact episode."})

    def test_additional_reference_does_not_create_empty_start_frame(self):
        planner = _NoLlmShortFilmPlanner()
        with tempfile.NamedTemporaryFile(suffix=".png") as reference:
            plan = planner.plan(
                story_description="A compact episode.",
                character_ref_paths=[reference.name],
                character_ref_labels=["Mara"],
            )
        self.assertTrue(planner.received_has_reference)
        self.assertIsNone(plan.reference_assets.start_image)

    def test_pipeline_renderer_recognizes_story_lab_references(self):
        self.assertTrue(_has_visual_references({
            "character_ref_paths": ["/tmp/mara.png"],
        }))
        self.assertTrue(_has_visual_references({
            "location_ref_paths": ["/tmp/city.png"],
        }))
        self.assertTrue(_has_visual_references({
            "provided_clip_image_paths": ["/tmp/comic-panel.png"],
        }))
        self.assertFalse(_has_visual_references({}))

    def test_short_film_plan_preserves_per_shot_location_label(self):
        shots = ShortFilmPlanner()._convert_story_shots(
            [{
                "title": "Harbor arrival",
                "duration_sec": 5,
                "scene_goal": "Reach the harbor",
                "location_ref_label": "Moon Harbor",
                "video_prompt": "A boat reaches the pier.",
                "image_prompt": "A still boat beside the pier.",
            }],
            [],
            True,
            24,
            17,
            107,
        )

        self.assertEqual(shots[0].metadata["location_ref_label"], "Moon Harbor")

    def test_story_screenplay_recovery_always_produces_clip_plans(self):
        profiles = [
            CharacterProfile(
                id="mara",
                display_name="Mara",
                physical_description="a young mechanic with cropped dark hair",
            ),
        ]
        shots = ShortFilmPlanner._fallback_shots_from_screenplay(
            screenplay=(
                "Mara enters the silent engine room. Warning lights pulse.\n\n"
                "Mara studies the broken core and admits she needs help.\n\n"
                "Her rivals arrive. Together they reconnect the final circuit.\n\n"
                "The city lights return, and Mara finally smiles."
            ),
            story_description="Mara learns to trust her rivals.",
            char_profiles=profiles,
            target_duration=45,
            target_scenes=3,
        )
        self.assertEqual(len(shots), 3)
        self.assertEqual(sum(shot["duration_sec"] for shot in shots), 45)
        self.assertTrue(all(shot["video_prompt"] for shot in shots))
        self.assertTrue(all(shot["image_prompt"] for shot in shots))
        self.assertEqual(shots[0]["subjects_on_screen"][0]["character_id"], "mara")

    def test_story_planner_recovers_when_pass_two_returns_only_prose(self):
        responses = iter([
            (
                "INT. ENGINE ROOM — NIGHT\n\n"
                "Mara enters the silent engine room while red warning lights pulse. "
                "She studies the broken core and admits that she needs help.\n\n"
                "Her rivals arrive, reconnect the final circuit with her, and the "
                "city lights return as Mara finally accepts their friendship."
            ),
            "Visualización de la escena: luces rojas y una cámara que avanza.",
            "La reparación culmina con una imagen esperanzadora.",
        ])

        def provider_ignoring_json(**_kwargs):
            return next(responses)

        planner = ShortFilmPlanner(
            llm_generate=provider_ignoring_json,
            llm_generate_streaming=provider_ignoring_json,
        )
        plan = planner.plan(
            story_description="Mara must trust her rivals to save the city.",
            characters=[{
                "name": "Mara",
                "description": "A young mechanic with cropped dark hair.",
            }],
            target_duration=40,
            target_scenes=2,
            fps=24,
            frames_steps=8,
            frames_minimum=41,
            visual_style="2D anime, clean cel shading",
            preserve_visual_style=True,
        )
        self.assertEqual(len(plan.shots), 2)
        self.assertTrue(all(shot.video_prompt for shot in plan.shots))
        self.assertTrue(all(shot.visual_style == "2D anime, clean cel shading" for shot in plan.shots))
        self.assertTrue(all(shot.metadata["preserve_visual_style"] for shot in plan.shots))
        self.assertTrue(all("VISUAL STYLE LOCK:" in shot.image_prompt for shot in plan.shots))
        self.assertTrue(all("no live action" in shot.video_prompt for shot in plan.shots))

    def test_comic_movie_falls_back_per_panel_when_provider_returns_prose(self):
        responses = iter([
            "A lyrical visual treatment, but not JSON.",
            "Still prose instead of the requested array.",
        ])

        def invalid_remote_response(**_kwargs):
            return next(responses)

        planner = ComicMoviePlanner(
            llm_generate=invalid_remote_response,
            llm_generate_streaming=invalid_remote_response,
        )
        plan = planner.plan(
            comic_context="A complete master story and character bible.",
            comic_shots=[
                {
                    "page_number": 1,
                    "panel_number": 1,
                    "duration": 3,
                    "scene_description": "Mara opens the engine room.",
                    "script": "[Mara] Not alone this time.",
                    "camera_move": "push-in",
                    "characters": ["Mara"],
                },
                {
                    "page_number": 1,
                    "panel_number": 2,
                    "duration": 4,
                    "scene_description": "The dormant city lights awaken.",
                    "camera_move": "pull-out",
                    "characters": ["Mara"],
                },
            ],
        )
        self.assertEqual(len(plan.shots), 2)
        self.assertEqual(plan.total_duration_sec, 7)
        self.assertTrue(all(shot.source_mode_preference == "i2v" for shot in plan.shots))
        self.assertIn("supplied comic artwork", plan.shots[0].video_prompt)

    def test_comic_movie_preserves_reviewed_storyboard_video_prompt(self):
        def must_not_call_llm(**_kwargs):
            raise AssertionError("Reviewed storyboard prompts must bypass the planning LLM")

        planner = ComicMoviePlanner(
            llm_generate=must_not_call_llm,
            llm_generate_streaming=must_not_call_llm,
        )
        reviewed_prompt = (
            "Mara looks up from the exact first frame. Her coat moves gently in the "
            "engine-room draft while the camera performs a slow push-in; the warning "
            "lights settle to green on the final beat."
        )
        plan = planner.plan(
            comic_context="A reviewed pre-video storyboard.",
            comic_shots=[{
                "page_number": 1,
                "panel_number": 1,
                "duration": 5,
                "scene_description": "The repaired engine answers Mara.",
                "camera_move": "push-in",
                "characters": ["Mara"],
                "video_prompt": reviewed_prompt,
            }],
        )

        self.assertEqual(len(plan.shots), 1)
        self.assertEqual(plan.shots[0].video_prompt, reviewed_prompt)
        self.assertEqual(plan.shots[0].duration_sec, 5)

    def test_comic_movie_living_still_bypasses_llm_and_keeps_requested_duration(self):
        def must_not_call_llm(**_kwargs):
            raise AssertionError("Living-still shots use the deterministic fidelity prompt")

        planner = ComicMoviePlanner(
            llm_generate=must_not_call_llm,
            llm_generate_streaming=must_not_call_llm,
        )
        plan = planner.plan(
            comic_context="A finished comic whose artwork must remain unchanged.",
            comic_shots=[{
                "page_number": 1,
                "panel_number": 1,
                "duration": 5,
                "motion_mode": "living-still",
                "camera_move": "push-in",
                "scene_description": "The traveler runs toward the tower.",
                "video_prompt": "The traveler runs across the entire frame.",
                "characters": ["NARA"],
            }],
        )

        self.assertEqual(plan.total_duration_sec, 5)
        self.assertEqual(plan.shots[0].duration_sec, 5)
        self.assertEqual(plan.shots[0].camera_plan.movement, "locked-off camera")
        self.assertIn("restrained living still", plan.shots[0].video_prompt)
        self.assertIn("same position", plan.shots[0].video_prompt)
        self.assertNotIn("runs across the entire frame", plan.shots[0].video_prompt)
        self.assertEqual(plan.shots[0].metadata["motion_mode"], "living-still")

    def test_comic_movie_contextual_mode_rewrites_generic_prompt_from_story(self):
        captured = {}

        def contextual_planner(**kwargs):
            captured.update(kwargs)
            return (
                '[{"source_index":0,"video_prompt":"With the camera fixed, Nara '
                'studies the seed in her palm, closes her fingers around it, then '
                'raises her eyes toward the silent guardian as crystal dust crosses '
                'the background."}]'
            )

        planner = ComicMoviePlanner(
            llm_generate=contextual_planner,
            llm_generate_streaming=contextual_planner,
        )
        plan = planner.plan(
            comic_context=(
                "Nara is a solitary messenger carrying the last seed. Kael is the "
                "guardian whose grief has kept the dead world unchanged."
            ),
            comic_shots=[{
                "page_number": 6,
                "panel_number": 3,
                "duration": 5,
                "motion_mode": "contextual",
                "narrative_role": "Nara decides to trust Kael.",
                "scene_description": "Nara silently offers the last seed.",
                "image_prompt": "Nara faces Kael in a crystal desert, the seed visible in her palm.",
                "image_path": "/tmp/nara-offers-seed.png",
                "script": "No dialogue. A deliberate moment of trust.",
                "camera_move": "push-in",
                "video_prompt": "Slow push-in with generic breathing.",
                "characters": ["NARA", "KAEL"],
            }],
        )

        self.assertIn('"motion_mode": "contextual"', captured["prompt"])
        self.assertIn("last seed", captured["prompt"])
        self.assertEqual(captured["image_paths"], ["/tmp/nara-offers-seed.png"])
        self.assertIn("When motion_mode is \"contextual\"", captured["system_prompt"])
        self.assertEqual(plan.shots[0].duration_sec, 5)
        self.assertEqual(plan.shots[0].camera_plan.movement, "locked-off camera")
        self.assertIn("studies the seed", plan.shots[0].video_prompt)
        self.assertNotIn("generic breathing", plan.shots[0].video_prompt)
        self.assertEqual(plan.shots[0].metadata["motion_mode"], "contextual")

    def test_comic_movie_plans_action_inside_panel_instead_of_a_transition(self):
        captured = {}

        def action_planner(**kwargs):
            captured.update(kwargs)
            return (
                '[{"source_index":0,"video_prompt":"The traveler plants her staff, '
                'shields her eyes from crystal dust, then steps onto the ridge while '
                'her cloak and the distant sand move in the wind."}]'
            )

        planner = ComicMoviePlanner(
            llm_generate=action_planner,
            llm_generate_streaming=action_planner,
        )
        plan = planner.plan(
            comic_context="A solitary crossing through a crystal desert.",
            comic_shots=[{
                "page_number": 1,
                "panel_number": 1,
                "duration": 5,
                "narrative_role": "The traveler commits to the crossing.",
                "scene_description": "She chooses the dangerous ridge path.",
                "image_prompt": "Wide comic panel: a cloaked traveler before a crystal ridge.",
                "camera_move": "push-in",
                "characters": ["NARA"],
            }],
        )

        self.assertIn("first_frame_visual_description", captured["prompt"])
        self.assertIn("cloaked traveler before a crystal ridge", captured["prompt"])
        self.assertIn("MUST PLAY AS ITS OWN SHOT", captured["system_prompt"])
        self.assertIn("movement is secondary", captured["system_prompt"])
        self.assertIn("plants her staff", plan.shots[0].video_prompt)

    def test_story_production_resolves_selected_provider_server_side(self):
        previous = director_pipeline._wgp
        director_pipeline._wgp = SimpleNamespace(server_config={
            "services": {
                "minimax_api_key": "server-secret",
                "openai_api_key": "different-secret",
            },
        })
        try:
            resolved = director_pipeline._scoped_writing_llm({
                "writing_provider": "minimax",
                "writing_model": "MiniMax-M3",
                # A caller-supplied key must never be trusted or persisted.
                "api_key": "browser-secret",
            })
        finally:
            director_pipeline._wgp = previous
        self.assertEqual(resolved["provider"], "minimax")
        self.assertEqual(resolved["model"], "MiniMax-M3")
        self.assertEqual(resolved["api_key"], "server-secret")


if __name__ == "__main__":
    unittest.main()

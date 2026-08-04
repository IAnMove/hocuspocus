"""Regression tests for Story Lab reference hand-off to Director v2."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.services.director.planners.comic_movie import ComicMoviePlanner
from app.services.director.planners.short_film import ShortFilmPlanner
from app.services.director.schema import CharacterProfile
from app.services import director_pipeline
from app.services.director_pipeline import _has_visual_references


def _load_planner_kwargs():
    source = Path(__file__).parents[1].joinpath("app", "launch.py").read_text(encoding="utf-8")
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
    exec(compile(ast.Module(body=selected, type_ignores=[]), "launch.py", "exec"), namespace)
    return namespace["_director_v2_planner_kwargs"]


_director_v2_planner_kwargs = _load_planner_kwargs()


class _NoLlmShortFilmPlanner(ShortFilmPlanner):
    def _plan_story_driven(self, **kwargs):
        self.received_has_reference = kwargs["has_reference"]
        return [], "Reference-only story"


class TestDirectorV2StoryRefs(unittest.TestCase):
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

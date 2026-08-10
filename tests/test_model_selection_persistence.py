"""Regressions for model choices surviving changing Pinokio UI ports."""
from __future__ import annotations

import ast
import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAUNCH_PATH = os.path.join(ROOT, "app", "launch.py")
CLIENT_PATH = os.path.join(ROOT, "ui", "src", "api", "client.ts")
STORE_PATH = os.path.join(ROOT, "ui", "src", "stores", "useStore.ts")
STORY_PATH = os.path.join(
    ROOT, "ui", "src", "features", "stories", "StoryLabPanel.tsx",
)


def _source(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class TestModelSelectionPersistence(unittest.TestCase):
    def test_global_production_profile_is_the_generic_llm_source(self):
        launch = _source(LAUNCH_PATH)
        store = _source(STORE_PATH)

        self.assertIn('@api.get("/api/v1/production-profile")', launch)
        self.assertIn('@api.put("/api/v1/production-profile")', launch)
        self.assertIn('"provider": "minimax", "model": "MiniMax-M3"', launch)
        self.assertIn('"model": "minimax_h3_legacy"', launch)
        self.assertIn("def _effective_llm_routing", launch)
        ensure = launch[launch.index("def _ensure_llm_loaded():"):]
        ensure = ensure[:ensure.index("@api.post", 1)]
        self.assertIn("_effective_llm_routing(services)", ensure)
        self.assertIn("loadProductionProfile", store)
        self.assertIn("updateProductionProfile", store)

    def test_backend_normalizes_per_mode_preferences(self):
        source = _source(LAUNCH_PATH)
        tree = ast.parse(source, filename=LAUNCH_PATH)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_normalize_model_selections"
        )
        module = ast.Module(body=[function], type_ignores=[])
        ast.fix_missing_locations(module)
        namespace = {
            "_MODEL_SELECTION_MODES": frozenset(
                {"image", "video", "audio", "model3d", "avatar"},
            ),
        }
        exec(compile(module, LAUNCH_PATH, "exec"), namespace)
        normalize = namespace["_normalize_model_selections"]

        self.assertEqual(
            normalize({"video": " minimax_h3 ", "image": "flux2_klein_9b"}),
            {"video": "minimax_h3", "image": "flux2_klein_9b"},
        )
        with self.assertRaisesRegex(ValueError, "Unknown generation mode"):
            normalize({"unknown": "minimax_h3"})
        with self.assertRaisesRegex(ValueError, "must be a string"):
            normalize({"video": 123})

    def test_client_and_boot_hydration_use_server_preferences(self):
        launch = _source(LAUNCH_PATH)
        client = _source(CLIENT_PATH)
        store = _source(STORE_PATH)

        self.assertIn('@api.get("/api/v1/model-selections")', launch)
        self.assertIn('@api.put("/api/v1/model-selections")', launch)
        self.assertIn("fetchModelSelections", client)
        self.assertIn("updateModelSelections", client)
        self.assertIn("api.fetchModelSelections()", store)
        self.assertIn("api.updateModelSelections(payload)", store)
        self.assertIn("durableSelections?.selected_models || {}", store)

    def test_story_lab_explains_the_ltx_gemma_dependency(self):
        story = _source(STORY_PATH)
        self.assertIn("Gemma 3 12B", story)
        self.assertIn("LTX dependency, not a separate setting", story)
        self.assertIn("This exact MiniMax H3 selection", story)

    def test_story_lab_video_format_is_selectable_and_reopenable(self):
        story = _source(STORY_PATH)
        self.assertIn("Landscape", story)
        self.assertIn("Portrait / Shorts", story)
        self.assertIn("20-step ConvRot recipe", story)
        self.assertIn("api.fetchModelOptions(videoModel)", story)
        self.assertIn("setDirectorResolution(generationSettings.resolution)", story)
        self.assertIn("setDirectorAspectRatio(generationSettings.aspectRatio)", story)
        self.assertGreaterEqual(story.count("resolution: storyVideoResolution"), 3)
        self.assertGreaterEqual(story.count("aspectRatio: storyVideoAspectRatio"), 3)
        self.assertIn("production.targetSnapshot?.resolution", story)
        self.assertIn("production.targetSnapshot?.aspectRatio", story)


if __name__ == "__main__":
    unittest.main()

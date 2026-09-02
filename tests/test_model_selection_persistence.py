"""Regressions for model choices surviving changing Pinokio UI ports."""
from __future__ import annotations

import ast
import os
import unittest

from tests.api_client_source import api_client_source


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAUNCH_PATH = os.path.join(ROOT, "app", "_launch_runtime.py")

STORE_PATH = os.path.join(ROOT, "ui", "src", "stores", "useStore.ts")
STORY_PATH = os.path.join(
    ROOT, "ui", "src", "features", "stories", "StoryLabPanel.tsx",
)
STORIES_DIR = os.path.join(ROOT, "ui", "src", "features", "stories")
STORY_UI_PATHS = tuple(
    [STORY_PATH]
    + [
        os.path.join(STORIES_DIR, name)
        for name in sorted(os.listdir(STORIES_DIR))
        if name.endswith((".tsx", ".ts"))
    ]
    + [
        os.path.join(ROOT, "ui", "src", "i18n", "locales", "en", "storyLab.json"),
        os.path.join(ROOT, "ui", "src", "i18n", "locales", "es", "storyLab.json"),
    ]
)
STORY_MODEL_PATH = os.path.join(
    ROOT, "ui", "src", "features", "stories", "model.ts",
)
STORY_STORE_PATH = os.path.join(
    ROOT, "ui", "src", "features", "stories", "store.ts",
)
STORY_TYPES_PATH = os.path.join(
    ROOT, "ui", "src", "features", "stories", "types.ts",
)


def _source(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _story_ui() -> str:
    return "\n".join(_source(path) for path in STORY_UI_PATHS)


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
        client = api_client_source()
        store = _source(STORE_PATH)

        self.assertIn('@api.get("/api/v1/model-selections")', launch)
        self.assertIn('@api.put("/api/v1/model-selections")', launch)
        self.assertIn("fetchModelSelections", client)
        self.assertIn("updateModelSelections", client)
        self.assertIn("api.fetchModelSelections()", store)
        self.assertIn("api.updateModelSelections(payload)", store)
        self.assertIn("durableSelections?.selected_models || {}", store)

    def test_story_lab_explains_the_ltx_gemma_dependency(self):
        story = _story_ui()
        self.assertIn("Gemma 3 12B", story)
        self.assertIn("LTX dependency, not a separate setting", story)
        self.assertIn("This exact MiniMax H3 selection", story)

    def test_story_lab_video_format_is_selectable_and_reopenable(self):
        story = _story_ui()
        self.assertIn("Landscape", story)
        self.assertIn("Portrait / Shorts", story)
        self.assertIn("20-step ConvRot recipe", story)
        self.assertIn("api.fetchModelOptions(model)", story)
        self.assertIn("resolveSupportedVideoFormat(", story)
        self.assertIn("setDirectorResolution(generationSettings.resolution)", story)
        self.assertIn("setDirectorAspectRatio(generationSettings.aspectRatio)", story)
        self.assertGreaterEqual(story.count("resolution: storyVideoResolution"), 3)
        self.assertGreaterEqual(story.count("aspectRatio: storyVideoAspectRatio"), 3)
        self.assertIn("production.targetSnapshot?.resolution", story)
        self.assertIn("production.targetSnapshot?.aspectRatio", story)

    def test_story_video_override_is_durable_local_and_explicitly_handed_to_director(self):
        story = _story_ui()
        model = _source(STORY_MODEL_PATH)
        story_store = _source(STORY_STORE_PATH)
        types = _source(STORY_TYPES_PATH)

        self.assertIn("export interface StoryVideoOverride", types)
        self.assertIn("videoOverride: StoryVideoOverride", types)
        self.assertIn("model: 'minimax_h3_legacy'", model)
        self.assertIn("model: ''", model)
        self.assertIn("instead of silently changing it", model)
        self.assertIn("useGlobalProfile: true", story_store)
        self.assertIn("selectStoryVideoModel", story)
        self.assertIn("setStoryVideoFormat", story)
        self.assertGreaterEqual(story.count("disabled={!storyVideoOptionsReady}"), 3)
        self.assertIn("provider: { ...project.provider, useGlobalProfile: false }", story)
        self.assertNotIn("const selectDirectorVideoModel = useStore", story)
        self.assertIn("await director.selectDirectorVideoModel(filmVideoModel)", story)
        self.assertIn("await store.selectDirectorVideoModel(generationSettings.videoModel)", story)
        self.assertIn("director.setDirectorResolution(storyVideoResolution)", story)
        self.assertIn("director.setDirectorAspectRatio(storyVideoAspectRatio)", story)

    def test_global_video_format_hydration_is_race_safe_and_override_aware(self):
        store = _source(STORE_PATH)
        helper = store[store.index(
            "async function _syncGlobalProductionVideoFormat",
        ):store.index("export const useStore", store.index(
            "async function _syncGlobalProductionVideoFormat",
        ))]

        self.assertIn("_globalModelSelectionModes.has('video')", helper)
        self.assertIn("before.selectedModelPerMode.video !== modelType", helper)
        self.assertIn("requestSeq !== _productionProfileVideoFormatSeq", helper)
        self.assertIn("latest.selectedModelPerMode.video !== modelType", helper)
        self.assertIn("resolveSupportedVideoFormat", helper)
        self.assertIn("directorResolution: format.resolution", helper)
        self.assertIn("directorAspectRatio: format.aspectRatio", helper)
        self.assertGreaterEqual(
            store.count("_syncGlobalProductionVideoFormat("),
            4,
        )


if __name__ == "__main__":
    unittest.main()

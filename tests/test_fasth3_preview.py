"""FastH3 Preview v1 request recipe — T2VA, 4 steps, managed LoRA."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_FASTH3 = _ROOT / "app" / "models" / "minimax_h3" / "fasth3.py"
_LAUNCH = _ROOT / "app" / "_launch_runtime.py"
_TOGGLE = _ROOT / "ui" / "src" / "components" / "Sidebar" / "MiniMaxH3FastH3Toggle.tsx"
_SIDEBAR = _ROOT / "ui" / "src" / "components" / "Sidebar" / "Sidebar.tsx"
_TYPES = _ROOT / "ui" / "src" / "types" / "index.ts"


def _load_fasth3():
    spec = importlib.util.spec_from_file_location("minimax_h3_fasth3", _FASTH3)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FastH3PreviewTests(unittest.TestCase):
    def test_preview_recipe_locks_four_steps_and_drops_turbo(self):
        fasth3 = _load_fasth3()
        body = {
            "minimax_h3_fasth3_mode": True,
            "minimax_h3_turbo_mode": True,
            "model_type": "minimax_h3",
            "num_inference_steps": 20,
            "activated_loras": [
                "cinematic_style.safetensors",
                "minimax_h3_turbo_4step_ckpt500.safetensors",
            ],
            "loras_multipliers": "1.15 0.50",
        }
        self.assertTrue(fasth3.normalize_fasth3_preview_request(body))
        self.assertEqual(body["num_inference_steps"], 4)
        self.assertEqual(body["minimax_h3_turbo_mode"], False)
        self.assertEqual(
            body["activated_loras"],
            ["cinematic_style.safetensors", fasth3.FASTH3_PREVIEW_LORA_FILENAME],
        )
        self.assertEqual(body["loras_multipliers"], "1.15 1.00")
        self.assertEqual(body["image_prompt_type"], "")
        self.assertEqual(
            fasth3.FASTH3_PREVIEW_LORA_SHA256,
            "42dc502a2078f166c396a1fa75f29728d1844363652d345d5ef3e2b444ed6470",
        )

    def test_preview_rejects_first_frame_and_omni_ref(self):
        fasth3 = _load_fasth3()
        with self.assertRaisesRegex(ValueError, "first or last frame"):
            fasth3.normalize_fasth3_preview_request({
                "minimax_h3_fasth3_mode": True,
                "image_prompt_type": "S",
            })
        with self.assertRaisesRegex(ValueError, "Omni"):
            fasth3.normalize_fasth3_preview_request({
                "minimax_h3_fasth3_mode": True,
                "minimax_h3_references": [{"type": "image", "path": "face.png"}],
            })
        with self.assertRaisesRegex(ValueError, "Ref2VA"):
            fasth3.normalize_fasth3_preview_request({
                "minimax_h3_fasth3_mode": True,
                "model_type": "minimax_h3_ref2va",
            })

    def test_preview_is_off_when_unchecked(self):
        fasth3 = _load_fasth3()
        body = {"minimax_h3_fasth3_mode": False, "num_inference_steps": 20}
        self.assertFalse(fasth3.normalize_fasth3_preview_request(body))
        self.assertEqual(body["num_inference_steps"], 20)

    def test_supported_architectures_are_t2va_fl2va_only(self):
        fasth3 = _load_fasth3()
        self.assertTrue(fasth3.fasth3_preview_supported("minimax_h3"))
        self.assertTrue(fasth3.fasth3_preview_supported("minimax_h3_full"))
        self.assertFalse(fasth3.fasth3_preview_supported("minimax_h3_ref2va"))
        self.assertFalse(fasth3.fasth3_preview_supported("minimax_h3_legacy"))

    def test_runtime_and_ui_advertise_the_managed_choice(self):
        launch = _LAUNCH.read_text(encoding="utf-8")
        toggle = _TOGGLE.read_text(encoding="utf-8")
        sidebar = _SIDEBAR.read_text(encoding="utf-8")
        types_source = _TYPES.read_text(encoding="utf-8")
        self.assertIn("def _minimax_h3_fasth3_option", launch)
        self.assertIn("FASTH3_PREVIEW_LORA_FILENAME", launch)
        self.assertIn('"minimax_h3_fasth3": _minimax_h3_fasth3_option(md)', launch)
        self.assertIn("normalize_fasth3_preview_request", launch)
        self.assertIn("<MiniMaxH3FastH3Toggle />", sidebar)
        self.assertIn("FastH3 Preview", toggle)
        self.assertIn("minimax_h3_fasth3_mode?: boolean", types_source)


if __name__ == "__main__":
    unittest.main()

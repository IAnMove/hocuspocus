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

    def test_fastvideo_adapter_is_rewritten_onto_native_h3_modules(self):
        import torch

        fasth3 = _load_fasth3()
        rank = 2
        hidden = 4
        head = fasth3._FASTVIDEO_HEAD_DIM_TOTAL
        half = fasth3._FASTVIDEO_FFN_HALF
        a_q = torch.arange(rank * hidden, dtype=torch.float32).reshape(rank, hidden)
        a_k = a_q + 10
        a_v = a_q + 20
        b_q = torch.arange(head * rank, dtype=torch.float32).reshape(head, rank)
        b_k = b_q + 1
        b_v = b_q + 2
        a_ff = torch.ones(rank, hidden)
        b_ff = torch.cat(
            [
                torch.full((half, rank), 3.0),
                torch.full((half, rank), 7.0),
            ],
            dim=0,
        )
        source = {
            "transformer_blocks.0.attn.to_q.lora_A.weight": a_q,
            "transformer_blocks.0.attn.to_q.lora_B.weight": b_q,
            "transformer_blocks.0.attn.to_k.lora_A.weight": a_k,
            "transformer_blocks.0.attn.to_k.lora_B.weight": b_k,
            "transformer_blocks.0.attn.to_v.lora_A.weight": a_v,
            "transformer_blocks.0.attn.to_v.lora_B.weight": b_v,
            "transformer_blocks.0.attn.to_out.0.lora_A.weight": a_q.clone(),
            "transformer_blocks.0.attn.to_out.0.lora_B.weight": torch.ones(hidden, rank),
            "transformer_blocks.0.ff.net.0.proj.lora_A.weight": a_ff,
            "transformer_blocks.0.ff.net.0.proj.lora_B.weight": b_ff,
            "transformer_blocks.0.ff.net.2.lora_A.weight": a_ff.clone(),
            "transformer_blocks.0.ff.net.2.lora_B.weight": torch.ones(hidden, rank),
            "transformer_blocks.0.attn.to_gate_compress.set_weight": torch.ones(8),
            "token_refiner.refiner_blocks.0.attn.to_q.lora_A.weight": a_q.clone(),
            "token_refiner.refiner_blocks.0.attn.to_q.lora_B.weight": b_q.clone(),
            "token_refiner.refiner_blocks.0.attn.to_k.lora_A.weight": a_k.clone(),
            "token_refiner.refiner_blocks.0.attn.to_k.lora_B.weight": b_k.clone(),
            "token_refiner.refiner_blocks.0.attn.to_v.lora_A.weight": a_v.clone(),
            "token_refiner.refiner_blocks.0.attn.to_v.lora_B.weight": b_v.clone(),
            "audio_proj_in.diff": torch.ones(hidden, 2),
            "time_embedder.linear_1.diff": torch.ones(hidden, hidden),
            "norm_out.linear.diff": torch.ones(6, 2688),
        }

        converted = fasth3.convert_fastvideo_h3_lora_to_native(
            source,
            drop_time_embedder=True,
        )

        self.assertNotIn("transformer_blocks.0.attn.to_q.lora_A.weight", converted)
        self.assertNotIn(
            "transformer_blocks.0.attn.to_gate_compress.set_weight",
            converted,
        )
        self.assertNotIn("time_embedder.proj_in.diff", converted)
        self.assertNotIn("time_embedder.linear_1.diff", converted)
        self.assertIn("blocks.0.attn.qkv_proj.lora_A.weight", converted)
        self.assertIn("blocks.0.attn.out_proj.lora_A.weight", converted)
        self.assertIn("blocks.0.mlp.fc1.lora_B.weight", converted)
        self.assertIn("blocks.0.mlp.fc2.lora_A.weight", converted)
        self.assertIn("token_refiner.blocks.0.attn.qkv_proj.lora_B.weight", converted)
        self.assertIn("audio_patch_proj.diff", converted)
        self.assertIn("final_layer.adaln_proj.linear.diff", converted)

        a_fused = converted["blocks.0.attn.qkv_proj.lora_A.weight"]
        b_fused = converted["blocks.0.attn.qkv_proj.lora_B.weight"]
        delta = b_fused @ a_fused
        expected = torch.cat((b_q @ a_q, b_k @ a_k, b_v @ a_v), dim=0)
        self.assertEqual(tuple(a_fused.shape), (6, hidden))
        self.assertEqual(tuple(b_fused.shape), (3 * head, 6))
        self.assertTrue(torch.allclose(delta, expected))

        swapped = converted["blocks.0.mlp.fc1.lora_B.weight"]
        self.assertTrue(torch.equal(swapped[:half], b_ff[half:]))
        self.assertTrue(torch.equal(swapped[half:], b_ff[:half]))

        native = {
            "blocks.0.attn.qkv_proj.lora_A.weight": a_q.clone(),
            "blocks.0.attn.qkv_proj.lora_B.weight": torch.ones(12, rank),
        }
        self.assertFalse(fasth3.is_fastvideo_h3_lora_state_dict(native))
        self.assertEqual(
            fasth3.convert_fastvideo_h3_lora_to_native(native).keys(),
            native.keys(),
        )

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

"""Registration tests for Qwen-Image 2.1."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import types
import unittest

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "app"
_HANDLER_PATH = _APP / "models" / "qwen" / "qwen_handler.py"
_MAIN_PATH = _APP / "models" / "qwen" / "qwen21_main.py"
_PIPELINE_PATH = _APP / "models" / "qwen" / "pipeline_qwenimage21.py"
_TRANSFORMER_PATH = _APP / "models" / "qwen" / "transformer_qwenimage21.py"
_VAE_PATH = _APP / "models" / "qwen" / "autoencoder_kl_qwenimage21.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_handler_class():
    source = _read(_HANDLER_PATH)
    tree = ast.parse(source, filename=str(_HANDLER_PATH))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(name.startswith("_QWEN21_") for name in names):
                selected.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "family_handler":
            selected.append(node)
    namespace = {
        "os": __import__("os"),
        "torch": types.SimpleNamespace(bfloat16="bfloat16", float32="float32"),
        "gr": types.SimpleNamespace(Info=lambda *_args, **_kwargs: None),
        "build_hf_url": lambda repo, *parts: "https://huggingface.co/" + repo + "/resolve/main/" + "/".join(parts),
    }
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(_HANDLER_PATH), "exec"), namespace)
    return namespace["family_handler"]


class TestQwenImage21Definitions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handler = _load_handler_class()

    def test_handler_registers_qwen_image_21(self):
        self.assertIn("qwen_image_21", self.handler.query_supported_types())
        model_def = self.handler.query_model_def("qwen_image_21", {})
        self.assertTrue(model_def["image_outputs"])
        self.assertEqual(model_def["text_encoder_folder"], "Qwen3-VL-8B-Instruct")
        self.assertEqual(model_def["max_image_refs"], 10)
        self.assertEqual(model_def["vae_upsampler"], [])
        urls = model_def["text_encoder_URLs"]
        self.assertTrue(any("qwen3vl_8b_bf16.safetensors" in url for url in urls))
        self.assertTrue(any("qwen3vl_8b_int8_convrot.safetensors" in url for url in urls))
        self.assertTrue(any("qwen3vl_8b_w4a8.safetensors" in url for url in urls))
        self.assertTrue(model_def["inpaint_support"])
        self.assertTrue(model_def["image_ref_inpaint"])
        self.assertTrue(model_def["native_rgba"])
        self.assertEqual(model_def["inpaint_video_prompt_type"], "VAG")
        self.assertEqual(model_def["video_guide_outpainting"], [1, 2])
        self.assertEqual(model_def["max_image_refs"], 10)
        self.assertTrue(model_def["background_removal_label"])
        self.assertEqual(model_def["resolution_presets"]["1080p"]["label"], "2K")
        self.assertEqual(model_def["resolution_presets"]["1080p"]["values"]["1:1"], "2048x2048")
        self.assertEqual(model_def["resolution_presets"]["auto"]["values"]["1:1"], "1024x1024")
        self.assertEqual(model_def["resolution_preset_order"], ["auto", "720p", "1080p"])
        self.assertIn("KI", [choice[1] for choice in model_def["image_ref_choices"]["choices"]])

    def test_every_qwen_canvas_is_aligned_and_invalid_custom_size_is_rejected(self):
        presets = self.handler.query_model_def("qwen_image_21", {})["resolution_presets"]
        for preset in presets.values():
            for size in preset["values"].values():
                width, height = map(int, size.split("x"))
                self.assertEqual(width % 32, 0)
                self.assertEqual(height % 32, 0)
                self.assertIsNone(self.handler.validate_generative_settings("qwen_image_21", {}, {"resolution": size}))
        self.assertIn("divisible by 32", self.handler.validate_generative_settings("qwen_image_21", {}, {"resolution": "1280x720"}))

    def test_defaults_point_at_comfy_and_gguf_weights(self):
        payload = json.loads((_APP / "defaults" / "qwen_image_21.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["model"]["architecture"], "qwen_image_21")
        self.assertEqual(payload["num_inference_steps"], 40)
        self.assertEqual(payload["guidance_scale"], 1)
        self.assertEqual(payload["resolution"], "1024x1024")
        self.assertIn("4090", payload["model"]["selector_help"])
        self.assertEqual(payload["model"]["resource_requirements"]["vram_gb"], 16)
        self.assertTrue(any("qwen_image_2.1_int8_convrot.safetensors" in url for url in payload["model"]["URLs"]))
        self.assertFalse(any("bf16.safetensors" in url for url in payload["model"]["URLs"]))

        bf16 = json.loads((_APP / "defaults" / "qwen_image_21_bf16.json").read_text(encoding="utf-8"))
        self.assertIn("qwen_image_2.1_bf16.safetensors", bf16["model"]["URLs"][0])
        self.assertEqual(bf16["model"]["preload_URLs"], "qwen_image_21")
        self.assertEqual(bf16["model"]["resource_requirements"]["vram_gb"], 24)

        catalog = {
            "qwen_image_21_gguf_q4_k.json": "qwen_image_2.1-Q4_K.gguf",
            "qwen_image_21_gguf_q5_0.json": "qwen_image_2.1-Q5_0.gguf",
            "qwen_image_21_gguf_q8_0.json": "qwen_image_2.1-Q8_0.gguf",
            "qwen_image_21_uncensored_gguf_q4_k_m.json": "qwen-image-2.1-Q4_K_M.gguf",
            "qwen_image_21_uncensored_gguf_q5_k_m.json": "qwen-image-2.1-Q5_K_M.gguf",
            "qwen_image_21_uncensored_gguf_q6_k.json": "qwen-image-2.1-Q6_K.gguf",
        }
        for filename, weight in catalog.items():
            with self.subTest(filename=filename):
                item = json.loads((_APP / "defaults" / filename).read_text(encoding="utf-8"))
                self.assertEqual(item["model"]["architecture"], "qwen_image_21")
                self.assertIn(weight, item["model"]["URLs"][0])
                if "uncensored" in filename:
                    self.assertFalse(item["model"].get("nsfw_only", False))
                    self.assertIn("abenzerps/Qwen-Image-2.1-GGUF", item["model"]["URLs"][0])
                self.assertEqual(item["model"]["preload_URLs"], "qwen_image_21")
                self.assertTrue(item["model"]["selector_help"])
                self.assertIn("vram_gb", item["model"]["resource_requirements"])

    def test_download_list_uses_qwen3_vl_and_new_vae(self):
        files = self.handler.query_model_files(lambda name: [name], "qwen_image_21", {})
        repos = {item["repoId"] for item in files}
        self.assertIn("Qwen/Qwen-Image-2.1", repos)
        self.assertIn("Comfy-Org/Qwen-Image-2.1", repos)
        vae = next(item for item in files if item["repoId"] == "Comfy-Org/Qwen-Image-2.1")
        self.assertIn("qwen_image_2.1_vae_bf16.safetensors", vae["fileList"][0])

    def test_default_settings_and_reference_cap(self):
        defaults = {}
        self.handler.update_default_settings("qwen_image_21", {}, defaults)
        self.assertEqual(defaults["guidance_scale"], 1)
        self.assertEqual(defaults["num_inference_steps"], 40)
        self.assertIsNone(self.handler.validate_generative_settings(
            "qwen_image_21", {}, {"image_refs": list(range(10))}
        ))
        self.assertIn("at most 10", self.handler.validate_generative_settings(
            "qwen_image_21", {}, {"image_refs": list(range(11))}
        ))

    def test_runtime_modules_are_the_2_1_stack(self):
        main = _read(_MAIN_PATH)
        self.assertIn("QwenImage21Transformer2DModel", main)
        self.assertIn("AutoencoderKLQwenImage21", main)
        self.assertIn("Qwen3VLForConditionalGeneration", main)
        self.assertIn("Qwen3VLProcessor", main)
        self.assertIn("_remap_qwen3vl_comfy_keys", main)
        self.assertIn("model.language_model.", main)
        self.assertIn("_locate_qwen21_vae", main)
        self.assertIn('os.path.join("vae", basename)', main)
        self.assertIn("convert_qwen_image_21_vae_state_dict", main)
        transformer = _read(_TRANSFORMER_PATH)
        self.assertIn("class QwenImage21Transformer2DModel", transformer)
        self.assertIn("causal_condition", transformer)
        self.assertIn("self.gate_up", transformer)
        self.assertNotIn("self.gate_layer", transformer)
        vae = _read(_VAE_PATH)
        self.assertIn("class AutoencoderKLQwenImage21", vae)
        self.assertIn("z_dim: int = 64", vae)
        pipeline = _read(_PIPELINE_PATH)
        self.assertIn("true_cfg_scale: float = 1.0", pipeline)
        self.assertIn("QwenImage21KVCache", pipeline)
        self.assertIn("image_mask=None", pipeline)
        self.assertIn("def _prepare_local_edit", pipeline)
        self.assertIn("do_convert_rgb=False", pipeline)
        self.assertIn("def _as_vae_tensor", pipeline)
        self.assertIn("image.shape[1] == 4", pipeline)
        self.assertIn("image_mask=image_mask", main)
        self.assertIn("denoising_strength=denoising_strength", main)
        self.assertIn("preprocessor_config.json", main)
        self.assertIn("text_encoder", main)

    def test_studio_image_generation_unlocks_2_1_features(self):
        root = _ROOT
        launch = _read(root / "app" / "_launch_runtime.py")
        types_source = _read(root / "ui" / "src" / "types" / "index.ts")
        sidebar = _read(root / "ui" / "src" / "components" / "Sidebar" / "Sidebar.tsx")
        image_gen = _read(root / "ui" / "src" / "lib" / "imageGeneration.ts")
        store = _read(root / "ui" / "src" / "stores" / "useStore.ts")
        self.assertIn('"inpaint_support": bool(md.get("inpaint_support", False))', launch)
        self.assertIn('"native_rgba": bool(md.get("native_rgba", False))', launch)
        self.assertIn("1 in md.get(\"video_guide_outpainting\")", launch)
        self.assertIn("inpaint_support?: boolean", types_source)
        self.assertIn("native_rgba?: boolean", types_source)
        panel = _read(root / "ui" / "src" / "components" / "Sidebar" / "ImageStudioPanel.tsx")
        self.assertIn("ImageStudioPanel", sidebar)
        self.assertIn("{isImage && <ImageStudioPanel />}", sidebar)
        self.assertIn("ImageEditSection", panel)
        self.assertIn("ImageIntentChooser", panel)
        self.assertIn("selected.startsWith('qwen_image_21')", image_gen)
        knowledge = _read(root / "ui" / "src" / "features" / "agent" / "agentKnowledge.ts")
        self.assertIn("qwen_image_21*", knowledge)
        self.assertIn("unified text-to-image and image-edit", knowledge)
        self.assertIn("reference_role=edit_source", knowledge)
        mcp = _read(root / "app" / "routers" / "image_generation_commands.py")
        self.assertIn("qwen_image_21*", mcp)
        self.assertIn("'qwen_image_21'", store.split("const DEFAULT_ENABLED_MODELS = new Set([", 1)[1].split("])\n", 1)[0])
        self.assertGreaterEqual(int(store.split("const DEFAULTS_VERSION = ", 1)[1].splitlines()[0]), 13)

    def test_enhance_guide_prefers_edit_when_images_are_present(self):
        from services.enhance_guides import _ARCHITECTURE_MAP
        from services.guide_resolution import longest_prefix

        self.assertEqual(_ARCHITECTURE_MAP["qwen_image_21"], ("qwen_image_edit.md", "qwen_image_gen.md"))
        self.assertEqual(longest_prefix("qwen_image_21", _ARCHITECTURE_MAP), "qwen_image_21")
        self.assertEqual(longest_prefix("qwen_image_21_gguf_q4_k", _ARCHITECTURE_MAP), "qwen_image_21")


class TestQwenImage21VaeConvert(unittest.TestCase):
    def test_nested_comfy_keys_and_5d_squeeze(self):
        import torch
        from models.qwen.convert_diffusers_qwen21_vae import convert_qwen_image_21_vae_state_dict

        source = {
            "conv1.weight": torch.zeros(128, 768, 1, 1, 1),
            "encoder.conv1.weight": torch.zeros(96, 4, 1, 3, 3),
            "encoder.downsamples.1.downsamples.0.residual.2.weight": torch.zeros(192, 96, 1, 3, 3),
            "encoder.downsamples.1.downsamples.0.shortcut.weight": torch.zeros(192, 96, 1, 1, 1),
            "encoder.downsamples.1.downsamples.2.resample.1.weight": torch.zeros(192, 192, 3, 3),
            "encoder.downsamples.1.downsamples.2.time_conv.weight": torch.zeros(192, 192, 1, 1, 1),
            "decoder.upsamples.2.upsamples.0.residual.2.weight": torch.zeros(576, 1152, 1, 3, 3),
            "decoder.upsamples.2.upsamples.3.resample.1.weight": torch.zeros(576, 576, 3, 3),
            "decoder.head.2.weight": torch.zeros(4, 144, 1, 3, 3),
        }
        converted = convert_qwen_image_21_vae_state_dict(source)
        self.assertEqual(tuple(converted["quant_conv.weight"].shape), (128, 768, 1, 1))
        self.assertEqual(tuple(converted["encoder.conv_in.weight"].shape), (96, 4, 3, 3))
        self.assertEqual(
            tuple(converted["encoder.down_blocks.1.resnets.0.conv1.weight"].shape),
            (192, 96, 3, 3),
        )
        self.assertEqual(
            tuple(converted["encoder.down_blocks.1.resnets.0.conv_shortcut.weight"].shape),
            (192, 96, 1, 1),
        )
        self.assertEqual(
            tuple(converted["encoder.down_blocks.1.downsampler.resample.1.weight"].shape),
            (192, 192, 3, 3),
        )
        self.assertEqual(
            tuple(converted["encoder.down_blocks.1.downsampler.time_conv.weight"].shape),
            (192, 192, 1, 1),
        )
        self.assertEqual(
            tuple(converted["decoder.up_blocks.2.resnets.0.conv1.weight"].shape),
            (576, 1152, 3, 3),
        )
        self.assertEqual(
            tuple(converted["decoder.up_blocks.2.upsampler.resample.1.weight"].shape),
            (576, 576, 3, 3),
        )
        self.assertEqual(tuple(converted["decoder.conv_out.weight"].shape), (4, 144, 3, 3))


class TestQwenImage21RgbFactors(unittest.TestCase):
    def test_preview_factors_are_64_channel(self):
        from shared.RGB_factors import get_rgb_factors

        factors, bias = get_rgb_factors("qwen", model_type="qwen_image_21")
        self.assertEqual(len(factors), 64)
        self.assertEqual(len(factors[0]), 3)
        self.assertEqual(bias, [-0.1228, -0.1869, -0.3083])
        old, old_bias = get_rgb_factors("qwen", model_type="qwen_image_20B")
        self.assertEqual(len(old), 16)
        self.assertEqual(old_bias, [-0.1835, -0.0868, -0.3360])

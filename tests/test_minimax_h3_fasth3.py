"""CPU coverage for the official FastVideo FastH3 V2 and Trim model entries.

The checkpoint tests read ``tests/fixtures/fasth3_checkpoint_headers.json``: the
safetensors headers of the pinned FastH3 files and of the fused INT8 ConvRot
checkpoint the loader already supports (rebuild it with
``scripts/h3_checkpoint_header_fixture.py``).  Tensors are built on the meta
device, so no weights and no GPU are involved.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

V2_DEFAULT = APP / "defaults" / "minimax_h3_fasth3_v2.json"
TRIM_DEFAULT = APP / "defaults" / "minimax_h3_fasth3_trim.json"
NOTICE = APP / "models" / "minimax_h3" / "H3_FASTH3_NOTICE.md"
FIXTURE = ROOT / "tests" / "fixtures" / "fasth3_checkpoint_headers.json"

# Tensors a FastH3 file carries that the loader's module tree has no slot for.
VSA_GATE = "blocks.N.attn.to_gate_compress"
FUSED_UNUSED = {"adaln_basis", "adaln_mean"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture() -> dict:
    return _load(FIXTURE)["checkpoints"]


class TestFastH3Definitions(unittest.TestCase):
    def test_entries_pin_the_files_the_fixture_describes(self):
        checkpoints = _fixture()
        for path, key in (
            (V2_DEFAULT, "fasth3_v2_int8_convrot"),
            (TRIM_DEFAULT, "fasth3_trim_int8_convrot"),
        ):
            with self.subTest(entry=path.name):
                model = _load(path)["model"]
                source = checkpoints[key]["source"]
                self.assertEqual(model["URLs"], [
                    f"https://huggingface.co/{source['repo']}/resolve/"
                    f"{source['revision']}/{source['path']}"
                ])
                self.assertEqual(model["source_revision"], source["revision"])
                self.assertEqual(model["source_sha256"], source["sha256"])
                self.assertEqual(model["architecture"], "minimax_h3")
                self.assertIn("int8_convrot", source["path"])

    def test_recipe_matches_fastvideo_settings(self):
        for path in (V2_DEFAULT, TRIM_DEFAULT):
            with self.subTest(entry=path.name):
                definition = _load(path)
                model = definition["model"]
                self.assertEqual(model["minimax_h3_sampler"], "res_multistep")
                self.assertEqual(model["minimax_h3_video_shift"], 10.0)
                self.assertEqual(model["minimax_h3_audio_shift"], 3.0)
                self.assertEqual(model["minimax_h3_qkv_layout"], "grouped")
                self.assertTrue(model["lock_inference_steps"])
                self.assertEqual(model["inference_steps_min"], 8)
                self.assertEqual(model["inference_steps_max"], 8)
                self.assertTrue(model["lock_guidance_scale"])
                self.assertTrue(model["loras_disabled"])
                self.assertFalse(model["first_block_cache"])
                self.assertEqual(definition["num_inference_steps"], 8)
                self.assertEqual(definition["guidance_scale"], 1.0)

    def test_sla_is_off_by_default_but_selectable(self):
        for path in (V2_DEFAULT, TRIM_DEFAULT):
            with self.subTest(entry=path.name):
                definition = _load(path)
                self.assertTrue(definition["model"]["sla_attention"])
                self.assertFalse(definition["model"]["sla_attention_default"])
                self.assertEqual(definition["override_attention"], "")

    def test_selector_help_states_what_is_and_is_not_known(self):
        for path in (V2_DEFAULT, TRIM_DEFAULT):
            with self.subTest(entry=path.name):
                help_text = _load(path)["model"]["selector_help"]
                self.assertIn("8 STEPS", help_text)
                self.assertIn("OFFICIAL FASTVIDEO", help_text)
                self.assertIn("Not yet benchmarked on a 4090", help_text)

    def test_vaes_and_text_encoder_are_the_apps_own(self):
        fused = _load(APP / "defaults" / "minimax_h3_fused_turbo.json")["model"]
        for path in (V2_DEFAULT, TRIM_DEFAULT):
            with self.subTest(entry=path.name):
                model = _load(path)["model"]
                self.assertEqual(
                    model["minimax_h3_video_vae_filename"],
                    fused["minimax_h3_video_vae_filename"],
                )
                for key in (
                    "video_vae_source_repo",
                    "video_vae_source_revision",
                    "video_vae_source_sha256",
                ):
                    self.assertEqual(model[key], fused[key])
                self.assertNotIn("text_encoder_URLs", model)
                assets = model["required_model_assets"]
                self.assertIn("minimax_h3/fasth3/LICENSE", assets)
                self.assertNotIn("minimax_h3/fused_turbo/NOTICE", assets)

    def test_notice_carries_revisions_hashes_and_license(self):
        notice = " ".join(NOTICE.read_text(encoding="utf-8").split())
        for path in (V2_DEFAULT, TRIM_DEFAULT):
            model = _load(path)["model"]
            self.assertIn(model["source_revision"], notice)
            self.assertIn(model["source_sha256"], notice)
        self.assertIn("MiniMax H3 Community License", notice)
        for territory in ("European Union", "United Kingdom", "Korea", "United States"):
            self.assertIn(territory, notice)


class TestFastH3Handler(unittest.TestCase):
    def test_definition_is_text_to_video_only(self):
        from models.minimax_h3.minimax_h3_handler import family_handler

        frames = family_handler.query_model_def("minimax_h3", {})
        definition = family_handler.query_model_def(
            "minimax_h3",
            {"minimax_h3_fused_turbo": True, "minimax_h3_fasth3": True},
        )

        self.assertEqual(frames["image_prompt_types_allowed"], "TSEV")
        self.assertEqual(definition["image_prompt_types_allowed"], "")
        self.assertTrue(definition["t2v_class"])
        self.assertTrue(definition["returns_audio"])
        for key in (
            "i2v_class",
            "end_frames_always_enabled",
            "custom_frames_injection",
            "sliding_window",
            "video_continuation",
        ):
            self.assertIs(definition[key], False, key)
        # WanGP reads these with defaults, so they must be absent, not None.
        for key in (
            "guide_custom_choices",
            "mask_preprocessing",
            "audio_prompt_type_sources",
            "sliding_window_defaults",
        ):
            self.assertNotIn(key, definition)

    def test_entry_json_wins_over_the_fused_defaults(self):
        from models.minimax_h3.minimax_h3_handler import family_handler

        model = _load(V2_DEFAULT)["model"]
        merged = family_handler.query_model_def("minimax_h3", model)
        merged.update(model)

        self.assertFalse(merged["sla_attention_default"])
        self.assertTrue(merged["lock_inference_steps"])
        self.assertEqual(merged["inference_steps_max"], 8)
        self.assertEqual(merged["minimax_h3_video_shift"], 10.0)
        self.assertFalse(merged["sol_attention"])

    def test_license_comes_from_minimax_not_the_fused_publisher(self):
        from models.minimax_h3 import minimax_h3_handler as handler

        def files(model_def):
            return [
                (item["repoId"], name)
                for item in handler.family_handler.query_model_files(
                    [], "minimax_h3", model_def
                )
                for group in item["fileList"]
                for name in group
            ]

        fasth3 = files({"minimax_h3_fused_turbo": True, "minimax_h3_fasth3": True})
        fused = files({"minimax_h3_fused_turbo": True})

        self.assertIn((handler._OFFICIAL_REPO, "LICENSE"), fasth3)
        self.assertNotIn((handler._FUSED_MODEL_REPO, "LICENSE"), fasth3)
        self.assertNotIn((handler._FUSED_MODEL_REPO, "NOTICE"), fasth3)
        self.assertIn((handler._FUSED_MODEL_REPO, "NOTICE"), fused)
        self.assertNotIn((handler._OFFICIAL_REPO, "LICENSE"), fused)

    def test_validate_pins_the_distilled_recipe(self):
        from models.minimax_h3.minimax_h3_handler import family_handler

        inputs = {
            "num_inference_steps": 20,
            "guidance_scale": 4.0,
            "override_attention": "sol",
            "activated_loras": [],
            "video_length": 124,
        }
        error = family_handler.validate_generative_settings(
            "minimax_h3",
            {"minimax_h3_fused_turbo": True, "minimax_h3_fasth3": True},
            inputs,
        )

        self.assertIsNone(error)
        self.assertEqual(inputs["num_inference_steps"], 8)
        self.assertEqual(inputs["flow_shift"], 10.0)
        self.assertEqual(inputs["audio_flow_shift"], 3.0)
        self.assertEqual(inputs["guidance_scale"], 1.0)
        self.assertEqual(inputs["override_attention"], "")

    def test_validate_returns_message_for_user_loras(self):
        from models.minimax_h3.minimax_h3_handler import family_handler

        error = family_handler.validate_generative_settings(
            "minimax_h3",
            {"minimax_h3_fused_turbo": True, "minimax_h3_fasth3": True},
            {"activated_loras": ["my_character.safetensors"], "video_length": 124},
        )
        self.assertIn("my_character.safetensors", error)


class TestFastH3Request(unittest.TestCase):
    def test_distilled_recipe_overrides_stale_values(self):
        from models.minimax_h3.fasth3 import normalize_fasth3_request

        body = {
            "activated_loras": ["MiniMax-H3-FL2VA-Acc-8Step.safetensors"],
            "loras_multipliers": "1.00",
            "num_inference_steps": 4,
            "guidance_scale": 5.0,
            "flow_shift": 12.0,
            "skip_steps_cache_type": "first_block",
            "minimax_h3_turbo_mode": True,
        }
        self.assertEqual(normalize_fasth3_request(body), 1)
        self.assertEqual(body["activated_loras"], [])
        self.assertEqual(body["num_inference_steps"], 8)
        self.assertEqual(body["flow_shift"], 10.0)
        self.assertEqual(body["audio_flow_shift"], 3.0)
        self.assertEqual(body["guidance_scale"], 1.0)
        self.assertEqual(body["skip_steps_cache_type"], "")
        self.assertFalse(body["minimax_h3_turbo_mode"])

    def test_attention_is_dense_unless_asked(self):
        from models.minimax_h3.fasth3 import normalize_fasth3_request

        for requested, expected in (
            (None, ""), ("", ""), ("sol", ""), ("sla", "sla"), ("SDPA", "sdpa"),
        ):
            with self.subTest(requested=requested):
                body = {"override_attention": requested}
                normalize_fasth3_request(body)
                self.assertEqual(body["override_attention"], expected)

    def test_runtime_policy_routes_fasth3_before_the_fused_recipe(self):
        from services.h3_runtime_policy import normalize_h3_runtime_request

        body = {"model_type": "minimax_h3", "num_inference_steps": 4}
        handled = normalize_h3_runtime_request(
            body,
            {"minimax_h3_fused_turbo": True, "minimax_h3_fasth3": True},
        )
        self.assertFalse(handled)
        self.assertEqual(body["num_inference_steps"], 8)
        self.assertEqual(body["flow_shift"], 10.0)
        self.assertEqual(body["override_attention"], "")

        fused = {"model_type": "minimax_h3", "num_inference_steps": 4}
        normalize_h3_runtime_request(fused, {"minimax_h3_fused_turbo": True})
        self.assertEqual(fused["flow_shift"], 12.0)
        self.assertEqual(fused["override_attention"], "sla")

    def test_production_and_typed_first_frame_commands_do_not_pick_it_up(self):
        """Those paths send start frames, which FastH3 was not distilled for."""

        from services import production_video_model as production
        from services import video_generation_v3 as api

        for model_type in ("minimax_h3_fasth3_v2", "minimax_h3_fasth3_trim"):
            self.assertNotIn(model_type, api.FL2VA_MODEL_TYPES)
            self.assertNotIn(model_type, production.VIDEO_MODELS)
            self.assertTrue((APP / "defaults" / f"{model_type}.json").is_file())


class TestFastH3Checkpoints(unittest.TestCase):
    """Compare the real file headers with what the loader builds."""

    @classmethod
    def setUpClass(cls):
        try:
            import torch
            from accelerate import init_empty_weights
            from mmgp import offload, quant_router
        except ModuleNotFoundError as error:
            raise unittest.SkipTest("FastH3 checkpoint tests need the app runtime") from error
        cls.torch = torch
        cls.init_empty_weights = staticmethod(init_empty_weights)
        cls.offload = offload
        cls.quant_router = quant_router
        cls.checkpoints = _fixture()

    DTYPES = {
        "F32": "float32", "F16": "float16", "BF16": "bfloat16",
        "I8": "int8", "U8": "uint8",
    }

    def state_dict(self, name: str) -> dict:
        """Meta tensors named like the real file; descriptors carry real bytes."""

        torch = self.torch
        entry = self.checkpoints[name]
        descriptors = entry["comfy_quant"]
        state = {}
        for pattern, (dtype, shape, count) in entry["tensors"].items():
            for index in range(count):
                key = self.expand(pattern, index)
                if pattern.endswith(".comfy_quant"):
                    # Every descriptor in a file has the same byte size (see
                    # comfy_quant_sizes); one real descriptor stands in for all.
                    text = descriptors["blocks.0.attn.qkv_proj"]
                    state[key] = torch.tensor(list(text.encode()), dtype=torch.uint8)
                else:
                    state[key] = torch.empty(
                        shape, dtype=getattr(torch, self.DTYPES[dtype]), device="meta"
                    )
        return state

    @staticmethod
    def expand(pattern: str, index: int) -> str:
        return pattern.replace(".N.", f".{index}.")

    def probe(self, name: str) -> dict:
        from models.minimax_h3 import minimax_h3_main as main

        metadata = self.checkpoints[name]["metadata"] or {}
        with patch.object(
            main.quant_router,
            "load_metadata_state_dict",
            return_value=(self.state_dict(name), metadata),
        ):
            return main.probe_h3_checkpoint(name)

    def test_probe_reads_depth_and_timestep_rank_from_headers(self):
        expected = {
            "fused_turbo_int8_convrot": (50, 8),
            "fasth3_v2_int8_convrot": (50, 8),
            "fasth3_trim_int8_convrot": (42, 16),
        }
        for name, (layers, rank) in expected.items():
            with self.subTest(checkpoint=name):
                info = self.probe(name)
                self.assertEqual(info["num_layers"], layers)
                self.assertEqual(info["time_embed_dim"], rank)
                self.assertEqual(info["adaln_curve_grid"], 1025)
                self.assertTrue(info["compressed_modulation"])
                self.assertTrue(info["convrot"])

    def test_header_diff_against_the_fused_checkpoint_is_exactly_known(self):
        fused = self.checkpoints["fused_turbo_int8_convrot"]["tensors"]
        v2 = self.checkpoints["fasth3_v2_int8_convrot"]["tensors"]
        trim = self.checkpoints["fasth3_trim_int8_convrot"]["tensors"]

        only_fused = set(fused) - set(v2)
        only_v2 = set(v2) - set(fused)
        self.assertEqual(only_fused, FUSED_UNUSED)
        self.assertEqual(
            {name for name in only_v2 if VSA_GATE in name},
            {f"{VSA_GATE}.{leaf}" for leaf in ("comfy_quant", "weight", "weight_scale")},
        )
        # The only other new tensors are the INT8 token refiner's scales and descriptors.
        self.assertEqual(
            {name for name in only_v2 if VSA_GATE not in name},
            {
                f"token_refiner.blocks.N.{layer}.{leaf}"
                for layer in ("attn.out_proj", "attn.qkv_proj", "mlp.fc1", "mlp.fc2")
                for leaf in ("comfy_quant", "weight_scale")
            },
        )
        self.assertEqual(set(v2), set(trim))
        # Trim differs from V2 only in depth, rank-16 curves and FP32 AdaLN projections.
        changed = {name for name in v2 if v2[name][:2] != trim[name][:2]}
        self.assertEqual(
            {name.split(".linear")[0] if ".linear" in name else name for name in changed},
            {"adaln_t_table", "blocks.N.adaln_proj", "final_layer.adaln_proj"},
        )
        self.assertEqual(v2["blocks.N.attn.qkv_proj.weight"][2], 50)
        self.assertEqual(trim["blocks.N.attn.qkv_proj.weight"][2], 42)

    def test_quantization_descriptors_are_the_convrot_format_the_app_reads(self):
        for name in self.checkpoints:
            for tensor, text in self.checkpoints[name]["comfy_quant"].items():
                with self.subTest(checkpoint=name, tensor=tensor):
                    descriptor = json.loads(text)
                    self.assertEqual(descriptor["format"], "int8_tensorwise")
                    self.assertTrue(descriptor["convrot"])
                    self.assertEqual(descriptor["convrot_groupsize"], 256)

    def convert_like_the_loader(self, name: str):
        """Run the real strip, quantization routing, QKV split and requantize steps."""

        from models.minimax_h3 import minimax_h3_main as main
        from models.minimax_h3.fasth3 import transformer_depth_kwargs
        from models.minimax_h3.transformer import (
            MiniMaxH3Transformer,
            get_linear_split_map,
        )

        torch = self.torch
        info = self.probe(name)
        state, _, _ = main._strip_transformer_wrappers(
            self.state_dict(name), interleave_qkv=False
        )
        with (
            patch.object(
                self.quant_router, "_HANDLER_MODULES", ["shared.qtypes.int8_convrot"]
            ),
            patch.object(self.quant_router, "_QTYPE_QMODULE_CACHE", None),
        ):
            converted = self.quant_router.detect_and_convert(
                state, default_dtype=torch.bfloat16, verboseLevel=0
            )
            self.assertEqual(converted["kind"], "int8_convrot")
            with self.init_empty_weights(include_buffers=True):
                model = MiniMaxH3Transformer(
                    curve_grid=info["adaln_curve_grid"],
                    curve_dim=info["time_embed_dim"],
                    dtype=torch.bfloat16,
                    **transformer_depth_kwargs(info),
                )
            split_map = get_linear_split_map(56 * 128)
            self.offload.split_linear_modules(model, split_map)
            state, quant_map = self.quant_router.split_fused_weights(
                converted["state_dict"],
                converted["quant_map"],
                split_map,
                default_dtype=torch.bfloat16,
                verboseLevel=0,
            )
            quant_map, _ = self.quant_router.apply_pre_quantization(
                model, state, quant_map, default_dtype=torch.bfloat16, verboseLevel=0
            )
            self.offload._requantize(
                model, state, quant_map, default_dtype=torch.bfloat16
            )
        return model, state

    def diff_keys(self, name: str):
        model, state = self.convert_like_the_loader(name)
        loaded = set()
        for key in state:
            if key.endswith(".weight._data"):
                loaded.add(key[: -len("._data")])
            elif not key.endswith((".weight._scale", ".convrot_group_size")):
                loaded.add(key)
        expected = set(model.state_dict())
        return model, expected - loaded, loaded - expected

    def test_loader_finds_a_slot_for_every_tensor_it_needs(self):
        for name in self.checkpoints:
            with self.subTest(checkpoint=name):
                _, missing, unused = self.diff_keys(name)
                self.assertEqual(missing, set())
                expected_unused = FUSED_UNUSED if name.startswith("fused") else set()
                self.assertEqual(unused, expected_unused)

    def test_vsa_gate_tensors_are_dropped_before_loading(self):
        from models.minimax_h3.fasth3 import drop_unused_vsa_tensors

        state = self.state_dict("fasth3_v2_int8_convrot")
        self.assertEqual(sum("to_gate_compress" in key for key in state), 150)
        self.assertEqual(drop_unused_vsa_tensors(state), 150)
        self.assertFalse(any("to_gate_compress" in key for key in state))
        self.assertEqual(drop_unused_vsa_tensors(state), 0)

    def test_token_refiner_is_quantized_and_split_like_the_main_blocks(self):
        for name in ("fasth3_v2_int8_convrot", "fasth3_trim_int8_convrot"):
            with self.subTest(checkpoint=name):
                model, _, _ = self.diff_keys(name)
                refiner = {
                    module_name: type(module).__name__
                    for module_name, module in model.named_modules()
                    if module_name.startswith("token_refiner.blocks.0.")
                    and module_name.rsplit(".", 1)[-1]
                    in {"q_proj", "k_proj", "v_proj", "out_proj", "fc1", "fc2"}
                }
                self.assertEqual(len(refiner), 6)
                main_blocks = {
                    type(module).__name__
                    for module_name, module in model.named_modules()
                    if module_name.startswith("blocks.0.attn.q_proj")
                }
                self.assertEqual(set(refiner.values()), main_blocks)

    def test_trim_builds_forty_two_blocks_and_rank_sixteen_curves(self):
        from models.minimax_h3.fasth3 import transformer_depth_kwargs

        model, _, _ = self.diff_keys("fasth3_trim_int8_convrot")
        self.assertEqual(len(model.blocks), 42)
        self.assertEqual(tuple(model.adaln_t_table.shape), (1025, 16))
        self.assertEqual(transformer_depth_kwargs({"num_layers": None}), {})
        self.assertEqual(transformer_depth_kwargs({"num_layers": 42}), {"num_layers": 42})

    def test_transformer_loader_builds_the_depth_the_file_has(self):
        from models.minimax_h3 import minimax_h3_main as main

        for name, layers, rank in (
            ("fused_turbo_int8_convrot", 50, 8),
            ("fasth3_v2_int8_convrot", 50, 8),
            ("fasth3_trim_int8_convrot", 42, 16),
        ):
            with self.subTest(checkpoint=name):
                metadata = self.checkpoints[name]["metadata"] or {}
                with (
                    patch.object(
                        main.quant_router,
                        "load_metadata_state_dict",
                        return_value=(self.state_dict(name), metadata),
                    ),
                    patch.object(main.offload, "load_model_data") as load,
                ):
                    transformer = main._load_transformer(
                        name, self.torch.bfloat16, qkv_layout="grouped"
                    )
                load.assert_called_once()
                self.assertEqual(len(transformer.blocks), layers)
                self.assertEqual(tuple(transformer.adaln_t_table.shape), (1025, rank))
                self.assertEqual(transformer.h3_checkpoint_info["num_layers"], layers)

    def test_non_contiguous_blocks_are_rejected(self):
        from models.minimax_h3.fasth3 import count_dit_blocks

        keys = [f"blocks.{i}.attn.q_norm.weight" for i in (0, 1, 3)]
        with self.assertRaisesRegex(ValueError, "non-contiguous"):
            count_dit_blocks(keys)
        self.assertIsNone(count_dit_blocks(["token_refiner.blocks.0.attn.q_norm.weight"]))
        self.assertEqual(
            count_dit_blocks(
                ["model.diffusion_model.blocks.0.x", "model.diffusion_model.blocks.1.x"]
            ),
            2,
        )


class TestFastH3Schedule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch  # noqa: F401
        except ModuleNotFoundError as error:
            raise unittest.SkipTest("FastH3 schedule tests need PyTorch") from error

    def test_shifts_come_from_the_model_definition(self):
        from models.minimax_h3.fasth3 import h3_shifts

        self.assertEqual(h3_shifts({}), (12.0, 3.0))
        self.assertEqual(h3_shifts(None), (12.0, 3.0))
        self.assertEqual(h3_shifts(_load(V2_DEFAULT)["model"]), (10.0, 3.0))
        main = (APP / "models" / "minimax_h3" / "minimax_h3_main.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("video_shift, audio_shift = h3_shifts(model_def)", main)
        self.assertIn("MiniMaxH3Scheduler(shift=audio_shift)", main)

    def test_eight_evaluations_at_shift_ten_build_a_complete_res_schedule(self):
        from models.minimax_h3.scheduler import MiniMaxH3Scheduler
        from models.minimax_h3.turbo import h3_scheduler_grid_points

        video = MiniMaxH3Scheduler(shift=10.0, solver="res_multistep")
        audio = MiniMaxH3Scheduler(shift=3.0)
        points = h3_scheduler_grid_points(8, turbo_active=False)
        video.set_timesteps(points, device="cpu")
        audio.set_timesteps(points, device="cpu")

        self.assertEqual(len(video.timesteps), 8)
        self.assertEqual(len(video.sigmas), 9)
        self.assertEqual(len(audio.timesteps), 8)
        self.assertEqual(video.coefficients_for_step(7)[2], 0.0)
        fused = MiniMaxH3Scheduler(shift=12.0, solver="res_multistep")
        fused.set_timesteps(points, device="cpu")
        # Shift 10 leaves the first step slightly less noisy than the fused 12.
        self.assertLess(float(video.sigmas[1]), float(fused.sigmas[1]))
        self.assertAlmostEqual(float(video.sigmas[0]), 1.0, places=5)


if __name__ == "__main__":
    unittest.main()

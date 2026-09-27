"""Viggle's adapter recipe on the existing native Qwen 2.1 runtime."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from diffusers import FlowMatchEulerDiscreteScheduler

from tests.test_qwen_image_21 import _load_handler_class
from models.qwen.qwen21_main import model_factory, _VIGGLE_TURBO_SIGMAS
from models.qwen.pipeline_qwenimage21 import calculate_shift, retrieve_timesteps
from models.qwen.qwen21_lora import fuse_qwen21_lora_projections

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = json.loads((ROOT / "app/defaults/qwen_image_21_viggle_turbo.json").read_text())


@pytest.mark.parametrize("alpha", [None, 1.0, 4.0])
def test_split_lora_updates_match_fused_gate_up_exactly(alpha):
    torch.manual_seed(12)
    prefix = "transformer.transformer_blocks.0.img_mlp"
    factors = {f"{prefix}.{projection}.lora_{side}.weight": torch.randn(*shape)
               for projection in ("gate_layer", "proj")
               for side, shape in (("A", (2, 4)), ("B", (6, 2)))}
    if alpha is not None:
        for projection in ("gate_layer", "proj"):
            factors[f"{prefix}.{projection}.alpha"] = torch.tensor(alpha)
    original_keys = set(factors)
    fused = fuse_qwen21_lora_projections(factors)
    x = torch.randn(3, 4)
    expected = torch.cat([
        (x @ factors[f"{prefix}.{projection}.lora_A.weight"].T)
        @ factors[f"{prefix}.{projection}.lora_B.weight"].T
        * (1 if alpha is None else alpha / 2)
        for projection in ("gate_layer", "proj")
    ], dim=-1)
    actual = (x @ fused[f"{prefix}.gate_up.lora_A.weight"].T) @ fused[f"{prefix}.gate_up.lora_B.weight"].T
    torch.testing.assert_close(actual, expected)
    assert fused[f"{prefix}.gate_up.alpha"] == 4
    assert set(factors) == original_keys
    assert not any("gate_layer" in key or ".proj." in key for key in fused)


def test_native_transformer_exposes_the_lora_conversion_hook():
    from models.qwen.transformer_qwenimage21 import QwenImage21Transformer2DModel
    passthrough = {"transformer.modulation.1.lora_A.weight": torch.ones(2, 4)}
    converted = QwenImage21Transformer2DModel.preprocess_loras(None, "qwen_image_21", passthrough)
    assert converted == passthrough


def test_turbo_reuses_base_weights_and_pins_one_runtime_adapter():
    base = json.loads((ROOT / "app/defaults/qwen_image_21.json").read_text())
    model = DEFINITION["model"]
    assert model["URLs"] == base["model"]["URLs"]
    assert model["preload_URLs"] == "qwen_image_21"
    assert len(model["loras"]) == 1
    assert "/b77064be8b3f0b1a13c6a212067cb3d281c60c84/" in model["loras"][0]
    assert model["loras"][0].endswith("v0.2.1-6step-lora-r256.safetensors")
    assert model["loras_multipliers"] == [1.0]
    assert model["lock_inference_steps"] and model["lock_guidance_scale"]
    assert model["no_negative_prompt"]


def test_turbo_defaults_and_reference_limit_do_not_change_base_model():
    handler = _load_handler_class()
    turbo = handler.query_model_def("qwen_image_21", DEFINITION["model"])
    base = handler.query_model_def("qwen_image_21", {})
    assert turbo["max_image_refs"] == 3
    assert base["max_image_refs"] == 10
    assert "6 steps" in turbo["resolution_presets"]["auto"]["hint"]
    assert "40 steps" in base["resolution_presets"]["auto"]["hint"]
    defaults = {}
    handler.update_default_settings("qwen_image_21", DEFINITION["model"], defaults)
    assert defaults["num_inference_steps"] == 6
    assert defaults["guidance_scale"] == 1
    handler.update_default_settings("qwen_image_21", {}, defaults)
    assert defaults["num_inference_steps"] == 40


@pytest.mark.parametrize("params,reason", [
    ({"num_inference_steps": 40}, "6-step"),
    ({"guidance_scale": 4}, "CFG 1"),
    ({"image_refs": ["one", "two", "three"], "image_guide": "source"}, "at most 3"),
])
def test_incompatible_settings_fail_before_generation(params, reason):
    handler = _load_handler_class()
    assert reason in handler.validate_generative_settings("qwen_image_21", DEFINITION["model"], params)
    assert handler.validate_generative_settings("qwen_image_21", DEFINITION["model"], {
        "image_refs": ["one", "two"], "image_guide": "source", "num_inference_steps": 6, "guidance_scale": 1,
    }) is None


@pytest.mark.parametrize("turbo,terminal", [(False, 0.02), (True, None)])
def test_scheduler_configuration_and_shifted_sigma_nodes(turbo, terminal):
    # Execute the actual constructor expression without loading model weights.
    tree = ast.parse((ROOT / "app/models/qwen/qwen21_main.py").read_text())
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "FlowMatchEulerDiscreteScheduler")
    scheduler = eval(compile(ast.Expression(call), "scheduler", "eval"), {
        "FlowMatchEulerDiscreteScheduler": FlowMatchEulerDiscreteScheduler,
        "self": SimpleNamespace(viggle_turbo=turbo),
    })
    assert scheduler.config.shift_terminal == terminal
    if turbo:
        raw = list(_VIGGLE_TURBO_SIGMAS)
        assert raw == [1.0, 0.9375, 0.875, 0.75, 0.5, 0.25]
        mu = calculate_shift(4096, 256, 8192, 0.5, 0.9)
        timesteps, steps = retrieve_timesteps(scheduler, 6, "cpu", sigmas=raw, mu=mu)
        assert steps == len(timesteps) == 6
        expected = torch.exp(torch.tensor(mu)) / (torch.exp(torch.tensor(mu)) + 1 / torch.tensor(raw) - 1)
        torch.testing.assert_close(scheduler.sigmas[:-1], expected)
        assert scheduler.sigmas[-1] == 0


@pytest.mark.parametrize("turbo,steps", [(False, 40), (True, 6)])
def test_generate_passes_recipe_and_ordered_edit_images_to_pipeline(monkeypatch, turbo, steps):
    from PIL import Image
    model = object.__new__(model_factory)
    model.viggle_turbo = turbo
    model.transformer = torch.nn.Identity()
    model.text_encoder = torch.nn.Identity()
    captured = {}
    def pipeline(**kwargs):
        captured.update(kwargs)
        return torch.zeros(1, 4, 32, 32)
    model.pipeline = pipeline
    generator = torch.Generator
    monkeypatch.setattr(torch, "Generator", lambda **_: generator(device="cpu"))
    refs = [Image.new("RGB", (64, 64), color) for color in ["red", "blue"]]
    result = model.generate(seed=3, sampling_steps=steps, input_ref_images=refs, width=64, height=64)
    assert result.shape == (4, 1, 32, 32)
    assert captured["num_inference_steps"] == steps
    assert captured["sigmas"] == (list(_VIGGLE_TURBO_SIGMAS) if turbo else None)
    assert captured["true_cfg_scale"] == 1
    assert captured["negative_prompt"] is None
    assert captured["image"] == refs

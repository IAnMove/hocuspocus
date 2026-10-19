"""Official Turbo must use its pre-shifted schedule, unlike Viggle Turbo."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("torch")

import torch
from diffusers import FlowMatchEulerDiscreteScheduler
from PIL import Image

from tests.test_qwen_image_21 import _load_handler_class
from models.qwen.qwen21_main import model_factory, _OFFICIAL_TURBO_SIGMAS
from models.qwen.pipeline_qwenimage21 import calculate_shift, retrieve_timesteps
from services.production_image_defaults import default_image_steps

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = json.loads((ROOT / "app/defaults/qwen_image_21_turbo.json").read_text())


def test_official_checkpoint_is_distinct_and_shares_only_encoder_and_vae():
    model = DEFINITION["model"]
    assert "qwen_image_2.1_turbo_int8_convrot.safetensors" in model["URLs"][0]
    assert "/df94239739eef7205973a145ffa6f441f7b64e84/" in model["URLs"][0]
    assert model["preload_URLs"] == "qwen_image_21"
    assert not model.get("loras")
    assert default_image_steps("qwen_image_21_turbo") == 8
    handler = _load_handler_class()
    capabilities = handler.query_model_def("qwen_image_21", model)
    assert capabilities["max_image_refs"] == 10
    assert capabilities["native_rgba"] and capabilities["inpaint_support"]
    assert "8-step" in capabilities["resolution_presets"]["auto"]["hint"]
    assert "40 steps" in handler.query_model_def("qwen_image_21", {})["resolution_presets"]["auto"]["hint"]
    defaults = {}
    handler.update_default_settings("qwen_image_21", model, defaults)
    assert defaults["num_inference_steps"] == 8 and defaults["guidance_scale"] == 1


@pytest.mark.parametrize("params,reason", [
    ({"num_inference_steps": 40}, "8-step"),
    ({"guidance_scale": 4}, "CFG 1"),
    ({"image_refs": ["ref"] * 10, "image_guide": "source"}, "at most 10"),
])
def test_invalid_recipe_is_rejected_before_model_load(params, reason):
    handler = _load_handler_class()
    assert reason in handler.validate_generative_settings("qwen_image_21", DEFINITION["model"], params)
    assert handler.validate_generative_settings("qwen_image_21", DEFINITION["model"], {
        "image_refs": ["ref"] * 9, "image_guide": "source", "num_inference_steps": 8, "guidance_scale": 1,
    }) is None


@pytest.mark.parametrize("sequence_length", [1024, 4096, 16384])
def test_official_sigmas_are_never_shifted_again_for_resolution(sequence_length):
    tree = ast.parse((ROOT / "app/models/qwen/qwen21_main.py").read_text())
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "FlowMatchEulerDiscreteScheduler")
    scheduler = eval(compile(ast.Expression(call), "scheduler", "eval"), {
        "FlowMatchEulerDiscreteScheduler": FlowMatchEulerDiscreteScheduler,
        "self": SimpleNamespace(viggle_turbo=False, official_turbo=True),
    })
    assert scheduler.config.shift_terminal is None
    assert not scheduler.config.use_dynamic_shifting
    raw = [1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568]
    assert list(_OFFICIAL_TURBO_SIGMAS) == raw
    mu = calculate_shift(sequence_length, 256, 8192, 0.5, 0.9)
    timesteps, steps = retrieve_timesteps(scheduler, 8, "cpu", sigmas=raw, mu=mu)
    assert steps == len(timesteps) == 8
    torch.testing.assert_close(scheduler.sigmas, torch.tensor(raw + [0.0]))
    torch.testing.assert_close(timesteps, torch.tensor(raw) * 1000)


def test_generate_passes_official_recipe_and_all_ten_references(monkeypatch):
    model = object.__new__(model_factory)
    model.official_turbo = True
    model.transformer = torch.nn.Identity()
    model.text_encoder = torch.nn.Identity()
    captured = {}
    def pipeline(**kwargs):
        captured.update(kwargs)
        return torch.zeros(1, 4, 32, 32)
    model.pipeline = pipeline
    generator = torch.Generator
    monkeypatch.setattr(torch, "Generator", lambda **_: generator(device="cpu"))
    refs = [Image.new("RGBA", (64, 64)) for _ in range(10)]
    result = model.generate(seed=42, sampling_steps=8, input_ref_images=refs, width=64, height=64)
    assert result.shape == (4, 1, 32, 32)
    assert captured["sigmas"] == list(_OFFICIAL_TURBO_SIGMAS)
    assert captured["image"] == refs
    assert captured["negative_prompt"] is None and captured["true_cfg_scale"] == 1
    for kwargs in ({"sampling_steps": 40}, {"sampling_steps": 8, "guide_scale": 4}):
        with pytest.raises(ValueError, match="8 steps and CFG 1"):
            model.generate(**kwargs)


def test_sets_keep_their_turbo_and_never_send_a_negative_the_model_refuses():
    """Registering the official checkpoint adds an option: set skins and props stay on the Viggle turbo they used."""
    config = json.loads((ROOT / "app/shared/set_defaults.json").read_text())
    assert config["imageModelOrder"][0] == "qwen_image_21_viggle_turbo"
    assert "qwen_image_21_turbo" in config["imageModelOrder"]
    for model in config["imageModelOrder"]:
        definition = json.loads((ROOT / f"app/defaults/{model}.json").read_text())["model"]
        assert model in config["imageParams"] and model in config["imageNegativePrompt"], model
        if definition.get("no_negative_prompt"):
            assert config["imageNegativePrompt"][model] is False, model

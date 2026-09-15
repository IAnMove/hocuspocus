"""Audio adoption boundaries: real handler metadata, native requests and small CPU math."""
from copy import deepcopy
import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.studio_music_preparation import prepare_studio_music
from services.studio_music_spec import freeze_studio_music_spec
from services.studio_speech_preparation import prepare_studio_speech
from services.studio_speech_spec import freeze_studio_speech_spec

ROOT = Path(__file__).resolve().parents[1]


def _load_model_package(name):
    # Load the actual model package without TTS.__init__ eagerly importing every
    # unrelated Gradio handler. CI deliberately installs a lightweight runtime.
    path = ROOT / "app/models/TTS" / name
    alias = f"_wangp1300_test_{name}"
    spec = importlib.util.spec_from_file_location(
        alias, path / "__init__.py", submodule_search_locations=[str(path)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[alias] = package
    spec.loader.exec_module(package)
    return importlib.import_module(f"{alias}.{name}_handler").family_handler


AuK = _load_model_package("auk")
YuE2 = _load_model_package("yue2")


class Resources:
    def __init__(self):
        self.calls = []

    def prepare_media(self, params):
        self.calls.append(deepcopy(params))
        return deepcopy(params), []

    def prepare_loras(self, *args):
        return []


def definition(model):
    native = json.loads((ROOT / f"app/defaults/{model}.json").read_text())["model"]
    handler = YuE2 if model == "yue2" else AuK
    return {**native, **handler.query_model_def(native["architecture"], native)}


def prepare(model, **overrides):
    music = model == "yue2"
    params = {
        "model_type": model, "resolution": "1280x720", "prompt": 'Say "Mara: hello".',
        "alt_prompt": "Spanish acoustic pop", "duration_seconds": 5,
        "guidance_scale": 1.0, "num_inference_steps": 32,
        **overrides,
    }
    freeze = freeze_studio_music_spec if music else freeze_studio_speech_spec
    frozen = freeze({"version": 2, "operation": "generation.music" if music else "generation.speech",
                     "intent_id": "audio-test", "input": {"workspace": "test", "params": params}})
    native = {**frozen["effective"]["input"]["params"], "workspace": "test"}
    resources = Resources()
    fn = prepare_studio_music if music else prepare_studio_speech
    result, _ = fn(native, model_definition={model: definition(model)},
                   model_downloaded=lambda _: True, resources=resources, execution_policy=lambda _: None)
    return result, frozen, resources


@pytest.mark.parametrize("model", ["auk", "auk_flash", "yue2"])
def test_native_command_preserves_literal_prompt_and_workspace(model):
    prompt = 'Mara: Keep this exact line.\n[Chorus]\n¡Aquí sigo!'
    params, frozen, resources = prepare(model, prompt=prompt)
    assert params["prompt"] == prompt
    assert frozen["original"]["input"]["params"]["prompt"] == prompt
    assert resources.calls[0]["workspace"] == "test"
    if model == "auk_flash":
        assert (params["num_inference_steps"], params["guidance_scale"], params["guidance_phases"]) == (4, 0, 0)


@pytest.mark.parametrize("model", ["auk", "auk_flash"])
def test_auk_requires_source_only_when_selected(model):
    with pytest.raises(HTTPException, match="") as exc:
        prepare(model, audio_prompt_type="A")
    assert "audio_guide" in str(exc.value.detail)
    result, _, _ = prepare(model, audio_prompt_type="A", audio_guide="/api/v1/uploads/voice.wav")
    assert result["audio_guide"] == "/api/v1/uploads/voice.wav"


@pytest.mark.parametrize("overrides", [
    {"duration_seconds": 0}, {"duration_seconds": 301},
    {"audio_prompt_type": "AB"}, {"audio_prompt_type": "AN"},
    {"_tts_speaker_name1": "Mara"}, {"_tts_voice_count": 1},
])
def test_auk_rejects_incompatible_inputs(overrides):
    with pytest.raises((HTTPException, ValueError)):
        prepare("auk", **overrides)


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_yue2_planning_and_one_second_maximum_are_preserved(mode):
    result, _, _ = prepare("yue2", model_mode=mode, duration_seconds=1)
    assert result["model_mode"] == mode
    assert result["duration_seconds"] == 1
    assert result["alt_prompt"] == "Spanish acoustic pop"


@pytest.mark.parametrize("overrides", [
    {"alt_prompt": ""}, {"duration_seconds": 601}, {"guidance_scale": 0.5},
    {"audio_prompt_type": "A"}, {"model_mode": 3},
])
def test_yue2_rejects_unsupported_requests(overrides):
    with pytest.raises((HTTPException, ValueError)):
        prepare("yue2", **overrides)


def test_weight_sources_are_pinned_and_yue2_does_not_download_cover_models():
    for model in ("yue2", "auk", "auk_flash"):
        d = definition(model)
        assert all("/resolve/main/" not in url for url in d["URLs"] + d["text_encoder_URLs"])
    files = YuE2.query_model_files(None, "yue2")
    assert len(files["revision"]) == 40
    assert files["sourceFolderList"] == ["yue2", "YuE2_AR"]


def test_auk_tiny_transformer_reference_and_cfg_cpu():
    import torch
    Flux2Edit = importlib.import_module("_wangp1300_test_auk.transformer").Flux2Edit
    model = Flux2Edit(dim=64, heads=2, text_hidden_dim=16, latent_dim=8,
                      num_layers=1, num_single_layers=1).eval()
    audio, text = torch.randn(1, 5, 8), torch.randn(1, 3, 16)
    with torch.inference_mode():
        for length in (0, 4):
            reference = torch.randn(1, length, 8)
            result = model(audio, text, torch.tensor(0.5), reference, 2.0)
            assert result.shape == audio.shape
            assert torch.isfinite(result).all()


def test_yue2_and_auk_keep_separate_engine_classes_from_existing_models():
    from shared.wangp1300.llm_engines.nanovllm.models.qwen3 import Qwen3ForCausalLM as New
    from shared.llm_engines.nanovllm.models.qwen3 import Qwen3ForCausalLM as Existing
    assert New is not Existing


def test_yue2_cfg_boundary_rejects_before_resolving_resources():
    assert prepare("yue2", guidance_scale=20)[0]["guidance_scale"] == 20
    resources = Resources()
    with pytest.raises(HTTPException) as error:
        prepare_studio_music({"workspace": "test", "model_type": "yue2", "prompt": "Keep these words", "alt_prompt": "Acoustic pop",
                              "guidance_scale": 21}, model_definition={"yue2": definition("yue2")},
                             model_downloaded=lambda _: True, resources=resources, execution_policy=lambda _: None)
    assert "guidance_scale" in str(error.value.detail)
    assert resources.calls == []

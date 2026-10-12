"""VoxCPM2 speech: handler contract, pipeline behaviour with a fake model, and its place in the speech services."""
import importlib
import json
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _tts_module(name):
    # Load from app/models/TTS without its __init__, which imports every TTS handler.
    alias = "_voxcpm2_test_tts"
    if alias not in sys.modules:
        package = types.ModuleType(alias)
        package.__path__ = [str(ROOT / "app/models/TTS")]
        sys.modules[alias] = package
    return importlib.import_module(f"{alias}.{name}")


handler_module = _tts_module("voxcpm2_handler")
VoxCPM2 = handler_module.family_handler
MODELS = ("voxcpm2_voicedesign", "voxcpm2_base")


def _definition(model):
    native = json.loads((ROOT / f"app/defaults/{model}.json").read_text(encoding="utf-8"))["model"]
    return {**native, **VoxCPM2.query_model_def(native["architecture"], native)}


# -- handler -------------------------------------------------------------------------------

def test_both_types_are_registered_in_wangp_and_share_one_pinned_checkpoint():
    wgp = (ROOT / "app/wgp.py").read_text(encoding="utf-8")
    assert '"models.TTS.voxcpm2_handler"' in wgp
    assert VoxCPM2.query_supported_types() == list(MODELS)
    for model in MODELS:
        native = json.loads((ROOT / f"app/defaults/{model}.json").read_text(encoding="utf-8"))["model"]
        assert native["architecture"] == model and native["URLs"] == []
    (files,) = VoxCPM2.query_model_files(None, "voxcpm2_base")
    assert files["repoId"] == "openbmb/VoxCPM2" and len(files["revision"]) == 40
    assert files["targetFolderList"] == ["voxcpm2"] and "model.safetensors" in files["fileList"][0]
    assert not any(name.endswith(".py") for name in files["fileList"][0]), "no remote code"
    assert VoxCPM2.query_model_files(None, "voxcpm2_voicedesign") == [files]


def test_design_takes_a_description_and_clone_mirrors_qwen3_base():
    design, base = _definition("voxcpm2_voicedesign"), _definition("voxcpm2_base")
    for definition in (design, base):
        assert definition["audio_only"] and definition["no_negative_prompt"] and definition["temperature"] is False
        assert definition["inference_steps"] and definition["guidance_max_phases"] == 1
        assert "model_modes" not in definition, "VoxCPM2 reads the language from the text"
    assert design["alt_prompt"]["label"] == "Voice description" and not design.get("any_audio_prompt")
    assert base["any_audio_prompt"] and base["audio_prompt_type_sources"]["selection"] == ["A", "AB"]
    assert "transcript" in base["alt_prompt"]["label"].lower()
    assert [setting["id"] for setting in base["custom_settings"]] == ["style", "auto_split_every_s"]
    assert VoxCPM2.get_lora_dir("voxcpm2_base", object(), "/loras") == "/loras/voxcpm2"


def test_the_lora_directory_flag_is_read_back():
    import argparse
    parser = argparse.ArgumentParser()
    VoxCPM2.register_lora_cli_args(parser, "/loras")
    args = parser.parse_args(["--lora-dir-voxcpm2", "/custom/voxcpm2"])
    assert VoxCPM2.get_lora_dir("voxcpm2_base", args, "/loras") == "/custom/voxcpm2"
    assert VoxCPM2.get_lora_dir("voxcpm2_base", parser.parse_args([]), "/loras") == "/loras/voxcpm2"


@pytest.mark.parametrize("model,inputs,prompt,error", [
    ("voxcpm2_voicedesign", {}, "  ", "cannot be empty"),
    ("voxcpm2_base", {}, "Hola", "reference audio"),
    ("voxcpm2_base", {"audio_guide": "a.wav"}, "Speaker 1: hola", "two-speaker mode"),
    ("voxcpm2_base", {"audio_guide": "a.wav", "audio_prompt_type": "AB"}, "Speaker 1: hola", "Speaker 2 reference"),
    ("voxcpm2_base", {"audio_guide": "a.wav", "audio_guide2": "b.wav", "audio_prompt_type": "AB"}, "hola", "Speaker 1: and Speaker 2:"),
])
def test_prompt_validation(model, inputs, prompt, error):
    assert error in VoxCPM2.validate_generative_prompt(model, {}, inputs, prompt)


def test_prompt_validation_accepts_design_clone_and_dialogue():
    assert VoxCPM2.validate_generative_prompt("voxcpm2_voicedesign", {}, {}, "Hola") is None
    assert VoxCPM2.validate_generative_prompt("voxcpm2_base", {}, {"audio_guide": "a.wav"}, "Hola") is None
    dialogue = {"audio_guide": "a.wav", "audio_guide2": "b.wav", "audio_prompt_type": "AB"}
    assert VoxCPM2.validate_generative_prompt("voxcpm2_base", {}, dialogue, "Speaker 1: hola\nSpeaker 2: adiós") is None


@pytest.mark.parametrize("inputs,error", [
    ({"num_inference_steps": 2}, "inference steps"),
    ({"num_inference_steps": 40}, "inference steps"),
    ({"guidance_scale": 9}, "guidance"),
    ({"custom_settings": {"auto_split_every_s": 2}}, "Auto Split"),
    ({"custom_settings": {"style": "x" * 301}}, "Style direction"),
])
def test_settings_validation(inputs, error):
    assert error in VoxCPM2.validate_generative_settings("voxcpm2_base", {}, deepcopy(inputs))


def test_settings_validation_normalises_auto_split():
    inputs = {"num_inference_steps": 10, "guidance_scale": 2.0, "custom_settings": {"auto_split_every_s": "20", "style": "susurrando"}}
    assert VoxCPM2.validate_generative_settings("voxcpm2_base", {}, inputs) is None
    assert inputs["custom_settings"]["auto_split_every_s"] == 20.0
    blank = {"custom_settings": {"auto_split_every_s": " "}}
    assert VoxCPM2.validate_generative_settings("voxcpm2_base", {}, blank) is None and blank["custom_settings"] == {}


# -- pipeline ------------------------------------------------------------------------------

torch = pytest.importorskip("torch")
for _dependency in ("einops", "librosa", "pydantic", "transformers"):
    pytest.importorskip(_dependency)
pipeline_module = _tts_module("voxcpm2.pipeline")
Pipeline = pipeline_module.VoxCPM2Pipeline
RATE = pipeline_module.SAMPLE_RATE


class FakeLM:
    def __init__(self):
        self.kv_cache = None
        self.caches = []

    def setup_cache(self, batch, length, device, dtype):
        self.caches.append(device)
        self.kv_cache = object()


class FakeModel:
    """Speaks one second per call; records the text and the voice cache of each call."""

    def __init__(self, stop_at=None, abort_at=None, owner=None):
        self.config = types.SimpleNamespace(dtype="bfloat16", max_length=8192)
        self.base_lm, self.residual_lm = FakeLM(), FakeLM()
        self.audio_vae = types.SimpleNamespace(to=lambda device: None)
        self.calls, self.stop_at, self.abort_at, self.owner = [], stop_at, abort_at, owner
        self._step_hook = None

    def build_prompt_cache(self, prompt_text=None, prompt_wav_path=None, reference_wav_path=None):
        mode = "ref_continuation" if prompt_text else "reference"
        return {"mode": mode, "ref": reference_wav_path, "transcript": prompt_text}

    def _generate_with_prompt_cache(self, target_text, prompt_cache, max_len, inference_timesteps, cfg_value, **_):
        self.calls.append({"text": target_text, "cache": prompt_cache, "max_len": max_len,
                           "steps": inference_timesteps, "cfg": cfg_value})
        if self.abort_at == len(self.calls):
            self.owner._interrupt = True
        for step in range(1, 4):
            if self._step_hook(step, max_len):
                break
        yield torch.ones(1, RATE), None, None


def make(model="voxcpm2_base", **fake):
    pipe = Pipeline.__new__(Pipeline)
    pipe.base_model_type, pipe.execution_device, pipe.sample_rate = model, "cpu", RATE
    pipe._cache_device, pipe._interrupt, pipe._early_stop = None, False, False
    pipe.model = FakeModel(owner=pipe, **fake)
    return pipe


def test_text_direction_helpers():
    compose = pipeline_module.compose_text
    assert compose("(susurrando) ven aquí", "mujer joven") == "(mujer joven, susurrando)ven aquí"
    assert compose("ven aquí", "") == "ven aquí" and compose("(gritando)¡Ven!", "") == "(gritando)¡Ven!"
    assert compose("hola", "(voz) grave") == "(voz grave)hola"
    assert pipeline_module.split_paragraphs("uno\n\n dos \n tres\n\n\n") == ["uno", "dos tres"]
    assert pipeline_module.parse_dialogue("Speaker 1: hola\nqué tal\nSpeaker 2: bien") == [(1, "hola qué tal"), (2, "bien")]
    pieces = pipeline_module.split_long_segment("Una frase corta. Otra frase algo más larga, con coma. Y una tercera.", 30)
    assert all(len(piece) <= 30 for piece in pieces) and " ".join(pieces).startswith("Una frase corta.")


def test_design_puts_the_description_before_every_segment_and_needs_no_reference():
    pipe = make("voxcpm2_voicedesign")
    result = pipe.generate("Hola.\n\nAdiós.", alt_prompt="mujer joven, voz cálida", sampling_steps=12, guide_scale=2.5,
                           pause_seconds=0.5, seed=3)
    calls = pipe.model.calls
    assert [call["text"] for call in calls] == ["(mujer joven, voz cálida)Hola.", "(mujer joven, voz cálida)Adiós."]
    assert all(call["cache"] is None and call["steps"] == 12 and call["cfg"] == 2.5 for call in calls)
    assert result["audio_sampling_rate"] == RATE and result["x"].numel() == int(2.5 * RATE)
    assert pipe.model.base_lm.caches == ["cpu"], "the static KV cache is placed on the execution device once"


def test_clone_uses_the_transcript_unless_a_style_or_a_line_direction_needs_reference_only():
    pipe = make()
    pipe.generate("Hola.", audio_guide="ref.wav", audio_prompt_type="A", alt_prompt="Muestra exacta.")
    assert pipe.model.calls[-1]["cache"] == {"mode": "ref_continuation", "ref": "ref.wav", "transcript": "Muestra exacta."}
    pipe.generate("Hola.", audio_guide="ref.wav", audio_prompt_type="A", alt_prompt="Muestra exacta.",
                  custom_settings={"style": "susurrando"})
    assert pipe.model.calls[-1]["cache"]["mode"] == "reference" and pipe.model.calls[-1]["text"] == "(susurrando)Hola."
    pipe.generate("(gritando) Hola.\n\nAdiós.", audio_guide="ref.wav", audio_prompt_type="A", alt_prompt="Muestra exacta.")
    shouted, calm = pipe.model.calls[-2:]
    assert shouted["text"] == "(gritando)Hola." and shouted["cache"]["mode"] == "reference"
    assert calm["text"] == "Adiós." and calm["cache"]["mode"] == "ref_continuation"


def test_dialogue_clones_each_speaker_with_its_own_transcript():
    pipe = make()
    pipe.generate("Speaker 1: Hola.\nSpeaker 2: Buenas.\nSpeaker 1: Adiós.", audio_guide="a.wav", audio_guide2="b.wav",
                  audio_prompt_type="AB", alt_prompt="Texto A.\nTexto B.")
    assert [(call["cache"]["ref"], call["cache"]["transcript"], call["text"]) for call in pipe.model.calls] == [
        ("a.wav", "Texto A.", "Hola."), ("b.wav", "Texto B.", "Buenas."), ("a.wav", "Texto A.", "Adiós.")]


def test_duration_budget_caps_the_steps_and_the_audio():
    pipe = make("voxcpm2_voicedesign")
    result = pipe.generate("Uno.\n\nDos.\n\nTres.", duration_seconds=1.5, pause_seconds=0)
    assert len(pipe.model.calls) == 2 and pipe.model.calls[0]["max_len"] == 10
    assert result["x"].numel() == int(1.5 * RATE)


def test_progress_reports_steps_and_abort_returns_none():
    reported = []
    pipe = make("voxcpm2_voicedesign")
    pipe.generate("Hola.", callback=lambda **kw: reported.append(kw["step_idx"]))
    assert reported == [1, 2, 3]
    assert make("voxcpm2_voicedesign", abort_at=1).generate("Hola.") is None


def test_early_stop_keeps_what_was_spoken():
    pipe = make("voxcpm2_voicedesign")
    pipe.generate("Uno.\n\nDos.", callback=lambda **_: pipe.request_early_stop())
    assert len(pipe.model.calls) == 1


def test_clone_without_reference_is_refused():
    with pytest.raises(ValueError, match="reference audio"):
        make().generate("Hola.", audio_prompt_type="A")


# -- speech services -----------------------------------------------------------------------

def test_speech_catalog_memory_and_reference_pauses_know_voxcpm2():
    from services.generation_memory import _TTS_ARCHITECTURES
    from services.speech_reference_pauses import CLONE_REFERENCE_FIELDS
    from services.studio_speech_spec import SPEECH_MODEL_TYPES
    assert set(MODELS) <= SPEECH_MODEL_TYPES and set(MODELS) <= _TTS_ARCHITECTURES
    assert CLONE_REFERENCE_FIELDS["voxcpm2_base"] == ("audio_guide", "audio_guide2")


REFERENCE = {"provider": "local", "model": "voxcpm2_base", "voiceId": "reference", "name": "Zilia ES",
             "referenceAudio": "/api/v1/uploads/zilia.wav", "transcript": "Hola, soy Zilia.", "language": "spanish"}


def test_character_reference_voices_accept_voxcpm2_and_its_style():
    from services.character_speech_definition import normalize_character_voice, normalize_character_voices_by_language
    assert normalize_character_voice(REFERENCE) == REFERENCE
    styled = normalize_character_voice({**REFERENCE, "instructions": " susurrando "})
    assert styled["instructions"] == "susurrando"
    assert "instructions" not in normalize_character_voice({**REFERENCE, "instructions": "  "})
    with pytest.raises(ValueError, match="no style"):
        normalize_character_voice({**REFERENCE, "model": "qwen3_tts_base", "instructions": "susurrando"})
    with pytest.raises(ValueError, match="too long"):
        normalize_character_voice({**REFERENCE, "instructions": "x" * 301})
    with pytest.raises(ValueError, match="language it is assigned"):
        normalize_character_voices_by_language({"english": REFERENCE})


def test_series_lines_in_a_voxcpm2_voice_send_no_language_mode_and_carry_the_style():
    from services.series_commands import _kit_summary
    from services.series_native_render import speech_params
    params = speech_params({**REFERENCE, "instructions": "susurrando"}, "uno dos tres", "spanish", 7)
    assert params["model_type"] == "voxcpm2_base" and "model_mode" not in params
    assert (params["audio_prompt_type"], params["audio_guide"], params["alt_prompt"]) == ("A", REFERENCE["referenceAudio"], REFERENCE["transcript"])
    assert params["custom_settings"] == {"style": "susurrando"}
    qwen = speech_params({**REFERENCE, "model": "qwen3_tts_base"}, "uno", "spanish", 7)
    assert qwen["model_mode"] == "spanish" and "custom_settings" not in qwen
    assert "Zilia ES" in json.dumps(_kit_summary({"id": "zilia", "name": "Zilia", "voice": REFERENCE}), ensure_ascii=False)


# -- readiness and pre-download of a folder-only model -------------------------------------------

def _runtime_function(name, namespace, *helpers):
    import ast
    path = ROOT / "app/_launch_runtime.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    wanted = {name, *helpers}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])), str(path), "exec"), namespace)
    return namespace[name]


def _readiness(present):
    import os
    definition = _definition("voxcpm2_base")
    fake_wgp = types.SimpleNamespace(
        get_model_def=lambda _model: definition, get_model_recursive_prop=lambda *_a, **_k: [],
        resolve_lora_path=lambda *_a, **_k: "", fl=types.SimpleNamespace(locate_file=lambda path, **_: path if path in present else None))
    check = _runtime_function("_check_model_downloaded", {
        "os": os, "wgp": fake_wgp, "minimax_h3_service": None,
        "_model_weight_groups": lambda _model: [], "_variant_group_downloaded": lambda _group: True}, "_folder_model_ready")
    return check("voxcpm2_base")


def test_a_folder_only_model_is_ready_when_its_declared_assets_are_on_disk():
    assets = _definition("voxcpm2_base")["required_model_assets"]
    assert assets == [f"voxcpm2/{name}" for name in handler_module.VOXCPM2_FILES]
    assert _readiness(set(assets)) is True
    assert _readiness(set(assets) - {"voxcpm2/model.safetensors"}) is False


def test_pre_download_fetches_the_handler_folder_when_there_is_no_main_file():
    calls = []
    fake_wgp = types.SimpleNamespace(
        get_model_def=lambda _model: {}, transformer_quantization="int8", transformer_dtype_policy="",
        get_transformer_dtype=lambda *_a: None, get_model_filename=lambda **_k: "",
        get_model_recursive_prop=lambda *_a, **_k: [] if _a[1] == "modules" else None,
        download_models=lambda *args, **_k: calls.append(args))
    download = _runtime_function("_download_model_files", {
        "wgp": fake_wgp, "_is_legacy_h3_model": lambda _model: False, "_check_model_downloaded": lambda _model: True})
    download("voxcpm2_base")
    assert calls == [("", "voxcpm2_base", 0, -1)]


# -- speech request boundary ---------------------------------------------------------------------

class _Resources:
    def prepare_media(self, params):
        return deepcopy(params), []

    def prepare_loras(self, *args):
        return []


def _prepare(model, **params):
    from services.studio_speech_preparation import prepare_studio_speech
    from services.studio_speech_spec import freeze_studio_speech_spec
    frozen = freeze_studio_speech_spec({"version": 2, "operation": "generation.speech", "intent_id": "vox-test",
                                        "input": {"workspace": "test", "params": {"model_type": model, "resolution": "1280x720",
                                                                                   "prompt": "Hola.", **params}}})
    native = {**frozen["effective"]["input"]["params"], "workspace": "test"}
    result, _ = prepare_studio_speech(native, model_definition={model: _definition(model)}, model_downloaded=lambda _: True,
                                      resources=_Resources(), execution_policy=lambda _: None)
    return result


def test_callers_that_leave_sampling_unset_get_the_voxcpm2_recipe():
    """Series lines, the Wizard and MCP send no steps; zero is the sentinel of models without a step control."""
    design = _prepare("voxcpm2_voicedesign", alt_prompt="mujer joven", duration_seconds=12)
    assert (design["num_inference_steps"], design["guidance_scale"]) == (10, 2.0) and "model_mode" not in design
    clone = _prepare("voxcpm2_base", audio_prompt_type="A", audio_guide="/api/v1/uploads/zilia.wav", alt_prompt="Hola, soy Zilia.",
                     custom_settings={"style": "susurrando"}, num_inference_steps=16, guidance_scale=3.0)
    assert (clone["num_inference_steps"], clone["guidance_scale"]) == (16, 3.0)
    assert clone["custom_settings"]["style"] == "susurrando"


@pytest.mark.parametrize("params", [{"model_mode": "spanish"}, {"num_inference_steps": 2}, {"temperature": 0.9}])
def test_the_boundary_refuses_what_voxcpm2_does_not_take(params):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _prepare("voxcpm2_voicedesign", **params)

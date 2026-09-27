"""Provider-free tests for Studio music model/resource preparation."""

from copy import deepcopy
import pytest
from fastapi import HTTPException

from services.studio_music_preparation import prepare_studio_music
from services.studio_music_spec import freeze_studio_music_spec


ACE_DEFINITION = {
    "audio_only": True,
    "image_outputs": False,
    "guidance_max_phases": 1,
    "no_negative_prompt": True,
    "inference_steps": True,
    "temperature": True,
    "top_p_slider": True,
    "top_k_slider": True,
    "audio_scale_name": "Source Audio Strength",
    "alt_guidance": "LM Guidance",
    "enabled_audio_lora": True,
    "duration_slider": {"min": 5, "max": 360, "default": 120},
    "audio_prompt_type_sources": {"selection": ["", "A", "B", "AB"], "default": ""},
    "custom_settings": [
        {"id": "bpm", "type": "int", "min": 30, "max": 300},
        {"id": "keyscale", "type": "text"},
        {"id": "timesignature", "type": "int", "min": 2, "max": 6},
        {"id": "language", "type": "text"},
    ],
}

MUSIC3_DEFINITION = {
    "audio_only": True,
    "image_outputs": False,
    "guidance_max_phases": 0,
    "lock_guidance_scale": True,
    "no_negative_prompt": True,
    "inference_steps": True,
    "temperature": False,
    "duration_slider": {"min": 5, "max": 300, "default": 120},
}


def command_params(model_type="ace_step_v1_5_xl_sft_lm_4b", **overrides):
    params = {
        "workspace": "music-test",
        "model_type": model_type,
        "prompt": "[Verse]\nKeep the literal line",
        "alt_prompt": "Warm acoustic pop",
        "generation_mode": "audio",
        "_audio_sub_mode": "music",
        "image_mode": 0,
        "video_length": 0,
        "duration_seconds": 20,
        "num_inference_steps": 8 if model_type != "minimax_music3" else 30,
        "guidance_scale": 1.0 if model_type != "minimax_music3" else 1.7,
        "seed": 7,
    }
    params.update(overrides)
    return params


class FakeResources:
    def __init__(self, *, media_result=None, lora_result=None, media_error=None):
        self.media_result = media_result
        self.lora_result = [] if lora_result is None else lora_result
        self.media_error = media_error
        self.media_calls = []
        self.lora_calls = []

    def prepare_media(self, params):
        self.media_calls.append(deepcopy(params))
        if self.media_error is not None:
            raise self.media_error
        if self.media_result is not None:
            return deepcopy(self.media_result)
        return deepcopy(params), []

    def prepare_loras(self, params, definition):
        self.lora_calls.append((deepcopy(params), deepcopy(definition)))
        return deepcopy(self.lora_result)


def invoke(params, *, definition=None, downloaded=True, resources=None, policy_error=None):
    definition = deepcopy(definition or ACE_DEFINITION)
    resources = resources or FakeResources()
    calls = {"policy": [], "definition": [], "downloaded": []}

    def model_definition(model_type):
        calls["definition"].append(model_type)
        return deepcopy(definition)

    def model_downloaded(model_type):
        calls["downloaded"].append(model_type)
        return downloaded

    def policy(workspace):
        calls["policy"].append(workspace)
        if policy_error is not None:
            raise policy_error

    result = prepare_studio_music(
        params,
        model_definition=model_definition,
        model_downloaded=model_downloaded,
        resources=resources,
        execution_policy=policy,
    )
    return result, calls, resources


def frozen_params(**overrides):
    native = command_params(**overrides)
    native.pop("workspace", None)
    command = {
        "version": 2,
        "operation": "generation.music",
        "intent_id": "music-intent",
        "input": {"workspace": "music-test", "params": native},
    }
    frozen = freeze_studio_music_spec(command)
    return {**frozen["effective"]["input"]["params"], "workspace": "music-test"}


def raw_params(**overrides):
    params = command_params(**overrides)
    params["workspace"] = "music-test"
    params.pop("_audio_sub_mode", None)
    return params


def test_installed_ace_returns_model_defaults_and_detached_resources():
    params = frozen_params()
    before = deepcopy(params)
    resources = FakeResources(
        media_result=({**params, "native_marker": {"kept": True}}, [{"role": "audio_guide"}]),
        lora_result=[{"role": "lora", "name": "music-style"}],
    )
    (native, identities), calls, _ = invoke(params, resources=resources)

    assert params == before
    assert native["native_marker"] == {"kept": True}
    assert identities == [{"role": "audio_guide"}, {"role": "lora", "name": "music-style"}]
    assert calls["policy"] == ["music-test"]
    assert calls["definition"] == ["ace_step_v1_5_xl_sft_lm_4b"]
    assert calls["downloaded"] == ["ace_step_v1_5_xl_sft_lm_4b"]
    native["native_marker"]["kept"] = False
    assert resources.media_result[0]["native_marker"] == {"kept": True}


@pytest.mark.parametrize("model_type", ["music-3.0", "minimax_music3_gguf", "unknown"])
def test_remote_community_and_unknown_models_fail_before_resource_inspection(model_type):
    resources = FakeResources()
    with pytest.raises(HTTPException) as error:
        invoke(raw_params(model_type=model_type), resources=resources)
    assert error.value.status_code == 422
    assert resources.media_calls == resources.lora_calls == []


@pytest.mark.parametrize(
    ("definition", "downloaded", "status"),
    [({**ACE_DEFINITION, "audio_only": False}, True, 422),
     ({**ACE_DEFINITION, "image_outputs": True}, True, 422),
     (ACE_DEFINITION, False, 409)],
)
def test_model_must_be_audio_only_compatible_and_installed(definition, downloaded, status):
    resources = FakeResources()
    with pytest.raises(HTTPException) as error:
        invoke(frozen_params(), definition=definition, downloaded=downloaded, resources=resources)
    assert error.value.status_code == status
    assert resources.media_calls == resources.lora_calls == []


def test_execution_policy_runs_before_model_or_resource_lookup():
    resources = FakeResources()
    with pytest.raises(HTTPException) as error:
        invoke(
            frozen_params(), resources=resources,
            policy_error=HTTPException(409, {"code": "execution_policy", "message": "busy"}),
        )
    assert error.value.status_code == 409
    assert resources.media_calls == resources.lora_calls == []


@pytest.mark.parametrize(
    ("model_type", "definition"),
    [("ace_step_v1_5_xl_sft_lm_4b", ACE_DEFINITION), ("minimax_music3", MUSIC3_DEFINITION)],
)
def test_duration_uses_native_slider_bounds_not_story_minimum(model_type, definition):
    params = frozen_params(model_type=model_type)
    params.pop("duration_seconds")
    (native, _), _, _ = invoke(params, definition=definition)
    assert native["duration_seconds"] == 120

    short = frozen_params(model_type=model_type, duration_seconds=5)
    (native, _), _, _ = invoke(short, definition=definition)
    assert native["duration_seconds"] == 5

    with pytest.raises(HTTPException) as error:
        invoke(frozen_params(model_type=model_type, duration_seconds=4), definition=definition)
    assert "duration_seconds" in error.value.detail["message"]

    maximum = definition["duration_slider"]["max"]
    with pytest.raises(HTTPException) as error:
        invoke(frozen_params(model_type=model_type, duration_seconds=maximum + 1), definition=definition)
    assert "duration_seconds" in error.value.detail["message"]


def test_missing_duration_slider_uses_native_music_minimum():
    definition = deepcopy(ACE_DEFINITION)
    definition.pop("duration_slider")

    with pytest.raises(HTTPException) as error:
        invoke(frozen_params(duration_seconds=4), definition=definition)
    assert "duration_seconds" in error.value.detail["message"]

    (native, _), _, _ = invoke(frozen_params(duration_seconds=5), definition=definition)
    assert native["duration_seconds"] == 5


@pytest.mark.parametrize("field", ["num_inference_steps", "guidance_scale"])
def test_nonfinite_or_invalid_sampling_fails_before_media(field):
    bad = raw_params(**{field: float("nan")}) if field == "guidance_scale" else raw_params(**{field: 0})
    resources = FakeResources()
    with pytest.raises(HTTPException) as error:
        invoke(bad, resources=resources)
    assert error.value.status_code == 422
    assert resources.media_calls == []


def test_music3_uses_its_defaults_and_rejects_unsupported_sampling():
    params = frozen_params(model_type="minimax_music3")
    params.pop("num_inference_steps")
    params.pop("guidance_scale")
    (native, _), _, _ = invoke(params, definition=MUSIC3_DEFINITION)
    assert native["num_inference_steps"] == 30
    assert native["guidance_scale"] == 1.7
    with pytest.raises(HTTPException) as error:
        invoke(frozen_params(model_type="minimax_music3", temperature=0.5), definition=MUSIC3_DEFINITION)
    assert "temperature" in error.value.detail["message"]


def test_ace_audio_selector_requires_canonical_reference_slots():
    missing = frozen_params(audio_prompt_type="A")
    with pytest.raises(HTTPException) as error:
        invoke(missing)
    assert "audio_guide" in error.value.detail["message"]

    orphan = frozen_params(audio_guide="/api/v1/uploads/track.wav")
    with pytest.raises(HTTPException) as error:
        invoke(orphan)
    assert "audio_prompt_type" in error.value.detail["message"]

    valid = frozen_params(
        audio_prompt_type="AB",
        audio_guide="/api/v1/uploads/one.wav",
        audio_guide2="/api/v1/file/two.wav?workspace=music-test",
    )
    resources = FakeResources()
    (native, _), _, _ = invoke(valid, resources=resources)
    assert native["audio_guide"] == valid["audio_guide"]
    assert native["audio_guide2"] == valid["audio_guide2"]


def test_music3_rejects_reference_audio_and_ace_rejects_extra_slots():
    with pytest.raises(HTTPException) as error:
        invoke(
            frozen_params(model_type="minimax_music3", audio_guide="/api/v1/uploads/song.wav"),
            definition=MUSIC3_DEFINITION,
        )
    assert "reference audio" in error.value.detail["message"]

    with pytest.raises(HTTPException) as error:
        invoke(frozen_params(audio_prompt_type="AB", audio_guide3="/api/v1/uploads/third.wav"))
    assert "audio_guide3" in error.value.detail["message"]


def test_music3_empty_reference_sentinels_are_normalized_for_native_handler():
    params = frozen_params(model_type="minimax_music3", audio_guide="", audio_guide2="")
    (native, _), _, _ = invoke(params, definition=MUSIC3_DEFINITION)
    assert native["audio_guide"] is None
    assert native["audio_guide2"] is None


def test_language_guard_reuses_music_contract_without_rewriting_lyrics():
    params = frozen_params(lyrics_language="es", prompt="[Verse]\nThe night is singing through the server")
    with pytest.raises(HTTPException) as error:
        invoke(params)
    assert "requested language" in error.value.detail["message"]

    valid = frozen_params(lyrics_language="es", prompt="[Verse]\nLa noche canta")
    (native, _), _, _ = invoke(valid)
    assert native["prompt"] == valid["prompt"]


def test_instrumental_flag_cannot_hide_vocal_lyrics():
    params = frozen_params(_music_instrumental=True, prompt="A vocal line")
    with pytest.raises(HTTPException) as error:
        invoke(params)
    assert "instrumental" in error.value.detail["message"].lower()

    valid = frozen_params(_music_instrumental=True, prompt="[Instrumental]")
    invoke(valid)


def test_custom_settings_use_model_metadata_and_unknown_keys_fail_closed():
    valid = frozen_params(custom_settings={"bpm": 120, "keyscale": "C major", "timesignature": 4, "language": "en"})
    (native, _), _, _ = invoke(valid)
    assert native["custom_settings"]["bpm"] == 120

    for values in ({"bpm": 29}, {"unknown": 1}):
        with pytest.raises(HTTPException) as error:
            invoke(raw_params(custom_settings=values))
        assert "custom_settings" in error.value.detail["message"]

    inactive = frozen_params(custom_settings={"bpm": "", "timesignature": ""})
    (native, _), _, _ = invoke(inactive)
    assert native["custom_settings"] == {"bpm": "", "timesignature": ""}


def test_loras_require_declared_capability_and_resource_errors_are_wrapped():
    params = frozen_params(activated_loras=["music-style"])
    with pytest.raises(HTTPException) as error:
        invoke(params, definition={**ACE_DEFINITION, "enabled_audio_lora": False})
    assert "lora" in error.value.detail["message"].lower()

    resources = FakeResources(media_error=ValueError("bad music reference"))
    with pytest.raises(HTTPException) as error:
        invoke(frozen_params(), resources=resources)
    assert "bad music reference" in error.value.detail["message"]
    assert resources.lora_calls == []

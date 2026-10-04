"""Typed generation.video version 3. No checkpoint and no GPU queue."""

from fastapi import HTTPException
import pytest

from services.video_generation_spec import VideoGenerationSpecError, freeze_video_generation_spec
from services.video_generation_v3 import (
    H3_EXTENDED_LENGTHS,
    H3_LENGTHS,
    H3_PRESET_RESOLUTIONS,
    LTX_VIDEO_LENGTHS,
    LTX_WINDOW_LENGTHS,
    VideoV3Params,
    prepare_video_generation_v3,
    video_generation_v3_schema,
)
from tests.test_video_generation_commands import configured_service
from tests.test_image_generation_commands import FakeNative, _run


def fl2va_command(**params):
    native = {
        "model_type": "minimax_h3",
        "prompt": "A lantern over wet cobblestones.",
        "resolution": "864x480",
        "video_length": 124,
        "image_start": "asset_start01",
        "audio_prompt_type": "A",
        "audio_guide": "asset_fullmix",
    }
    native.update(params)
    return {
        "version": 3,
        "operation": "generation.video",
        "intent_id": "h3-fl2va",
        "input": {"workspace": "video-test", "params": native},
    }


def ref_command(references, **params):
    native = {
        "model_type": "minimax_h3_ref2va",
        "prompt": "Use the ordered references.",
        "resolution": "864x480",
        "video_length": 124,
        "references": references,
    }
    native.update(params)
    return {
        "version": 3,
        "operation": "generation.video",
        "intent_id": "h3-ref2va",
        "input": {"workspace": "video-test", "params": native},
    }


def ltx_command(**params):
    native = {
        "model_type": "ltx2_22B_distilled_1_1",
        "prompt": "A warm sunny backyard.",
        "resolution": "1280x720",
        "video_length": 241,
        "image_start": "/api/v1/file/start.png?workspace=source",
        "image_end": "asset_end01",
        "audio_prompt_type": "A",
        "audio_guide": "/api/v1/uploads/mix.wav",
    }
    native.update(params)
    return {
        "version": 3,
        "operation": "generation.video",
        "intent_id": "ltx23",
        "input": {"workspace": "video-test", "params": native},
    }


def references(kind, count, **extra):
    items = []
    for index in range(count):
        item = {"type": kind, "source": f"asset_{kind}{index}"}
        item.update(extra)
        items.append(item)
    return items


def detail(error):
    return error.value.detail


def test_h3_lengths_follow_the_published_lattice():
    assert H3_LENGTHS[0] == 124
    assert H3_LENGTHS[1] - H3_LENGTHS[0] == 17
    assert H3_LENGTHS[-1] == 345
    assert H3_EXTENDED_LENGTHS[-1] == 719
    assert 120 not in H3_LENGTHS
    assert set(LTX_VIDEO_LENGTHS) <= set(LTX_WINDOW_LENGTHS)
    assert "1280x720" not in H3_PRESET_RESOLUTIONS
    assert "864x480" in H3_PRESET_RESOLUTIONS


def test_valid_fl2va_payload_is_accepted_by_the_schema():
    command = fl2va_command(image_end="/api/v1/file/end.png?workspace=source")
    frozen = freeze_video_generation_spec(command)
    params = frozen["effective"]["input"]["params"]
    schema = video_generation_v3_schema()
    assert frozen["effective"]["version"] == 3
    assert schema["version"] == 3
    assert "minimax_h3" in schema["families"]["minimax_h3_fl2va"]
    assert "image_start" in schema["input"]["$defs"]["VideoV3Params"]["properties"]
    VideoV3Params.model_validate(command["input"]["params"])
    assert params["image_prompt_type"] == "SE"
    assert params["image_start"] == "asset_start01"
    assert params["audio_prompt_type"] == "A"
    assert params["audio_guide"] == "asset_fullmix"
    assert params["sliding_window_size"] == 124
    assert params["generation_mode"] == "video"
    assert params["multi_prompts_gen_type"] == 2


def test_valid_ref2va_payload_keeps_reference_limits():
    # 8 images + 3 videos + 1 drive audio = the published total of 12.
    items = (
        references("image", 8)
        + references("video", 3)
        + [{"type": "audio", "source": "asset_drive0", "audio_intent": "drive"}]
    )
    frozen = freeze_video_generation_spec(ref_command(items))
    manifest = frozen["effective"]["input"]["params"]["minimax_h3_references"]
    assert len(manifest) == 12
    assert manifest[-1]["path"] == "asset_drive0"
    assert manifest[-1]["audio_intent"] == "drive"
    assert "image_start" not in frozen["effective"]["input"]["params"]


def test_ref2va_limits_match_the_existing_manifest_contract():
    cases = [
        (references("image", 10), "9"),
        (references("image", 1) + references("video", 4), "3"),
        (references("image", 1) + references("audio", 4), "3"),
        (references("image", 9) + references("video", 3) + references("audio", 1), "12"),
        (references("audio", 1), "image or video"),
        (
            references("image", 1)
            + [{"type": "audio", "source": "asset_drive0", "audio_intent": "drive"}]
            + [{"type": "audio", "source": "asset_drive1", "audio_intent": "drive"}],
            "one Music",
        ),
    ]
    for items, needle in cases:
        with pytest.raises(VideoGenerationSpecError, match=needle) as error:
            freeze_video_generation_spec(ref_command(items))
        assert error.value.code == "invalid_reference"


def test_invalid_h3_length_names_the_lattice_and_does_not_enqueue(tmp_path):
    native = FakeNative(tmp_path)
    service, _ = configured_service(native, tmp_path)
    command = fl2va_command(video_length=120)
    command["validate"] = True
    with pytest.raises(HTTPException) as rejected:
        _run(service.submit(command))
    body = detail(rejected)
    assert rejected.value.status_code == 422
    assert body["code"] == "invalid_selector"
    assert "124+17k" in body["message"]
    assert "120" in body["message"]
    assert "124" in body["message"]
    assert "345" in body["message"]
    assert native.dispatch_calls == []
    assert native.prepare_calls == 0
    assert native.registry("video-test").command_admission("h3-fl2va") is None


def test_invalid_sliding_window_is_rejected():
    with pytest.raises(VideoGenerationSpecError, match="sliding_window_size 130") as error:
        freeze_video_generation_spec(fl2va_command(sliding_window_size=130))
    assert error.value.code == "invalid_selector"
    assert "124+17k" in str(error.value)


def test_extended_h3_length_requires_the_existing_flag():
    with pytest.raises(VideoGenerationSpecError) as rejected:
        freeze_video_generation_spec(fl2va_command(video_length=719))
    assert rejected.value.code == "invalid_selector"
    accepted = freeze_video_generation_spec(
        fl2va_command(video_length=719, sliding_window_size=719, minimax_h3_extended_duration=True)
    )
    params = accepted["effective"]["input"]["params"]
    assert params["video_length"] == 719
    assert params["minimax_h3_extended_duration"] is True


def test_h3_resolution_must_be_an_existing_preset():
    with pytest.raises(VideoGenerationSpecError, match="1280x720") as error:
        freeze_video_generation_spec(fl2va_command(resolution="1280x720"))
    assert error.value.code == "invalid_selector"
    assert "864x480" in str(error.value)


def test_audio_mode_a_requires_an_audio_guide_asset():
    with pytest.raises(VideoGenerationSpecError, match="audio_guide") as error:
        freeze_video_generation_spec(fl2va_command(audio_guide=None))
    assert error.value.code == "invalid_selector"
    missing = fl2va_command()
    del missing["input"]["params"]["audio_guide"]
    with pytest.raises(VideoGenerationSpecError, match="audio mode A"):
        freeze_video_generation_spec(missing)


def test_fl2va_requires_image_start():
    command = fl2va_command()
    del command["input"]["params"]["image_start"]
    with pytest.raises(VideoGenerationSpecError, match="image_start") as error:
        freeze_video_generation_spec(command)
    assert error.value.code == "invalid_selector"


def test_validate_true_returns_the_payload_without_enqueue(tmp_path):
    native = FakeNative(tmp_path)
    service, _ = configured_service(native, tmp_path)
    command = fl2va_command()
    command["validate"] = True
    result = _run(service.submit(command))
    assert result == {
        "validated": True,
        "enqueued": False,
        "payload": result["payload"],
    }
    assert result["payload"]["model_type"] == "minimax_h3"
    assert result["payload"]["image_prompt_type"] == "S"
    assert result["payload"]["audio_guide"] == "asset_fullmix"
    assert result["payload"]["workspace"] == "video-test"
    assert "_video_v3" not in result["payload"]
    assert native.dispatch_calls == []
    assert native.prepare_calls == 0
    assert native.registry("video-test").command_admission("h3-fl2va") is None


def test_ltx23_uses_its_own_lattice_and_presets():
    frozen = freeze_video_generation_spec(ltx_command())
    params = frozen["effective"]["input"]["params"]
    assert params["image_prompt_type"] == "SE"
    assert params["audio_prompt_type"] == "A"
    assert params["sliding_window_size"] == 241
    assert "ltx2_22B_distilled_1_1" in video_generation_v3_schema()["families"]["ltx2_3"]
    with pytest.raises(VideoGenerationSpecError, match="17\\+8k") as error:
        freeze_video_generation_spec(ltx_command(video_length=120))
    assert error.value.code == "invalid_selector"
    assert "124+17k" not in str(error.value)
    assert "17" in str(error.value)
    assert "241" in str(error.value)


def test_missing_typed_model_does_not_enqueue():
    with pytest.raises(HTTPException) as rejected:
        prepare_video_generation_v3(
            {
                "_video_v3": True,
                "workspace": "video-test",
                "model_type": "minimax_h3",
                "prompt": "A lantern.",
                "video_length": 124,
            },
            model_definition=lambda _model: None,
            model_downloaded=lambda _model: False,
            resources=None,
            execution_policy=lambda _workspace: None,
        )
    assert rejected.value.status_code == 422
    assert detail(rejected)["code"] == "unsupported_model"


def test_installed_check_failure_stays_before_any_worker():
    calls = []

    def downloaded(_model):
        calls.append("downloaded")
        return False

    with pytest.raises(HTTPException) as rejected:
        prepare_video_generation_v3(
            {"_video_v3": True, "workspace": "video-test", "model_type": "ltx2_22B", "prompt": "x"},
            model_definition=lambda _model: {"architecture": "ltx2_22B"},
            model_downloaded=downloaded,
            resources=None,
            execution_policy=lambda _workspace: calls.append("policy"),
        )
    assert rejected.value.status_code == 409
    assert detail(rejected)["code"] == "model_unavailable"
    assert calls == ["policy", "downloaded"]

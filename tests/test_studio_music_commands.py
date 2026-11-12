"""Local music uses the same admission and queue, without a Story reservation."""
from copy import deepcopy
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from routers.image_generation_commands import create_image_generation_commands_router, image_command_handlers
from services.studio_music_commands import music_command_catalog
from services.native_generation_operation import NativeGenerationOperation
from services.studio_music_spec import freeze_studio_music_spec
from services.image_generation_runtime import create_image_generation_commands
from services.wangp_submission import JsonRequest, prepare_generation_inputs
from tests.test_image_generation_commands import FakeNative, _command as image_command, _run
from tests.test_studio_music_preparation import ACE_DEFINITION
from tests.test_studio_speech_resources import write_wave


def test_the_catalog_description_names_every_model_type_the_command_accepts():
    """gen-04: the description named two of the three registered models, so an agent never tried yue2."""
    from services.studio_music_spec import STUDIO_MUSIC_MODEL_TYPES

    catalog = music_command_catalog()
    assert set(catalog["musicModelTypes"]) == set(STUDIO_MUSIC_MODEL_TYPES)
    for model_type in STUDIO_MUSIC_MODEL_TYPES:
        assert model_type in catalog["description"], model_type


def music_command(intent="music-intent"):
    return {"version": 2, "operation": "generation.music", "intent_id": intent,
            "input": {"workspace": "music-test", "params": {
                "model_type": "ace_step_v1_5_xl_sft_lm_4b",
                "prompt": "  [Verse]\nThe city listens\nEvery light replies\n  ",
                "alt_prompt": "  Soft drums, luminous synths.\nA quiet chorus.  ",
                "_music_description": "  A supervisor watches the city.  ",
                "_music_instrumental": False,
                "duration_seconds": 20, "seed": 42,
                "num_inference_steps": 8, "guidance_scale": 7.0,
                "resolution": "1280x720", "generation_mode": "audio",
                "image_mode": 0, "video_length": 0, "_audio_sub_mode": "music",
            }}}


def music_service(native):
    service = native.service()
    native_prepare = service.prepare

    async def prepare_request(request):
        assert request.prepared_studio_audio is True
        assert request.prepared_studio_speech is False
        return await native_prepare(request)

    def freeze(command):
        frozen = freeze_studio_music_spec(command)
        effective = frozen["effective"]["input"]
        return frozen, {**deepcopy(effective["params"]), "workspace": effective["workspace"]}

    service.prepare = prepare_request
    service.operations["generation.music"] = NativeGenerationOperation(
        freeze=freeze, prepare=lambda params: (params, []), catalog=music_command_catalog(),
    )
    return service


def test_local_music_http_and_mcp_share_literal_request_and_admission(tmp_path):
    native = FakeNative(tmp_path)
    service = music_service(native)
    app = FastAPI()
    app.include_router(create_image_generation_commands_router(service))
    command = music_command()
    with TestClient(app) as client:
        response = client.post('/api/v1/generation/commands', json=command,
                               headers={"X-Hocus-UI-Surface": "wizard"})
        assert response.status_code == 200, response.text
    reply = _run(image_command_handlers(service)["generation.music"](
        {key: value for key, value in command.items() if key != "operation"}))
    assert reply == {"receipt": response.json()["receipt"], "replayed": True}
    assert len(native.dispatch_calls) == 1
    job = native.dispatch_calls[0]
    for key in ("prompt", "alt_prompt", "_music_description", "duration_seconds", "seed"):
        assert job["params"][key] == command["input"]["params"][key]
    assert job["provenance"]["actor"] == "wizard"
    assert job["provenance"]["capability"] == "generation.music"
    assert reply["receipt"]["result"]["workspace"] == "music-test"
    entry = native.registry("music-test").command_admission(command["intent_id"])
    assert entry["original"] == command
    assert entry["effective"]["runtime"]["params"]["prompt"] == command["input"]["params"]["prompt"]


def test_new_music_intention_is_distinct_but_reused_intention_rejects_changed_lyrics(tmp_path):
    native = FakeNative(tmp_path)
    service = music_service(native)
    first = _run(service.submit(music_command()))
    altered = music_command()
    altered["input"]["params"]["prompt"] += "Another line"
    with pytest.raises(HTTPException) as conflict:
        _run(service.submit(altered))
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException) as domain_conflict:
        _run(service.submit(image_command("music-intent", workspace="music-test")))
    assert domain_conflict.value.status_code == 409
    second = _run(service.submit(music_command("deliberate-second-song")))
    assert first["receipt"]["taskIds"] != second["receipt"]["taskIds"]
    assert len(native.dispatch_calls) == 2


def test_music_recovery_keeps_original_lyrics_and_job_without_dispatch(tmp_path):
    native = FakeNative(tmp_path)
    first = _run(music_service(native).submit(music_command()))
    restarted = FakeNative(tmp_path, interrupt_stale=True)
    service = music_service(restarted)
    service.restore_recovery(["music-test"])
    assert restarted.dispatch_calls == []
    record = restarted.persist_calls[0]
    assert record["params"]["prompt"] == music_command()["input"]["params"]["prompt"]
    assert record["id"] == first["receipt"]["result"]["job_id"]
    assert service.filter_recovery([record]) == [record]
    assert _run(service.submit(music_command()))["receipt"] == first["receipt"]
    assert restarted.dispatch_calls == []


def test_music_factory_preserves_audio_origin_through_native_preparation(tmp_path):
    native = FakeNative(tmp_path)
    for folder in ("music-test", "reference", "uploads"):
        (tmp_path / folder).mkdir()
    source = tmp_path / "reference" / "music.wav"
    write_wave(source, 800)
    write_wave(tmp_path / "music-test" / "music.wav", 1600)
    observed = {}

    async def native_generate(request):
        body = await request.json()
        assert request.prepared_studio_audio is True
        assert request.prepared_studio_speech is False
        prepare_generation_inputs(
            body, ACE_DEFINITION, body["workspace"],
            uploads_dir=tmp_path / "uploads", workspace_dir=tmp_path / body["workspace"],
            prepared_speech=request.prepared_studio_audio is True,
        )
        observed.update(deepcopy(body))
        return await native.prepare(JsonAdmissionRequest(body, request.admit_generation_command))

    runtime = {
        "_task_registry": native.registry, "generate": native_generate,
        "_new_generation_job": native.make_job,
        "_generation_task_fields": native.service().task_fields,
        "_jobs": {}, "_check_model_downloaded": lambda _model: True,
        "_workspace_dir": lambda workspace: str(tmp_path / workspace),
        "_list_workspaces": lambda: [{"name": "reference"}, {"name": "music-test"}],
        "_lora_is_compatible_with_model": lambda *_args: False,
        "wgp": SimpleNamespace(primary_settings={}, get_model_def=lambda _: deepcopy(ACE_DEFINITION),
                               get_lora_search_dirs=lambda _: []),
        "execution_mode": SimpleNamespace(validate_generation=lambda _: None),
    }
    service = create_image_generation_commands(runtime)
    # Stop at the existing dispatch seam; resource inspection and the runtime
    # factory are real, but this test does not load a model or start a worker.
    service.dispatch = native.dispatch
    service.persist_recovery = native.persist_recovery
    command = music_command()
    command["input"]["params"].update(audio_prompt_type="A",
        audio_guide="/api/v1/file/music.wav?workspace=reference")
    reply = _run(service.submit(command))
    assert observed["audio_guide"] == str(source)
    assert observed["prompt"] == command["input"]["params"]["prompt"]
    assert len(native.dispatch_calls) == 1
    entry = native.registry("music-test").command_admission(command["intent_id"])
    resource = entry["effective"]["resources"][0]
    assert resource["workspace"] == "reference"
    assert resource["duration_seconds"] == 0.1
    assert reply["receipt"]["operation"] == "generation.music"
    assert _run(service.submit(command))["replayed"] is True
    assert len(native.dispatch_calls) == 1


class JsonAdmissionRequest(JsonRequest):
    def __init__(self, body, admit):
        super().__init__(body)
        self.admit_generation_command = admit


def test_music_preparation_marker_cannot_be_forged_by_json():
    assert getattr(JsonRequest({"prepared_studio_audio": True}), "prepared_studio_audio", False) is False

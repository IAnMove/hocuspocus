"""Creation models keep reference identities, native contracts and cancellation."""
import threading
from pathlib import Path

import pytest

from services.creation_model_catalog import MODEL_TYPES, assets, model_definition, validate
from services.creation_model_graphs import build_workflow
from services.studio_speech_spec import SPEECH_MODEL_TYPES


def test_speech_registered_separately_from_images():
    assert {name for name in MODEL_TYPES if name in SPEECH_MODEL_TYPES} == {"drama3_base", "drama3_voicedesign"}
    for model in MODEL_TYPES:
        definition = model_definition(model)
        assert definition["image_outputs"] != definition["audio_only"]
        assert definition["group"] == ("flux3" if model.startswith("flux3_") else "tts")
        assert definition["required_model_assets"]
        assert len(assets(model)[1]) == 40


def test_flux_ten_references_are_encoded_in_order(tmp_path):
    refs = []
    for i in range(10):
        source = tmp_path / f"view{i}.png"
        source.write_bytes(bytes([i]))
        refs.append(str(source))
    params = {"model_type": "flux3_klein_edit", "prompt": "Same character, four views", "seed": 42,
              "image_guide": refs[0], "image_refs": refs[1:]}
    graph, output = build_workflow(params, "test", tmp_path / "inputs")
    assert graph[output]["class_type"] == "SaveImage"
    for i in range(10):
        name = graph[str(20 + 5 * i)]["inputs"]["image"]
        assert (tmp_path / "inputs" / name).read_bytes() == bytes([i])
        assert graph[str(21 + 5 * i)]["inputs"]["resolution_steps"] == 16
    assert graph["7"]["inputs"]["positive"] == ["68", 0]
    assert graph["7"]["inputs"]["negative"] == ["69", 0]
    with pytest.raises(ValueError, match="ten"):
        validate({**params, "image_refs": refs})


def test_clone_needs_both_audio_and_exact_transcript(tmp_path):
    params = {"model_type": "drama3_base", "prompt": "Hello", "seed": 7, "audio_guide": "clip.wav"}
    with pytest.raises(ValueError, match="transcript"):
        validate(params)
    source = tmp_path / "clip.wav"
    source.write_bytes(b"audio fixture")
    params.update(audio_guide=str(source), alt_prompt="Original words")
    graph, _ = build_workflow(params, "clone", tmp_path / "inputs")
    assert graph["7"]["inputs"]["transcript"] == "Original words"
    assert graph["3"]["inputs"]["voices.voice0"] == ["7", 0]
    assert graph["1"]["inputs"]["experts"] == "in RAM"


def test_voice_direction_is_not_added_to_reference_transcript(tmp_path):
    graph, _ = build_workflow({"model_type": "drama3_voicedesign", "prompt": "Hola. [language: es]",
                              "alt_prompt": "Warm and clear", "seed": 3}, "speech", tmp_path)
    assert graph["3"]["inputs"]["text"] == "Direction: Warm and clear\nLine: Hola. [language: es]"
    assert "voices.voice0" not in graph["3"]["inputs"]


def test_inactive_wangp_outpaint_sentinel_is_not_an_edit():
    validate({"model_type": "drama3_voicedesign", "prompt": "Hola", "video_guide_outpainting": "#"})
    validate({"model_type": "flux3_klein", "prompt": "A cube", "video_guide_outpainting": "0 0 0 0"})
    with pytest.raises(ValueError, match="outpainting"):
        validate({"model_type": "flux3_klein", "prompt": "A cube", "video_guide_outpainting": "0 16 0 0"})


def test_cancel_does_not_wait_for_the_generation_lock(monkeypatch):
    from services import creation_model_service as service
    done = threading.Event()
    monkeypatch.setattr(service, "_port", 1234)
    monkeypatch.setattr(service, "_request", lambda *a, **k: done.set())
    with service._lock:
        thread = threading.Thread(target=service.cancel, daemon=True)
        thread.start()
        assert done.wait(1), "Cancellation blocked on the active generation lock"
    thread.join(timeout=1)


def test_runtime_is_stopped_if_assets_fail(monkeypatch, tmp_path):
    from services import creation_model_service as service
    stopped = []
    monkeypatch.setattr(service, "download_assets", lambda *a: (_ for _ in ()).throw(RuntimeError("gated")))
    monkeypatch.setattr(service, "stop_runtime", lambda: stopped.append(True))
    with pytest.raises(RuntimeError, match="gated"):
        service.generate({"model_type": "flux3_klein"}, "job", str(tmp_path), lambda *a: None, lambda: False)
    assert stopped == [True]


def test_edit_admission_accepts_a_source_but_requires_conditioning():
    from fastapi import HTTPException
    from services.image_generation_commands import validate_image_model
    params = {"model_type": "flux3_klein_edit", "resolution": "1024x1024"}
    callbacks = {"model_definition": model_definition, "model_downloaded": lambda _: True}
    with pytest.raises(HTTPException) as missing:
        validate_image_model(params, allow_references=True, **callbacks)
    assert missing.value.detail["code"] == "reference_required"
    validate_image_model({**params, "image_guide": "source.png"}, allow_references=True, **callbacks)
    with pytest.raises(HTTPException):
        validate_image_model({**params, "image_guide": "source.png"}, **callbacks)


def test_a_delayed_history_poll_does_not_discard_a_finished_output(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from services import creation_model_service as service
    output = tmp_path / "runtime"
    output.mkdir()
    (output / "take.flac").write_bytes(b"generated audio")
    polls = []

    def request(method, base, suffix, **kwargs):
        if suffix == "/prompt":
            return SimpleNamespace(json=lambda: {"prompt_id": "one"})
        polls.append(suffix)
        if len(polls) == 1:
            raise service.requests.Timeout("kernel busy")
        return SimpleNamespace(json=lambda: {"one": {"outputs": {"5": {"audio": [{"filename": "take.flac"}]}}}})

    monkeypatch.setattr(service, "_request", request)
    monkeypatch.setattr(service, "_process", SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(service, "OUTPUT_DIR", output)
    monkeypatch.setattr(service, "INPUT_DIR", tmp_path / "inputs")
    monkeypatch.setattr(service, "download_assets", lambda *args: None)
    monkeypatch.setattr(service, "ensure_runtime", lambda *args: "http://runtime")
    monkeypatch.setattr(service, "stop_runtime", lambda: None)
    monkeypatch.setattr(service, "build_workflow", lambda *args: ({}, "5"))
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    result = service.generate({"model_type": "drama3_base", "seed": 1}, "job", tmp_path / "published",
                              lambda *args: None, lambda: False)
    assert Path(result[0]).read_bytes() == b"generated audio"
    assert len(polls) == 2


def test_shared_weights_cannot_be_deleted_while_the_other_variant_is_queued(monkeypatch, tmp_path):
    from fastapi import HTTPException
    from services import creation_model_service as service, model_downloads
    monkeypatch.setattr(model_downloads, "_active_gen_states", {})
    monkeypatch.setattr(model_downloads, "_jobs", {"queued": {"status": "queued", "params": {"model_type": "flux3_klein_edit"}}})
    with pytest.raises(HTTPException) as busy:
        model_downloads.delete_model("flux3_klein")
    assert busy.value.status_code == 409
    monkeypatch.setattr(model_downloads, "_jobs", {})
    monkeypatch.setattr(service, "ASSET_ROOT", tmp_path)
    for name in assets("flux3_klein")[2]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    result = model_downloads.delete_model("flux3_klein")
    assert set(result["affected_models"]) == {"flux3_klein", "flux3_klein_edit"}
    assert len(result["deleted"]) == 3
    assert all(not (tmp_path / name).exists() for name in result["deleted"])


def test_random_seed_is_resolved_and_each_repeat_keeps_its_effective_seed(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from services import creation_model_execution as execution
    observed, published = [], []
    paths = [str(tmp_path / f"flux3_klein_job_{i}_00001_.png") for i in range(2)]
    monkeypatch.setattr(execution.secrets, "randbelow", lambda _: 12345)
    monkeypatch.setattr(execution.service, "generate", lambda params, *args: observed.append(params) or paths)
    monkeypatch.setattr(execution, "record_job_outputs", lambda *args: None)
    monkeypatch.setattr(execution, "is_cancel_requested", lambda _: False)
    monkeypatch.setattr(execution, "finish_job", lambda *args, **kwargs: True)
    original = {"model_type": "flux3_klein", "seed": -1}
    state = SimpleNamespace(job={"out_dir": str(tmp_path)}, raw_params=original, job_id="job", start_time=0, finalize=True)
    execution.run_creation_job(state, engine=SimpleNamespace(), publish=lambda job, path, meta: published.append(meta))
    assert original["seed"] == -1
    assert observed[0]["seed"] == 12345
    assert [meta["params"]["seed"] for meta in published] == [12345, 12346]


def test_drama_flac_outputs_appear_in_the_audio_gallery(monkeypatch, tmp_path):
    from fastapi import Response
    from services import output_listing
    (tmp_path / "drama.flac").write_bytes(b"fLaC fixture")
    monkeypatch.setattr(output_listing, "_workspace_dir", lambda _: str(tmp_path))
    monkeypatch.setattr(output_listing, "_load_favorites", lambda: set())
    result = output_listing.list_outputs(Response(), workspace="demo", media_type="audio")
    assert result["total"] == 1
    assert result["outputs"][0]["name"] == "drama.flac"
    assert result["outputs"][0]["type"] == "audio"

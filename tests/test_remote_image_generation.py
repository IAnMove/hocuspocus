"""MiniMax Image-01 as a normal ``generation.image`` model (services/remote_image_generation.py and remote_image_worker.py).

The MiniMax HTTP call is always a fake. No test reaches the network, and no key in this file is real.
"""
from __future__ import annotations

import base64
import io
import json
import os
import threading
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
from fastapi import HTTPException
from PIL import Image

from services import media_options, minimax_image_service, remote_image_generation as remote, remote_image_worker
from services.job_lifecycle import request_cancel

KEY = "test-key-not-real-0123456789"
SERVICES = {"minimax_image_api_key": KEY}


def _png(path: Path, size: int = 8) -> Path:
    Image.new("RGB", (size, size), (200, 40, 40)).save(path)
    return path


def _resolver(root: Path):
    def resolve(value: str):
        path = root / Path(urlsplit(value).path).name
        if not path.is_file():
            raise ValueError("the picture is not available")
        return str(path), {"sha256": "0" * 64, "size_bytes": path.stat().st_size}
    return resolve


def _params(**more):
    return {"workspace": "default", "model_type": "minimax:image-01", "prompt": "a lantern in the rain", "resolution": "1920x1080",
            "num_inference_steps": 1, "guidance_scale": 1.0, "seed": 3, **more}


def _http_error(call):
    with pytest.raises(HTTPException) as caught:
        call()
    return caught.value


# ----- what is a remote image model -----

def test_only_a_minimax_prefix_names_a_remote_image_model():
    assert remote.is_remote_image_model("minimax:image-01")
    assert not remote.is_remote_image_model("qwen_image_21_turbo")
    assert not remote.is_remote_image_model("minimax_h3")  # the local video family has an underscore, not a provider prefix
    assert not remote.is_remote_image_model(None)
    assert remote.is_remote_image_params({"model_type": "minimax:image-01"}) and not remote.is_remote_image_params("minimax:image-01")


def test_the_catalog_says_it_is_remote_needs_a_key_and_takes_one_reference():
    entry = remote.catalog_entry(key_set=False)
    assert entry["model_type"] == "minimax:image-01" and entry["family"] == remote.FAMILY["id"] == "minimax"
    assert entry["resource_requirements"]["tier"] == "remote" and entry["remote"] is True and entry["requires_api_key"] is True
    assert entry["api_key_set"] is False and entry["is_downloaded"] is True and entry["director"]["max_image_refs"] == 1
    assert "api_key_set" not in remote.catalog_entry()
    options = remote.model_options()
    assert options["lock_inference_steps"] and options["lock_guidance_scale"] and options["no_negative_prompt"]
    assert options["max_image_refs"] == 1 and options["image_ref_choices"]["choices"][-1][1] == "I"
    assert remote.defaults()["num_inference_steps"] == 1 and remote.defaults()["guidance_scale"] == 1.0


def test_media_options_lists_a_remote_model_under_cloud_not_as_a_local_one():
    models = [remote.catalog_entry(True),
              {"model_type": "qwen_image_21_turbo", "architecture": "qwen_image_21", "name": "Qwen Turbo", "is_downloaded": True}]
    assert [item["id"] for item in media_options._local_images(models)] == ["qwen_image_21_turbo"]


# ----- the command may leave out what a remote model does not use -----

@pytest.mark.parametrize("version", [1, 2])
def test_a_remote_command_may_omit_steps_guidance_and_seed(version):
    input_ = {"workspace": "default", "model_type": "minimax:image-01", "prompt": "a lantern", "resolution": "1024x1024"}
    command = {"version": version, "operation": "generation.image", "intent_id": "i1",
               "input": input_ if version == 1 else {"workspace": "default", "params": {k: v for k, v in input_.items() if k != "workspace"}}}
    sent = json.loads(json.dumps(command))
    completed = remote.complete_remote_command(command)
    target = completed["input"] if version == 1 else completed["input"]["params"]
    assert (target["num_inference_steps"], target["guidance_scale"], target["seed"]) == (1, 1.0, -1)
    assert command == sent, "the caller's command is not changed"
    explicit = json.loads(json.dumps(command))
    (explicit["input"] if version == 1 else explicit["input"]["params"]).update(num_inference_steps=4, guidance_scale=2.0, seed=9)
    assert remote.complete_remote_command(explicit) is explicit, "what the caller wrote stays"


def test_a_local_model_command_is_never_completed():
    command = {"version": 1, "operation": "generation.image", "intent_id": "i1",
               "input": {"workspace": "default", "model_type": "qwen_image_21_turbo", "prompt": "x", "resolution": "1024x1024"}}
    assert remote.complete_remote_command(command) is command
    assert remote.complete_remote_command("not a command") == "not a command"


# ----- preparation: key, policy, prompt, references -----

def test_without_a_key_the_request_is_refused_before_admission_and_says_where_the_key_goes():
    error = _http_error(lambda: remote.prepare_remote_image(_params(), services={}))
    assert error.status_code == 409 and error.detail["code"] == "provider_key_missing" and error.detail["retryable"] is False
    message = error.detail["message"]
    assert "Settings → Services" in message and "minimax_image_api_key" in message and "minimax_api_key" in message


def test_the_shared_minimax_key_is_enough_and_the_image_key_wins():
    assert remote.api_key({"minimax_api_key": "shared"}) == "shared"
    assert remote.api_key({"minimax_api_key": "shared", "minimax_image_api_key": "image"}) == "image"
    remote.prepare_remote_image(_params(), services={"minimax_api_key": "shared"})


def test_an_execution_policy_that_forbids_paid_providers_is_a_409():
    from services import execution_mode

    with patch.object(execution_mode, "validate_remote_provider", side_effect=execution_mode.ExecutionModeError("no paid providers")):
        error = _http_error(lambda: remote.prepare_remote_image(_params(), services=SERVICES))
    assert error.status_code == 409 and error.detail["code"] == "execution_policy" and "no paid providers" in error.detail["message"]


def test_an_empty_prompt_is_refused():
    error = _http_error(lambda: remote.prepare_remote_image(_params(prompt="   "), services=SERVICES))
    assert error.status_code == 422 and error.detail["code"] == "invalid_command"


def test_steps_and_guidance_are_not_validated_and_the_resolution_becomes_an_aspect_ratio():
    working, resources = remote.prepare_remote_image(_params(num_inference_steps=999, guidance_scale=77.0), services=SERVICES)
    assert working["aspect_ratio"] == "16:9" and working["generation_mode"] == "image" and resources == []
    assert remote.prepare_remote_image(_params(resolution="1024x1024"), services=SERVICES)[0]["aspect_ratio"] == "1:1"


def test_the_first_reference_is_the_character_and_every_other_one_is_listed_as_ignored(tmp_path):
    for name in ("a.png", "b.png", "c.png"):
        _png(tmp_path / name)
    working, resources = remote.prepare_remote_image(
        _params(image_refs=["/api/v1/file/a.png?workspace=default", "/api/v1/file/b.png?workspace=default", "/api/v1/file/c.png?workspace=default"],
                negative_prompt="blurry", activated_loras=["style"]),
        services=SERVICES, resolve=_resolver(tmp_path))
    assert working["image_refs"] == [str(tmp_path / "a.png")]
    subject = [item for item in resources if item["role"] == "subject_reference"]
    assert len(subject) == 1 and subject[0]["index"] == 0 and subject[0]["url"].endswith("a.png?workspace=default")
    notes = remote.receipt_notes(resources)
    assert len(notes) == 4 and notes == working["_remote_notes"]
    assert "image_refs[1]" in notes[0] and "image_refs[2]" in notes[1] and "one character reference" in notes[0]
    assert any("negative prompt" in note for note in notes) and any("LoRA" in note for note in notes)


def test_a_start_frame_is_the_character_only_when_there_are_no_references(tmp_path):
    _png(tmp_path / "start.png")
    _png(tmp_path / "ref.png")
    only_start, _ = remote.prepare_remote_image(_params(image_start="/api/v1/file/start.png?workspace=default"),
                                                services=SERVICES, resolve=_resolver(tmp_path))
    assert only_start["image_refs"] == [str(tmp_path / "start.png")] and "image_start" not in only_start
    both, resources = remote.prepare_remote_image(
        _params(image_refs=["/api/v1/file/ref.png?workspace=default"], image_start="/api/v1/file/start.png?workspace=default",
                image_guide="/api/v1/file/start.png?workspace=default"),
        services=SERVICES, resolve=_resolver(tmp_path))
    assert both["image_refs"] == [str(tmp_path / "ref.png")]
    assert {"image_start", "image_guide"} <= {item["source_field"] for item in resources if item["role"] == "ignored_reference"}
    assert all(field not in both for field in ("image_start", "image_end", "image_guide", "image_mask"))


def test_a_reference_that_cannot_be_read_is_a_422_that_names_it(tmp_path):
    error = _http_error(lambda: remote.prepare_remote_image(
        _params(image_refs=["/api/v1/file/missing.png?workspace=default"]), services=SERVICES, resolve=_resolver(tmp_path)))
    assert error.status_code == 422 and error.detail["code"] == "invalid_reference" and error.detail["message"].startswith("image_refs[0]:")
    big = tmp_path / "big.png"
    big.write_bytes(b"x")
    with patch.object(remote, "MAX_REFERENCE_BYTES", 0):
        error = _http_error(lambda: remote.prepare_remote_image(
            _params(image_refs=["/api/v1/file/big.png?workspace=default"]), services=SERVICES, resolve=_resolver(tmp_path)))
    assert error.status_code == 422 and "20 MB" in error.detail["message"]


def test_a_long_prompt_is_flagged_as_shortened():
    _, resources = remote.prepare_remote_image(_params(prompt="word " * 400), services=SERVICES)
    assert any("1,500" in note for note in remote.receipt_notes(resources))


# ----- the worker: a normal job that waits for HTTP, not for the GPU queue -----

class _Response:
    text = ""

    def __init__(self, body: bytes | None = None, payload: dict | None = None):
        self._payload = payload or {"data": {"image_base64": [base64.b64encode(body or _jpeg()).decode("ascii")]},
                                    "base_resp": {"status_code": 0, "status_msg": "success"}}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 120, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _job(tmp_path: Path, **params):
    return {"id": "job1", "task_id": "task-generation-job1", "root_task_id": "task-generation-job1", "status": "queued",
            "progress": 0, "message": "Queued", "out_dir": str(tmp_path), "workspace": "default", "output_files": [],
            "params": {"model_type": "minimax:image-01", "prompt": "a lantern in the rain", "resolution": "1920x1080",
                       "aspect_ratio": "16:9", **params}}


def _run(job, services=SERVICES, published=None, removed=None):
    published = [] if published is None else published
    removed = [] if removed is None else removed
    done = remote_image_worker.run_remote_image_job(
        job, services=lambda: services, publish_sidecar=lambda *args: published.append(args), remove_persisted=removed.append)
    return done, published, removed


def test_the_worker_calls_minimax_once_with_the_character_and_completes_the_job(tmp_path):
    reference = _png(tmp_path / "hero.png")
    job = _job(tmp_path, image_refs=[str(reference)], _remote_notes=["image_refs[1]: not sent"])
    seen = {}

    def post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, headers=headers)
        return _Response()

    with patch.object(minimax_image_service.requests, "post", post):
        done, published, removed = _run(job)
    assert done is True and job["status"] == "completed" and job["progress"] == 100
    assert seen["url"] == minimax_image_service.API_URL and seen["body"]["model"] == "image-01" and seen["body"]["aspect_ratio"] == "16:9"
    assert seen["body"]["subject_reference"][0]["type"] == "character"
    assert seen["body"]["subject_reference"][0]["image_file"].startswith("data:image/png;base64,")
    assert seen["headers"]["Authorization"] == f"Bearer {KEY}"
    assert len(job["output_files"]) == 1 and (tmp_path / job["output_files"][0]).is_file()
    assert job["acquired_resources"] == [remote.lane_key()] and "image_refs[1]: not sent" in job["message"]
    assert len(published) == 1 and published[0][1].endswith(job["output_files"][0]) and published[0][2]["params"]["provider"] == "minimax"
    assert removed == [job], "a finished job must not come back as a restart leftover"
    assert KEY not in json.dumps(job, default=str) and KEY not in json.dumps(published, default=str)


def test_a_request_without_a_reference_sends_no_subject_reference(tmp_path):
    job = _job(tmp_path)
    bodies = []

    def post(url, json=None, headers=None, timeout=None):
        bodies.append(json)
        return _Response()

    with patch.object(minimax_image_service.requests, "post", post):
        assert _run(job)[0] is True
    assert "subject_reference" not in bodies[0]


def test_the_output_name_a_caller_chose_is_used(tmp_path):
    job = _job(tmp_path, output_filename="lantern.png")
    with patch.object(minimax_image_service.requests, "post", lambda *a, **k: _Response()):
        assert _run(job)[0] is True
    assert job["output_files"] == ["lantern.jpg"]


def test_a_provider_error_fails_the_job_with_the_providers_message_and_no_key(tmp_path):
    job = _job(tmp_path)
    bad = _Response(payload={"data": {}, "base_resp": {"status_code": 1004, "status_msg": "login fail: Please carry the API secret key"}})
    with patch.object(minimax_image_service.requests, "post", lambda *a, **k: bad):
        done, published, removed = _run(job)
    assert done is False and job["status"] == "failed" and "login fail" in job["error"] and job["output_files"] == []
    assert published == [] and removed == [job] and KEY not in json.dumps(job, default=str)


def test_a_key_removed_after_admission_fails_the_job_and_says_where_it_goes(tmp_path):
    job = _job(tmp_path)
    done, _, removed = _run(job, services={})
    assert done is False and job["status"] == "failed" and "Settings → Services" in job["error"] and removed == [job]


def test_a_reference_that_vanished_fails_the_job_without_calling_minimax(tmp_path):
    job = _job(tmp_path, image_refs=[str(tmp_path / "gone.png")])
    calls = []
    with patch.object(minimax_image_service.requests, "post", lambda *a, **k: calls.append(1) or _Response()):
        done, _, _ = _run(job)
    assert done is False and job["status"] == "failed" and calls == []


def test_a_job_cancelled_before_it_starts_never_calls_minimax(tmp_path):
    job = _job(tmp_path)
    request_cancel(job)
    calls = []
    with patch.object(minimax_image_service.requests, "post", lambda *a, **k: calls.append(1) or _Response()):
        done, _, removed = _run(job)
    assert done is False and job["status"] == "cancelled" and calls == [] and removed == [job]


def test_a_cancel_while_the_request_is_in_flight_ends_cancelled_and_deletes_the_picture(tmp_path):
    job = _job(tmp_path)
    started, release = threading.Event(), threading.Event()

    def post(url, json=None, headers=None, timeout=None):
        started.set()
        assert release.wait(5)
        return _Response()

    outcome = {}
    with patch.object(minimax_image_service.requests, "post", post):
        worker = threading.Thread(target=lambda: outcome.update(done=_run(job)[0]))
        worker.start()
        assert started.wait(5)
        assert job["status"] == "running"
        request_cancel(job)
        release.set()
        worker.join(5)
    assert outcome["done"] is False and job["status"] == "cancelled" and job["output_files"] == []
    assert [name for name in os.listdir(tmp_path)] == [], "neither the picture nor its sidecar is left"


def test_a_sidecar_that_cannot_be_written_does_not_fail_a_finished_picture(tmp_path):
    job = _job(tmp_path)

    def broken(*_args):
        raise OSError("disk full")

    with patch.object(minimax_image_service.requests, "post", lambda *a, **k: _Response()):
        done = remote_image_worker.run_remote_image_job(job, services=lambda: SERVICES, publish_sidecar=broken, remove_persisted=lambda _job: None)
    assert done is True and job["status"] == "completed"


def test_only_a_minimax_job_goes_to_this_worker():
    assert remote_image_worker.is_remote_image_job({"params": {"model_type": "minimax:image-01"}})
    assert not remote_image_worker.is_remote_image_job({"params": {"model_type": "qwen_image_21_turbo"}})
    assert not remote_image_worker.is_remote_image_job({"params": None}) and not remote_image_worker.is_remote_image_job(None)

"""Output names and published file identity without starting a model."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.asset_catalog import _stable_unmanaged_id
from services.asset_manifest import SCHEMA_NAME
from services.generation_output_name import (
    INVALID_OUTPUT_NAME,
    OutputNameError,
    apply_output_name,
    attach_output_name,
    chosen_image_filename,
    generation_receipt_view,
    legacy_prompt_stem,
    prepare_command_output_name,
    status_output_fields,
    validate_output_name,
)
from services.image_generation_commands import ImageGenerationCommands
from services.image_generation_spec import freeze_image_generation_spec
from services.task_manager import TaskRegistry
from shared.utils.utils import sanitize_file_name, truncate_for_filesystem


def _run(awaitable):
    return asyncio.run(awaitable)


def _command(intent_id="named-image", **overrides):
    payload = {
        "workspace": "workspace-a",
        "model_type": "pi_flux2",
        "prompt": "a lantern in the rain",
        "negative_prompt": "",
        "resolution": "512x512",
        "num_inference_steps": 1,
        "seed": 1,
        "guidance_scale": 1.0,
    }
    payload.update(overrides)
    return {
        "version": 1,
        "operation": "generation.image",
        "intent_id": intent_id,
        "input": payload,
    }


def _service(registry, prepare):
    return ImageGenerationCommands(
        registry=lambda _workspace: registry,
        prepare=prepare,
        preflight=lambda _params: None,
        make_job=lambda *_args, **_kwargs: {},
        task_fields=lambda _job: {},
        dispatch=lambda _job: None,
        persist_recovery=lambda _job: None,
        active_job_ids=lambda: [],
    )


def test_omitted_output_name_keeps_the_truncated_prompt_stem():
    prompt = "a lantern in the rain " * 20
    body = {"prompt": prompt, "output_filename": ""}
    assert apply_output_name(body) is None
    assert body["output_filename"] == ""
    assert "output_name" not in body
    stem = legacy_prompt_stem(prompt)
    assert stem == sanitize_file_name(truncate_for_filesystem(prompt)).strip()
    assert len(stem.encode("utf-8")) <= 100
    assert stem.startswith("a lantern")
    source = Path(__file__).resolve().parents[1].joinpath("app", "wgp.py").read_text(encoding="utf-8")
    assert "sanitize_file_name(truncate_for_filesystem(save_prompt))" in source


def test_output_name_replaces_the_prompt_stem():
    body = {"prompt": "a lantern in the rain", "output_filename": "{date}-{prompt(40)}", "output_name": "lantern.png"}
    assert apply_output_name(body) == "lantern.png"
    assert body["output_filename"] == "lantern.png"
    assert "output_name" not in body


@pytest.mark.parametrize("name", [
    "../secret.png",
    "..\\secret.png",
    "/tmp/secret.png",
    "folder/lantern.png",
    "folder\\lantern.png",
    "..",
    ".",
    "C:secret.png",
    "a\x00b.png",
    "",
    "  lantern.png",
    "lantern.png  ",
    "{prompt}",
    12,
])
def test_escaping_or_separated_names_use_a_stable_code(name):
    with pytest.raises(OutputNameError) as caught:
        validate_output_name(name)
    assert caught.value.code == INVALID_OUTPUT_NAME
    body = {"prompt": "keep me", "output_name": name}
    with pytest.raises(OutputNameError) as caught:
        apply_output_name(body)
    assert caught.value.code == INVALID_OUTPUT_NAME
    assert "output_filename" not in body


def test_submit_accepts_output_name_and_rejects_escapes_before_prepare(tmp_path):
    seen = {}

    async def prepare(request):
        seen["body"] = await request.json()
        return seen["body"]

    service = _service(TaskRegistry(str(tmp_path), interrupt_stale=False), prepare)
    accepted = _run(service.submit(_command(output_name="lantern.png")))
    assert accepted["output_name"] == "lantern.png"
    assert seen["body"]["prompt"] == "a lantern in the rain"

    calls = {"n": 0}

    async def counting(_request):
        calls["n"] += 1
        return {}

    service = _service(TaskRegistry(str(tmp_path / "reject"), interrupt_stale=False), counting)
    with pytest.raises(HTTPException) as caught:
        _run(service.submit(_command("bad-name", output_name="../secret.png")))
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == INVALID_OUTPUT_NAME
    assert calls["n"] == 0


def test_output_name_changes_the_generation_fingerprint():
    plain = freeze_image_generation_spec(_command("same"))
    cloned, name = prepare_command_output_name(_command("same", output_name="lantern.png"))
    frozen = freeze_image_generation_spec(cloned)
    assert frozen["fingerprint"] == plain["fingerprint"]
    bound, params = attach_output_name(frozen, dict(frozen["effective"]["input"]), name)
    assert params["output_name"] == "lantern.png"
    assert bound["effective"]["input"]["output_name"] == "lantern.png"
    assert bound["fingerprint"] != plain["fingerprint"]
    again, _params = attach_output_name(frozen, dict(frozen["effective"]["input"]), name)
    assert again["fingerprint"] == bound["fingerprint"]


def test_null_output_name_is_omitted():
    cloned, name = prepare_command_output_name(_command(output_name=None))
    assert name is None
    frozen = freeze_image_generation_spec(cloned)
    assert "output_name" not in frozen["effective"]["input"]


def test_chosen_image_name_keeps_the_stamp_when_omitted():
    stamped = chosen_image_filename(None, filename_prefix="minimax-image-01")
    assert stamped.endswith(".jpg")
    assert "_minimax-image-01_" in stamped
    assert chosen_image_filename("lantern.png", filename_prefix="minimax-image-01") == "lantern.jpg"


def test_status_and_receipt_return_the_produced_file(tmp_path):
    workspace = "workspace-a"
    filename = "lantern.jpg"
    media = tmp_path / filename
    media.write_bytes(b"jpeg")
    asset_id = "asset_named_lantern"
    media.with_suffix(".meta.json").write_text(json.dumps({
        "schema": SCHEMA_NAME,
        "asset": {"id": asset_id},
    }), encoding="utf-8")
    fields = status_output_fields([filename], workspace=workspace, workspace_dir=str(tmp_path))
    assert fields["outputs"] == [{
        "asset_id": asset_id,
        "canonical_url": "/api/v1/file/lantern.jpg?workspace=workspace-a",
        "path": filename,
    }]
    assert fields["asset_id"] == asset_id
    assert fields["canonical_url"].endswith("lantern.jpg?workspace=workspace-a")
    assert fields["path"] == filename

    missing = status_output_fields(["other.png"], workspace=workspace, workspace_dir=str(tmp_path))
    assert missing["asset_id"] == _stable_unmanaged_id(workspace, "other.png")
    assert missing["path"] == "other.png"
    assert missing["canonical_url"] == "/api/v1/file/other.png?workspace=workspace-a"

    escaped = status_output_fields(["../secret.png"], workspace=workspace, workspace_dir=str(tmp_path))
    assert escaped["outputs"] == []
    assert escaped["asset_id"] is None
    assert escaped["canonical_url"] is None
    assert escaped["path"] is None

    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    admitted = registry.admit_command_task(
        intent_id="done",
        operation="generation.image",
        digest="a" * 64,
        original={"version": 1, "operation": "generation.image", "intent_id": "done", "input": {}},
        effective={"version": 1, "operation": "generation.image", "intent_id": "done", "input": {}},
        task_fields={
            "id": "task-done",
            "root_id": "task-done",
            "kind": "image",
            "workflow": "generation.image",
            "status": "queued",
            "workspace": workspace,
            "backend_job_id": "job-done",
        },
    )
    registry.update("task-done", status="running")
    registry.update("task-done", status="completed", result_refs=[filename])
    service = _service(registry, prepare=None)

    async def _unused(_request):
        return {}

    service.prepare = _unused
    view = service.receipt(workspace, "done")
    assert view["receipt"] == admitted["receipt"]
    assert view["task"]["status"] == "completed"
    assert view["asset_id"] == asset_id
    assert view["canonical_url"] == fields["canonical_url"]
    assert view["path"] == filename
    assert view["outputs"] == fields["outputs"]
    assert "asset_id" not in view["receipt"]


def test_generation_receipt_view_reads_a_fake_completed_task(tmp_path):
    task = {
        "status": "completed",
        "result_refs": ["my lantern.png"],
    }
    view = generation_receipt_view(
        {"status": "queued"}, task, workspace="default", workspace_dir=str(tmp_path),
    )
    assert view["path"] == "my lantern.png"
    assert view["canonical_url"] == "/api/v1/file/my%20lantern.png?workspace=default"
    assert view["asset_id"] == _stable_unmanaged_id("default", "my lantern.png")
    assert view["receipt"]["status"] == "queued"

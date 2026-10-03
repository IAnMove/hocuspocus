"""Receipts of queued exports report the task's live status and published file.

The stored admission receipt stays as admitted ("queued"). Readers of
scenes.video2d.export.receipt and scenes.world3d.export.receipt get a
projected copy that follows the canonical task.
"""
from __future__ import annotations

from copy import deepcopy


def _output_artifact(output: dict, task: dict) -> dict | None:
    name = output.get("name")
    url = output.get("url")
    workspace = output.get("workspace") if isinstance(output.get("workspace"), str) else task.get("workspace")
    if isinstance(name, str) and name and isinstance(url, str) and url and isinstance(workspace, str) and workspace:
        return {"name": name, "url": url, "workspace": workspace}
    return None


def _ref_artifact(task: dict) -> dict | None:
    if task.get("status") != "completed":
        return None
    refs = task.get("result_refs")
    workspace = task.get("workspace")
    if not isinstance(refs, list) or not refs or not isinstance(refs[0], str) or not refs[0]:
        return None
    if not isinstance(workspace, str) or not workspace:
        return None
    return {"name": refs[0], "url": f"/api/v1/file/{refs[0]}", "workspace": workspace}


def _published_artifact(task: dict) -> dict | None:
    metadata = task.get("metadata")
    output = metadata.get("output") if isinstance(metadata, dict) else None
    if isinstance(output, dict):
        artifact = _output_artifact(output, task)
        if artifact is not None:
            return artifact
    return _ref_artifact(task)


def _with_task_status(receipt: dict, task: dict) -> dict:
    status = task.get("status")
    if not isinstance(status, str) or not status:
        return receipt
    updated = {**receipt, "status": status}
    result = receipt.get("result")
    if isinstance(result, dict):
        updated["result"] = {**result, "status": status}
    return updated


def project_export_receipt(receipt: dict, task: dict | None) -> dict:
    """Copy of the admission receipt whose status and artifacts follow the task.

    The stored admission stays queued. Callers of scenes.video2d.export.receipt
    see the canonical task status and, once an MP4 exists, one artifact.
    """
    if not isinstance(task, dict):
        return deepcopy(receipt)
    projected = _with_task_status(deepcopy(receipt), task)
    metadata = task.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("quality"), str):
        projected["quality"] = metadata["quality"]
    if isinstance(metadata, dict) and isinstance(metadata.get("geometry"), dict):
        projected["geometry"] = deepcopy(metadata["geometry"])
    artifact = _published_artifact(task)
    if artifact is not None:
        projected["artifacts"] = [artifact]
    return projected

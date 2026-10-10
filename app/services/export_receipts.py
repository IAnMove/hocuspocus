"""Receipts of queued exports report the task's live status and published file.

The stored admission receipt stays as admitted ("queued"). Readers of
scenes.video2d.export.receipt and scenes.world3d.export.receipt get a
projected copy that follows the canonical task.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from urllib.parse import quote, urlencode
from services.export_output_name import previous_path
from services.media_publication import file_sha256


def _output_artifact(output: dict, task: dict) -> dict | None:
    name = output.get("name")
    url = output.get("url")
    workspace = output.get("workspace") if isinstance(output.get("workspace"), str) else task.get("workspace")
    if isinstance(name, str) and name and isinstance(url, str) and url and isinstance(workspace, str) and workspace:
        artifact = {"name": name, "url": url, "workspace": workspace}
        if isinstance(output.get("sha256"), str):
            artifact["sha256"] = output["sha256"]
        if output.get("replaced") is True and isinstance(output.get("previous"), str):
            # A named export (output_name) replaced an earlier file, kept as ``previous``.
            artifact.update(replaced=True, previous=output["previous"])
        return artifact
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


def _verified_artifact(artifact: dict, folder) -> dict:
    """An alias receipt follows its exact bytes, or explicitly has no downloadable artifact."""
    if folder is None or not artifact.get("sha256"):
        return artifact
    name, root = artifact["name"], Path(folder)
    if Path(name).name != name:
        return {**artifact, "name": None, "url": None, "available": False}
    for candidate in (root / name, previous_path(root / name)):
        try:
            matches = not candidate.is_symlink() and file_sha256(candidate) == artifact["sha256"]
        except OSError:
            matches = False
        if matches:
            url = f"/api/v1/file/{quote(candidate.name)}?{urlencode({'workspace': artifact['workspace'], 'sha256': artifact['sha256']})}"
            if candidate.name == name:
                return {**artifact, "url": url}
            return {**artifact, "name": candidate.name, "alias": name, "available": True, "superseded": True,
                    "url": url}
    return {**artifact, "name": None, "url": None, "alias": name, "available": False, "superseded": True}


def project_export_task(task: dict | None, receipt: dict) -> dict | None:
    """Include the receipt's verified URL in task fallbacks, without mutating the stored task."""
    artifacts = receipt.get("artifacts") or []
    if not task or not artifacts or not artifacts[0].get("sha256"):
        return task
    artifact = artifacts[0]
    metadata = {**(task.get("metadata") or {}), "output": artifact}
    return {**task, "metadata": metadata, "result_refs": [artifact["name"]] if artifact.get("available", True) else []}


def project_export_receipt(receipt: dict, task: dict | None, *, folder=None) -> dict:
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
        projected["artifacts"] = [_verified_artifact(artifact, folder)]
    metadata = task.get("metadata")
    qa = metadata.get("qa") if isinstance(metadata, dict) else None
    if isinstance(qa, dict):
        projected["qa"] = deepcopy(qa)
    return projected

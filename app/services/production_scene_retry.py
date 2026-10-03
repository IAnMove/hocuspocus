"""Retry a Video 2D scene export before the montage step.

``scenes()`` admits each export once. A receipt that is failed or cancelled, or
a job the queue lost on restart, is submitted once more (two exports in total).
Keys that still have no file become ``scene_export_failed: <sorted keys>``.
The montage step must not call ``montages.save`` when that happens or when no
scene file exists.
"""
from __future__ import annotations

import time
from collections.abc import Callable

EXPORT = "scenes.video2d.export"
RECEIPT = "scenes.video2d.export.receipt"
MAX_EXPORTS = 2
_TERMINAL = frozenset({"failed", "cancelled"})

Mcp = Callable[[str, dict], dict]
Sleep = Callable[[float], None]
Save = Callable[[], None]
Log = Callable[[str], None]


def scene_export_error(keys: list[str]) -> str:
    return "scene_export_failed: " + ", ".join(sorted(keys))


def apply_scene_export_failure(state: dict, failed: list[str]) -> None:
    if failed:
        state["status"] = "failed"
        state["error"] = scene_export_error(failed)
        return
    error = state.get("error")
    if isinstance(error, str) and error.startswith("scene_export_failed:"):
        state["error"] = None


def skip_montage(state: dict) -> bool:
    """True when montages.save must not run."""
    if state.get("status") == "failed":
        return True
    scenes = state.get("scenes") or {}
    for scene in scenes.values():
        if isinstance(scene, dict) and scene.get("file"):
            return False
    return True


def _artifact_name(response: object) -> str | None:
    if not isinstance(response, dict):
        return None
    receipt = response.get("receipt")
    if not isinstance(receipt, dict):
        return None
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or not isinstance(artifacts[0], dict):
        return None
    name = artifacts[0].get("name")
    if isinstance(name, str) and name:
        return name
    return None


def _lost(response: object) -> bool:
    if not isinstance(response, dict):
        return True
    if "task" in response and response.get("task") is None:
        return True
    task = response.get("task")
    if isinstance(task, dict) and task.get("status") in _TERMINAL:
        return True
    receipt = response.get("receipt")
    if isinstance(receipt, dict) and receipt.get("status") in _TERMINAL:
        return True
    if response.get("code") == "receipt_not_found":
        return True
    error = response.get("error")
    if isinstance(error, dict) and error.get("code") == "receipt_not_found":
        return True
    return False


def receipt_action(response: object) -> str:
    """ready when an MP4 is published, retry when the job will not finish, else wait."""
    if _artifact_name(response):
        return "ready"
    if _lost(response):
        return "retry"
    return "wait"


def _submit(mcp: Mcp, workspace: str, production_id: str, key: str, scene: dict, document: dict) -> None:
    intent = f"{production_id}-scene-{key}-{time.time_ns()}"
    response = mcp(EXPORT, {"version": 1, "intent_id": intent, "input": {"workspace": workspace, "document": document}})
    receipt = response.get("receipt") if isinstance(response, dict) else None
    scene["intent"] = receipt.get("commandId") if isinstance(receipt, dict) else None
    scene["file"] = None


def _poll(mcp: Mcp, workspace: str, scene: dict) -> tuple[str, str | None]:
    response = mcp(RECEIPT, {"version": 1, "input": {"workspace": workspace, "intent_id": scene.get("intent")}})
    action = receipt_action(response)
    if action == "ready":
        return action, _artifact_name(response)
    return action, None


def _finish_one(mcp: Mcp, workspace: str, production_id: str, key: str, scene: dict, document: dict | None,
                sleep: Sleep, save: Save) -> bool:
    # scenes() already admitted the first export.
    exports = 1
    while not scene.get("file") and exports <= MAX_EXPORTS:
        if scene.get("intent"):
            action, name = _poll(mcp, workspace, scene)
            if action == "ready" and name:
                scene["file"] = name
                save()
                return True
            if action == "wait":
                sleep(4)
                continue
            scene["intent"] = None
        if exports >= MAX_EXPORTS or document is None:
            return False
        exports += 1
        _submit(mcp, workspace, production_id, key, scene, document)
        save()
    return bool(scene.get("file"))


def finish_scene_exports(mcp: Mcp, workspace: str, production_id: str, scenes: dict, documents: dict[str, dict],
                         sleep: Sleep, save: Save, log: Log) -> list[str]:
    failed: list[str] = []
    for key, document in documents.items():
        scene = scenes.get(key)
        if not isinstance(scene, dict) or scene.get("file"):
            continue
        if _finish_one(mcp, workspace, production_id, key, scene, document, sleep, save):
            continue
        log(f"scene {key} failed")
        failed.append(key)
    return failed

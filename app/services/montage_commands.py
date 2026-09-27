"""Versioned montage commands shared by HTTP and external agents (MCP).

Commands never render implicitly: ``montages.export`` queues the ordinary Video
Editor export job and returns its job id, which ``montages.export.status`` reads.
"""
from __future__ import annotations

from typing import Any, Callable

from services.montage_documents import MontageError, MontageStore, export_body

WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
FILE = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.montage\.json$"}

MONTAGE_SCHEMA = {
    "type": "object",
    "description": ("Version 1 montage: name, width, height, fps (24/25/30/50/60), clips[{source, name, trimStart, "
                    "trimEnd, volume, muted, fit, transition, transitionDuration, origin{kind, scene}}], soundtrack{source, "
                    "trimStart, trimEnd, volume, loop}|null, audioCues[{id, source, start, volume}], overlays[{id, source "
                    "(PNG/JPEG/WebP), start, end, x, y, width (percent), opacity, fadeIn, fadeOut}], duck (0-1)."),
    "required": ["version", "name", "clips"],
}

OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "montages.list": ({"workspace": WORKSPACE}, ["workspace"], False,
                      "List editable Video Editor montages (<name>.montage.json) saved in a workspace."),
    "montages.get": ({"workspace": WORKSPACE, "file": FILE}, ["workspace", "file"], False,
                     "Read one montage document with its revision."),
    "montages.save": ({"workspace": WORKSPACE, "montage": MONTAGE_SCHEMA, "file": FILE,
                       "expected_revision": {"type": "integer", "minimum": 0}},
                      ["workspace", "montage"], True,
                      "Create or update an editable montage. Clips, soundtrack, audio cues and image overlays must be "
                      "existing workspace media. To update, pass file and expected_revision (compare-and-swap). "
                      "Nothing is rendered; open it in the Video Editor or call montages.export."),
    "montages.export": ({"workspace": WORKSPACE, "file": FILE}, ["workspace", "file"], True,
                        "Queue the ordinary Video Editor FFmpeg export of a saved montage (overlays and audio cues "
                        "included). Returns job_id; poll montages.export.status."),
    "montages.export.status": ({"job_id": {"type": "string", "minLength": 1, "maxLength": 80}}, ["job_id"], False,
                               "Read a montage export job: status, progress, filename and url when completed."),
}


def command_catalog() -> list[dict[str, Any]]:
    operations = []
    for name, (properties, required, mutation, description) in OPERATIONS.items():
        payload = {"type": "object", "additionalProperties": False, "properties": properties, "required": required}
        operations.append({
            "name": name, "version": 1, "domain": "montages", "mutation": mutation, "description": description,
            "inputSchema": {"type": "object", "additionalProperties": False,
                            "properties": {"version": {"type": "integer", "const": 1}, "input": payload},
                            "required": ["version", "input"]},
        })
    return operations


def _payload(arguments: Any, name: str) -> dict[str, Any]:
    properties, required, _, _ = OPERATIONS[name]
    if not isinstance(arguments, dict) or arguments.get("version") != 1 or not isinstance(arguments.get("input"), dict):
        raise MontageError("Use version 1 and an input object", code="invalid_command")
    payload = arguments["input"]
    unknown = set(payload) - set(properties)
    missing = [key for key in required if key not in payload]
    if unknown or missing:
        raise MontageError(f"Invalid input fields; required: {', '.join(required)}", code="invalid_command")
    return payload


class MontageCommands:
    def __init__(self, store: MontageStore, *, start_export: Callable[[dict], dict],
                 get_export: Callable[[str], dict]) -> None:
        self.store = store
        self.start_export = start_export
        self.get_export = get_export

    def execute(self, name: str, arguments: Any) -> dict[str, Any]:
        if name not in OPERATIONS:
            raise MontageError("Unknown montage operation", code="invalid_command")
        payload = _payload(arguments, name)
        if name == "montages.list":
            result: Any = {"montages": self.store.list(payload["workspace"])}
        elif name == "montages.get":
            result = self.store.get(payload["workspace"], payload["file"])
        elif name == "montages.save":
            result = self.store.save(payload["workspace"], payload["montage"], file=payload.get("file"),
                                     expected_revision=payload.get("expected_revision"))
        elif name == "montages.export":
            saved = self.store.get(payload["workspace"], payload["file"])
            result = {"file": saved["file"], "job": self.start_export(export_body(saved["montage"], payload["workspace"]))}
        else:
            result = {"job": self.get_export(payload["job_id"])}
        return {"version": 1, "status": "completed", "operation": name, "result": result}

    def handlers(self) -> dict[str, Callable[[Any], Any]]:
        return {name: self._handler(name) for name in OPERATIONS}

    def _handler(self, name: str) -> Callable[[Any], Any]:
        async def handle(arguments: Any) -> dict[str, Any]:
            from fastapi import HTTPException
            from starlette.concurrency import run_in_threadpool
            try:
                return await run_in_threadpool(self.execute, name, arguments)
            except MontageError as error:
                raise HTTPException(error.status, {"code": error.code, "message": str(error)}) from error
        return handle


__all__ = ["MontageCommands", "OPERATIONS", "command_catalog"]

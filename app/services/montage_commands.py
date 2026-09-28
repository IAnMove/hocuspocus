"""Versioned montage commands shared by HTTP and external agents (MCP).

Commands never render implicitly: ``montages.export`` queues the ordinary Video
Editor export job and returns its job id, which ``montages.export.status`` reads.
"""
from __future__ import annotations

from typing import Any, Callable

from services.montage_documents import MontageError, MontageStore, export_body
from services.montage_shots import ShotBoard

WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
FILE = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.montage\.json$"}
CLIP_ID = {"type": "string", "minLength": 1, "maxLength": 160}
INTENT = {"type": "string", "minLength": 1, "maxLength": 160}

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
    "montages.shots.get": ({"workspace": WORKSPACE, "file": FILE}, ["workspace", "file"], False,
                           "Shot board of a montage: each clip's slot on the timeline, its provenance (prompt, seed, start "
                           "image and model read from the generation sidecar, or the scene it was rendered from) and its takes. "
                           "Pending takes resolve from the workspace once their generation finishes."),
    "montages.shot.regenerate": ({"workspace": WORKSPACE, "file": FILE, "clip_id": CLIP_ID, "intent_id": INTENT,
                                  "expected_revision": {"type": "integer", "minimum": 1},
                                  "prompt": {"type": "string", "minLength": 1, "maxLength": 4000},
                                  "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647}},
                                 ["workspace", "file", "clip_id", "intent_id", "expected_revision"], True,
                                 "Queue a new take of one generated shot with its original parameters (optionally a new "
                                 "prompt or seed) on the normal generation queue. Adds a pending take; the clip keeps its "
                                 "current media until montages.shot.select."),
    "montages.shot.select": ({"workspace": WORKSPACE, "file": FILE, "clip_id": CLIP_ID, "take_id": CLIP_ID,
                              "expected_revision": {"type": "integer", "minimum": 1}, "retime": {"type": "boolean"}},
                             ["workspace", "file", "clip_id", "take_id", "expected_revision"], True,
                             "Use a finished take for a clip. The previous media stays as a take. A take shorter than "
                             "the clip's slot is slowed to cover it unless retime is false. Export again afterwards."),
    "montages.export.status": ({"job_id": {"type": "string", "minLength": 1, "maxLength": 80}, "workspace": WORKSPACE},
                               ["job_id"], False,
                               "Read a montage export job: status, progress, filename and url when completed. "
                               "workspace is optional, same string as the other montage commands; job_id still selects the job."),
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
                 get_export: Callable[[str], dict], shots: ShotBoard | None = None) -> None:
        self.store = store
        self.start_export = start_export
        self.get_export = get_export
        self.shots = shots

    def _board(self) -> ShotBoard:
        if self.shots is None:
            raise MontageError("The shot board is not available on this server", status=503, code="unavailable")
        return self.shots

    async def execute_async(self, name: str, arguments: Any) -> dict[str, Any]:
        """Like execute, but runs the generation submission of montages.shot.regenerate on the event loop."""
        from starlette.concurrency import run_in_threadpool
        if name != "montages.shot.regenerate":
            return await run_in_threadpool(self.execute, name, arguments)
        payload = _payload(arguments, name)
        result = await self._board().regenerate(
            payload["workspace"], payload["file"], payload["clip_id"], intent_id=payload["intent_id"],
            expected_revision=payload["expected_revision"], prompt=payload.get("prompt"), seed=payload.get("seed"))
        return {"version": 1, "status": "completed", "operation": name, "result": result}

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
        elif name == "montages.shots.get":
            result = self._board().shots(payload["workspace"], payload["file"])
        elif name == "montages.shot.select":
            result = self._board().select(payload["workspace"], payload["file"], payload["clip_id"], payload["take_id"],
                                          expected_revision=payload["expected_revision"], retime=payload.get("retime", True))
        elif name == "montages.shot.regenerate":
            raise MontageError("montages.shot.regenerate is asynchronous; use execute_async", code="invalid_command")
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
            try:
                return await self.execute_async(name, arguments)
            except MontageError as error:
                raise HTTPException(error.status, {"code": error.code, "message": str(error)}) from error
        return handle


__all__ = ["MontageCommands", "OPERATIONS", "command_catalog"]

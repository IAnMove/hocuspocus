"""Add clips to a workspace GLB that already has the standard humanoid skeleton."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from routers.wangp_mcp import RequestJournal
from services.asset_manifest import publish_generation_sidecar
from services.mcp_intent import check_intent_id, intent_digest

OPERATION = "model3d.animate"
_IMPORT_SUFFIXES = {".bvh", ".glb", ".gltf"}


def command_catalog():
    return [{"name": OPERATION, "version": 1, "domain": "model3d", "mutation": True,
             "description": "Add in-place humanoid clips, or one imported BVH/glTF clip, to a GLB that already "
                            "has the standard Mixamo-named skeleton. CPU only. Returns each clip index, name and duration "
                            "for a Video 3D slot. Fails when that skeleton is missing.",
             "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "intent_id", "input"],
                             "properties": {"version": {"const": 1, "type": "integer"},
                                            "intent_id": {"type": "string", "minLength": 1, "maxLength": 160},
                                            "input": {"type": "object", "additionalProperties": False,
                                                      "required": ["workspace", "source"], "properties": {
                                                          "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
                                                          "source": {"type": "string", "minLength": 1, "maxLength": 240},
                                                          "clips": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                                                          "bpm": {"type": "number", "minimum": 60, "maximum": 180},
                                                          "import": {"type": "object", "additionalProperties": False,
                                                                     "required": ["file"], "properties": {
                                                                         "file": {"type": "string", "minLength": 1, "maxLength": 240}}}}}}}}]


def _envelope(arguments):
    if not isinstance(arguments, dict) or type(arguments.get("version")) is not int or arguments["version"] != 1:
        raise ValueError("Use version 1, intent_id and input")
    if set(arguments) - {"version", "intent_id", "input"}:
        raise ValueError("Unknown envelope field")
    payload = arguments.get("input")
    if not isinstance(payload, dict) or set(payload) - {"workspace", "source", "clips", "bpm", "import"}:
        raise ValueError("input needs workspace and source")
    if "workspace" not in payload or "source" not in payload:
        raise ValueError("input needs workspace and source")
    return payload, check_intent_id(arguments.get("intent_id"))


def _text(payload: dict, field: str, limit: int) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be a nonempty string (max {limit})")
    return value.strip()


def _clip_ids(value) -> list[str]:
    from services.humanoid_rig.names import CLIP_IDS

    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("clips must be a list of animation ids")
    clips = list(dict.fromkeys(item.strip() for item in value))
    if any(not item for item in clips):
        raise ValueError("Animation identifiers cannot be empty")
    invalid = [item for item in clips if item not in CLIP_IDS]
    if invalid:
        raise ValueError(f"Unknown animations: {', '.join(invalid)}")
    return clips


def _bpm(value) -> float:
    if value is None:
        return 120.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("bpm must be a number between 60 and 180")
    bpm = float(value)
    if not math.isfinite(bpm) or bpm < 60 or bpm > 180:
        raise ValueError("bpm must be a number between 60 and 180")
    return bpm


def _import_name(payload: dict) -> str | None:
    if "import" not in payload:
        return None
    imported = payload["import"]
    if not isinstance(imported, dict) or set(imported) != {"file"}:
        raise ValueError("import needs file")
    name = imported["file"]
    if not isinstance(name, str) or not name.strip() or len(name) > 240:
        raise ValueError("import file is required")
    if Path(name.strip()).suffix.lower() not in _IMPORT_SUFFIXES:
        raise ValueError("import file must be .bvh, .glb or .gltf")
    return name.strip()


def _inside(root: Path, name: str) -> Path:
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("path must stay inside the workspace") from exc
    if not candidate.is_file():
        raise ValueError("file not found in the workspace")
    return candidate


def _python() -> Path:
    from services.rig_service import cpu_worker_python

    python = cpu_worker_python()
    if python is None:
        raise RuntimeError("Humanoid rig runtime is not installed")
    return python


def _worker_payload(completed: subprocess.CompletedProcess[str]) -> dict:
    line = next((item for item in reversed(completed.stdout.splitlines()) if item.startswith("MAESTRO_RESULT ")), "")
    if not line:
        detail = (completed.stderr or completed.stdout or "").strip()[:400]
        raise RuntimeError(detail or f"Humanoid animate worker exited {completed.returncode}")
    payload = json.loads(line[len("MAESTRO_RESULT "):])
    if not payload.get("ok"):
        raise ValueError(str(payload.get("reason") or payload.get("error") or "rig_failed"))
    return payload


def execute_animate(request: dict, output: Path, *, python: Path | None = None) -> dict:
    """Run the CPU worker. The app process does not import pygltflib."""
    from services.rig_service import APP_DIR
    from services.runtime_environment import isolated_environment

    python = python or _python()
    env = isolated_environment(python)
    env["PYTHONUNBUFFERED"] = "1"
    with tempfile.TemporaryDirectory(prefix="humanoid-animate-") as folder:
        request_path = Path(folder) / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        try:
            completed = subprocess.run(
                [str(python), "-m", "services.humanoid_rig.worker", "--request", str(request_path), "--output", str(output)],
                cwd=str(APP_DIR),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Humanoid animate worker timed out") from exc
    return _worker_payload(completed)


def _request(source: Path, clips: list[str], bpm: float, imported: Path | None) -> dict:
    request = {"mode": "animate", "source": str(source), "animations": clips, "animation_bpm": bpm}
    if imported is not None:
        request["import_file"] = str(imported)
    return request


def _publish(folder: Path, filename: str, payload: dict, intent: str, clips: list[str], bpm: float, imported: Path | None) -> None:
    publish_generation_sidecar(
        folder / filename,
        {"generation_mode": "model3d", "model_type": "humanoid-animate", "command_id": intent,
         "params": {"workspace": payload["workspace"], "source": payload["source"], "clips": clips,
                    "bpm": bpm, "import": None if imported is None else imported.name}},
        output_folder=payload["workspace"], tool="model3d", actor="user", capability=OPERATION,
    )


def command_handlers(workspace_dir, journal_path, runner=None):
    journal = RequestJournal(journal_path)
    run = runner or execute_animate

    def animate(arguments):
        payload, intent = _envelope(arguments)
        clips = _clip_ids(payload.get("clips"))
        bpm = _bpm(payload.get("bpm"))
        imported_name = _import_name(payload)
        if not clips and imported_name is None:
            raise ValueError("Select at least one animation")
        workspace = _text(payload, "workspace", 120)
        root = Path(workspace_dir(workspace))
        source = _inside(root, _text(payload, "source", 240))
        if source.suffix.lower() != ".glb":
            raise ValueError("Rigging currently supports GLB sources only")
        imported = _inside(root, imported_name) if imported_name else None
        digest = intent_digest({"workspace": workspace, "source": source.name, "clips": clips, "bpm": bpm,
                                "import": None if imported is None else imported.name})
        identity = hashlib.sha256(f"{OPERATION}:{workspace}:{intent}".encode()).hexdigest()
        stored = journal.reserve(identity, digest)
        if stored is not None:
            return stored
        root.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", source.stem).strip("-")[:48] or "model"
        filename = f"humanoid-{stem}-{identity[:16]}.glb"
        temporary = root / f".{filename}-{uuid.uuid4().hex}.tmp"
        try:
            result = run(_request(source, clips, bpm, imported), temporary)
            if not temporary.is_file():
                raise RuntimeError("Humanoid animate worker did not write a GLB")
            temporary.replace(root / filename)
        finally:
            temporary.unlink(missing_ok=True)
        _publish(root, filename, payload, intent, clips, bpm, imported)
        body = {"version": 1, "operation": OPERATION, "status": "completed", "result": {
            "file": filename, "workspace": workspace,
            "url": f"/api/v1/file/{filename}?{urlencode({'workspace': workspace})}",
            "clips": list(result.get("clips") or []), "warnings": list(result.get("warnings") or []),
            "bytes": (root / filename).stat().st_size,
        }}
        journal.finish(identity, body)
        return body

    async def handle(arguments):
        return await run_in_threadpool(animate, arguments)

    return {OPERATION: handle}


def create_model3d_animate_router(handlers):
    router = APIRouter()

    @router.post("/api/v1/model3d/animate")
    async def animate(request: Request):
        try:
            return await handlers[OPERATION](await request.json())
        except ValueError as error:
            raise HTTPException(422, {"code": "invalid_command", "message": str(error), "retryable": False}) from error

    return router

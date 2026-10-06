"""Add clips to a workspace GLB that already has the standard humanoid skeleton."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import struct
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from routers.wangp_mcp import RequestJournal, UncertainRequest
from services.asset_manifest import publish_generation_sidecar
from services.mcp_intent import check_intent_id, intent_digest
from services.agent_activity import trusted_tool as agent_trusted_tool

OPERATION = "model3d.animate"
_IMPORT_SUFFIXES = {".bvh", ".glb", ".gltf"}
IMPORT_FOLDER = "animation-imports"
_MAX_IMPORT_BYTES = 64 * 1024 * 1024
_REFUSAL_CODES = ("not_humanoid", "invalid_input")
logger = logging.getLogger(__name__)


class AnimateRefused(ValueError):
    """The worker declined the source or the animation file; the same request always fails the same way."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def command_catalog():
    return [{"name": OPERATION, "version": 1, "domain": "model3d", "mutation": True,
             "description": "Add humanoid clips to a GLB that already has the standard Mixamo-named skeleton (from "
                            "model3d.rig engine humanoid). Clips are baked for that body. import.file is a .bvh, .glb or "
                            ".gltf inside the workspace (Mixamo, VRM/VRoid, Unreal, Blender, Daz or CMU bone names); every "
                            "animation in it is retargeted in place. path adds a walk along points with the feet planted "
                            "(the clip moves the hips; play it with the slot still). CPU only. Returns each clip index, name, duration and foot landings "
                            "for a Video 3D slot (library clips add loop; false means play it once), plus warnings. Unusable inputs (no skeleton, no humanoid in the file, "
                            "compressed meshes) answer invalid_input; the same intent replays that answer.",
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
                                                                         "file": {"type": "string", "minLength": 1, "maxLength": 240}}},
                                                          "path": {"type": "object", "additionalProperties": False,
                                                                   "required": ["points", "duration"],
                                                                   "description": "Walk along these points (model-space metres, ground under the hips; the first is the start) with the feet planted: the clip moves the hips, so play it with the slot standing still.",
                                                                   "properties": {
                                                                       "points": {"type": "array", "minItems": 2, "maxItems": 64,
                                                                                  "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number"}}},
                                                                       "duration": {"type": "number", "minimum": 0.5, "maximum": 120},
                                                                       "name": {"type": "string", "minLength": 1, "maxLength": 60}}},
                                                          "interactions": {"type": "array", "minItems": 1, "maxItems": 8,
                                                                           "description": "Clips that meet the scene, with model-space points: {kind: 'sit', seat: [x,y,z] top of the seat, stand_up?, look?}, {kind: 'reach', target, hand?: left|right|auto, hold?, look?}, {kind: 'look', target}; each takes duration (0.8-30 s) and name.",
                                                                           "items": {"type": "object", "required": ["kind"],
                                                                                     "properties": {"kind": {"enum": ["sit", "reach", "look"]}}}}}}}}}]


def _envelope(arguments):
    if not isinstance(arguments, dict) or type(arguments.get("version")) is not int or arguments["version"] != 1:
        raise ValueError("Use version 1, intent_id and input")
    if set(arguments) - {"version", "intent_id", "input"}:
        raise ValueError("Unknown envelope field")
    payload = arguments.get("input")
    if not isinstance(payload, dict) or set(payload) - {"workspace", "source", "clips", "bpm", "import", "path", "interactions"}:
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


def _path(payload: dict) -> dict | None:
    """The walk path, checked here so a bad request never reaches the worker."""
    if "path" not in payload:
        return None
    value = payload["path"]
    if not isinstance(value, dict) or set(value) - {"points", "duration", "name"} or not {"points", "duration"} <= set(value):
        raise ValueError("path needs points and duration")
    path = {"points": _path_points(value["points"]), "duration": _path_duration(value["duration"])}
    if "name" in value:
        path["name"] = _text(value, "name", 60)
    return path


def _path_points(points) -> list[list[float]]:
    def number(item) -> bool:
        return not isinstance(item, bool) and isinstance(item, (int, float)) and math.isfinite(item)

    if (not isinstance(points, list) or not 2 <= len(points) <= 64
            or any(not isinstance(item, list) or len(item) != 2 or not all(map(number, item)) for item in points)):
        raise ValueError("path points must be 2 to 64 [x, z] number pairs")
    return [[float(x), float(z)] for x, z in points]


def _path_duration(duration) -> float:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0.5 <= duration <= 120:
        raise ValueError("path duration must be between 0.5 and 120 seconds")
    return float(duration)


_INTERACTION_FIELDS = {
    "sit": ({"seat"}, {"duration", "stand_up", "look", "name"}),
    "reach": ({"target"}, {"duration", "hand", "hold", "look", "name"}),
    "look": ({"target"}, {"duration", "name"}),
}


def _interactions(payload: dict) -> list[dict] | None:
    """Sit, reach and look clips, checked here so a bad request never reaches the worker."""
    if "interactions" not in payload:
        return None
    value = payload["interactions"]
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError("interactions must be a list of 1 to 8 entries")
    return [_interaction(item) for item in value]


def _interaction(item) -> dict:
    kind = item.get("kind") if isinstance(item, dict) else None
    if kind not in _INTERACTION_FIELDS:
        raise ValueError("interaction kind must be sit, reach or look")
    required, optional = _INTERACTION_FIELDS[kind]
    if not required <= set(item) or set(item) - required - optional - {"kind"}:
        raise ValueError(f"{kind} takes {', '.join(sorted(required | optional))}")
    clean = {"kind": kind, **{name: _point3(item[name], name) for name in required}}
    if "duration" in item:
        clean["duration"] = _bounded_number(item["duration"], 0.8, 30.0, "interaction duration")
    for flag in ("stand_up", "hold"):
        if flag in item:
            clean[flag] = _flag(item[flag], flag)
    if "look" in item:
        clean["look"] = _flag(item["look"], "look") if kind == "reach" else _point3(item["look"], "look")
    if "hand" in item:
        if item["hand"] not in ("left", "right", "auto"):
            raise ValueError("hand must be left, right or auto")
        clean["hand"] = item["hand"]
    if "name" in item:
        clean["name"] = _text(item, "name", 60)
    return clean


def _point3(value, label: str) -> list[float]:
    if (not isinstance(value, list) or len(value) != 3
            or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in value)):
        raise ValueError(f"{label} must be [x, y, z] numbers")
    return [float(n) for n in value]


def _bounded_number(value, low: float, high: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{label} must be between {low:g} and {high:g}")
    return float(value)


def _flag(value, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true or false")
    return value


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
    if payload.get("ok"):
        return payload
    code = str(payload.get("error") or "rig_failed")
    reason = str(payload.get("reason") or code)
    if code in _REFUSAL_CODES:
        raise AnimateRefused(code, reason if code == "invalid_input" else f"{code}: {reason}")
    logger.warning("Humanoid animate worker failed: %s\n%s", reason, (completed.stderr or "")[-4000:])
    raise RuntimeError(f"Humanoid animate worker failed: {reason}")


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


def _request(source: Path, clips: list[str], bpm: float, imported: Path | None, path: dict | None = None,
             interactions: list[dict] | None = None) -> dict:
    request = {"mode": "animate", "source": str(source), "animations": clips, "animation_bpm": bpm}
    if path is not None:
        request["path"] = path
    if interactions:
        request["interactions"] = interactions
    if imported is not None:
        request["import_file"] = str(imported)
        request["import_label"] = _import_label(imported)
    return request


def _output_stem(stem: str) -> str:
    """The source name without earlier ``humanoid-`` prefixes, the rig job's timestamp and ``rigged_`` mark, or hash suffixes."""
    plain = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-")
    plain = re.sub(r"^(humanoid-)+", "", plain)
    plain = re.sub(r"(-[0-9a-f]{16})+$", "", plain)
    plain = re.sub(r"^\d{4}-\d{2}-\d{2}-\d{2}h\d{2}m\d{2}s_rigged_(.+)_[0-9a-f]{8}$", r"\1", plain)
    return plain[:48].strip("-_") or "model"


def _import_label(path: Path) -> str:
    """Clip name from the file name, without the hash ``store_import`` adds to uploads."""
    stem = re.sub(r"-[0-9a-f]{8}$", "", path.stem) if path.parent.name == IMPORT_FOLDER else path.stem
    return re.sub(r"[_-]+", " ", stem).strip()[:60] or "Imported"


def store_import(root: Path, filename: str, payload: bytes) -> str:
    """Save an uploaded animation under the workspace; return its workspace path."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _IMPORT_SUFFIXES:
        raise ValueError("import file must be .bvh, .glb or .gltf")
    if not payload or len(payload) > _MAX_IMPORT_BYTES:
        raise ValueError("import file must be between 1 byte and 64 MB")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(filename).stem).strip("-")[:48] or "animation"
    name = f"{stem}-{hashlib.sha256(payload).hexdigest()[:8]}{suffix}"
    folder = root / IMPORT_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if not target.is_file():
        temporary = folder / f".{name}-{uuid.uuid4().hex}.tmp"
        temporary.write_bytes(payload)
        temporary.replace(target)
    return f"{IMPORT_FOLDER}/{name}"


def _publish(folder: Path, filename: str, payload: dict, intent: str, clips: list[str], bpm: float, imported: Path | None,
             path: dict | None = None, interactions: list[dict] | None = None) -> None:
    publish_generation_sidecar(
        folder / filename,
        {"generation_mode": "model3d", "model_type": "humanoid-animate", "command_id": intent,
         "params": {"workspace": payload["workspace"], "source": payload["source"], "clips": clips,
                    "bpm": bpm, "import": None if imported is None else imported.name, "path": path,
                    "interactions": interactions}},
        output_folder=payload["workspace"], tool=agent_trusted_tool() or "model3d", actor="user", capability=OPERATION,
    )


def command_handlers(workspace_dir, journal_path, runner=None):
    journal = RequestJournal(journal_path)
    run = runner or execute_animate

    def animate(arguments):
        payload, intent = _envelope(arguments)
        clips = _clip_ids(payload.get("clips"))
        bpm = _bpm(payload.get("bpm"))
        imported_name = _import_name(payload)
        path = _path(payload)
        interactions = _interactions(payload)
        if not clips and imported_name is None and path is None and not interactions:
            raise ValueError("Select at least one animation")
        workspace = _text(payload, "workspace", 120)
        root = Path(workspace_dir(workspace))
        source = _inside(root, _text(payload, "source", 240))
        if source.suffix.lower() != ".glb":
            raise ValueError("Rigging currently supports GLB sources only")
        imported = _inside(root, imported_name) if imported_name else None
        digest = intent_digest({"workspace": workspace, "source": source.name, "clips": clips, "bpm": bpm,
                                "import": None if imported is None else imported.name, "path": path,
                                "interactions": interactions})
        identity = hashlib.sha256(f"{OPERATION}:{workspace}:{intent}".encode()).hexdigest()
        stored = journal.reserve(identity, digest)
        if stored is not None:
            return stored
        root.mkdir(parents=True, exist_ok=True)
        stem = _output_stem(source.stem)
        filename = f"humanoid-{stem}-{identity[:16]}.glb"
        temporary = root / f".{filename}-{uuid.uuid4().hex}.tmp"
        try:
            result = run(_request(source, clips, bpm, imported, path, interactions), temporary)
            if not temporary.is_file():
                raise RuntimeError("Humanoid animate worker did not write a GLB")
            temporary.replace(root / filename)
        except AnimateRefused as refused:
            # Nothing was written; record the answer so a retry with this intent gets it again.
            body = {"version": 1, "operation": OPERATION, "status": "failed", "status_code": 422,
                    "error": {"code": refused.code, "message": str(refused), "retryable": False}}
            journal.finish(identity, body)
            return body
        finally:
            temporary.unlink(missing_ok=True)
        _publish(root, filename, payload, intent, clips, bpm, imported, path, interactions)
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


def humanoid_rigs(root: Path) -> list[dict]:
    """Workspace GLBs that carry the standard skeleton, newest first, with their clip names."""
    from services.humanoid_rig.names import BONE_NAMES

    found = []
    for path in root.glob("*.glb"):
        document = _glb_json(path)
        nodes = document.get("nodes") if isinstance(document, dict) else None
        if not isinstance(nodes, list):
            continue
        names = {str(node.get("name") or "") for node in nodes if isinstance(node, dict)}
        if not set(BONE_NAMES) <= names:
            continue
        animations = document.get("animations") if isinstance(document.get("animations"), list) else []
        clips = [str((item.get("name") if isinstance(item, dict) else None) or f"Clip {index + 1}")
                 for index, item in enumerate(animations)]
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue  # removed while listing
        found.append({"name": path.name, "clips": clips, "modified": modified})
    return sorted(found, key=lambda item: item["modified"], reverse=True)


def _glb_json(path: Path) -> dict | None:
    """The JSON chunk of a GLB, without reading its binary payload."""
    try:
        with path.open("rb") as handle:
            header = handle.read(20)
            if len(header) < 20:
                return None
            magic, _version, _length, size, kind = struct.unpack("<IIIII", header)
            if magic != 0x46546C67 or kind != 0x4E4F534A or size > 16 * 1024 * 1024:
                return None
            return json.loads(handle.read(size))
    except (OSError, ValueError):
        return None


async def _bounded_body(request: Request) -> bytes:
    """The request body, refused with 413 as soon as it passes the import limit."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _MAX_IMPORT_BYTES:
        raise HTTPException(413, "Animation file exceeds the 64 MB limit")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_IMPORT_BYTES:
            raise HTTPException(413, "Animation file exceeds the 64 MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


def create_model3d_animate_router(handlers, workspace_dir=None):
    router = APIRouter()

    @router.post("/api/v1/model3d/animate")
    async def animate(request: Request):
        try:
            body = await handlers[OPERATION](await request.json())
        except UncertainRequest as error:
            raise HTTPException(409, {"code": "submission_uncertain", "message": str(error), "retryable": False}) from error
        except ValueError as error:
            raise HTTPException(422, {"code": "invalid_command", "message": str(error), "retryable": False}) from error
        except RuntimeError as error:
            raise HTTPException(500, {"code": "animate_failed", "message": f"{error}. Retry with a new intent_id.",
                                      "retryable": False}) from error
        if body.get("status") == "failed":
            raise HTTPException(int(body.get("status_code") or 422), body["error"])
        return body

    @router.get("/api/v1/model3d/humanoid-rigs")
    async def rigs(workspace: str):
        if workspace_dir is None:
            raise HTTPException(503, "rig listing is not available")
        return {"rigs": await run_in_threadpool(humanoid_rigs, Path(workspace_dir(workspace)))}

    @router.post("/api/v1/model3d/animation-files")
    async def upload(request: Request, workspace: str, filename: str):
        """Raw-body upload of a .bvh/.glb/.gltf for ``import.file``; kept out of the gallery."""
        if workspace_dir is None:
            raise HTTPException(503, "uploads are not available")
        payload = await _bounded_body(request)
        try:
            root = Path(workspace_dir(workspace))
            stored = await run_in_threadpool(store_import, root, filename, payload)
        except ValueError as error:
            raise HTTPException(422, {"code": "invalid_upload", "message": str(error), "retryable": False}) from error
        return {"file": stored, "workspace": workspace, "name": Path(filename).name}

    return router
